// quest_objectives.js — статическая таблица объектов квестов
// (источник: src/sim/content/zone1.ts, zone2.ts, zone3.ts)
// Игра не отдаёт questDefs — используем fallback как EASTBROOK_GATHER_NODES.

const QUEST_OBJECTIVES = {
  "q_prof_intro": [{"type": "gather", "nodeType": "ore", "count": 5}],
  "q_wolves": [{"type": "kill", "targetMobId": "forest_wolf", "count": 8}],
  "q_greyjaw": [{"type": "collect", "itemId": "greyjaw_fang", "count": 1}],
  "q_boars": [{"type": "collect", "itemId": "boar_hide", "count": 5}],
  "q_spiders": [{"type": "kill", "targetMobId": "webwood_spider", "count": 6}, {"type": "collect", "itemId": "webwood_silk", "count": 4}],
  "q_murlocs": [{"type": "kill", "targetMobId": "mudfin_murloc", "count": 8}],
  "q_bandits": [{"type": "kill", "targetMobId": "vale_bandit", "count": 10}],
  "q_prof_workorder_kitchens": [{"type": "collect", "itemId": "game_meat", "count": 8}],
  "q_prof_workorder_loom": [{"type": "collect", "itemId": "spider_silk", "count": 6}],
  "q_prof_attune_smith": [{"type": "gather", "nodeType": "ore", "count": 3}],
  "q_prof_workorder_forge": [{"type": "collect", "itemId": "copper_ore", "count": 8}],
  "q_prof_workorder_toolworks": [{"type": "collect", "itemId": "ironbark_log", "count": 8}],
};

module.exports = { QUEST_OBJECTIVES };
