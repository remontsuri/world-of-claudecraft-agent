"""LLM в мозгу (а не над мозгом): двусторонняя связка с замороженным коннектомом.

Зачем этот модуль, если уже есть fly_llm.py: там LLM стояла НАД мозгом (выбирала цель,
мозг исполнял). Здесь — то, чем занята настоящая наука: LLM **пользуется** коннектомом
как вычислительной подложкой, а коннектом влияет на её состояние.

Научная основа (проверено 2026-09-17):
  * «Flies Are All You Need» (GPF/FLM, artificialscientific.com): замороженная LLM 1.17B
    + замороженный граф MaleCNS (166 700 узлов, 25 582 938 рёбер); эмбеддинги токенов
    через ФИКСИРОВАННЫЙ интерфейс заводят граф, обученный readout (278 528 параметров)
    добавляет ограниченную поправку к логитам. Измерено: NLL −0.0222 ната/токен, но
    контроль «прямой вход» (те же параметры без графа) чуть лучше (+0.000488). Разрыв
    связи убирает вклад РОВНО; переименование узлов ломает интерфейс. Вывод авторов:
    граф влияет, преимущества проводки нет. Отсюда наш обязательный контроль:
    disconnected=True обязан давать строго нулевой сдвиг, иначе «вклад» неотличим от шума.
  * Спайковые LLM (SpikeLLM 7–70B, SDLLM, SpikingBrain 7B/76B, NSLLM 1.5B, TTFS-LLM):
    языковую модель можно целиком исполнять на импульсной подложке; платим качеством,
    выигрываем энергию и разреженность.
  * Патентный трек (публикуется раньше статей, поэтому это ближайшее к «закрытому», что
    доступно): WO2025062034A1 (кодирование признаков для нейроморфных чипов),
    US11468299B2 / US11657257B2 (BrainChip, реконфигурируемая нейрофабрика),
    US11017288B2 (STDP в железе), US20120109864A1 (Modha, IBM).

Контур (двусторонний, замкнут через игру):

    игра ──► 13 каналов ──(+ сдвиг от LLM)──► коннектом 8835 ──► 82 DN ──► политика ──► действие
      ▲                                                 │
      │                                                 ▼
      └──── LLM-кортекс ◄── сводка активности (какие DN горят, возбуждение) ────┘
                │
                └── состояние LLM ──► фиксированный (seeded) проектор ──► сдвиг каналов

Что здесь измерено, а не заявлено:
  * калибровка интерфейса. Схема реагирует на каналы крайне неравномерно. Замер
    (сдвиг +0.3, схема 8835, obs из игры): target_exists 43.7 % масштаба DN, mob0_dist
    22.1 %, mob0_cos 15.9 %, resource 12.2 %, ... interact_prox 1.15 %, quest_signal
    0.30 %, gcd_ready 0.00 %. Поэтому «безопасный» вариант «писать только в каналы
    11–12» оставлял LLM ровно два самых ГЛУХИХ входа в мозг (в 30–140 раз слабее
    остальных) — это была ошибка, и она исправлена: проектор КАЛИБРУЕТСЯ, то есть по
    каждому каналу измеряет наклон dDN/dchannel и подбирает такую амплитуду сдвига,
    чтобы вклад канала в DN был одинаковым (равноправный интерфейс). Каналы, которые
    схема не слышит вовсе (gcd_ready), честно помечаются как «deaf» — в них писать
    можно, но мозг этого не услышит.
  * две группы каналов: 0..10 — «реактивные» (hp, бой, цель, мобы: из них политика
    понимает, что происходит в мире) — им разрешён лишь ограниченный сдвиг (по умолчанию
    ±0.10), потому что LLM не должна подменять агенту реальность; 11..12 (взаимодействие
    и квест) — до ±0.25.
  * контроль: disconnected=True даёт строго нулевой сдвиг, и тогда DN совпадают с базой
    бит-в-бит (проверяется в tools/test_llm_in_brain.py).

Честные границы:
  * это численные состояния, а не спайки и не биология; 8835 нейронов = 5.3 % MaleCNS;
  * проектор фиксирован и случаен (как random interface у GPF) — он даёт ВХОД, а не
    утверждение, что проводка полезна. Вопрос «полезнее ли мозг как подложка» решается
    контролем reservoir vs direct input (tools/reservoir_experiment.py), и его результат
    печатается открыто, даже если он отрицательный — как вышло у FLM.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

import numpy as np

N_CHANNELS = 13
N_DN = 82

# каналы 0..10 — реактивные (реальность мира), 11..12 — задача (взаимодействие/квест)
REALITY_CHANNELS = tuple(range(11))

FEATURE_NAMES_V2 = ("hp", "resource", "in_combat", "gcd_ready", "target_exists",
                    "target_dist", "target_sin", "target_cos", "mob0_dist",
                    "mob0_sin", "mob0_cos", "interact_prox", "quest_signal")


# --------------------------------------------------------------- проектор LLM → мозг


@dataclass
class LLMProjector:
    """Фиксированный интерфейс «состояние LLM → сдвиг входных каналов мозга».

    Матрица не обучается (как у GPF), но и не произвольна: она seeded, поэтому прогон
    воспроизводим, а другой seed — готовый контроль «связь есть, проводка произвольна».

    Калибровка (`calibrate`) измеряет наклон dDN/dchannel на живой схеме и выбирает
    амплитуду по каналу так, чтобы все каналы влияли на DN сопоставимо (равноправный
    интерфейс). Без калибровки разрешённые каналы 11–12 в 30–140 раз глуше остальных,
    то есть «LLM в мозгу» превращалась бы в фикцию.
    """

    n_dim: int = 16
    seed: int = 20260917
    target_influence: float = 0.10      # цель: вклад канала ~10 % масштаба DN
    bound_reality: float = 0.10         # предела сдвига для каналов реальности
    bound_task: float = 0.25            # предел сдвига для каналов задачи
    probe: float = 0.15                 # проба для измерения наклона, в единицах канала

    def __post_init__(self) -> None:
        rng = np.random.default_rng(self.seed)
        self.W = rng.normal(0.0, 1.0, size=(self.n_dim, N_CHANNELS)).astype(np.float32)
        self.W /= max(1e-9, float(np.abs(self.W).max()))
        self.bound = np.array([self.bound_reality] * 11 + [self.bound_task] * 2,
                              dtype=np.float32)
        self.gain = np.zeros(N_CHANNELS, dtype=np.float32)     # заполняется калибровкой
        self.sens = np.zeros(N_CHANNELS, dtype=np.float32)     # наклон dDN/dканал
        self.calibration_report: dict = {}                     # что померили и что выставили
        self.calibrated = False

    # ------------------------------------------------------------ калибровка
    def calibrate(self, brain, feats: np.ndarray) -> dict:
        """Измерить, как схема слышит каждый канал, и выставить амплитуды сдвига.

        brain — FlyBrain (замороженная схема), feats — 13 каналов из живого наблюдения.
        Возвращает таблицу-отчёт: наклон, выбранная амплитуда, достигается ли цель.
        """
        import torch

        def dn(f: np.ndarray) -> np.ndarray:
            brain.reset(1)
            with torch.no_grad():
                return brain.step(torch.as_tensor(f[None]))[0].numpy().copy()

        base = dn(feats)
        scale = max(1e-9, float(np.abs(base).max()))
        rows = []
        for i in range(N_CHANNELS):
            probe = feats.copy()
            probe[i] = float(probe[i]) + self.probe
            slope = float(np.abs(dn(probe) - base).max()) / self.probe      # dDN/dканал
            self.sens[i] = slope
            need = self.target_influence * scale / max(slope, 1e-12)        # сколько надо
            self.gain[i] = min(self.bound[i], need)
            rows.append({"channel": FEATURE_NAMES_V2[i], "slope": round(slope, 5),
                         "bound": round(float(self.gain[i]), 4),
                         "influence_pct": round(slope * float(self.gain[i]) / scale * 100, 2),
                         "target_met": bool(need <= self.bound[i] + 1e-9),
                         "deaf": bool(slope <= 1e-7)})
        self.calibrated = True
        self.calibration = rows
        self.calibration_report = {
            "dn_scale": round(scale, 4), "target_influence": self.target_influence,
            "probe": self.probe, "bound_reality": self.bound_reality,
            "bound_task": self.bound_task, "rows": rows,
            "deaf_channels": [r["channel"] for r in rows if r["deaf"]],
            "clipped_channels": [r["channel"] for r in rows if not r["target_met"]]}
        return self.calibration_report

    # ------------------------------------------------------------ сдвиг
    def drive(self, llm_state: np.ndarray | None) -> np.ndarray:
        """Сдвиг 13 каналов. Нет состояния — нет сдвига (строго ноль, не «шум»)."""
        if llm_state is None:
            return np.zeros(N_CHANNELS, dtype=np.float32)
        v = np.asarray(llm_state, dtype=np.float32).reshape(-1)[: self.n_dim]
        if v.shape[0] < self.n_dim:                          # добираем нулями, не мусором
            v = np.pad(v, (0, self.n_dim - v.shape[0]))
        raw = np.tanh(v @ self.W)                            # ∈ (−1, 1), seeded-интерфейс
        if not self.calibrated:                              # без калибровки — мягкий режим
            return (self.bound_reality * 0.5 * raw).astype(np.float32)
        return (self.gain * raw).astype(np.float32)

    def sensitivity_report(self) -> dict:
        if not self.calibrated:
            return {"calibrated": False}
        return {"calibrated": True,
                "deaf": [r["channel"] for r in self.calibration if r["deaf"]],
                "clipped": [r["channel"] for r in self.calibration if not r["target_met"]],
                "gain_by_channel": {r["channel"]: r["bound"] for r in self.calibration}}


def llm_state_from_goal(goal: dict | None, n_dim: int = 16) -> np.ndarray:
    """Разложить решение кортекса в вектор состояния для мозга.

    Без доступа к скрытым слоям модели это единственная честная замена: берём то, что
    LLM выдала (квест, режим, куда идти, индекс задачи, отпечаток id квеста), и
    превращаем в вектор. Это НЕ «скрытые состояния» LLM, и так и написано в отчёте.
    """
    v = np.zeros(n_dim, dtype=np.float32)
    if goal is None:
        return v
    if not isinstance(goal, dict):                       # Goal из fly_llm — тоже годится
        goal = {k: getattr(goal, k, None)
                for k in ("quest", "mode", "go", "objective_index")}
    modes = ("survive", "quest", "earn", "explore")
    v[0] = 1.0
    if goal.get("mode") in modes:
        v[1 + modes.index(goal["mode"])] = 1.0
    v[5] = 1.0 if goal.get("go") == "objective" else 0.0
    v[6] = 1.0 if goal.get("go") == "turnin" else 0.0
    v[7] = 1.0 if goal.get("go") == "giver" else 0.0
    v[8] = float(goal.get("objective_index") or 0) / 7.0
    q = str(goal.get("quest") or "")
    for i, ch in enumerate(q[:7]):                       # детерминированный «отпечаток» id
        v[9 + (i % 4)] += (ord(ch) % 26) / 26.0 / 7.0
    return v


# --------------------------------------------------------------- сводка мозг → LLM


@dataclass
class BrainSummary:
    """Что LLM видит про мозг: какие нисходящие горят и насколько мозг возбуждён."""

    top: list[dict] = field(default_factory=list)
    arousal: float = 0.0
    n_active: int = 0

    def as_dict(self) -> dict:
        return {"top_dn": self.top, "arousal": round(self.arousal, 3),
                "n_active": self.n_active, "text": self.text()}

    def text(self) -> str:
        if not self.top:
            return "мозг: нет активности (схема молчит)"
        parts = ", ".join(f"{d['type']}{d['side']}={d['act']:+.2f}" for d in self.top)
        return (f"мозг: возбуждение {self.arousal:.2f}, активных DN {self.n_active}; "
                f"сильнее всех: {parts}")


_DN_IDENT: list[dict] | None = None


def dn_identity(circuit_path=None) -> list[dict]:
    """Имена и стороны 82 выходных клеток схемы (из data/circuit.json, дальше из кэша).

    Нужны для читаемой сводки: LLM видит не «DN[37]», а «DNp20 R». Типы берём из схемы,
    ничего не досочиняем: какой тип у выходной клетки, такой и показываем.
    """
    global _DN_IDENT
    if _DN_IDENT is None:
        import json
        import os
        path = circuit_path or os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                            "data", "circuit.json")
        with open(path, encoding="utf-8") as fh:
            circuit = json.load(fh)
        nodes = circuit["nodes"]
        _DN_IDENT = [{"type": str(nodes[i]["type"]).strip(),
                      "side": str(nodes[i].get("side") or "").strip()}
                     for i in circuit["outputs"]]
    return _DN_IDENT


def summarize_brain(dn: np.ndarray, dn_types: list[str] | None = None,
                    dn_sides: list[str] | None = None, k: int = 5,
                    active_thr: float = 0.05) -> BrainSummary:
    """Сводка активности 82 нисходящих: кто горит, насколько в целом возбуждён мозг."""
    v = np.asarray(dn, dtype=np.float32).reshape(-1)
    types = dn_types or [f"DN[{i}]" for i in range(v.shape[0])]
    sides = dn_sides or [""] * v.shape[0]
    order = np.argsort(-np.abs(v))[:k]
    top = [{"type": str(types[i]).strip(), "side": str(sides[i]).strip(),
            "act": round(float(v[i]), 3), "index": int(i)} for i in order]
    return BrainSummary(top=top, arousal=float(np.mean(np.abs(v))),
                        n_active=int(np.sum(np.abs(v) > active_thr)))


# --------------------------------------------------------------- связка целиком


class LLMInBrain:
    """Замкнутый контур «игра → мозг → LLM → мозг → игра».

    Порядок в такте (см. tools/record_replay.py --llm-couple brain):
      1. берём сдвиг каналов по последнему решению LLM (LLM пишет в мозг);
      2. шагаем коннектом (13 каналов + сдвиг) и получаем 82 DN;
      3. из DN собираем сводку и кладём её в состояние кортекса (LLM читает мозг);
      4. следующее решение LLM снова превращается в сдвиг каналов.

    Обучения в связке нет: интерфейс фиксирован. Обучаемым может быть только readout
    поверх DN — см. tools/reservoir_experiment.py (там же контроль FLM «мозг против
    прямого входа»).
    """

    def __init__(self, projector: LLMProjector | None = None, disconnected: bool = False,
                 feature_clip: float = 1.5):
        self.projector = projector or LLMProjector()
        # disconnected=True — контроль из FLM: связь порвана, вклад обязан исчезнуть РОВНО.
        self.disconnected = disconnected
        self.feature_clip = feature_clip
        self.last_drive = np.zeros(N_CHANNELS, dtype=np.float32)
        self.last_summary: BrainSummary | None = None
        self.log: list[dict] = []

    # ------------------------------------------------------------ калибровка
    def calibrate(self, brain, feats: np.ndarray) -> dict:
        return self.projector.calibrate(brain, feats)

    # ------------------------------------------------------------ запись в мозг
    def drive_from_goal(self, goal: dict | None) -> np.ndarray:
        self.last_drive = (np.zeros(N_CHANNELS, dtype=np.float32) if self.disconnected
                          else self.projector.drive(llm_state_from_goal(goal)))
        return self.last_drive

    def apply(self, feats: np.ndarray) -> np.ndarray:
        """Каналы с учётом последнего решения LLM: это и есть «вход LLM в мозг»."""
        if self.disconnected:
            return feats
        out = np.asarray(feats, dtype=np.float32) + self.last_drive
        return np.clip(out, -self.feature_clip, self.feature_clip).astype(np.float32)

    # ------------------------------------------------------------ чтение мозга
    def observe_brain(self, dn: np.ndarray, dn_types=None, dn_sides=None) -> BrainSummary:
        self.last_summary = summarize_brain(dn, dn_types, dn_sides)
        self.log.append({"arousal": self.last_summary.arousal,
                         "drive_norm": float(np.abs(self.last_drive).sum()),
                         "top": self.last_summary.top[0]["type"] if self.last_summary.top else None})
        return self.last_summary

    def report(self) -> dict:
        if not self.log:
            return {"frames": 0, "disconnected": self.disconnected,
                    "drive_norm_mean": 0.0, "drive_norm_max": 0.0,
                    "arousal_mean": 0.0, "top_dn_hist": {}}
        dr = np.array([r["drive_norm"] for r in self.log])
        ar = np.array([r["arousal"] for r in self.log])
        counts: dict[str, int] = {}
        for r in self.log:
            if r["top"]:
                counts[r["top"]] = counts.get(r["top"], 0) + 1
        return {"frames": len(self.log), "disconnected": self.disconnected,
                "drive_norm_mean": round(float(dr.mean()), 4),
                "drive_norm_max": round(float(dr.max()), 4),
                "arousal_mean": round(float(ar.mean()), 4),
                "top_dn_hist": dict(sorted(counts.items(), key=lambda kv: -kv[1])[:5])}


def main() -> int:
    """Самопроверка без игры: калибровка, вклад каналов, строго нулевой разрыв."""
    import os
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import torch
    from fly_brain import FlyBrain, extract_features

    obs = np.zeros(607, dtype=np.float32)
    obs[0], obs[1] = 0.7, 0.9                     # hp, resource
    obs[4], obs[5], obs[6], obs[7] = -0.1, -0.05, 0.0, 1.0   # позиция и направление
    feats = extract_features(obs)
    brain = FlyBrain()

    link = LLMInBrain()
    cal = link.calibrate(brain, feats)
    print(f"калибровка: масштаб DN {cal['dn_scale']}, цель вклада {cal['target_influence']}")
    print("  канал            наклон    предел   вклад в DN   цель 10 %")
    for r in cal["rows"]:
        print(f"  {r['channel']:14s} {r['slope']:.5f}  {r['bound']:.4f}  "
              f"{r['influence_pct']:8.2f} %   {'да' if r['target_met'] else 'нет: упирается в предел'}")

    def dn(f: np.ndarray) -> np.ndarray:
        brain.reset(1)
        with torch.no_grad():
            return brain.step(torch.as_tensor(f[None]))[0].numpy()

    base = dn(feats)
    scale = float(np.abs(base).max())
    goal = {"quest": "q_prof_intro", "mode": "quest", "go": "objective", "objective_index": 0}
    d1 = link.drive_from_goal(goal)
    e1 = float(np.abs(dn(link.apply(feats)) - base).max())
    d2 = link.drive_from_goal({**goal, "mode": "survive", "go": "turnin"})
    e2 = float(np.abs(dn(link.apply(feats)) - base).max())
    print(f"сдвиг (quest/objective): {np.round(d1, 3).tolist()}")
    print(f"сдвиг (survive/turnin):  {np.round(d2, 3).tolist()}")
    print(f"вклад в DN: {e1 / scale * 100:.1f} % масштаба (quest), "
          f"{e2 / scale * 100:.1f} % (survive)")
    print(f"каналы реальности 0..10 в пределах ±{link.projector.bound_reality}: "
          f"{bool(np.all(np.abs(np.stack([d1, d2])[:, :11]) <= link.projector.bound_reality + 1e-6))}")

    d = np.zeros(82, dtype=np.float32)
    d[:6] = [0.9, -0.7, 0.5, 0.31, -0.12, 0.08]
    print("сводка для LLM:", summarize_brain(d, [f"T{i}" for i in range(82)], ["R"] * 82).text()[:110])

    link.drive_from_goal(goal)
    link.observe_brain(base)
    cut = LLMInBrain(disconnected=True)
    cut.drive_from_goal(goal)
    cut.observe_brain(base)
    print("связь включена:", json.dumps(link.report(), ensure_ascii=False))
    print("разрыв связи:   ", json.dumps(cut.report(), ensure_ascii=False))
    assert link.report()["drive_norm_max"] > 0, "связь обязана давать ненулевой вклад"
    assert cut.report()["drive_norm_max"] == 0.0, "разрыв обязан давать ровно ноль"
    assert np.array_equal(cut.apply(feats), feats), "при разрыве каналы не меняются вовсе"
    print("OK: калиброванная связь даёт вклад, разрыв — строго нулевой")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
