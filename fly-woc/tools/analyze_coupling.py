#!/usr/bin/env python3
"""analyze_coupling.py — что реально даёт двусторонняя связка (и что не даёт).

Считает по двум (или более) прогонам записи:
  * расхождение траекторий: связка `brain` против контроля `brain-cut` (связь разорвана,
    сдвиг каналов ровно нулевой) — то есть изолирует вклад именно ЗАПИСИ LLM в мозг;
  * метрики игры (xp, киллы, смерти, квесты) и длину пути;
  * отчёт связки из meta: нормы сдвига каналов, среднее возбуждение DN, топ-DN;
  * сколько кадров метка цели совпадала (если цель одна и та же, а маршрут разный —
    значит влияние идёт через подложку, а не через «LLM выбрала другой квест»).

Честность: один прогон на режим ничего не доказывает. Скрипт не выводит «лучше/хуже»,
он печатает числа, а вывод формулируется в отчёте с указанием числа прогонов и сидов.

Запуск:
    python3 tools/analyze_coupling.py /home/user/ablation/brain_900001.json \
        /home/user/ablation/brain-cut_900001.json
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path


def path_len(frames: list[dict]) -> float:
    return sum(math.dist((a["x"], a["z"]), (b["x"], b["z"]))
               for a, b in zip(frames, frames[1:]))


def summarize(data: dict) -> dict:
    m, fr = data["meta"], data["frames"]
    info = fr[-1] if fr else {}
    out = {"frames": len(fr), "seed": m.get("seed"),
           "policy": m["policy"], "checkpoint": m["checkpoint"],
           "path_len": round(path_len(fr), 1),
           "finish": [round(fr[-1]["x"], 1), round(fr[-1]["z"], 1)] if fr else None,
           "quests_labels": sorted({f["goal"]["quest"] for f in fr if f.get("goal")}),
           "xp": info.get("xp"), "kills": info.get("kills"),
           "deaths": info.get("deaths"), "quests_done": info.get("quests_done"),
           "level": info.get("level")}
    llm = m.get("llm") or {}
    if llm:
        out["llm"] = {"mode": llm["mode"], "calls": llm["stats"]["calls"],
                      "ok": llm["stats"]["ok"], "fallback": llm["stats"]["fallback"],
                      "vetoed": llm["stats"]["vetoed"], "stale": llm["stats"]["stale"]}
    cp = m.get("llm_couple")
    if cp:
        out["couple"] = {"mode": cp["mode"], "disconnected": cp["disconnected"],
                         "drive_norm_mean": cp["report"]["drive_norm_mean"],
                         "arousal_mean": cp["report"]["arousal_mean"],
                         "top_dn": cp["report"]["top_dn_hist"],
                         "calib": {r["channel"]: r["influence_pct"]
                                   for r in (cp["calibration"] or {}).get("rows", [])}}
    probes = [f["dnprobe"]["delta"] for f in fr if "dnprobe" in f and f["dnprobe"]["drive_l1"] > 0]
    if probes:
        probes.sort()
        out["dn_probe"] = {"n": len(probes), "median_pct": round(100 * probes[len(probes) // 2], 2),
                           "min_pct": round(100 * probes[0], 2),
                           "max_pct": round(100 * probes[-1], 2)}
    return out


def divergences(a: dict, b: dict) -> dict:
    fa, fb = a["frames"], b["frames"]
    n = min(len(fa), len(fb))
    d = [math.dist((fa[i]["x"], fa[i]["z"]), (fb[i]["x"], fb[i]["z"])) for i in range(n)]
    same_label = sum(1 for i in range(n)
                     if (fa[i].get("goal") or {}).get("quest") == (fb[i].get("goal") or {}).get("quest"))
    return {"frames_compared": n,
            "mean_divergence": round(sum(d) / max(1, n), 1),
            "max_divergence": round(max(d) if d else 0.0, 1),
            "final_divergence": round(d[-1] if d else 0.0, 1),
            "frames_same_goal": same_label,
            "frames_diff_goal": n - same_label}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("couple", type=Path, help="прогон со связкой (--llm-couple brain)")
    ap.add_argument("control", type=Path, help="контроль (--llm-couple brain-cut)")
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()
    a = json.loads(args.couple.read_text())
    b = json.loads(args.control.read_text())
    sa, sb = summarize(a), summarize(b)
    div = divergences(a, b)

    print("| Прогон | Кадров | Путь | Финиш | xp | киллы | смерти | Вызовов LLM (ok) | Сдвиг каналов |")
    print("|---|---|---|---|---|---|---|---|---|")
    for tag, s in (("LLM в мозгу (связка)", sa), ("Контроль: связь разорвана", sb)):
        llm = s.get("llm", {})
        cp = s.get("couple", {})
        print(f"| {tag} | {s['frames']} | {s['path_len']} | {s['finish']} | {s['xp']} | "
              f"{s['kills']} | {s['deaths']} | {llm.get('calls')} ({llm.get('ok')}) | "
              f"{cp.get('drive_norm_mean')} |")
    print(f"\nрасхождение траекторий (кадр-в-кадр, {div['frames_compared']} кадров): "
          f"среднее {div['mean_divergence']}, максимум {div['max_divergence']}, "
          f"в конце {div['final_divergence']} юнитов")
    print(f"метка цели совпала в {div['frames_same_goal']} кадрах, различалась в "
          f"{div['frames_diff_goal']}")
    print(f"топ-DN, которые видела LLM: связка "
          f"{sa.get('couple', {}).get('top_dn')}, контроль {sb.get('couple', {}).get('top_dn')}")
    print(f"среднее возбуждение DN: связка {sa.get('couple', {}).get('arousal_mean')}, "
          f"контроль {sb.get('couple', {}).get('arousal_mean')}")
    if sa.get("dn_probe"):
        p = sa["dn_probe"]
        print(f"парный замер вклада в живом такте: {p['n']} замеров, медиана {p['median_pct']} %, "
              f"мин {p['min_pct']} %, макс {p['max_pct']} % масштаба DN")
    if args.out:
        args.out.write_text(json.dumps({"couple": sa, "control": sb, "divergence": div},
                                       ensure_ascii=False, indent=1))
        print(f"файл: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
