---
name: reward-policy-debug
description: Diagnose reward signal and policy divergence in RL agents.
version: 1.0.0
author: WoC
tags: [debugging, reinforcement-learning, reward, policy]
---

# Reward/Policy Debug

Use when:
- `reward/100steps < 0` consistently
- `repeated_error_rate > 10%`
- Q-values diverge (NaN, Inf, or frozen)
- Policy picks same action regardless of state

## Diagnostic Steps

### 1. Reward Signal Audit
```python
rewards = [r.get('reward', 0) for r in run]
print(f"mean={mean(rewards):.4f} std={std(rewards):.4f}")
print(f"positive={sum(1 for r in rewards if r>0)} negative={sum(1 for r in rewards if r<0)}")
```

### 2. Policy Divergence Check
- Is softmax temperature too high (uniform) or too low (greedy)?
- Are Q-values initialized reasonably (not all-zero)?
- Is learning rate causing oscillation or stalling?

### 3. Common Reward Traps

| Trap | Symptom | Root Cause |
|------|---------|------------|
| Negative reward spiral | Agent gets -0.1 per step forever | No positive signal (kills=+0.2 too rare vs step=-0.01) |
| Death penalty too small | Agent farms at hp=0.05 repeatedly | death=-5 vs kill=+0.2; death too infrequent to learn |
| Reward delay | Agent doesn't connect kill to reward | Kill happens 50 steps after the approach |
| Q-value overflow | NaN in Q-table | Unclipped rewards + high learning rate |

### 4. Resolution Protocol
1. Dump reward histogram for last 500 steps
2. Check Q-value range (should be bounded)
3. Verify reward function in `reward.py` matches actual game events
4. Test with fixed policy (no exploration) to isolate signal from noise
