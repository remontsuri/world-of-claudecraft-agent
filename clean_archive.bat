@echo off
set SRC=D:\world-of-claudecraft\python
set DST=D:\woc_archive\python
del /Q %DST%\*_*.py 2>nul
for %%f in (agent.py bc_nav_model.py browser_env.py hierarchical_env.py llama_agent.py memory.py obs_encoder.py play_autonomous.py policy.py ppo_agent.py quest_capability.py quest_skill.py reward.py verifiers_py.py world_state.py wow_env.py headless_bridge.py experiment_a.py experiment_b2.py experiment_b3.py experiment_b3_control.py experiment_b4.py experiment_real.py train_hierarchical.py train_ppo_from_b1.py train_ppo_full.py nav_features.py oracle_nav_dataset.py example_random_agent.py scripted_agent.py simple_warrior_agent.py llama_selfplay.py debug_episode.py debug_obs.py debug_step.py debug_timer.py test_chains_headless.py test_chain_quest.py test_skills_headless.py) do copy /Y %SRC%\%%f %DST%\
echo CLEANED
dir /b %DST%
