// src/bridge/quest_turnin.cjs
// Таблица «квест -> NPC сдачи», СГЕНЕРИРОВАНА из исходников игры
// (src/sim/content/zone1.ts, поле turnInNpcId у каждого квеста), а не набрана
// руками. Причина: в snapshot.cjs таблица EASTBROOK_QUEST_TURNIN перечисляла
// только обычные квесты, поэтому у профессиональных (q_prof_*) turnInNpc
// оставался null. Замер 2026-08-24: q_prof_workorder_loom был готов (6/6), но
// агент 14 шагов «шёл» в неизвестную точку и не двигался с места.
//
// Регенерация при изменении контента:
//   grep -n "turnInNpcId" src/sim/content/zone1.ts
// Тесты: src/bridge/test_prof_turnin.cjs

const QUEST_TURNIN_BY_ID = {
  q_bandits: 'marshal_redbrook',
  q_boars: 'trader_wilkes',
  q_bones: 'brother_aldric',
  q_divine_tome: 'brother_aldric',
  q_gravecallers_trail: 'brother_aldric',
  q_greyjaw: 'marshal_redbrook',
  q_hollow: 'brother_aldric',
  q_mine: 'foreman_odell',
  q_mogger: 'marshal_redbrook',
  q_murlocs: 'fisherman_brandt',
  q_names_of_the_dead: 'brother_aldric',
  q_prof_amends_apothecary: 'cook_marlow',
  q_prof_amends_bombardier: 'tinker_gizzel',
  q_prof_amends_outfitter: 'weaver_ottilie',
  q_prof_amends_smith: 'forgemistress_darva',
  q_prof_attune_apothecary: 'cook_marlow',
  q_prof_attune_bombardier: 'tinker_gizzel',
  q_prof_attune_outfitter: 'weaver_ottilie',
  q_prof_attune_smith: 'forgemistress_darva',
  q_prof_hobby_switch: 'smith_haldren',
  q_prof_intro: 'foreman_odell',
  q_prof_workorder_forge: 'forgemistress_darva',
  q_prof_workorder_kitchens: 'cook_marlow',
  q_prof_workorder_loom: 'weaver_ottilie',
  q_prof_workorder_toolworks: 'tinker_gizzel',
  q_ringleader: 'marshal_redbrook',
  q_rite: 'brother_aldric',
  q_sexton: 'brother_aldric',
  q_silence_the_call: 'brother_aldric',
  q_spiders: 'apothecary_lin',
  q_supplies: 'trader_wilkes',
  q_whispers: 'brother_aldric',
  q_wolves: 'marshal_redbrook',
};

/** NPC-id, которому сдаётся квест, либо null если квест неизвестен. */
function npcIdForQuest(questId) {
  return QUEST_TURNIN_BY_ID[questId] || null;
}

module.exports = { QUEST_TURNIN_BY_ID, npcIdForQuest };
