// src/bridge/test_prof_turnin.cjs — гиверы профессиональных квестов.
// Баг (замер 2026-08-24): у q_prof_workorder_loom turnInNpc был null, потому что
// таблица EASTBROOK_QUEST_TURNIN в snapshot.cjs перечисляла только обычные
// квесты. Итог: агент 14 шагов «шёл» в неизвестную точку, позиция не менялась,
// сдача невозможна. Истина есть в исходниках игры: zone1.ts хранит turnInNpcId
// у каждого квеста.
// Run: node src/bridge/test_prof_turnin.cjs
const assert = require('assert');
const { QUEST_TURNIN_BY_ID, npcIdForQuest } = require('./quest_turnin.cjs');

let passed = 0;
function t(name, fn) {
  try { fn(); passed++; console.log('PASS', name); }
  catch (e) { console.error('FAIL', name, '-', e.message); process.exitCode = 1; }
}

t('профессиональные work-order квесты имеют гивера', () => {
  // zone1.ts:1402-1403 -> q_prof_workorder_loom: weaver_ottilie
  assert.strictEqual(npcIdForQuest('q_prof_workorder_loom'), 'weaver_ottilie');
});

t('attune-квесты имеют гивера', () => {
  assert.strictEqual(npcIdForQuest('q_prof_attune_smith'), 'forgemistress_darva');
  assert.strictEqual(npcIdForQuest('q_prof_attune_outfitter'), 'weaver_ottilie');
});

t('обычные квесты по-прежнему разрешаются', () => {
  assert.strictEqual(npcIdForQuest('q_greyjaw'), 'marshal_redbrook');
  assert.strictEqual(npcIdForQuest('q_spiders'), 'apothecary_lin');
  assert.strictEqual(npcIdForQuest('q_bones'), 'brother_aldric');
});

t('q_prof_intro и q_mine -> foreman_odell (zone1.ts:828)', () => {
  assert.strictEqual(npcIdForQuest('q_prof_intro'), 'foreman_odell');
  assert.strictEqual(npcIdForQuest('q_mine'), 'foreman_odell');
});

t('неизвестный квест -> null, без выдумок', () => {
  assert.strictEqual(npcIdForQuest('q_does_not_exist'), null);
});

t('таблица покрывает все q_prof_* из zone1', () => {
  const profQuests = Object.keys(QUEST_TURNIN_BY_ID).filter((q) => q.startsWith('q_prof'));
  assert.ok(profQuests.length >= 10,
    `ожидали >=10 профессиональных квестов, есть ${profQuests.length}`);
  for (const q of profQuests) {
    assert.ok(QUEST_TURNIN_BY_ID[q], `${q} без гивера`);
  }
});

console.log('\n' + passed + ' tests passed');
