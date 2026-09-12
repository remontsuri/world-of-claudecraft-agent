# Graph Report - world-of-claudecraft  (2026-09-12)

## Corpus Check
- cluster-only mode — file stats not available

## Summary
- 2948 nodes · 5564 edges · 160 communities (138 shown, 18 thin omitted)
- Extraction: 97% EXTRACTED · 3% INFERRED · 0% AMBIGUOUS · INFERRED: 170 edges (avg confidence: 0.9)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `895e1bea`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- ExperienceStore
- ArbitrationLayer
- build_world_state
- autonomy.py
- test_safety.py
- _bucket
- QuestTruth
- GoalFSM
- test_skill_index_contract.py
- action_mask.py
- test_autonomy_core.py
- test_evaluation.py
- test_quest_chain.py
- StrategyMemory
- check_preconditions
- _fsm
- detect_progress
- policy.py
- arbitration.py
- encode_observation
- test_planner.py
- test_failure_analyzer.py
- MockEnv
- AutonomyLoop
- ArbitrationLayer
- _fsm
- puppeteer-core
- test_event_bus.py
- QuestState
- plan_leg
- NpcRegistry
- NavigationController
- WorldMemory
- NavMemory
- SelfReflection
- BoundedExecution
- observation.py
- skill_contracts.py
- verifiers_py.py
- load_spawns
- Skill
- WorkAnchor
- find_next_quest
- BrowserEnv
- outcome_reward
- test_navigate_fallback_when_no_quest
- actions.cjs
- test_decision_trace_smoke.py
- test_quest_target.py
- autonomous_master.py
- CurriculumState
- ExtendedReplayBuffer
- Planner
- _make_agent
- BrowserBridgeError
- ._get_json
- test_canonical_state.py
- test_nav_avoidance.py
- test_quest_cycle.py
- Any
- test_by_id_field_contract.py
- ReplayBuffer
- test_causal_stall.py
- _read
- rich_snapshot
- browser_bridge.cjs
- BrowserBase
- item_prices.py
- QuestCapability
- test_j5_episodic.py
- test_policy_softmax_only.py
- FakeResp
- test_loot_targets.py
- tolerance_for
- planner.py
- main
- QuestChain
- Agent
- HeadlessEnv
- test_combat_kill.py
- test_p3_red.py
- test_quest_phase_mask.py
- test_flee_no_target_falls_back
- ._evaluate
- find_target
- test_arbitration_quest_none.py
- test_autonomy_no_force.py
- verify_quest_turn_in
- load_reflection_hints
- TestQuestLifecycle
- EpisodicLog
- test_giver_position.py
- test_fix1_quest_available.py
- test_learning_signals.py
- ._cycle
- quest_skill.py
- ._log_transition
- test_bounded_harness.py
- test_p0b_regression.py
- test_schema_contract.py
- test_survival_learning.py
- test_turnin_honesty.py
- test_verify_heal_regen.py
- GameClient
- test_heading.cjs
- snapshot.cjs
- GameSource
- test_decision_context_red.py
- verify_gather
- test_gather_precondition.py
- test_plan_stack.py
- test_spin_no_hard_removal.py
- createCmdQueue
- .get_npcs_with_quests
- test_reflection_fixes.py
- test_accept_new_quests.py
- test_gather_bag_cycle.py
- _obs
- TestPolicyNoOverrides
- test_strategy_alive.py
- test_p0_hotpath.py
- test_self_reflection.py
- test_vendor_flag.cjs
- goal_fsm.py
- .step
- test_agent_bridge_review_fixes.py
- test_obs_mobs_spatial.py
- TestWorldEntityFactsSurvive
- test_brain_glue.py
- test_bridge.cjs
- .get_nearby_entities
- .get
- test_policy_fallback.py
- test_verdict_lifecycle.py
- test_fence_jump.cjs
- test_quests_done.cjs
- test_buy_vendor_range.cjs
- offline_train.py
- test_farm_targeting.cjs
- test_respawn_chain.cjs
- .before_action
- game_source.py
- .get_camps
- .get_quest
- .reset
- .find_giver_for_quest
- .to_dict
- test_navigate_timing.cjs
- test_log_goal.py
- _probe_stock.cjs
- test_gather_nav.cjs
- .get_mob
- .explore_command
- .recovery_for
- test_go_to_giver_generates_nav_command
- sanitize_qtable.py

## God Nodes (most connected - your core abstractions)
1. `ExperienceStore` - 119 edges
2. `build_world_state()` - 115 edges
3. `GoalManager` - 103 edges
4. `GoalFSM` - 100 edges
5. `encode_observation()` - 83 edges
6. `AutonomyLoop` - 70 edges
7. `QuestState` - 53 edges
8. `NavigationController` - 43 edges
9. `NpcRegistry` - 41 edges
10. `Planner` - 40 edges

## Surprising Connections (you probably didn't know these)
- `TestHasHealingFromCanonicalState` --uses--> `ExperienceStore`  [INFERRED]
  python/test_by_id_field_contract.py → python/memory.py
- `TestNoDiskWriteInUpdateP02` --uses--> `ExperienceStore`  [INFERRED]
  python/test_p0_hotpath.py → python/memory.py
- `TestHasHealingFromCanonicalState` --uses--> `GoalManager`  [INFERRED]
  python/test_by_id_field_contract.py → python/policy.py
- `test_explicit_context_replaces_hints()` --uses--> `GoalManager`  [INFERRED]
  python/test_decision_context_red.py → python/policy.py
- `test_no_retreat_when_safe()` --uses--> `GoalManager`  [INFERRED]
  python/test_survival_learning.py → python/policy.py

## Import Cycles
- None detected.

## Communities (160 total, 18 thin omitted)

### Community 0 - "ExperienceStore"
Cohesion: 0.05
Nodes (57): ExperienceStore, Tabular value memory over (state_bucket, action)., Restore weights/counts/experiences written by save(). save() serializes…, Atomically persist memory. Write to a temp file in the same directory then…, Append a full experience tuple: (bucket, action, reward, next_bucket,…, J5: return the set of target_mob_ids that have a NEGATIVE episodic outcome for…, max_a' Q(bucket(state), a') for the TD bootstrap target. Standard Q-learning…, Record one (state, action, reward, next_state) and shift the value estimate.… (+49 more)

### Community 1 - "ArbitrationLayer"
Cohesion: 0.06
Nodes (30): ArbitrationLayer, Navigate to quest giver., Verify quest was accepted., Execute quest objective (farm, loot, gather)., Check quest progress., Return to quest giver for turn-in., Verify quest turn-in., Handle respawn state. (+22 more)

