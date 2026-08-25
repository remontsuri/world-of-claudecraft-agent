"""analyze_regression_run.py — разбор trajectory по 5 вопросам review.

Запуск после прогона: python analyze_regression_run.py [PID]
"""
import json, sys, collections

path = "D:/world-of-claudecraft/python/autonomous_log.jsonl"
recs = []
with open(path, encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if line.startswith("{"):
            try:
                recs.append(json.loads(line))
            except Exception:
                pass

pids = sorted(set(r.get("pid") for r in recs if r.get("pid")))
pid = int(sys.argv[1]) if len(sys.argv) > 1 else pids[-1]
run = [r for r in recs if r.get("pid") == pid]

print(f"=== REGRESSION RUN PID {pid}: {len(run)} шагов ===")
t0, t1 = run[0].get("t", 0), run[-1].get("t", 0)
print(f"время: {t1 - t0:.0f}s, {len(run)/max(t1-t0,0.1):.2f} шаг/сек\n")

# --- 1. BUY ---
buys = [r for r in run if r.get("action") == "buy"]
bv = collections.Counter(r.get("verdict") for r in buys)
print("1. BUY:")
print(f"   attempts={len(buys)} verdicts={dict(bv)}")
# повторная покупка имеющегося: buy при том же bucket и без дельты
buy_no_delta = sum(1 for b in buys if (b.get("reward") or 0) <= 0 and b.get("verdict") != "success")
print(f"   покупок без результата (candidate для cooldown): {buy_no_delta}")

# --- 2. GATHER ---
gathers = [r for r in run if r.get("action") == "gather"]
gv = collections.Counter(r.get("verdict") for r in gathers)
print("\n2. GATHER:")
print(f"   attempts={len(gathers)} verdicts={dict(gv)}")

# --- 3. QUEST ---
turns = [r for r in run if r.get("action") == "turn_in_quest"]
tv = collections.Counter(r.get("verdict") for r in turns)
qprog = [r.get("qprog") for r in run if r.get("qprog") is not None]
accepts = [r for r in run if r.get("action") == "accept_quest"]
print("\n3. QUEST:")
print(f"   accepts={len(accepts)}, turn_ins={len(turns)} verdicts={dict(tv)}")
if qprog:
    print(f"   objective progress: {qprog[0]} -> {qprog[-1]}")
kills = [r.get("kills") for r in run if r.get("kills") is not None]
if kills:
    print(f"   kills: {kills[0]} -> {kills[-1]} ({kills[-1]-kills[0]:+d})")

# --- 4. AUTONOMY: повторы и стагнация ---
actions_seq = [r.get("action") for r in run]
max_repeat, cur, cur_a = 1, 1, actions_seq[0] if actions_seq else None
for a in actions_seq[1:]:
    if a == cur_a:
        cur += 1
        max_repeat = max(max_repeat, cur)
    else:
        cur_a, cur = a, 1
print("\n4. AUTONOMY:")
print(f"   макс. повтор одного skill подряд: {max_repeat}")
runs_of_5 = sum(1 for i in range(len(actions_seq) - 5)
                if len(set(actions_seq[i:i+5])) == 1)
print(f"   серий 5+ одинаковых действий: {runs_of_5}")
# world-state progress: шаги с ненулевым reward
progress_steps = sum(1 for r in run if abs(r.get("reward") or 0) > 0.01)
print(f"   шагов с |reward|>0.01: {progress_steps}/{len(run)} ({100*progress_steps/max(len(run),1):.0f}%)")
deaths = [r.get("deaths") for r in run if r.get("deaths") is not None]
if deaths:
    print(f"   deaths: {deaths[0]} -> {deaths[-1]} ({deaths[-1]-deaths[0]:+d})")

# --- 5. LEARNING ---
rew = sum(r.get("reward") or 0 for r in run)
rv = collections.Counter(r.get("verdict") for r in run)
print("\n5. LEARNING:")
print(f"   суммарный reward: {rew:+.3f}, mean={rew/max(len(run),1):+.4f}")
print(f"   вердикты все: {dict(rv.most_common(6))}")

# --- VERDICT: deadlock или прогресс ---
print("\n=== ВЕРДИКТ ===")
world_delta = ((kills[-1]-kills[0]) if kills else 0) + (abs(qprog[-1]-qprog[0]) if qprog else 0) + progress_steps
if world_delta == 0:
    print("DEADLOCK: 0 world-state delta за прогон — диагностировать по последним действиям:")
    print("   последние 15:", [(r.get('step'), r.get('action'), r.get('verdict')) for r in run[-15:]])
else:
    print(f"ПРОГРЕСС: kills+{kills[-1]-kills[0] if kills else 0}, "
          f"objective+{abs(qprog[-1]-qprog[0]) if qprog else 0}, "
          f"{100*progress_steps/max(len(run),1):.0f}% шагов меняли мир")
