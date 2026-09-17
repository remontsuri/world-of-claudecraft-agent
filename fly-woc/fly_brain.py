"""Frozen MaleCNS circuit engine + engineered sensory drive (world-of-claudecraft).

Dynamics follow the Fly Dino v2 protocol (flyjump src/lib/connectome.ts):
signed, normalized, leaky-tanh rate units, 3 synchronous iterations per
decision, dimensionless activity (NOT firing rates or membrane voltage).

    W[j,i] = c[j,i] * s[j] / sum_k(c[k,i] * |s[k]|)   (normalize into post cell)
    h_new  = 0.3 * h + 0.7 * tanh(u + 1.4 * sum_j W[j,i] * h[j])
    output = 4 * h[outputCell]

Only the artificial readout downstream is trained; the graph, signs,
normalization and drive mapping are fixed.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np
import torch

from device_utils import describe_device, resolve_device

import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent))  # obs_layout рядом
from obs_layout import from_obs  # noqa: E402

DYNAMICS = {"iterations": 3, "leak": 0.7, "gain": 1.4, "outputGain": 4.0}  # Fly Dino v2 constants

DEFAULT_CIRCUIT = Path(__file__).parent / "data" / "circuit.json"

# ---------------------------------------------------------------- observations
# WoWClassicEnv obs layout (src/sim/obs.ts): self 16 | abilities 2*ABILITY_SLOTS |
# target 9 | mobs 5x6 | interactable 5 | quests 2*QUEST_ORDER.length | paladin 3.
# Индексы блоков НЕ захардкожены: игра меняет ABILITY_SLOTS (48 -> 28 в текущей
# версии), и всё после способностей сдвигается. Блоки выводятся из длины obs
# через obs_layout.from_obs: 607 -> цель 112, мобы 121, интеракт 151, квесты 156;
# 567 -> цель 72, мобы 81, интеракт 111, квесты 116.
# 13 engineered features; the assignment to cell types is a fixed engineering
# encoder with no claimed biological interpretation (Fly Dino v2 wording).
# v2 channel names (same 13 slots, different semantics from index 8 on).
FEATURE_NAMES_V2 = ["hp", "resource", "in_combat", "gcd_ready", "target_exists",
                    "target_dist", "target_sin", "target_cos", "mob0_dist",
                    "mob0_sin", "mob0_cos", "interact_prox", "quest_signal"]
FEATURE_NAMES = ["hp", "resource", "in_combat", "gcd_ready", "target_exists",
                 "target_dist", "target_hp", "target_sin", "target_cos",
                 "nearest_mob_dist", "mob_pressure", "ability_ready", "quest_progress"]


def extract_features_v2(obs: np.ndarray) -> np.ndarray:
    """Navigation-aware encoder: same 13 channels, richer semantics.

    v1 collapsed the observation to 13 scalars that carry NO direction and NO
    position (it averaged quest progress and mob aggro). That is enough to fight
    whatever happens to be in front of you and to finish a quest by accident, but
    it cannot express "walk to that corpse" or "go to the quest giver", which is
    what every milestone past the starter quest needs.

    v2 keeps the SAME 13 channel slots, so the existing circuit.json (13 channels
    x 4 cells = 52 input cells) is reused unchanged and only the readout is
    retrained:

        0 hp                       [v1: same]
        1 resource                 [v1: same]
        2 in_combat                [v1: same]
        3 gcd_ready                [v1: same]
        4 target_exists            [v1: same, now hostile-aware]
        5 target_dist              [v1: same, d/40 clamped to the obs ceiling]
        6 target_sin               [v1: same]
        7 target_cos               [v1: same]
        8 mob0_dist                [v1: "nearest mob dist" - identical index]
        9 mob0_sin                 [v1: mob aggro fraction -> replaced by bearing]
       10 mob0_cos                 [same slot, other bearing component]
       11 interact_proximity       [v1: mean ability readiness -> replaced: how
                                    close the nearest interactable is, 1 = in
                                    range, which is exactly the signal that
                                    gates interact/loot/quest-NPC actions]
       12 quest_signal             [v1: mean quest progress -> now progress of the
                                    most advanced open quest (falls back to mean)]

    Observation indices are from the game's own encoder,
    src/sim/obs.ts encodeObs(): mobs 121..150 are 5 x [dist, sin, cos, hp, level,
    aggro], the interactable block is 151..155, quests are 156..603 as 224 pairs
    [progress, state] with state 'done' -> progress 1.
    """
    o = np.asarray(obs, dtype=np.float32).reshape(-1)
    n = o.shape[0]
    try:
        L = from_obs(o)
    except ValueError:               # truncated/foreign obs (tests): fall back to v1
        return extract_features_v1(obs)
    if n != L.obs_size or n < L.paladin_base:   # sanity: вектор короче раскладки
        return extract_features_v1(obs)

    # Distances in the obs are ALREADY d/40 clamped to 1.5 (the 60-unit obs
    # radius), so they only need rescaling into 0..1 - never another /40.
    def unit(i: int) -> float:
        return float(np.clip(o[i] / 1.5, 0.0, 1.0))

    # Interactable block = [exists, d/40, sin, cos, type]
    ib = L.interact_base
    interact_exists = float(o[ib])
    interact_prox = interact_exists * (1.0 - unit(ib + 1))

    # Quest block = N x [state, progress], states:
    # 0 not taken, 0.33 active, 0.66 ready to turn in, 1 done.
    quests = o[L.quest_slice()].reshape(-1, 2)
    if quests.size:
        state, progress = quests[:, 0], quests[:, 1]
        ready = bool(((state > 0.5) & (state < 1.0)).any())   # 0.66: hand it in
        active = state == 0.33
        # Prefer "something is ready to turn in" (that is the productive action),
        # else the most advanced active quest.
        quest_signal = 1.0 if ready else (float(progress[active].max()) if active.any() else 0.0)
    else:
        quest_signal = 0.0

    return np.array([
        o[0],                                        # hp ratio
        o[1],                                        # resource ratio
        o[11],                                       # in combat flag
        1.0 - o[8],                                  # gcd ready
        o[L.target_base],                            # target exists
        unit(L.target_base + 3),                     # target distance
        0.5 * (float(o[L.target_base + 4]) + 1.0),   # target bearing sin -> 0..1
        0.5 * (float(o[L.target_base + 5]) + 1.0),   # target bearing cos -> 0..1
        unit(L.mobs_base),                           # nearest hostile mob distance
        0.5 * (float(o[L.mobs_base + 1]) + 1.0),     # nearest mob bearing sin
        0.5 * (float(o[L.mobs_base + 2]) + 1.0),     # nearest mob bearing cos
        interact_prox,                               # interactable/loot/quest-NPC proximity
        quest_signal,                                # ready-to-turn-in, else max progress
    ], dtype=np.float32)


def extract_features_v1(obs: np.ndarray) -> np.ndarray:
    """Original 13-channel encoder (kept for the committed v1 checkpoints)."""
    o = np.asarray(obs, dtype=np.float32).reshape(-1)
    L = from_obs(o)
    mob_aggro = o[L.mobs_base + 5: L.interact_base: 6].mean()   # per-mob aggro flag
    return np.array([
        o[0],                                        # hp ratio
        o[1],                                        # resource ratio
        o[11],                                       # in combat flag
        1.0 - o[8],                                  # gcd ready
        o[L.target_base],                            # target exists
        min(o[L.target_base + 3] / 1.5, 1.0),        # target distance (0..1)
        o[L.target_base + 1],                        # target hp ratio
        (o[L.target_base + 4] + 1.0) / 2.0,          # target bearing sin
        (o[L.target_base + 5] + 1.0) / 2.0,          # target bearing cos
        min(o[L.mobs_base] / 1.5, 1.0),              # nearest mob distance
        mob_aggro,                                   # fraction of mobs aggroed
        o[L.ability_base: L.target_base: 2].mean(),  # ability readiness fraction
        o[L.quest_base + 1: L.quest_end: 2].mean(),  # mean quest progress
    ], dtype=np.float32)


# Feature set selector. v1 = committed checkpoints (params_fly_v2.pt); v2 =
# navigation-aware, same 13 slots, needs a retrained readout. Set FLY_FEATURES=v2.
FEATURE_VERSION = os.environ.get("FLY_FEATURES", "v1").strip().lower()


def extract_features(obs: np.ndarray) -> np.ndarray:
    """Dispatch on FLY_FEATURES so one env var switches encoder+checkpoint together."""
    return extract_features_v2(obs) if FEATURE_VERSION == "v2" else extract_features_v1(obs)


# --------------------------------------------------------------- загрузка схемы
def _skip_ws(text: str, i: int) -> int:
    while i < len(text) and text[i] in " \t\r\n":
        i += 1
    return i


class _Grow:
    """Растущий numpy-массив: схема из 1.87M рёбер не должна собираться сначала в
    список Python-объектов."""

    __slots__ = ("a", "n")

    def __init__(self, dtype, cap: int = 4096):
        self.a = np.empty(max(cap, 1), dtype)
        self.n = 0

    def add(self, value) -> None:
        if self.n == self.a.size:
            self.a = np.resize(self.a, self.a.size * 2)
        self.a[self.n] = value
        self.n += 1

    def array(self) -> np.ndarray:
        return self.a[: self.n]


def load_circuit(path: str | Path) -> dict:
    """Потоково разбирает schematic-json и отдаёт массивы вместо дерева объектов.

    Зачем не `json.loads`: на нашей схеме (8835 узлов / 1.87M рёбер) он строит
    1.87M вложенных списков — пик ~0.6 ГБ, из которых 0.5 ГБ сразу становятся мусором.
    Тут пик — текст файла (25 МБ) плюс нужные массивы (~45 МБ), то есть в 10 раз меньше.
    Формат чтения тот же; при незнакомой структуре разбор падает с явной ошибкой,
    а не молча отдаёт пустые массивы.
    """
    text = Path(path).read_text()
    dec = json.JSONDecoder()
    i = _skip_ws(text, text.index("{") + 1)

    meta: dict = {}
    node_field = {k: [] for k in ("type", "side", "nt", "role")}
    # Оценка ёмкости по размеру файла: на нашей схеме это ~28 байт на ребро, берём с
    # запасом. Иначе удвоение буфера даёт пик в 2 раза выше нужного (и лишний churn).
    cap = max(4096, len(text) // 16)
    signs = _Grow(np.float64, cap // 200)
    pre = _Grow(np.int64, cap)
    post = _Grow(np.int64, cap)
    contacts = _Grow(np.float64, cap)
    seen = set()

    while True:
        i = _skip_ws(text, i)
        if text[i] == "}":
            break
        if text[i] == ",":
            i += 1
            continue
        key, i = dec.raw_decode(text, i)
        i = _skip_ws(text, i)
        if text[i] != ":":
            raise ValueError(f"схема {path}: ожидался ':' после ключа {key!r}")
        i = _skip_ws(text, i + 1)
        seen.add(key)

        if key in ("nodes", "edges"):
            if text[i] != "[":
                raise ValueError(f"схема {path}: {key} должен быть списком")
            i += 1
            big = key == "edges"
            while True:
                i = _skip_ws(text, i)
                if text[i] == "]":
                    i += 1
                    break
                if text[i] == ",":
                    i += 1
                    continue
                item, i = dec.raw_decode(text, i)
                if big:
                    pre.add(item[0])
                    post.add(item[1])
                    contacts.add(item[2])
                else:
                    signs.add(item.get("sign", 1.0))
                    for f in node_field:
                        node_field[f].append(item.get(f))
        else:
            meta[key], i = dec.raw_decode(text, i)

    missing = {"version", "nodes", "edges", "inputs", "outputs"} - seen
    if missing:
        raise ValueError(f"схема {path}: нет обязательных ключей {sorted(missing)}")
    n = signs.n
    if len(pre.array()) == 0:
        raise ValueError(f"схема {path}: рёбер нет — это не схема")
    lo, hi = int(min(pre.array().min(), post.array().min())), int(max(pre.array().max(), post.array().max()))
    if lo < 0 or hi >= n:
        raise ValueError(f"схема {path}: ребро ссылается на узел вне 0..{n - 1} ({lo}..{hi})")

    return {
        "n": n,
        "pre": pre.array(), "post": post.array(), "contacts": contacts.array(),
        "signs": signs.array(),
        "nodes": node_field,
        "inputs": meta["inputs"], "outputs": meta["outputs"],
        "channels": meta.get("channels"), "input_types": meta.get("input_types"),
        "version": meta.get("version"),
        "n_edges": int(pre.n),
    }


class FlyBrain:
    """Пакетная замороженная схема: вход (B, 13), выход (B, n_dn) — тензор НА self.device.

    Три бэкенда одного и того же уравнения:
      scipy  — CPU-эталон (numpy + scipy CSR). На CPU быстрее torch: у torch
               CPU-разрежённый matmul на этой схеме измерялся ~234 мс/умножение
               против ~2 мс у scipy (одноядерный путь);
      edge   — gather + index_add по рёбрам. Основной для GPU: 1.87M рёбер,
               батч маленький (2-8), память под один шаг ~B*M*4 байт;
      sparse — torch.sparse CSR matmul. Кроссплатформенная альтернатива и,
               главное, эталон для сверки — eq-тест всех трёх бэкендов.
               Формат — CSR, не COO: на шаге B=8 (CPU, эта схема) COO-умножение
               заняло 59.0 мс против 2.3 мс у CSR при расхождении 1.8e-07;
               полный шаг — 157 мс против 7.4 мс. ROCm/hipSPARSE тоже считает
               CSR нативно, а COO torch каждый раз конвертирует внутри вызова.
               Вернуться к COO можно переменной WOC_SPARSE_FORMAT=coo.

    Прежняя версия считала всё в scipy и возвращала CPU-тензор независимо от
    device, поэтому в train.py жил костыль base.to(self.device), а «GPU» в
    названиях файлов ни к чему не обязывал. Здесь устройство выбирается один раз
    (device_utils.resolve_device), и состояние h живёт на нём же.
    """

    BACKENDS = ("scipy", "edge", "sparse")

    _buffers: dict | None = None

    def __init__(self, circuit_path: str | Path | None = None, device=None,
                 backend: str | None = None, dtype: torch.dtype = torch.float32):
        self.graph_path = Path(circuit_path or DEFAULT_CIRCUIT)
        circuit = load_circuit(self.graph_path)
        n = self.n = circuit["n"]
        self.device = resolve_device(device)
        self.dtype = dtype

        pre, post = circuit["pre"], circuit["post"]
        contacts, signs = circuit["contacts"], circuit["signs"]

        # Fly Dino normalization: входящие знаковые веса нормируются на суммарный
        # абсолютный контакт постсинаптической клетки; ноль -> 0.
        denom = np.zeros(n)
        np.add.at(denom, post, contacts * np.abs(signs[pre]))
        w = np.where(denom[post] > 0,
                     contacts * signs[pre] / np.maximum(denom[post], 1e-12), 0.0).astype(np.float32)

        self.input_idx_np = np.array([c for c, _ in circuit["inputs"]], dtype=np.int64)
        self.input_ch_np = np.array([ch for _, ch in circuit["inputs"]], dtype=np.int64)
        self.out_idx_np = np.array(circuit["outputs"], dtype=np.int64)
        self.n_dn = len(circuit["outputs"])
        self.n_edges = circuit["n_edges"]
        # Компактные метаданные вместо полного графа: 1.87M рёбер в Python-объектах —
        # это ~0.5 ГБ на каждую копию мозга (на машине с 1 ГБ два Runner'а падали по
        # OOM). Полный файл при необходимости перечитывается по self.graph_path,
        # типы клеток нужны для адресации входов по типам (см. ECOSYSTEM.md).
        self.graph = {
            "version": circuit["version"],
            "n_nodes": n,
            "n_edges": self.n_edges,
            "channels": circuit["channels"],
            "input_types": circuit["input_types"],
            "inputs": [list(map(int, pair)) for pair in circuit["inputs"]],
            "outputs": [int(o) for o in circuit["outputs"]],
            "node_types": circuit["nodes"]["type"],
        }
        # Драйв пишется индексацией; при дубликатах индексов numpy берёт последний,
        # torch — недетерминирован. Сейчас индексы уникальны (52 нейрона), но при
        # пересборке схемы это не гарантировано — на такой случай есть index_add_.
        self._input_idx_unique = len(set(self.input_idx_np.tolist())) == self.input_idx_np.size

        backend = (backend or os.environ.get("WOC_BRAIN_BACKEND") or "auto").strip().lower()
        if backend == "auto":
            backend = "scipy" if self.device.type == "cpu" else "edge"
        if backend not in self.BACKENDS:
            raise ValueError(f"неизвестный бэкенд схемы {backend!r}; доступны {self.BACKENDS}")
        self.backend = backend

        if backend == "scipy":
            from scipy.sparse import coo_matrix
            # W_T[post, pre], чтобы (W_T @ h.T) собирал активность пре-клеток в пост.
            self.W_T = coo_matrix((w, (post, pre)), shape=(n, n)).tocsr()
            self.W_T.sum_duplicates()
            self.h = None                       # numpy (B, n)
        else:
            self.pre_t = torch.as_tensor(pre, dtype=torch.long, device=self.device)
            self.post_t = torch.as_tensor(post, dtype=torch.long, device=self.device)
            self.w_t = torch.as_tensor(w, dtype=self.dtype, device=self.device)
            self.input_idx = torch.as_tensor(self.input_idx_np, dtype=torch.long, device=self.device)
            self.input_ch = torch.as_tensor(self.input_ch_np, dtype=torch.long, device=self.device)
            self.out_idx = torch.as_tensor(self.out_idx_np, dtype=torch.long, device=self.device)
            if backend == "sparse":
                # CSR (см. докстринг класса): COO torch конвертирует в CSR на каждом
                # вызове sparse.mm, и платим за это на каждом шаге. Формат можно
                # вернуть к COO через WOC_SPARSE_FORMAT=coo — на случай, если на
                # конкретной сборке torch CSR-путь сломан; тест эквивалентности
                # (test_device.py) сравнивает бэкенды независимо от формата.
                fmt = (os.environ.get("WOC_SPARSE_FORMAT") or "csr").strip().lower()
                indices = torch.stack([self.post_t, self.pre_t])
                coo = torch.sparse_coo_tensor(
                    indices, self.w_t, (n, n), device=self.device).coalesce()
                if fmt == "coo":
                    self.W_sparse = coo
                else:
                    # CSR: indptr/col_indices считает сам torch при конверсии;
                    # строить их вручную по списку рёбер — лишний повод ошибиться.
                    self.W_sparse = coo.to_sparse_csr()
                del coo
                self.sparse_format = fmt
            self.h = None                       # torch (B, n) на self.device

    # ---------------------------------------------------------------- состояние
    def reset(self, batch: int):
        self._buffers = None                     # форма батча меняется — буферы заново
        if self.backend == "scipy":
            self.h = np.zeros((batch, self.n), np.float32)
        else:
            self.h = torch.zeros((batch, self.n), dtype=self.dtype, device=self.device)

    def zero_all(self):
        if self.h is None:
            return
        if self.backend == "scipy":
            self.h[:] = 0
        else:
            self.h.zero_()

    def zero_rows(self, mask) -> None:
        """Обнулить состояние выбранных окружений (авто-ресет среды)."""
        if self.h is None:
            return
        if self.backend == "scipy":
            self.h[np.asarray(mask, dtype=bool)] = 0.0
        else:
            m = mask if isinstance(mask, torch.Tensor) else torch.as_tensor(mask, device=self.device)
            self.h[m.to(torch.bool)] = 0.0

    def state_copy(self):
        """Копия состояния для диагностики (check_io) — тип зависит от бэкенда."""
        if self.h is None:
            return None
        return self.h.copy() if self.backend == "scipy" else self.h.detach().clone()

    def restore_state(self, state) -> None:
        if state is None:
            return
        if self.backend == "scipy":
            self.h = np.array(state, dtype=np.float32)
        else:
            self.h = state.clone().to(self.device, dtype=self.dtype)

    # ----------------------------------------------------------------- буферы
    def _scratch(self, batch: int) -> dict:
        """Рабочие буферы шага на устройстве и в dtype мозга.

        Зачем: шаг раньше аллоцировал на каждой итерации (B, n) и (B, M) — на
        B=8 это ~60 МБ мусора на итерацию, три итерации на шаг. Кэш буферов
        снимает и аллокации, и их синхронизацию с устройством. Измерено (CPU,
        эта схема, B=8): 189 мс -> 115 мс на шаг, расхождение с прежней
        реализацией 6e-08 (test_device.py сверяет бэкенды отдельно).
        """
        if getattr(self, "_buffers", None) is not None and self._buffers.get("batch") == batch:
            return self._buffers
        buf = {"batch": batch}
        if self.backend == "edge":
            buf["g"] = torch.empty((batch, self.n_edges), dtype=self.dtype, device=self.device)
            buf["rec"] = torch.empty((batch, self.n), dtype=self.dtype, device=self.device)
        buf["u"] = torch.zeros((batch, self.n), dtype=self.dtype, device=self.device)
        self._buffers = buf
        return buf

    def describe(self) -> str:
        return (f"FlyBrain(backend={self.backend}, device={describe_device(self.device)}, "
                f"dtype={str(self.dtype).replace('torch.', '')}, n={self.n}, "
                f"n_dn={self.n_dn}, edges={self.n_edges})")

    # ---------------------------------------------------------------- шаг схемы
    def step(self, feats, silenced: bool = False):
        """feats: (B, 13) torch-тензор или numpy -> (B, n_dn) на self.device.

        Конверсий устройства внутри шага нет: если вход пришёл с другого
        устройства, он переносится один раз на входе.
        """
        B = int(feats.shape[0])
        if self.h is None or self.h.shape[0] != B:
            self.reset(B)
        if silenced:
            self.zero_all()
            if self.backend == "scipy":
                return torch.zeros(B, self.n_dn, dtype=torch.float32)
            return torch.zeros(B, self.n_dn, dtype=self.dtype, device=self.device)

        leak = DYNAMICS["leak"]
        gain = DYNAMICS["gain"]
        out_gain = DYNAMICS["outputGain"]

        if self.backend == "scipy":
            f = feats.detach().cpu().numpy() if isinstance(feats, torch.Tensor) else np.asarray(feats)
            u = np.zeros((B, self.n), np.float32)
            # Fly Dino drive encoding: u = 2 * (feature - 0.5) только на драйв-клетках.
            u[:, self.input_idx_np] = 2.0 * (f[:, self.input_ch_np] - 0.5)
            for _ in range(DYNAMICS["iterations"]):
                inp = u + gain * (self.W_T @ self.h.T).T
                self.h = (1 - leak) * self.h + leak * np.tanh(inp, dtype=np.float32)
            out = self.h[:, self.out_idx_np] * out_gain
            return torch.from_numpy(np.ascontiguousarray(out))

        x = feats if isinstance(feats, torch.Tensor) else torch.as_tensor(feats)
        if x.device != self.device:
            x = x.to(self.device, non_blocking=True)
        if x.dtype != self.dtype:
            x = x.to(self.dtype)

        # Схема заморожена: ни один её параметр не обучается, граф автограда здесь
        # не нужен. Выход — обычный тензор, поэтому читаут поверх него учится как
        # и раньше (no_grad не превращает результат в «inference tensor»).
        with torch.no_grad():
            buf = self._scratch(B)
            u = buf["u"]
            drive = 2.0 * (x[:, self.input_ch] - 0.5)
            if self._input_idx_unique:
                # Драйв пишется в свои столбцы; остальные в u — нули с момента
                # создания буфера, поэтому обнулять u каждый шаг не нужно.
                u[:, self.input_idx] = drive
            else:
                u.zero_()
                u.index_add_(1, self.input_idx, drive)

            h = self.h
            for _ in range(DYNAMICS["iterations"]):
                if self.backend == "edge":
                    g, r = buf["g"], buf["rec"]
                    if r is h or g is h:            # страховка от алиасинга буферов
                        r = torch.empty_like(h)
                        buf["rec"] = r
                    torch.index_select(h, 1, self.pre_t, out=g)
                    g.mul_(self.w_t)
                    r.zero_()
                    r.index_add_(1, self.post_t, g)
                    # h_new = (1-leak)*h + leak*tanh(u + gain*rec) — in-place, тем же
                    # порядком операций, что и в записи формулы (сверено: 6e-08).
                    r.mul_(gain).add_(u).tanh_().mul_(leak).add_(h, alpha=1 - leak)
                    h, r = r, h
                    buf["rec"] = r
                else:
                    rec = torch.sparse.mm(self.W_sparse, h.transpose(0, 1)).transpose(0, 1)
                    h = (1 - leak) * h + leak * torch.tanh(u + gain * rec)
            self.h = h
            return h.index_select(1, self.out_idx) * out_gain
