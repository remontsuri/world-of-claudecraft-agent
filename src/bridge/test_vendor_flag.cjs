// src/bridge/test_vendor_flag.cjs — RED test: nearby NPC entries must carry a
// `vendor` flag so Python's sell_junk gate can see merchants.
// Run: node src/bridge/test_vendor_flag.cjs
const assert = require('assert');
const fs = require('fs');
const path = require('path');

const src = fs.readFileSync(path.join(__dirname, 'snapshot.cjs'), 'utf8');
const m = src.match(/function readGameState\(\) \{[\s\S]*?\n\}/);
assert(m, 'readGameState not found in snapshot.cjs');

// Evaluate readGameState against a FAKE window.__game (no browser needed).
const fnSrc = m[0];
// NOTE: fnSrc is OUR OWN module source (not user input) — injection risk is nil.
const sandbox = `
  const window = { __game: {
    sim: {
      player: { hp: 100, maxHp: 100, level: 5, dead: false,
                pos: { x: 0, z: 0 }, resource: 100, maxResource: 100,
                inventory: [], cooldowns: new Map() },
      entities: new Map([
        [1, { id: 1, kind: 'npc', name: 'Trader', templateId: 'trader_wilkes',
              pos: { x: 2, z: 2 }, vendorItems: ['baked_bread'] }],   // REAL vendor
        [2, { id: 2, kind: 'npc', name: 'Plain NPC', templateId: 'plain',
              pos: { x: 3, z: 3 }, vendorItems: [] }],                 // empty stock
        [3, { id: 3, kind: 'mob', name: 'wolf', templateId: 'wolf_mob',
              pos: { x: 1, z: 1 }, hp: 30, maxHp: 30, hostile: true }],
      ]),
      questLog: null,
      deedStats: null,
    },
    online: {},
  } };
`;
let result;
{
  const window = JSON.parse(JSON.stringify({}));
  // Build the fake env in this scope and run the real function source.
  const fakeSim = {
    player: { hp: 100, maxHp: 100, level: 5, dead: false,
              pos: { x: 0, z: 0 }, resource: 100, maxResource: 100,
              inventory: [], cooldowns: new Map(), facing: 0 },
    entities: new Map([
      [1, { id: 1, kind: 'npc', name: 'Trader', templateId: 'trader_wilkes',
            pos: { x: 2, z: 2 }, vendorItems: ['baked_bread'] }],   // REAL vendor
      [2, { id: 2, kind: 'npc', name: 'Plain NPC', templateId: 'plain',
            pos: { x: 3, z: 3 }, vendorItems: [] }],                 // empty stock
      [3, { id: 3, kind: 'mob', name: 'wolf', templateId: 'wolf_mob',
            pos: { x: 1, z: 1 }, hp: 30, maxHp: 30, hostile: true }],
    ]),
    questLog: null,
    deedStats: null,
  };
  const fakeGame = { sim: fakeSim, online: {} };
  global.window = { __game: fakeGame };
  result = new Function('window', fnSrc + '\n return readGameState;')(global.window)();
}

const trader = result.nearby.find((e) => e.name === 'Trader');
const plain = result.nearby.find((e) => e.name === 'Plain NPC');

assert(trader, 'trader missing from nearby');
assert(trader.vendor === true, 'trader_wilkes-like vendor NPC must expose vendor=true, got ' + JSON.stringify(trader));
assert(plain.vendor === false, 'empty-stock NPC must be vendor=false');
console.log('PASS vendor flag present on nearby NPCs');
