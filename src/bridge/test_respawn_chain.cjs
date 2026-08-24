// test_respawn_chain.cjs — двухэтапный respawn (TDD RED→GREEN).
// Контракт (план 2026-08-24):
//   1) resurrectAtCorpse() — дешёвая попытка (призрак у трупа, без штрафа);
//   2) если всё ещё мёртв — releaseSpirit() → resurrectAtSpiritHealer();
//   3) итог подтверждается ТОЛЬКО по опросу: dead===false && hp>0;
//   4) revived:false при неудаче; timeout на ОБА этапа.
// Run: node src/bridge/test_respawn_chain.cjs

const assert = require('assert');
const { createActions } = require('./actions.cjs');

let passed = 0, failed = 0;
function t(name, fn) {
  return Promise.resolve()
    .then(fn)
    .then(() => { passed++; console.log('PASS', name); })
    .catch((e) => { failed++; console.error('FAIL', name, '-', e.message); process.exitCode = 1; });
}

// Мок: классифицирует каждый evaluate по содержимому переданного кода.
// script управляет: isDeadBefore, aliveAfterCorpse, aliveAfterHealer.
function mockClient(script, tickMs = 1) {
  let phase = 'probe'; // probe -> corpse -> corpsePoll -> release -> healer -> healerPoll
  return {
    tickMs,
    calls: [],
    async evaluate(fn) {
      const src = String(fn);
      this.calls.push(src);
      if (src.includes('resurrectAtCorpse')) {
        script.corpseAttempted = true;
        phase = 'corpse';
        return null;
      }
      if (src.includes('releaseSpirit')) {
        script.releaseAttempted = true;
        return null;
      }
      if (src.includes('resurrectAtSpiritHealer')) {
        script.healerAttempted = true;
        phase = 'healer';
        return script.healerWorks ? Promise.resolve(true) : Promise.resolve(false);
      }
      if (src.includes('.dead')) {
        // Либо первичный probe, либо poll после действий.
        // Порядок фаз определяет ответ:
        if (script.callsSeen === undefined) script.callsSeen = 0;
        const isProbe = this._probeDone !== true && !script.corpseAttempted;
        if (isProbe) {
          this._probeDone = true;
          return script.isDeadBefore === true;
        }
        // poll: жив ли?
        const alive = phase === 'corpse' ? !!script.aliveAfterCorpse
                    : (script.healerWorks ? true : !!script.aliveAfterHealer);
        return alive;
      }
      return null;
    },
  };
}

(async () => {
  await t('respawn chain: corpse rez attempted BEFORE release/healer', async () => {
    const script = { isDeadBefore: true, aliveAfterCorpse: false, healerWorks: false };
    const gc = mockClient(script);
    const a = createActions({ gameClient: gc, buildSnapshot: async () => ({ dead: true }), tickMs: 1 });
    const r = await a.respawn();
    assert.strictEqual(script.corpseAttempted, true, 'resurrectAtCorpse должен вызываться первым');
    assert.strictEqual(script.releaseAttempted, true, 'releaseSpirit после неудачной corpse-попытки');
    assert.strictEqual(script.healerAttempted, true, 'healer после release');
    const iCorpse = gc.calls.findIndex(c => c.includes('resurrectAtCorpse'));
    const iRelease = gc.calls.findIndex(c => c.includes('releaseSpirit'));
    assert(iCorpse >= 0 && iRelease > iCorpse, 'corpse-rez должен идти раньше release');
    assert.strictEqual(r.revived, false, 'не ожили по опросу -> revived:false');
    assert.strictEqual(r.ok, true);
  });

  await t('respawn chain: corpse rez success -> NO release/healer', async () => {
    const script = { isDeadBefore: true, aliveAfterCorpse: true };
    const gc = mockClient(script);
    const a = createActions({ gameClient: gc, buildSnapshot: async () => ({ dead: false }), tickMs: 1 });
    const r = await a.respawn();
    assert.strictEqual(script.corpseAttempted, true);
    assert.strictEqual(script.releaseAttempted, undefined, 'corpse удался — release не нужен');
    assert.strictEqual(script.healerAttempted, undefined);
    assert.strictEqual(r.revived, true);
  });

  await t('respawn chain: healer success -> revived:true', async () => {
    const script = { isDeadBefore: true, aliveAfterCorpse: false, healerWorks: true };
    const gc = mockClient(script);
    const a = createActions({ gameClient: gc, buildSnapshot: async () => ({ dead: false, hp: 50 }), tickMs: 1 });
    const r = await a.respawn();
    assert.strictEqual(script.healerAttempted, true);
    assert.strictEqual(r.revived, true);
  });

  await t('respawn chain: not dead on entry -> honest shortcut, no sim calls', async () => {
    const script = { isDeadBefore: false };
    const gc = mockClient(script);
    const a = createActions({ gameClient: gc, buildSnapshot: async () => ({ alive: true }), tickMs: 1 });
    const r = await a.respawn();
    assert.strictEqual(r.revived, true);
    assert.strictEqual(script.corpseAttempted, undefined, 'мёртвости не было — никаких вызовов сима');
    assert.strictEqual(script.releaseAttempted, undefined);
  });

  console.log(`\n${passed} passed, ${failed} failed`);
  if (failed > 0) process.exit(1);
})();
