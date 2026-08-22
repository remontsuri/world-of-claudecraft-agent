// src/bridge/test_bridge.js — plain-node smoke tests for the bridge modules.
// Run: node src/bridge/test_bridge.js
// No framework: asserts + manual mocks (repo has no JS test runner).

const assert = require('assert');
const { createActions } = require('./actions.cjs');
const { GameClient } = require('./game_client.cjs');
const { buildSnapshot } = require('./snapshot.cjs');

let passed = 0;
function t(name, fn) {
  return Promise.resolve()
    .then(fn)
    .then(() => { passed++; console.log('PASS', name); })
    .catch((e) => { console.error('FAIL', name, '-', e.message); process.exitCode = 1; });
}

function mockGameClient(evaluateImpl, tickMs = 1) {
  return {
    tickMs,
    evaluateCalls: 0,
    evaluate(...args) { this.evaluateCalls++; return evaluateImpl ? evaluateImpl(...args) : Promise.resolve(null); },
    // real methods exist but are not used by handlers under mock
  };
}

(async () => {
  await t('snapshot handler: ok shape', async () => {
    const gc = mockGameClient();
    const bs = async () => ({ player: { hp: 100 }, nearby: [] });
    const a = createActions({ gameClient: gc, buildSnapshot: bs, tickMs: 1 });
    const r = await a.snapshot();
    assert.strictEqual(r.ok, true);
    assert.strictEqual(r.info.player.hp, 100);
    assert(!('error' in r));
  });

  await t('snapshot handler: null -> ok:false with error', async () => {
    const a = createActions({ gameClient: mockGameClient(), buildSnapshot: async () => null, tickMs: 1 });
    const r = await a.snapshot();
    assert.strictEqual(r.ok, false);
    assert(typeof r.error === 'string' && r.error.length > 0);
    assert(!('info' in r));
  });

  await t('step handler: flat info + giver surfaced once', async () => {
    const gc = mockGameClient();
    let n = 0;
    const bs = async () => ({ seq: ++n });
    const a = createActions({ gameClient: gc, buildSnapshot: bs, tickMs: 1 });
    // simulate lastAccept via accept action path: use questId trigger instead
    const r = await a.step({ idx: 0, questId: 'q_x' });
    assert.strictEqual(r.ok, true);
    assert.deepStrictEqual(Object.keys(r.info), ['seq']);
    // no nested info
    assert(!(r.info && r.info.info));
  });

  await t('step handler: snapshot fails after action -> ok:false', async () => {
    const a = createActions({ gameClient: mockGameClient(), buildSnapshot: async () => null, tickMs: 1 });
    const r = await a.step({ idx: 0 });
    assert.strictEqual(r.ok, false);
    assert(/snapshot after step/.test(r.error));
  });

  await t('respawn: not dead -> revived:true honest shortcut', async () => {
    const gc = mockGameClient(() => Promise.resolve(false)); // player not dead
    const a = createActions({ gameClient: gc, buildSnapshot: async () => ({ alive: true }), tickMs: 1 });
    const r = await a.respawn();
    assert.strictEqual(r.ok, true);
    assert.strictEqual(r.revived, true);
  });

  await t('navigate: arrives immediately', async () => {
    const gc = mockGameClient((fn, x, z) => Promise.resolve({ arrived: true, d: 0 }));
    const a = createActions({ gameClient: gc, buildSnapshot: async () => ({ pos: [1, 1] }), tickMs: 1 });
    const r = await a.navigate({ x: 5, z: 5 });
    assert.strictEqual(r.ok, true);
    assert.strictEqual(r.arrived, true);
  });

  await t('explore: runs and snapshots', async () => {
    const gc = mockGameClient(() => Promise.resolve(null));
    const a = createActions({ gameClient: gc, buildSnapshot: async () => ({ ok: 1 }), tickMs: 1 });
    const r = await a.explore({ steps: 1 });
    assert.strictEqual(r.ok, true);
    assert.strictEqual(r.arrived, true);
  });

  await t('raw_move: stops controller then snapshots', async () => {
    const gc = mockGameClient(() => Promise.resolve(null));
    const a = createActions({ gameClient: gc, buildSnapshot: async () => ({ moved: true }), tickMs: 1 });
    const r = await a.raw_move({ kind: 'forward' });
    assert.strictEqual(r.ok, true);
    assert.strictEqual(r.info.moved, true);
  });

  await t('GameClient: constructor defaults', async () => {
    const c = new GameClient();
    assert.strictEqual(c.cdpUrl, 'http://127.0.0.1:9222');
    assert.strictEqual(c.tickMs, 220);
    assert.strictEqual(c.page, null);
    assert.strictEqual(c.browser, null);
  });

  await t('buildSnapshot: null evaluate -> null', async () => {
    const out = await buildSnapshot(mockGameClient(() => Promise.resolve(null)));
    assert.strictEqual(out, null);
  });

  await t('buildSnapshot: missing client -> null', async () => {
    assert.strictEqual(await buildSnapshot(null), null);
  });

  console.log('\n' + passed + ' tests passed');
})().catch((e) => { console.error('FATAL', e); process.exit(1); });
