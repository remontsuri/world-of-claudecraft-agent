// src/bridge/test_quests_done.cjs
// КОРНЕВАЯ ПРИЧИНА (найдена 2026-08-24 методом systematic-debugging).
//
// Симптом: агент «не сдаёт квесты» — quests_done в снапшоте всегда 0, поэтому
// верификатор считал каждую сдачу провалом, а обучение получало ложный
// отрицательный сигнал.
//
// Живой замер клиента показал, что сдачи РАБОТАЛИ:
//   online.questsDone = Set(7) { q_wolves, q_boars, q_bandits, q_murlocs,
//                                q_spiders, q_prof_workorder_kitchens,
//                                q_prof_workorder_loom }
//   cadenceBlockedQuests = ['q_prof_workorder_loom']   // work-order в кулдауне
//
// Баг в мосте (src/bridge/snapshot.cjs:233):
//   quests_done: (typeof (g.online && g.online.questsDone) === 'number')
//     ? g.online.questsDone : done.length
// questsDone — это Set, значит typeof === 'object', условие ВСЕГДА ложно, и
// берётся done.length. А ведро done в онлайне пустое (сервер не присылает
// историю пройденных квестов), поэтому счётчик вечно 0.
//
// Run: node src/bridge/test_quests_done.cjs
const assert = require('assert');
const { questsDoneCount } = require('./quests_done.cjs');

let passed = 0;
function t(name, fn) {
  try { fn(); passed++; console.log('PASS', name); }
  catch (e) { console.error('FAIL', name, '-', e.message); process.exitCode = 1; }
}

t('Set из 7 квестов -> 7 (главный кейс, был 0)', () => {
  const online = { questsDone: new Set(['q_wolves', 'q_boars', 'q_bandits',
    'q_murlocs', 'q_spiders', 'q_prof_workorder_kitchens', 'q_prof_workorder_loom']) };
  assert.strictEqual(questsDoneCount(online, []), 7);
});

t('пустой Set -> 0', () => {
  assert.strictEqual(questsDoneCount({ questsDone: new Set() }, []), 0);
});

t('число (офлайн-путь) по-прежнему работает', () => {
  assert.strictEqual(questsDoneCount({ questsDone: 4 }, []), 4);
});

t('массив questsDone тоже считается', () => {
  assert.strictEqual(questsDoneCount({ questsDone: ['a', 'b'] }, []), 2);
});

t('нет online -> фоллбек на ведро done', () => {
  assert.strictEqual(questsDoneCount(null, [{ id: 'x' }, { id: 'y' }]), 2);
});

t('online без questsDone -> фоллбек на done', () => {
  assert.strictEqual(questsDoneCount({}, [{ id: 'x' }]), 1);
});

t('Set пустой, но done непустое -> берём большее (не теряем историю)', () => {
  // офлайн-сим может знать done, а online.questsDone ещё не пришёл
  assert.strictEqual(questsDoneCount({ questsDone: new Set() }, [{ id: 'x' }]), 1);
});

console.log('\n' + passed + ' tests passed');
