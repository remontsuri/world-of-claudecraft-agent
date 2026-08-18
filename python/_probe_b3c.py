"""Minimal probe: run ONE eval seed through measure_phase with verbose force
logging, MEASURE_STEPS=2. Goal: see whether force_far_mob terminates and where
measure_phase stalls. Imports the real functions from experiment_b3_control."""
import experiment_b3_control as E

E.EVAL_SEEDS = [4242]
E.MEASURE_STEPS = 2

rows = []
print("=== SINGLE-SEED PROBE (seed=4242, measure=2) ===")
r = E.measure_phase("PROBE", E.ExperienceStore(path="probe_b3c.json"), E.EVAL_SEEDS, rows)
print("result:", r["far_mob_decisions"], "decisions, actions:", r["P"])
print("rows:", len(rows))
