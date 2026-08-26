// quest_objectives.cjs — статическая таблица objectives для квестов.
// Офлайн-клиент не отдаёт objectives в questLog (только counts/resolvedCounts),
// поэтому мост обогащает снапшот из этой таблицы. Источник: src/sim/content/zone1.ts
const QUEST_OBJECTIVES = {
  q_wolves: [{ type: 'kill', targetMobId: 'forest_wolf', count: 8 }],
  q_greyjaw: [{ type: 'collect', itemId: 'greyjaw_fang', count: 1 }],
  q_boars: [{ type: 'collect', itemId: 'boar_hide', count: 5 }],
  q_spiders: [
    { type: 'kill', targetMobId: 'webwood_spider', count: 6 },
    { type: 'collect', itemId: 'webwood_silk', count: 4 },
  ],
  q_murlocs: [{ type: 'kill', targetMobId: 'mudfin_murloc', count: 8 }],
  q_bandits: [{ type: 'kill', targetMobId: 'vale_bandit', count: 10 }],
  q_prof_workorder_kitchens: [{ type: 'collect', itemId: 'game_meat', count: 8 }],
  q_prof_workorder_loom: [{ type: 'collect', itemId: 'spider_silk', count: 6 }],
  q_prof_attune_smith: [{ type: 'gather', nodeType: 'ore', count: 3 }],
  q_prof_workorder_forge: [{ type: 'collect', itemId: 'copper_ore', count: 8 }],
  q_prof_workorder_toolworks: [{ type: 'collect', itemId: 'ironbark_log', count: 8 }],
  q_supplies: [{ type: 'collect', itemId: 'supply_crate', count: 4 }],
  q_prowlers: [{ type: 'kill', targetMobId: 'mire_prowler', count: 12 }],
  q_bones: [{ type: 'collect', itemId: 'restless_skull', count: 8 }],
  q_mine: [{ type: 'gather', nodeType: 'ore', count: 5 }],
  q_prof_intro: [{ type: 'gather', nodeType: 'ore', count: 5 }],
};

module.exports = { QUEST_OBJECTIVES };