### Community 2 - "build_world_state"
Cohesion: 0.07
Nodes (45): _info(), TDD tests for the economy loop (spec:…, 4 ready quests but ws picked an ACTIVE 0/0 one -> turn_in still offered., SKILL_TURN_IN_IF_IMPORTED(), test_craftable_now_field_recipe_with_reagents(), test_inv_by_id_counts_slots(), test_not_craftable_when_reagents_missing(), test_policy_no_craft_without_materials() (+37 more)

### Community 3 - "autonomy.py"
Cohesion: 0.06
Nodes (37): autonomy.py — замкнутый автономный контур (ARCHITECTURE.md §13). Склеивает уже…, DecisionContext, decision_context.py — explicit decision context (ARCHITECTURE-CONSENSUS §12).…, Immutable decision context passed from Autonomy to Policy. One per decision…, assert_recovery_executable(), ladder_for(), ObjectiveBlacklist, plan_recovery() (+29 more)

### Community 4 - "test_safety.py"
Cohesion: 0.07
Nodes (48): _has_healing(), safety.py — Safety gate for the arbitration layer. Single responsibility:…, Есть ли в сумках то, чем heal сработает. Нет данных -> считаем что нет. P0.10:…, Return forced action if safety requires it, else None. Returns: "respawn" if…, Convenience predicate: True if HP is below critical threshold., safety_check(), should_force_heal(), RED -> GREEN: agent must FORCE heal when hp_frac < 0.2, bypassing the policy… (+40 more)

### Community 5 - "_bucket"
Cohesion: 0.08
Nodes (33): WorldState for reward + memory — delegates to the SINGLE shared builder. This…, _world_state_dict(), live_smoke_test.py — verify the fix in the REAL game., _bucket(), Experience / Memory store — the learning loop's long-term memory. Per user…, J5: record an identity-aware episodic memory tied to a specific target (mob…, # NOTE: no per-step decay. Tabular Q-learning is already adaptive — new, Coarse, comparable state key. Intentionally LOSSY so experiences transfer.… (+25 more)

### Community 6 - "QuestTruth"
Cohesion: 0.08
Nodes (32): accept_blocked_by_identity(), is_identity_transition(), _objectives_done(), _progress_of(), QuestTruth, remaining(), Quest Truth Layer — абсолютная истина о состоянии квестов (этап 1, пункт 1).…, ACCEPT законен ТОЛЬКО для квеста, которого нет в логе. (+24 more)

### Community 7 - "GoalFSM"
Cohesion: 0.06
Nodes (27): GoalFSM, Восстановление состояния из файла., Current quest phase (without quest_id suffix). Returns the QuestState name for…, Record a quest as done. Called after successful turn-in., Get the next incomplete objective from the active quest., Запомнить совет от LLM/политики. НЕ меняет цель FSM. Возврат False означает…, Установить цель FSM. Возврат True означает «цель изменилась». Контракт: -…, Возвращает диагностическую информацию. (+19 more)

### Community 8 - "test_skill_index_contract.py"
Cohesion: 0.07
Nodes (32): HierarchicalWoWEnv, hierarchical_env.py — minimal stub for backward compatibility. The original…, Stub — not used in production. Agent uses BrowserEnv instead., assert_skill_indices_match(), check(), parse_bridge_cases(), RuntimeError, skill_index_contract.py — runtime-ассерт «Python SKILLS == индексы моста».… (+24 more)

### Community 9 - "action_mask.py"
Cohesion: 0.09
Nodes (37): available_actions(), endpoint_of(), get_action_mask(), index_of(), mask_candidates(), maskable_skills(), Any, Action masking for the high-level agent skill space. The canonical step… (+29 more)

### Community 10 - "test_autonomy_core.py"
Cohesion: 0.08
Nodes (29): detect_loop(), get_loop_recovery(), LoopGuard, Any, anti_loop.py — Anti-loop system (ARCHITECTURE.md §8). Детекция циклов STATE-…, Одно и то же состояние N шагов подряд — топчемся на месте., Зафиксировать цикл: вернуть recovery и поставить cooldown., Убрать действия на cooldown-е (но не оставить пустой список). (+21 more)

### Community 11 - "test_evaluation.py"
Cohesion: 0.13
Nodes (37): _attempts(), _delta(), _dist_improved_fraction(), evaluate(), _fmt(), format_report(), load_run(), main() (+29 more)

### Community 12 - "test_quest_chain.py"
Cohesion: 0.11
Nodes (34): ChainResult, Quest lifecycle coordinator. Keeps orchestration thin: the policy selects the…, Result of one quest-chain tick., dispatch_objective(), Objective, ObjectiveType, Enum, quest_objective.py — Objective resolution and dispatch. Maps quest objectives… (+26 more)

### Community 13 - "StrategyMemory"
Cohesion: 0.08
Nodes (27): _goal_key(), Стабильный ключ текущего goal для трекинга в памяти., StrategyMemory — какие стратегии РЕАЛЬНО завершали квесты. Переписано…, Множитель веса для политики: >1.0 только для доказанного навыка., Устаревшее имя: раньше писало стратегию из вердиктов шага. Теперь это просто…, ЕДИНСТВЕННЫЙ источник стратегического знания: квест завершён, и последним…, Статистика шагов. НЕ влияет на preference/boost — именно смешение этих двух…, Навык с наибольшим числом ДОКАЗАННЫХ завершений, иначе None. (+19 more)

### Community 14 - "check_preconditions"
Cohesion: 0.09
Nodes (36): check_preconditions(), Проверить предусловия навыка. Возвращает {ok: bool, failed: [названия…, handaxe стоит 20, на руках 14 -> покупка обречена, знать это ЗАРАНЕЕ., Нет данных о цене/наличии -> НЕ пытаться (раньше fail-open)., test_buy_blocked_when_price_exceeds_copper(), test_buy_fail_closed_on_unknown_price_and_stock(), test_preconditions_fail_without_vendor(), test_preconditions_pass_with_vendor_in_range() (+28 more)

### Community 15 - "_fsm"
Cohesion: 0.09
Nodes (14): _fsm(), Full quest lifecycle via update_from_world: NONE -> DO -> RETURN -> DONE., Simulate a complete quest cycle through FSM., Fix5 regression: TURN_IN against incomplete ACTIVE demotes., Death and recovery flow., update_from_world syncs FSM with observed quest state., STREAM J2: FSM must NOT have decide() method., FSM must not contain decision logic. (+6 more)

### Community 16 - "detect_progress"
Cohesion: 0.11
Nodes (31): Проверить постусловия, решить recovery, записать в LoopGuard., classify_outcome(), detect_progress(), _equipment_diff(), _g(), _item_diff(), Any, progress.py — детектор прогресса (ARCHITECTURE.md §9). progress(obs_before,… (+23 more)

### Community 17 - "policy.py"
Cohesion: 0.08
Nodes (23): get_ability_for_class(), get_class_config(), get_playstyle(), get_range_for_class(), Any, class_config.py — конфигурация классов WoC для агента. Источник:…, Возвращает стиль игры: melee или ranged_kite., Возвращает конфигурацию класса по его ID. (+15 more)

### Community 18 - "arbitration.py"
Cohesion: 0.09
Nodes (27): arbitrate(), _bag_survival_sell(), _corpses_nearby(), _giver_distance(), _loot_priority(), _phase_return(), arbitration.py — Single decision point for the agent. Priority-ordered decision…, Loot override: corpses nearby -> loot. (+19 more)

### Community 19 - "encode_observation"
Cohesion: 0.09
Nodes (25): encode_observation(), Собрать observation из WorldState (+ сырой info как fallback)., Тесты Observation Encoder и Action Mask (ARCHITECTURE.md §2, §4). Запуск: cd…, Число в quality — не хлам: игра такого не отдаёт, значит данных нет., junk = quality 'poor' — СТРОКА, как в woc-game/src/sim/content/items.ts.…, test_all_six_blocks_present(), test_dead_mob_is_corpse_not_target(), test_encoder_reads_info_fallback() (+17 more)

### Community 20 - "test_planner.py"
Cohesion: 0.13
Nodes (33): current_subgoal(), plan_subgoals(), Первый (актуальный сейчас) шаг плана., Разложить текущее состояние в последовательность subgoal-ов. Порядок отражает…, Планировщик выдаёт GO_TO_GIVER когда гивер далеко., Планировщик выдаёт ACCEPT когда гивер близко., test_giver_far_produces_go_to_giver_subgoal(), test_giver_near_produces_accept_subgoal() (+25 more)

### Community 21 - "test_failure_analyzer.py"
Cohesion: 0.09
Nodes (24): classify(), FailureAnalyzer, failure_analyzer.py — классификация каждой FAILURE в структурированное знание.…, Накапливает причины неудач и выдаёт агрегированные рекомендации. Это данные для…, Прокормить один шаг; вернуть запись анализа либо None., Топ причин: [(action, cause, count), ...]., Действенные выводы: причины, повторившиеся min_count раз. Возвращает [{action,…, Одна строка для финального summary прогона. (+16 more)

### Community 22 - "MockEnv"
Cohesion: 0.08
Nodes (28): MockAgent, MockEnv, Minimal mock of BrowserEnv for testing QuestChain., Minimal mock of Agent for testing QuestChain., QuestChain.discover finds the best quest giver., QuestChain.discover filters out done quests., QuestChain.resolve_objective returns the first incomplete objective., QuestChain.resolve_target finds the target entity. (+20 more)

### Community 23 - "AutonomyLoop"
Cohesion: 0.16
Nodes (28): AutonomyLoop, Поставить цель навигации и вернуть (команда моста, статус)., Один экземпляр на прогон агента., Стабильный ключ текущей цели для блеклиста., _info(), Update test_autonomy_loop.py for Phase 5 architecture. Phase 5 changes: -…, Минимальный ws: контур толерантен, ему хватает info + пары полей., Phase 5: before_action returns minimal dict. (+20 more)

### Community 24 - "ArbitrationLayer"
Cohesion: 0.12
Nodes (25): ArbitrationLayer, Single decision point for the agent. Priority-ordered decision flow: 1. Safety…, Return (action, ctx, reason). reason: "safety" | "recovery" | "policy" |…, Stable key for current objective (for blacklist)., Force accept_quest when a quest giver with an available quest is nearby. This…, _info(), Update test_arbitration_phase5.py for Phase 5 architecture., Phase 5: Critical HP triggers safety (heal). (+17 more)

### Community 25 - "_fsm"
Cohesion: 0.11
Nodes (10): _fsm(), test_fsm_demote.py — Verify GoalFSM is demoted to a pure state tracker.…, FSM still has state-tracking methods., FSM must NOT have decide() or _handle_* methods., FSM must have a phase property returning the state name., FSM tracks state via update_from_world() — the ONLY method that matters., TestFSMHasPhaseProperty, TestFSMKeptMethods (+2 more)

### Community 26 - "puppeteer-core"
Cohesion: 0.07
Nodes (17): dependencies, puppeteer-core, name, private, version, puppeteer-core, { connect }, path (+9 more)

### Community 27 - "test_event_bus.py"
Cohesion: 0.13
Nodes (24): EventBus, _inv_ids(), _q_ids(), _q_progress(), Event Bus — события мира из дельты снапшотов (этап 1, пункт 2). Зачем (ТЗ…, quest_id -> суммарный прогресс по активным и готовым квестам., Принять снапшот, вернуть список событий (может быть пустым)., _bus() (+16 more)

### Community 28 - "QuestState"
Cohesion: 0.10
Nodes (27): QuestState, Состояния квестового FSM., RED TESTS: FSM persistence, quest cycle, bounded harness. Verifies: - FSM state…, fsm.suggest() must NOT change FSM state (advisory only)., enter_dead() must save quest for respawn recovery., resume_from_dead() must restore quest after death., FSM state must survive save/load cycle., FSM counters (kills, deaths, xp, copper) must persist. (+19 more)

### Community 29 - "plan_leg"
Cohesion: 0.12
Nodes (24): execute(), plan_leg(), Geometric walker over bridge raw_move — the honest replacement for…, Return {'turns': int(-1|0|1), 'forward_ticks': int, 'jump': bool} or None if…, Run up to `legs` plan-and-move cycles via env._raw_move. Returns final pos., _pos(), RED TESTS: facing / turn geometry. Measured facts (skill world-of-claudecraft-…, If already facing the target, plan_leg should NOT issue a turn. (+16 more)

### Community 30 - "NpcRegistry"
Cohesion: 0.10
Nodes (26): NpcRegistry, Canonical NPC registry — единый источник истины об NPC., P0-A: тесты Canonical NPC Registry (FIX #2 + FIX #3)., WorldMemory как fallback для позиции (только если нет лучшего источника)., Snapshot (priority 1) НЕ должен перезаписывать runtime_entity (priority 3)., world_content (priority 2) перезаписывает snapshot (priority 1)., Memory (priority 0) НЕ должен перезаписывать runtime_entity (priority 3)., FIX #3: runtime entity использует templateId как ключ, НЕ entity.id. (+18 more)

### Community 31 - "NavigationController"
Cohesion: 0.19
Nodes (25): NavigationController, Держит текущую цель, историю дистанций и бюджет шагов., _giver(), _mob(), _obs(), Тесты Navigation Controller (ARCHITECTURE.md §6). Запуск: cd python && python…, Живой баг: моб в 32 yd, farm возвращал NO_OP, агент топтался., test_arrived_when_within_tolerance() (+17 more)

### Community 32 - "WorldMemory"
Cohesion: 0.11
Nodes (13): Record (or refresh) the turn-in NPC for a quest., Return {x,z} for the turn-in NPC of a quest, or None if unknown., Compatibility shim: agent.py reads active_quest/pending_quest as if WorldMemory…, WorldMemory, Walk to turn-in NPC (short nav) and call turn_in_quest. Returns SUCCESS /…, turn_in_quest(), FakeBase, FakeEnv (+5 more)

### Community 33 - "NavMemory"
Cohesion: 0.12
Nodes (18): _cell(), NavMemory, nav_memory.py — Navigation Memory (план 2026-08-24, п.5, отдельным изменением).…, Маршрут проблемный? >=STUCK_THRESHOLD неудач ПОДРЯД в конце окна. «Хожу по…, Стабильный ключ маршрута по ячейкам., Начало движения. Возвращает ключ маршрута (или None)., Итог попытки: дошли ли + насколько сократилась дистанция., route_key() (+10 more)

### Community 34 - "SelfReflection"
Cohesion: 0.08
Nodes (19): Feed one step record (autonomous_log-style dict). Extended (STREAM J4) to…, Detect a causal chain: farm mob#ID -> mob dies -> loot -> no progress. The…, Run the review; append conclusions to journal; return them., Rolling self-review over the recent step records + persistent journal., Принять события Event Bus за шаг (QuestCompleted, PlayerDied, NavigationStuck,…, Вербальные уроки из событий (Reflexion: событие -> урок -> правило). Каждый…, SelfReflection, Правило NAVIGATION_STUCK: застревание -> вербальный урок -> подавление. (+11 more)

### Community 35 - "BoundedExecution"
Cohesion: 0.11
Nodes (9): BoundedExecution, bounded_execution.py — bounded execution guarantees for autonomous agent.…, Record a step's outcome. Call this AFTER each learning step. Args: action: the…, Return current bound status for logging., Track all execution bounds and detect breaches. Usage: bounds =…, Install SIGTERM/SIGINT handler to trigger graceful shutdown., Check all bounds. Returns (should_stop, reason). Call this at the TOP of every…, BoundedExecution stops runaway loops. (+1 more)

### Community 36 - "observation.py"
Cohesion: 0.11
Nodes (25): _bearing_of(), _buy_available(), _buy_price(), _buy_target(), _dist_of(), _relative_angle(), _entities(), _is_kind() (+17 more)

### Community 37 - "skill_contracts.py"
Cohesion: 0.10
Nodes (24): all_predicates(), all_skills(), assert_predicates_implemented(), get_skill_contract(), _pred(), Any, RuntimeError, skill_contracts.py — формальные контракты навыков (ARCHITECTURE.md §3). Каждый… (+16 more)

### Community 38 - "verifiers_py.py"
Cohesion: 0.13
Nodes (24): test_buy_verifier_gives_failure_not_inconclusive(), test_heal_success_still_works(), test_heal_without_potion_is_failure(), _corpse_exists(), _equip_slot(), _inv_total(), _item_count(), _junk_items() (+16 more)

### Community 39 - "load_spawns"
Cohesion: 0.13
Nodes (22): _find_mob_for_item(), _load_export(), load_spawns(), _load_zone(), nearest_spawn(), nearest_spawns(), _parse_collect_drops(), _parse_spawn_zones() (+14 more)

### Community 40 - "Skill"
Cohesion: 0.11
Nodes (8): create_primitive_skills(), ensure_library_initialized(), skill_library.py — persistent skill library for WoC agent. Each skill has: -…, Find skills similar to the goal using simple keyword matching., Create the base set of primitive skills., Ensure the skill library exists with primitive skills., Skill, SkillLibrary

### Community 41 - "WorkAnchor"
Cohesion: 0.11
Nodes (17): Пустая позиция не должна становиться якорем — иначе запомним пустоту., Если якоря ещё нет, цель возврата — гивер активного квеста., Шаг #3 (Q6, консенсус): агент запоминает позицию, где были объекты действия…, test_anchor_ignores_empty_surroundings(), test_anchor_persists_across_instances(), test_anchor_records_position_when_object_present(), test_needs_return_when_far_and_nothing_around(), test_no_return_when_objects_are_around() (+9 more)

### Community 42 - "find_next_quest"
Cohesion: 0.09
Nodes (23): filter_done_quests(), find_next_quest(), quest_chaining.py — Post-turn-in quest chaining. After a quest is turned in,…, Filter NPCs to those with at least one non-done quest., Select the best quest from candidates (closest, lowest distance)., Find the next available quest giver, excluding done quests. Priority: 1. NPC…, select_best_quest(), filter_done_quests excludes NPCs where all quests are done. (+15 more)

### Community 43 - "BrowserEnv"
Cohesion: 0.13
Nodes (11): BrowserEnv, Decode a Transfer-Encoding: chunked body into the raw payload., POST and raise BrowserBridgeError on ok:false so the Agent records ENV_ERROR…, Apply one skill action (idx). Returns (obs, reward, done, truncated, info) like…, Walk to (tx,tz). Returns True if arrived. Used by return_to_giver. `timeout`…, Send a single raw movement through the bridge (forward/back/turnLeft/…, Release spirit + resurrect at healer (online-safe glue; does NOT mutate the…, Sustained exploration: walk toward nearest mob/NPC (or forward) for `steps`… (+3 more)

### Community 44 - "outcome_reward"
Cohesion: 0.15
Nodes (13): outcome_reward(), Reward computation — from FACT, not from our interpretation. Per user…, Compute reward strictly from observed world deltas., Reward is computed from world deltas, not opinions., TestKillReward, test_death_penalty_dominates_kill_signal(), test_kill_is_positive_without_hp_loss(), _state() (+5 more)

### Community 45 - "test_navigate_fallback_when_no_quest"
Cohesion: 0.09
Nodes (7): TDD for navigate -> spawn targeting (agent.py navigate handler)., Without an active quest, navigate falls back to explore_walk., When active quest has spawn, navigate should call _navigate_to_coord toward it., When quest has no spawn data, navigate falls back to explore_walk., test_navigate_fallback_when_no_quest(), test_navigate_fallback_when_spawn_not_found(), test_navigate_toward_spawn()

### Community 46 - "actions.cjs"
Cohesion: 0.13
Nodes (15): applyAction(), createActions(), rawMoveHandler(), respawnHandler(), EASTBROOK_GATHER_NODES, exploreWalk(), { fenceHopPlan }, fs (+7 more)

### Community 47 - "test_decision_trace_smoke.py"
Cohesion: 0.17
Nodes (20): _canonical_json(), _close_trace_file(), DecisionTrace, decompose_reward(), make_decision_trace(), Any, Canonical telemetry record for every agent decision., Single factory for the canonical trace schema. (+12 more)

### Community 48 - "test_quest_target.py"
Cohesion: 0.21
Nodes (21): _mob_matches(), _pick_target(), Совпадает ли моб с id квестовой цели. В снапшоте id бывает и templateId…, Квестовый моб приоритетнее ближайшего; среди квестовых — ближайший. Не…, _info(), _mob(), Тесты выбора цели боя: квестовый моб vs ближайший (аудит P0.5). Запуск: cd…, Ключевой кейс ревью: кабан 4 yd, квестовый волк 12 yd. (+13 more)

### Community 49 - "autonomous_master.py"
Cohesion: 0.26
Nodes (19): _dead(), _hp_frac(), _in_combat(), _live_mobs(), _lock(), main(), _player(), _player_pos() (+11 more)

### Community 50 - "CurriculumState"
Cohesion: 0.12
Nodes (10): CurriculumState, curriculum.py — automatic curriculum for WoC agent. Manages skill progression:…, Tracks curriculum progress., Get the next uncompleted goal at the current level., Advance to the next level if current level is complete., Mark a goal as completed., Mark a skill as mastered., Mark a skill as unstable. (+2 more)

### Community 51 - "ExtendedReplayBuffer"
Cohesion: 0.11
Nodes (14): make_extended_replay(), Build an ExtendedReplayBuffer for this store's learning loop. Defaults to a…, ExtendedReplayBuffer, Begin a new episode; subsequent transitions get a fresh episode_id., Store a transition, stamping the current episode_id if absent. Sampling weight:…, Build (create_transition) + store in one call, stamping the episode., Most recent FAILURE transitions for `skill`, newest first (max `limit`)., Fraction of stored transitions for `skill` that are SUCCESS. Returns 0.0 when… (+6 more)

### Community 52 - "Planner"
Cohesion: 0.18
Nodes (16): Planner, Держит план и min-dwell, чтобы агент не дёргал цель каждый шаг. STREAM J3…, Сбросить удержание цели: следующий step обязан перепланировать. Нужно recovery-…, Шаг выполнен: снять его с плана, следующий станет текущим., _obs(), test_planner_advisor.py — verify advisor_context returns correct structure.…, advisor_context must return context, not force a skill choice., test_advisor_context_accept_quest() (+8 more)

### Community 53 - "_make_agent"
Cohesion: 0.11
Nodes (11): _make_agent(), Unit tests for the respawn recovery state machine (design: variant A). These…, revived=False, False, True -> proceeds (no pause); respawn retried <= max., Integration smoke: force death -> respawn -> verify revived via real bridge.…, Build an Agent with a stub env whose respawn() returns items from respawn_seq.…, revived=True -> cycle does not pause; a normal 'farm' action is produced., revived=False three times -> early ENV_ERROR return, no skill executed., test_respawn_failure_pauses_as_env_error() (+3 more)

### Community 54 - "BrowserBridgeError"
Cohesion: 0.13
Nodes (13): BrowserBridgeError, RuntimeError, browser_env.py — online WoC environment adapter for the Python Agent.…, Fetch real bridge health; never use stale game state for recovery., Infrastructure failure: the bridge/CDP/HTTP transport is down or rejected the…, _quest_ids(), Live integration/regression test for BrowserBase.turn_in_quest. Unlike…, Regression: the real turn-in command must reach sim.turnInQuest(qid). (+5 more)

### Community 55 - "._get_json"
Cohesion: 0.10
Nodes (10): Evaluate and parse JSON result., Get specific NPC by ID., Get all quest definitions from the game., Get player's current quest log., Get all zone definitions., Get specific zone by ID., Get all item definitions., Get all ability definitions. (+2 more)

### Community 56 - "test_canonical_state.py"
Cohesion: 0.18
Nodes (18): _info(), test_canonical_state.py — Task 1: canonical WorldState. Every field in ws MUST…, Без сущностей КАЖДЫЙ блок world пуст. Раньше проверялся точный набор из трёх…, test_existing_bucket_fields_preserved(), test_inventory_free_slots_from_bag_capacity(), test_inventory_quest_items_from_quest_objectives(), test_mana_and_max_mana_raw_from_player(), test_mana_none_when_game_has_no_mana() (+10 more)

### Community 57 - "test_nav_avoidance.py"
Cohesion: 0.17
Nodes (19): _giver(), _obs(), K-NAV-001 RED tests: navigation with obstacle avoidance. When the agent is…, After max_steps, TIMEOUT must fire even with detour attempts., When STUCK (not moving at all), recovery should trigger a jump/unstuck., Detour waypoint should not be absurdly far from current position., recovery_for(BLOCKED) must return alternate_route., Agent must not crash or loop forever when blocked repeatedly. (+11 more)

### Community 58 - "test_quest_cycle.py"
Cohesion: 0.10
Nodes (19): RED TESTS: quest cycle (accept -> objective -> turn-in -> next quest). Verifies…, When a quest is accepted (ACTIVE), FSM must be in DO_OBJECTIVE., When quest objectives complete (READY_TO_TURN_IN), FSM must return., When quest is DONE, FSM must be in DONE., When quest is cleared (NONE) after DONE, FSM must reset., When quest is cleared (NONE) after ERROR, FSM must reset., build_world_state must produce quest_status=ACTIVE for active quest., build_world_state must produce quest_status=READY_TO_TURN_IN for complete quest. (+11 more)

### Community 59 - "Any"
Cohesion: 0.14
Nodes (9): Any, Обновить из WorldMemory (persisted) — низший приоритет., Обновить из snapshot (live bridge data) — средний приоритет. FIX #3: ключ =…, Все гиверы (NPC с quest_ids)., Извлечь роли из определения NPC., Resolve canonical registry key. Priority: npc_id > template_id > name. Never…, Check if new source can update position (FIX #2). If no position exists yet,…, Обновить из worldContent.npcs (static content). (+1 more)

### Community 60 - "test_by_id_field_contract.py"
Cohesion: 0.16
Nodes (12): _has_healing(), Есть ли в сумках то, чем heal сработает. Нет данных -> считаем что нет., P0.10 — inventory_by_id vs inv_by_id: имя поля разъехалось между слоями.…, Сквозная проверка: раненый + зелье -> heal среди кандидатов., Canonical WorldState обязан отдавать инвентарь по стабильному имени., Имя, которое читают потребители, должно существовать в ws., Пока живут оба имени, они обязаны совпадать, а не расходиться., _has_healing обязан работать от canonical ws без помощи моста. (+4 more)

### Community 61 - "ReplayBuffer"
Cohesion: 0.13
Nodes (10): Replay Buffer — store transitions, prioritize RARE events. Per user 2026-08-20:…, transition = { state, action, reward, next_state, done, goal, skill, event…, Sample n transitions with probability proportional to _w. Falls back to uniform…, JSON serializer — поддержка set, frozenset, NpcRegistry и объектов с __json__., ReplayBuffer, set_to_list(), _fresh(), test_replay_persistence.py — regression для 64ea6ad. Баг: transition с set… (+2 more)

### Community 62 - "test_causal_stall.py"
Cohesion: 0.19
Nodes (18): _fresh(), Tests for SelfReflection causal chain learning (STREAM J4)., When target mob never dies, NO CAUSAL_STALL., CAUSAL_STALL hint must be 'exclude_target' so policy can act on it., When one mob advances quest and another doesn't, only the bad one is excluded., CAUSAL_STALL conclusion is written to journal and survives restart., Build a step record with all fields (including STREAM J4 target info)., When mob#152 is farmed, dies, looted, but qprog frozen -> CAUSAL_STALL. (+10 more)

### Community 63 - "_read"
Cohesion: 0.13
Nodes (11): P0.3: _cycle.log I/O в горячем цикле должен быть за env-гейтом., Ни один open() лог-файла не должен вызываться без проверки флага., Поведенческая: без WOC_TRACE вызов _trace() не создаёт файл., Обратная сторона: с WOC_TRACE=1 трассировка обязана писать., P0.4: сломанный контракт при WOC_AUTONOMY=1 обязан остановить процесс., WOC_AUTONOMY=0 — единственный законный путь к legacy-режиму., Сбой контура в горячем цикле обязан считаться, а не тонуть в traceback., nav_command обходит agent.step() — такие шаги нельзя звать переходами. (+3 more)

### Community 64 - "rich_snapshot"
Cohesion: 0.11
Nodes (10): facts_of(), Плоская выжимка фактов observation, которые читают контракты., Квестовая цель обязана переживать переход., Игрок: уровень и мана — вход в классовые предикаты., Обобщение: ни один факт не должен молча исчезать на границе., Снапшот, в котором ЕСТЬ каждый факт, читаемый контрактами. Все id предметов и…, rich_snapshot(), TestNoSilentDrop (+2 more)

### Community 65 - "browser_bridge.cjs"
Cohesion: 0.12
Nodes (14): actions, { buildSnapshot }, client, CMD_TIMEOUT_MS, { createActions }, { createCmdQueue }, dispatch(), fs (+6 more)

### Community 66 - "BrowserBase"
Cohesion: 0.13
Nodes (10): BrowserBase, Low-level action interface (ACT_* indices) for quest_skill.explore. quest_skill…, Server-side turn-in via the bridge (2026-08-25). quest_capability.turn_in()…, _FakeRequireEnv, test_browser_base_turnin.py — BrowserBase.turn_in_quest существует и работает.…, Ловит payload вместо реального HTTP., Полная цепочка: capability.turn_in -> base.turn_in_quest -> SUCCESS., test_browser_base_has_turn_in_quest() (+2 more)

### Community 67 - "item_prices.py"
Cohesion: 0.16
Nodes (16): buy_price(), is_junk_item(), is_junk_quality(), item_quality(), price_from_snapshot(), Any, item_prices.py — цены предметов ИЗ ИСХОДНИКОВ игры (P0.4). Источник: woc-…, Цена покупки в медяках, None если неизвестна. (+8 more)

### Community 68 - "QuestCapability"
Cohesion: 0.14
Nodes (6): QuestCapability, Walk to the turn-in NPC. Returns SUCCESS if within interact range. Uses SHORT…, The quest that CAN be turned in right now (state == ready)., An NPC near the player that offers a quest (has non-empty questIds)., Observable fact for the policy — NOT a trigger. A quest is READY_TO_TURN_IN…, Return current/required per objective (server-authoritative counts).

### Community 69 - "test_j5_episodic.py"
Cohesion: 0.15
Nodes (17): _info_with_target(), J5 regression: identity-aware episodic memory. Acceptance criteria: -…, After failure on mob#152, policy.decide() suppresses farm on that target., Episodic memory survives save/load., Minimal world state dict for testing., When there's no target, episodic recording is a no-op (no crash)., Minimal info dict with a targeted mob (dead) and a live mob nearby., ExperienceStore.record_episodic stores target_mob_id. (+9 more)

### Community 70 - "test_policy_softmax_only.py"
Cohesion: 0.18
Nodes (12): _gm(), _info(), test_policy_softmax_only.py — Verify policy only samples, doesn't override.…, When candidates exist and no override fires, action is valid for phase., When no candidates exist, fallback to farm (default exploration)., Verify _candidates() accepts phase and advisor params., _candidates() should accept a phase parameter., _candidates() should accept an advisor parameter. (+4 more)

### Community 71 - "FakeResp"
Cohesion: 0.17
Nodes (10): Текущая цель FSM для логирования., FakeResp, _ok_content(), test_decide_parses_valid(), fake_urlopen(), test_garbage_json_returns_none(), test_invalid_goal_returns_none(), test_prompt_contains_world_and_failures() (+2 more)

### Community 72 - "test_loot_targets.py"
Cohesion: 0.23
Nodes (16): _matches(), _cleanup(), _info(), _policy(), Тесты: лут — труп МОБА, а не декорация мира. Живой баг (замер agent_run5.log):…, Труп в 40 ярдах — работа навигации, а не повод звать loot., Главный тест: именно он ловит 153 холостых шага., test_dead_mob_is_a_corpse() (+8 more)

### Community 73 - "tolerance_for"
Cohesion: 0.13
Nodes (11): Обновить состояние по новому observation и вернуть статус., Допуск «дошли» для типа цели. Для моба зависит от класса., tolerance_for(), test_giver_tolerance_is_inside_game_gate(), test_mob_tolerance_is_class_dependent(), test_node_tolerance_inside_interact_range(), test_vendor_tolerance_inside_buy_gate(), Different classes have different attack ranges. (+3 more)

### Community 74 - "planner.py"
Cohesion: 0.15
Nodes (15): _can_heal(), _has_tool(), _plan_for_objective(), Any, planner.py — Planner выше PPO (ARCHITECTURE.md §5). PPO не должен с нуля…, Шаги под конкретную цель квеста., Какой инструмент нужен для gather-цели (None если не нужен)., Записать результат шага для memory-aware planning. Вызывается из… (+7 more)

### Community 75 - "main"
Cohesion: 0.17
Nodes (15): _acquire_lock(), cell_of(), main(), _excepthook(), _log_lifecycle(), snap(), play_autonomous.py — persistent autonomous game session (Level 3). NOT a…, Coarse position cell for exploration tracking. (+7 more)

### Community 76 - "QuestChain"
Cohesion: 0.18
Nodes (7): QuestChain, Advance the quest state machine by one bounded, observable transition., Advance one step of the quest lifecycle from current world state.…, Canonical completed-quest set owned by Agent., Find the best available quest giver not present in ``agent.done_ids``., Navigate, accept, then verify the quest is ACTIVE., Navigate, turn in, and rely on QuestCapability's authoritative verification.

### Community 77 - "Agent"
Cohesion: 0.17
Nodes (10): Agent, One full learning-cycle iteration., Set the AutonomyLoop and create the ArbitrationLayer., Run n learning-cycle steps. Optionally accept the welcome quest first (so there…, Accept the nearest available quest IF none is active yet. Online interface:…, Machine-actionable hints aggregated from the journal tail. Returns…, _fake_env(), R4: the live Agent must wire reflection hints into its GoalManager. Yesterday's… (+2 more)

### Community 78 - "HeadlessEnv"
Cohesion: 0.18
Nodes (8): main(), Headless nav training: teach the agent to walk TO a point. Reward = distance…, bucket(), HeadlessEnv, main(), Quick offline training: tabular Q-learning against the HEADLESS env server.…, NDJSON client over env_server.cjs stdin/stdout., Coarse key from the obs vector: hp_frac, in_combat, nearby count.

### Community 79 - "test_combat_kill.py"
Cohesion: 0.16
Nodes (15): _info(), RED TESTS: combat damage, kill, kill reward. Verifies the kill signal chain:…, GoalFSM.total_kills should increment when kills happen., A kill between before/after must register as SUCCESS., A kill must produce reward >= 1.0 (WEIGHTS['kills']=0.5 + success_bonus=0.5)., Each kill delta gives the same reward (per-kill-delta contract)., Death must produce FAILURE verdict and negative reward., Without a kill, no kill bonus should be given. (+7 more)

### Community 80 - "test_p3_red.py"
Cohesion: 0.18
Nodes (7): _mob(), P3 RED TESTS: navigation, facing, target, combat, kill, quest, respawn, FSM…, If player turns 90 degrees right, a mob that was straight ahead is now at -pi/2…, Quest mob is prioritized over nearest mob., Observation encodes angle RELATIVE to player facing, not world north., TestFacing, TestTargetSelection

### Community 81 - "test_quest_phase_mask.py"
Cohesion: 0.17
Nodes (15): _fake_info(), Tests for the quest-phase truth + action-mask fix. These run WITHOUT a live…, When complete, turn_in_quest is a candidate and accept_quest is not., explore must not appear while a quest is active (no drift to fences)., Build a minimal env info dict with the given quests.active list., A freshly-accepted quest (bridge reports 0/0, no objectives) must be ACTIVE., objectives present but current<required -> ACTIVE (not READY)., every current>=required AND objectives present -> READY (complete=True). (+7 more)

### Community 82 - "test_flee_no_target_falls_back"
Cohesion: 0.12
Nodes (7): TDD for flee action — uses REAL bridge snapshot format (player_pos, targetId,…, When targetId is null but hostile mob nearby, flee from it., Verify flee navigates away from target (opposite direction)., Without a target, flee does nothing (no crash)., test_flee_fallback_to_nearest_hostile(), test_flee_no_target_falls_back(), test_flee_runs_away_from_target()

### Community 83 - "._evaluate"
Cohesion: 0.13
Nodes (8): run(), Any, Get state of a specific quest., Get current player position [x, z]., Get current player facing., Get current player HP fraction., Check if player is dead., Evaluate JS expression in the game tab.

### Community 84 - "find_target"
Cohesion: 0.19
Nodes (12): _find_matching(), find_target(), Any, navigation.py — Navigation Controller (ARCHITECTURE.md §6). Навигация отделена…, Ближайшая сущность нужного типа с координатами ИЗ ИГРЫ. Если по name_hint…, Назначить цель. Сброс бюджета только при СМЕНЕ типа цели., Команда для моста: {'action':'navigate','x':..,'z':..}., target_kind_for_subgoal() (+4 more)

### Community 85 - "test_arbitration_quest_none.py"
Cohesion: 0.30
Nodes (14): _info(), _make_arbitration_layer(), _make_policy(), test_arbitration_quest_none.py — RED test for farm→loot→heal loop fix. Bug:…, QUEST_NONE + quest giver far + available quest → navigate to giver. If the…, QUEST_NONE + no quest giver nearby → policy decides (farm is OK). When there's…, QUEST_NONE + giver nearby but all quests done → no accept_quest. If the only…, Create an ArbitrationLayer with a fresh AutonomyLoop. (+6 more)

### Community 86 - "test_autonomy_no_force.py"
Cohesion: 0.25
Nodes (14): _info(), test_autonomy_no_force.py — verify before_action doesn't force skills. Phase 5:…, Phase 5: before_action still returns advisor context., Phase 5: When planner says FIND_MOB, before_action must NOT force explore., Phase 5: When agent is far from giver, before_action must NOT force…, Phase 5: before_action no longer builds DecisionContext., Phase 5: before_action should NOT emit any signals., test_before_action_no_anchor_force() (+6 more)

### Community 87 - "verify_quest_turn_in"
Cohesion: 0.25
Nodes (14): Согласовано с со-диагностом (D4): в ОНЛАЙНЕ ведро done всегда пусто —…, Квест ушёл из лога, но счётчик не вырос -> сервер отклонил (или ресинк). Это НЕ…, Квест остался в ready -> сдача не состоялась (сервер молча отказал: далеко от…, Офлайн-путь (headless-сим) кладёт квест в done — старое поведение живо., Даже без известного quest_id рост счётчика — доказательство сдачи., _snap(), test_counter_growth_without_handle_still_success(), test_disappeared_without_counter_growth_is_failure() (+6 more)

### Community 88 - "load_reflection_hints"
Cohesion: 0.23
Nodes (11): ExperienceStore, Reload reflection hints from the journal into the live policy. from policy…, load_reflection_hints(), Load machine hints from self_reflection.json (the SelfReflection journal).…, _journal(), Fix4 regression: reflection hints must EXPIRE. 2026-08-23: spin:turn_in_quest…, A hand-written or corrupt entry without t is unusable for TTL -> drop., test_entry_without_timestamp_dropped() (+3 more)

### Community 89 - "TestQuestLifecycle"
Cohesion: 0.22
Nodes (8): integration, _post(), fixture, test_quest_lifecycle.py — детерминированный полный цикл квеста на живой игре.…, Активный kill/gather квест прогрессирует до READY за N шагов farm/gather.…, READY-квест: turn_in_quest -> quests_done+1 И квест покинул active., _snapshot(), TestQuestLifecycle

### Community 90 - "EpisodicLog"
Cohesion: 0.23
Nodes (7): EpisodicLog, _norm(), Episodic memory: one jsonl line per attempt (the agent's own experience). Feeds…, test_append_and_recent_by_quest(), test_corrupt_lines_skipped(), test_missing_fields_tolerated(), test_recent_failures_only_failures()

### Community 91 - "test_giver_position.py"
Cohesion: 0.19
Nodes (12): npc_registry.py — Canonical NPC registry. P0-A: единый runtime слой для NPC,…, _obs_with_giver(), P0-B: тесты giver_position_known., giver_position_known = True, если позиция гивера известна в registry., giver_position_known = False, если позиция неизвестна., giver_reachable используется для recovery routing., giver_exists работает без npc_registry (fallback)., Создать obs с гивером. (+4 more)

### Community 92 - "test_fix1_quest_available.py"
Cohesion: 0.22
Nodes (13): _make_ws(), FIX #1 regression: quest_available uses questState, not just bool(givers). Iron…, quest_states отсутствует → fail-closed (False), не паника., 3 NPC разные квесты, только один available., Build a minimal world state for encode_observation., Железный invariant: 11 NPC с questIds но ни один quest не available. Симулирует…, test_givers_with_available_quest(), test_givers_with_done_quest_not_available() (+5 more)

### Community 93 - "test_learning_signals.py"
Cohesion: 0.21
Nodes (13): _info(), Шаг 1. Найдено со-аудитором: world_state брал quests_done из поля, которое в…, Офлайн-сим (headless) кладёт квесты в ведро done и не заполняет поле., Приёмка A1: завершение квеста обязано давать ≥ +5.0., Приёмка A4. Найдено со-аудитором: success_bonus=0.5 платился за ЛЮБОЙ вердикт…, Обратная сторона: реальный прогресс мира по-прежнему оплачивается., Провал остаётся наказуемым независимо от дельты мира., test_failure_penalty_survives() (+5 more)

### Community 94 - "._cycle"
Cohesion: 0.17
Nodes (8): Persist NPC facts observed by the live browser without steering policy., Execute one skill, return (after_info, verdict, outcome_kind)., Controlled training probe: execute ONE specific action (real world effect),…, One cycle with memory FROZEN — used for honest BEFORE/AFTER measurement.…, Пишет строку трассировки, если WOC_TRACE включён. Держит один открытый handle…, Resolve giver (x, z) for accept_quest navigation. Order (game truth wins over…, resolve_giver_pos(), _trace()

### Community 95 - "quest_skill.py"
Cohesion: 0.15
Nodes (10): quest_state_for_policy(), QuestCapability — thin, script-free wrappers over the existing capability API.…, Helper: best active-quest status string for the WorldState., complete_quest_objective(), QuestSkill (atomic capabilities) — tools, NOT a hidden GoalManager. Per user…, ONE SHORT leg toward the turn-in NPC. Atomic, measurable, non-terminal.…, Sell junk using remembered vendor knowledge. This is an atomic capability: it…, ONE attempt at the active quest's first incomplete objective. Returns SUCCESS… (+2 more)

### Community 96 - "._log_transition"
Cohesion: 0.17
Nodes (6): Сохранение состояния., Агент воскрес — сохраняем квест и гивер., Агент умер — переводим FSM в RESPAWN, сохраняя квест., Агент воскрес — восстанавливаем квест., Записывает причину неудачи для анализа., Логирует переход между состояниях (P0: телеметрия).

### Community 97 - "test_bounded_harness.py"
Cohesion: 0.17
Nodes (11): BOUNDED HARNESS: FSM stress test — never crashes, never invalid state. After…, Exhaustively test all (state, quest_status) combinations., Random walk through states — FSM must never crash., STREAM J2: FSM must NOT have decide() — decision logic moved to…, FSM state must always be a valid QuestState after any update_from_world call., All nav recovery actions must be valid skill names or None., test_bounded_harness_all_combinations(), test_bounded_harness_random_walk() (+3 more)

### Community 98 - "test_p0b_regression.py"
Cohesion: 0.23
Nodes (11): _make_obs(), P0-B regression: target-aware action planning. Проверяет, что: - giver 3 yd →…, Создать obs для тестов., giver 3 yd → accept_quest не блокируется дистанцией., giver 12 yd → accept_quest блокируется, но навигация должна помочь., giver неизвестен → giver_position_known = False., quest недоступен → accept_quest заблокирован., test_giver_far_navigate_first() (+3 more)

### Community 99 - "test_schema_contract.py"
Cohesion: 0.26
Nodes (11): _info_from_bridge(), fixture, test_schema_contract.py — контракт snapshot -> WorldState -> policy ->…, needs_tool учитывает wield-гейт игры: инструмент в сумке + proficiency.…, snap(), _snapshot(), test_inventory_by_id_matches_inventory(), test_inventory_canonical_item_id() (+3 more)

### Community 100 - "test_survival_learning.py"
Cohesion: 0.24
Nodes (11): _fake_info(), TDD tests for the survival-learning fixes (user report 2026-08-22): The agent…, At low-but-not-crit HP with an active quest, retreat must be a candidate., danger (hp<0.3... no: in_combat) + active quest + hp>=0.35 -> retreat., When healthy, the phase gate should still hold (no premature return)., test_bucket_distinguishes_strong_mob(), test_bucket_stable_when_neither(), test_no_retreat_when_safe() (+3 more)

### Community 101 - "test_turnin_honesty.py"
Cohesion: 0.21
Nodes (10): _ctx(), Fix2 regression: a REJECTED turn-in must be a FAILURE, not INCONCLUSIVE.…, Quest ready before, STILL ready after (server rejected): failure., Quest ready before, gone from ready and present in done after: success., No quest-log evidence at all -> cannot judge: inconclusive., Attempted turn-in on an ACTIVE (not ready) quest that stayed active: also a…, test_active_untouched_by_turnin_is_failure(), test_missing_before_info_stays_inconclusive() (+2 more)

### Community 102 - "test_verify_heal_regen.py"
Cohesion: 0.17
Nodes (11): RED -> GREEN: verify_heal must accept 'success' when regen (out-of-combat auto-…, h1 > h0 -> success (potion, food, or regen)., h1 >= maxHp -> success (full heal)., Regen (out-of-combat) raised HP from 80 to 92 -> 92% > 90% threshold., h0 == h1 AND in_combat=True (regen blocked) AND no potion -> failure., h0 == h1, in_combat=False, h1>0 -> success (regen path ran, snapshot timing)., test_heal_failure_when_no_supplies_and_hp_stuck(), test_heal_success_when_hp_at_max() (+3 more)

### Community 103 - "GameClient"
Cohesion: 0.35
Nodes (4): DEFAULT_TAB_MATCH, GameClient, puppeteer, tabMatches()

### Community 104 - "test_heading.cjs"
Cohesion: 0.23
Nodes (7): decideTurn(), faceTargetPlan(), normalizeAngle(), assert, { faceTargetPlan, FACE_EPS }, assert, { decideTurn, normalizeAngle, TURN_START, TURN_STOP }

### Community 105 - "snapshot.cjs"
Cohesion: 0.21
Nodes (11): buildSnapshot(), EASTBROOK_NPC_POS, EASTBROOK_QUEST_TURNIN, EXPORT, FARSHORE_NPC_POS, FARSHORE_QUEST_TURNIN, fs, loadWorldMemory() (+3 more)

### Community 106 - "GameSource"
Cohesion: 0.18
Nodes (6): GameSource, Get all mob templates from the game., Get all gather node definitions., Connects to running WoC game via CDP and provides live access to game data., Connect to the game tab via CDP., Close CDP connection.

### Community 107 - "test_decision_context_red.py"
Cohesion: 0.25
Nodes (10): _fake_info_ws(), _make_policy(), RED test: ONE DECISION CYCLE invariant. Current bug: AutonomyLoop writes to…, After fix: policy.decide() accepts explicit context, ignores hints. This test…, Minimal info/ws so policy.decide() doesn't crash., Invariant: policy.hints must NOT influence decide() output. If Autonomy writes…, Invariant: autonomy_subgoal hint must NOT be a hidden force command. Autonomy…, test_autonomy_subgoal_hint_does_not_force() (+2 more)

### Community 108 - "verify_gather"
Cohesion: 0.33
Nodes (10): Найдено измерением 2026-08-24: 25 подряд gather при ПОЛНОМ отсутствии…, Если объект БЫЛ (мост его нашёл), но предмет не выпал — это честный…, Обратная совместимость: старые handle без флага noTarget ведут себя как раньше…, _snap(), test_gather_inconclusive_when_target_existed_but_no_gain(), test_gather_missing_flag_defaults_to_inconclusive(), test_gather_no_object_is_failure_not_inconclusive(), test_gather_success_when_material_gained() (+2 more)

### Community 109 - "test_gather_precondition.py"
Cohesion: 0.36
Nodes (10): _gm(), _info(), Q5 (гибрид, согласовано с со-архитектором): без узла и без трупа рядом gather…, Труп с componentTags рядом — законный объект для harvestCorpse., Разведочный бюджет: раз в GATHER_PROBE_EVERY шагов пробуем вопреки фильтру —…, test_exploration_budget_allows_periodic_probe(), test_gather_filtered_out_when_no_object_nearby(), test_gather_offered_when_corpse_nearby() (+2 more)

### Community 110 - "test_plan_stack.py"
Cohesion: 0.29
Nodes (10): _gm(), _info(), test_plan_stack.py — Plan-Stack: квест становится транзакцией с планом. Фарм-…, Живая схема снапшота (проверена schema contract test)., Квест 5/8 -> политика ведёт к добыче (gather/navigate), не sell., ГЛАВНЫЙ тест фарм-бот фикса: 8/8 -> ОБЯЗАН идти сдавать, не farm. Гивер далеко…, READY-квест У ГИВЕРА (dist<=6) -> сразу turn_in_quest (следующий шаг стека)., test_complete_objective_forces_return_to_giver() (+2 more)

### Community 111 - "test_spin_no_hard_removal.py"
Cohesion: 0.33
Nodes (10): _hints(), _info(), Найдено со-архитектором 2026-08-24: policy делал cands.remove(bad) — жёсткое…, Подавление должно жить в весах: скилл остаётся кандидатом, но его вес…, Ключевой регресс: при spin:return_to_giver фаза RETURN_TO_GIVER всё равно…, Даже когда ВСЕ доступные скиллы под spin-хинтами, набор кандидатов не должен…, test_deterministic_override_survives_spin_hint(), test_multiple_spin_hints_keep_every_action_available() (+2 more)

### Community 112 - "createCmdQueue"
Cohesion: 0.22
Nodes (5): createCmdQueue(), submit(), withWatchdog(), assert, { createCmdQueue }

### Community 113 - ".get_npcs_with_quests"
Cohesion: 0.20
Nodes (5): Get all NPC definitions from the game., Get only NPCs that offer quests., Get NPCs that are quest givers (alias for get_npcs_with_quests)., Find the NPC that gives a specific quest., Return (x, z) for the NPC that gives a specific quest, or None.

### Community 114 - "test_reflection_fixes.py"
Cohesion: 0.29
Nodes (8): Self-reflection loop (the missing 'делал выводы' step). Every SAVE_EVERY steps…, _fsm_turnin(), Regression tests for the 2026-08-23 stall: after a restart the agent ran 1860x…, Persisted TURN_IN/q_greyjaw + live world showing ACTIVE quest_status -> FSM…, test_fsm_demotes_turnin_when_active_quest_observed(), test_fsm_keeps_turnin_when_same_quest_still_ready(), test_fsm_reset_when_tracked_quest_vanished_from_world(), test_observe_is_per_step_and_reflect_on_cadence()

### Community 115 - "test_accept_new_quests.py"
Cohesion: 0.38
Nodes (9): _gm(), _info(), Измерено на живом мире 2026-08-24: рядом были Weaver Ottilie и Tinker Gizzel с…, Обратная сторона: если у NPC только те квесты, что уже взяты — не предлагаем…, npc_quests: список questIds у NPC рядом; have: наши уже взятые квесты., test_accept_not_offered_when_all_npc_quests_already_taken(), test_accept_not_offered_without_npc_nearby(), test_accept_offered_when_npc_has_quest_we_dont_have() (+1 more)

### Community 116 - "test_gather_bag_cycle.py"
Cohesion: 0.24
Nodes (9): _info_full_bags(), test_gather_bag_cycle.py — цикл «полные сумки -> продать -> вернуться к…, Живой мир: сумки полны, рядом нет вендора., SKILL_SELL должен быть в PHASE_ALLOWED['DO_OBJECTIVE']., При ПОЛНЫХ сумках политика выбирает sell, даже если вендора нет рядом…, При продаже copper_ore/ironbark_log (квестовые) защищены keepIds., test_full_bags_force_sell_even_without_nearby_vendor(), test_sell_allowed_in_do_objective_phase() (+1 more)

### Community 117 - "_obs"
Cohesion: 0.29
Nodes (5): _giver(), _obs(), Navigation controller + observation work together., Simulate navigating to a giver and reaching it., TestNavigationIntegration

### Community 118 - "TestPolicyNoOverrides"
Cohesion: 0.20
Nodes (6): Verify decide() has no hardcoded overrides in policy.py source., policy.py must not contain the loot_priority override logic., policy.py must not contain the bag_survival_sell override logic., policy.py must not contain the phase_return override logic., policy.py must not contain the turn_in_phase override logic., TestPolicyNoOverrides

### Community 119 - "test_strategy_alive.py"
Cohesion: 0.29
Nodes (9): Найдено со-аудитором: record_outcome инкрементил success на КАЖДЫЙ SUCCESS-…, Второй дефект: preference() возвращала best_skill только при success > fail,…, Приёмка A2: доказанный скилл получает множитель веса ≥1.5., _sm(), test_boost_multiplier_scales_with_evidence(), test_most_completed_skill_wins(), test_persists_across_instances(), test_preference_needs_evidence_not_majority() (+1 more)

### Community 120 - "test_p0_hotpath.py"
Cohesion: 0.22
Nodes (5): P0 hot-path defects — RED tests. Четыре дефекта, подтверждённых живым замером…, P0.2: update() не должен писать на диск., Поведенческая проверка: 200 update() не должны писать файл., save() не должен писать _mem.log рядом (тоже синхронный I/O)., TestNoDiskWriteInUpdateP02

### Community 121 - "test_self_reflection.py"
Cohesion: 0.50
Nodes (8): _fresh(), Tests for SelfReflection — the 'делал выводы' loop., _rec(), test_action_saturation_detected(), test_death_cluster_detected(), test_journal_persists_and_hints_readable(), test_quest_stall_detected(), test_vendor_cycle_positive()

### Community 122 - "test_vendor_flag.cjs"
Cohesion: 0.22
Nodes (8): assert, fs, m, path, plain, NOTE: fnSrc is OUR OWN module source (not user input) — injection risk is nil., src, trader

### Community 123 - "goal_fsm.py"
Cohesion: 0.29
Nodes (6): arbitration_layer.py — Decision logic separate from FSM state tracking. This…, FailureReason, Enum, goal_fsm.py — Quest Goal Finite State Machine (persistent state tracker ONLY).…, # NOTE: done_ids is NOT cleared — it persists across quests, Причины неудач для анализа и восстановления.

### Community 124 - ".step"
Cohesion: 0.25
Nodes (4): Вернуть актуальный subgoal. force=True (смерть, критический HP) перепланирует…, Return context dict for policy consumption. { "subgoal": "KILL" | "GATHER" |…, Если APPROACH провалился — заменить на FIND_MOB (обходной путь). Вместо…, Добавить memory-based hints в текущий план. Если StrategyMemory знает успешную…

### Community 126 - "test_obs_mobs_spatial.py"
Cohesion: 0.39
Nodes (7): Milestone 1 — spatial mob observation (RED then GREEN). Contract (per user…, Minimal ws/info carrying two live mobs near the player., test_angle_relative_to_facing_not_world_zero(), test_dx_dz_relative_to_player(), test_mobs_present_with_spatial_fields(), test_quest_target_flag(), _ws_with_mobs()

### Community 128 - "test_brain_glue.py"
Cohesion: 0.29
Nodes (5): КОНТРАКТ ИЗМЕНЁН 2026-08-24 (аудит LLM: HARMFUL). Раньше LLM писала цель в FSM,…, SURVIVE по-прежнему нормализуется в HEAL, но попадает в СОВЕТ, а не в цель:…, test_apply_decision_no_longer_writes_goal(), test_apply_rejects_none_and_bad_goal(), test_survive_maps_to_heal_in_suggestion_only()

### Community 130 - "test_bridge.cjs"
Cohesion: 0.29
Nodes (4): assert, { buildSnapshot }, { createActions }, { GameClient }

### Community 131 - ".get_nearby_entities"
Cohesion: 0.33
Nodes (3): Get entities within radius of player., Get NPCs within radius of player., Get mobs within radius of player.

### Community 132 - ".get"
Cohesion: 0.33
Nodes (3): Получить NPC по canonical ID., Получить NPC по templateId., Получить позицию NPC по ID.

### Community 133 - "test_policy_fallback.py"
Cohesion: 0.33
Nodes (5): RED test: policy.decide() should NOT silently pick 'explore' as fallback. Per…, policy.decide() with context.allowed_skills=['explore','navigate'] and all…, When phase=DO_OBJECTIVE and only fallback skills available, the policy context…, test_policy_fallback_uses_masked_list(), test_policy_phase_do_objective_picks_navigate()

### Community 134 - "test_verdict_lifecycle.py"
Cohesion: 0.33
Nodes (5): test_verdict_lifecycle.py — regression test for P0 verdict UnboundLocalError., Verify verdict is assigned before _is_progress uses it in the bounds block., Verify _summary() accepts bounds parameter and callers pass it., test_summary_receives_bounds_parameter(), test_verdict_initialized_before_bounds_check()

### Community 135 - "test_fence_jump.cjs"
Cohesion: 0.40
Nodes (3): fenceHopPlan(), assert, { fenceHopPlan, FENCE_LOOKAHEAD }

### Community 136 - "test_quests_done.cjs"
Cohesion: 0.40
Nodes (3): questsDoneCount(), assert, { questsDoneCount }

### Community 137 - "test_buy_vendor_range.cjs"
Cohesion: 0.33
Nodes (5): callPos, farPos, fs, m, src

### Community 138 - "offline_train.py"
Cohesion: 0.50
Nodes (4): bucket_of(), main(), Offline training: replay the historical autonomous_log through TD(0) into a…, The log stores bucket_before already normalized — use it directly.

### Community 142 - "game_source.py"
Cohesion: 0.50
Nodes (3): get_game_source(), Dynamic game source adapter — reads game data directly from running WoC…, Get or create the singleton GameSource instance.

### Community 149 - "test_navigate_timing.cjs"
Cohesion: 0.50
Nodes (3): fs, navMatch, src

## Knowledge Gaps
- **79 isolated node(s):** `DEFAULT_TAB_MATCH`, `puppeteer`, `assert`, `{ faceTargetPlan, FACE_EPS }`, `assert` (+74 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 1188 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **18 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `GoalFSM` connect `GoalFSM` to `test_brain_glue.py`, `ArbitrationLayer`, `autonomy.py`, `_bucket`, `test_quest_chain.py`, `_fsm`, `.reset`, `AutonomyLoop`, `ArbitrationLayer`, `_fsm`, `QuestState`, `autonomous_master.py`, `test_quest_cycle.py`, `FakeResp`, `main`, `test_combat_kill.py`, `test_p3_red.py`, `test_arbitration_quest_none.py`, `._log_transition`, `test_bounded_harness.py`, `test_reflection_fixes.py`, `goal_fsm.py`?**
  _High betweenness centrality (0.159) - this node is a cross-community bridge._
- **Why does `ExperienceStore` connect `ExperienceStore` to `build_world_state`, `autonomy.py`, `_bucket`, `action_mask.py`, `StrategyMemory`, `policy.py`, `AutonomyLoop`, `ArbitrationLayer`, `WorldMemory`, `autonomous_master.py`, `test_by_id_field_contract.py`, `test_j5_episodic.py`, `test_policy_softmax_only.py`, `test_loot_targets.py`, `main`, `Agent`, `test_quest_phase_mask.py`, `test_arbitration_quest_none.py`, `test_schema_contract.py`, `test_decision_context_red.py`, `test_gather_precondition.py`, `test_plan_stack.py`, `test_spin_no_hard_removal.py`, `test_accept_new_quests.py`, `test_gather_bag_cycle.py`, `test_strategy_alive.py`, `test_p0_hotpath.py`?**
  _High betweenness centrality (0.157) - this node is a cross-community bridge._
- **Why does `build_world_state()` connect `build_world_state` to `ExperienceStore`, `_bucket`, `action_mask.py`, `check_preconditions`, `policy.py`, `encode_observation`, `ArbitrationLayer`, `NpcRegistry`, `autonomous_master.py`, `test_quest_cycle.py`, `test_by_id_field_contract.py`, `rich_snapshot`, `item_prices.py`, `test_j5_episodic.py`, `test_loot_targets.py`, `main`, `test_quest_phase_mask.py`, `test_arbitration_quest_none.py`, `test_learning_signals.py`, `test_schema_contract.py`, `test_survival_learning.py`, `test_p0_hotpath.py`?**
  _High betweenness centrality (0.102) - this node is a cross-community bridge._
- **Are the 3 inferred relationships involving `ExperienceStore` (e.g. with `GoalManager` and `TestHasHealingFromCanonicalState`) actually correct?**
  _`ExperienceStore` has 3 INFERRED edges - model-reasoned connections that need verification._
- **Are the 3 inferred relationships involving `build_world_state()` (e.g. with `_world_state_dict()` and `_giver_known()`) actually correct?**
  _`build_world_state()` has 3 INFERRED edges - model-reasoned connections that need verification._
- **Are the 7 inferred relationships involving `GoalManager` (e.g. with `.__init__()` and `ExperienceStore`) actually correct?**
  _`GoalManager` has 7 INFERRED edges - model-reasoned connections that need verification._
- **Are the 3 inferred relationships involving `GoalFSM` (e.g. with `_recover_death()` and `_sync_fsm()`) actually correct?**
  _`GoalFSM` has 3 INFERRED edges - model-reasoned connections that need verification._