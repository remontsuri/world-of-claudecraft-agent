// test_cmd_queue_timeout.cjs — bounded command queue (TDD RED→GREEN).
// Контракт (план 2026-08-24, пункт 2):
//   - CMD_TIMEOUT_MS: каждая команда в очереди получает собственный watchdog;
//   - timeout НЕ превращается в бесконечную очередь — зависший handler
//     отбрасывается, очередь движется дальше;
//   - после timeout recovery использует существующий freshPage() (один механизм);
//   - очередь продолжает работу только после проверки bridge/page.
//
// Здесь тестируем чистую логику ограниченной очереди: вынесена в
// src/bridge/cmd_queue.cjs (createCmdQueue), чтобы её можно было
// тестировать без HTTP и CDP.
// Run: node src/bridge/test_cmd_queue_timeout.cjs

const assert = require('assert');
const { createCmdQueue } = require('./cmd_queue.cjs');

let passed = 0, failed = 0;
function t(name, fn) {
  return Promise.resolve()
    .then(fn)
    .then(() => { passed++; console.log('PASS', name); })
    .catch((e) => { failed++; console.error('FAIL', name, '-', e.message); process.exitCode = 1; });
}
const sleep = (ms) => new Promise(r => setTimeout(r, ms));

(async () => {
  await t('queue: fast commands execute in order', async () => {
    const q = createCmdQueue({ cmdTimeoutMs: 500 });
    const out = [];
    q.submit(async () => { out.push(1); return { ok: true, n: 1 }; });
    q.submit(async () => { out.push(2); return { ok: true, n: 2 }; });
    await q.idle();
    assert.deepStrictEqual(out, [1, 2]);
  });

  await t('queue: hung command rejected by watchdog, next command still runs', async () => {
    const recovered = [];
    const q = createCmdQueue({
      cmdTimeoutMs: 80,
      onTimeout: async () => { recovered.push('freshPage'); },
    });
    let hungSettled = false;
    const p1 = q.submit(async () => { await sleep(2000); hungSettled = true; return { ok: true }; }); // висит
    const t0 = Date.now();
    const p2 = q.submit(async () => ({ ok: true, fast: true }));
    const r1 = await p1;
    assert.strictEqual(r1.ok, false, 'зависшая команда -> ok:false');
    assert.ok(/timeout/i.test(r1.error || ''), 'ошибка должна упоминать timeout');
    assert.strictEqual(hungSettled, false, 'зависший handler не должен успеть завершиться');
    const r2 = await p2;
    assert.strictEqual(r2.fast, true, 'следующая команда выполнилась после timeout');
    assert.deepStrictEqual(recovered, ['freshPage'], 'onTimeout (freshPage recovery) вызван ровно раз');
    assert.ok(Date.now() - t0 < 1500, 'очередь не ждала полный hang');
  });

  await t('queue: timeout error does not kill the chain', async () => {
    const q = createCmdQueue({ cmdTimeoutMs: 60, onTimeout: async () => {} });
    await q.submit(async () => { await sleep(1000); return { ok: true }; }); // зависнет -> timeout
    const r = await q.submit(async () => { if (this && this.x) throw new Error('x'); return { ok: true, after: true }; });
    assert.strictEqual(r.after, true);
  });

  await t('queue: handler throws -> ok:false with error, queue continues', async () => {
    const q = createCmdQueue({ cmdTimeoutMs: 500 });
    const r1 = await q.submit(async () => { throw new Error('boom'); });
    assert.strictEqual(r1.ok, false);
    assert.ok(/boom/.test(r1.error));
    const r2 = await q.submit(async () => ({ ok: true }));
    assert.strictEqual(r2.ok, true);
  });

  console.log(`\n${passed} passed, ${failed} failed`);
  if (failed > 0) process.exit(1);
})();
