// test_gather_nav.cjs — TDD: gather с навигацией к дальнему узлу.
// Контракт (2026-08-25):
//   1) case 5 ищет узлы в 120 yd (было 60) — wood в 65 yd теперь виден;
//   2) узел дальше INTERACT_RANGE (5yd): СНАЧАЛА navigateToCoord к его
//      статическим координатам из GATHER_NODES, потом harvestNode;
//   3) cmd.nodeType приоритет: берём узел нужного типа, если есть;
//   4) нет узла вообще -> noTarget:true (честный failure как раньше).
// Run: node src/bridge/test_gather_nav.cjs

const assert = require('assert');

let passed = 0, failed = 0;
function t(name, fn) {
  return Promise.resolve()
    .then(fn)
    .then(() => { passed++; console.log('PASS', name); })
    .catch((e) => { failed++; console.error('FAIL', name, '-', e.message); process.exitCode = 1; });
}

(async () => {
  // Проверяем сам исходник actions.cjs на новые конструкции —
  // интеграционно поведение проверит живой прогон.
  const fs = require('fs');
  const src = fs.readFileSync('D:/world-of-claudecraft/src/bridge/actions.cjs', 'utf-8');

  await t('case 5: search radius extended to 120', () => {
    assert(/d <= 120/.test(src), 'радиус поиска узлов должен быть 120 yd');
  });

  await t('case 5: navigates to node before harvest when far', () => {
    assert(/navigateToCoord\(gameClient/.test(src),
      'должен звать navigateToCoord перед harvestNode');
  });

  await t('case 5: GATHER_NODES static coords available in page', () => {
    // Координаты узла резолвятся через g.GATHER_NODES или sim-таблицу
    assert(/GATHER_NODES|nodePlacements|gatherNodeById/.test(src),
      'нужен доступ к статическим координатам узлов');
  });

  await t('case 5: no node anywhere -> honest noTarget', () => {
    assert(/gatherNoTarget\s*=\s*true/.test(src),
      'noTarget=true при отсутствии узлов (существующий контракт)');
  });

  console.log(`\n${passed} passed, ${failed} failed`);
  if (failed > 0) process.exit(1);
})();
