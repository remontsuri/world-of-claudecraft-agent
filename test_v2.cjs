// headless тест v2-оркестратора на mock-AgentApi (без браузера)
const { step, initMemory } = require('./dist-tools/agent_core.cjs');

// --- mock AgentApi ---
function makeMock(initial) {
  let ws = JSON.parse(JSON.stringify(initial));
  const calls = [];
  return {
    _ws: ws,
    _set: (next) => { ws = next; },
    _calls: calls,
    ready: () => true,
    readWorldState: () => JSON.parse(JSON.stringify(ws)),
    move: () => { calls.push('move'); return { ok: true }; },
    stop: () => { calls.push('stop'); return { ok: true }; },
    target: (id) => { calls.push('target:'+id); return { ok: true }; },
    attack: () => { calls.push('attack'); return { ok: true }; },
    castSlot: (n) => { calls.push('castSlot:'+n); return { ok: true }; },
    loot: () => { calls.push('loot'); return { ok: true }; },
    openQuestDialog: (id) => { calls.push('openQuestDialog:'+id); return { ok: true }; },
    acceptQuest: (qid) => { calls.push('acceptQuest:'+qid); return { ok: true }; },
    turnInQuest: (id) => { calls.push('turnInQuest:'+id); return { ok: true }; },
    sellAllJunk: () => { calls.push('sellAllJunk'); return { ok: true }; },
    sellItem: (i,c) => { calls.push('sellItem:'+i+'@'+c); return { ok: true }; },
    buyItem: (n,i,o) => { calls.push('buyItem'); return { ok: true }; },
    useItem: (i) => { calls.push('useItem:'+i); return { ok: true }; },
    equipItem: (i) => { calls.push('equipItem'); return { ok: true }; },
    openVendor: () => { calls.push('openVendor'); return { ok: true }; },
    harvestNode: (id) => { calls.push('harvestNode:'+id); return { ok: true }; },
    market: () => ({ ok:false, reason:'x' }),
    craft: () => ({ ok:false, reason:'x' }),
  };
}

const base = {
  t: 1, ok: true,
  player: { id: 1, level: 11, hp: 438, maxHp: 438, pos:{x:0,y:0,z:0}, facing:0, dead:false, inCombat:false, targetId:null },
  economy: { copper: 100 },
  quests: { active: [], done: [] },
  inventory: { items: [], junkCount: 0, slotsUsed: 0 },
  nearby: { vendors: [], givers: [], nodes: [], hostileMobsInRange: [] },
};

let pass = 0, fail = 0;
function check(name, cond) { if (cond) { pass++; console.log('  PASS', name); } else { fail++; console.log('  FAIL', name); } }

initMemory();

// T1: sell_junk когда junkCount>0 -> вызывает sellAllJunk, верификация success (copper растёт, junk падает)
(function(){
  const api = makeMock({ ...base, inventory: { items:[{quality:0,count:5}], junkCount:5, slotsUsed:1 }, economy:{copper:100} });
  const r = step(api);
  check('T1 goal=sell_junk', r.goal === 'sell_junk');
  check('T1 calls sellAllJunk', api._calls.includes('sellAllJunk'));
  // эмулируем изменение мира после продажи
  api._set({ ...base, inventory: { items:[], junkCount:0, slotsUsed:0 }, economy:{copper:300} });
  // повторный step уже после изменения не нужен — verify внутри step читает after как текущий ws
})();

// T2: accept_quest когда гивер рядом -> openQuestDialog + acceptQuest
(function(){
  const api = makeMock({ ...base, nearby:{ vendors:[], givers:[{id:42, dist:2, questIds:['q_boars']}], nodes:[], hostileMobsInRange:[] }, quests:{active:[], done:[]} });
  const before = api.readWorldState();
  const r = step(api);
  check('T2 goal=accept_quest', r.goal === 'accept_quest');
  check('T2 calls openQuestDialog:42', api._calls.includes('openQuestDialog:42'));
  check('T2 calls acceptQuest:q_boars', api._calls.includes('acceptQuest:q_boars'));
})();

// T3: complete_quest когда ready -> turnInQuest
(function(){
  const api = makeMock({ ...base, quests:{ active:[{id:'q_x', state:'ready', ready:true}], done:[] }, nearby:{ vendors:[], givers:[{id:7,dist:1,questIds:[]}], nodes:[], hostileMobsInRange:[] } });
  const r = step(api);
  check('T3 goal=complete_quest', r.goal === 'complete_quest');
  check('T3 calls turnInQuest:q_x', api._calls.includes('turnInQuest:q_x'));
})();

// T4: gather когда node рядом
(function(){
  const api = makeMock({ ...base, nearby:{ vendors:[], givers:[], nodes:[{id:'n1', dist:1, nodeType:'ore'}], hostileMobsInRange:[] } });
  const r = step(api);
  check('T4 goal=gather', r.goal === 'gather');
  check('T4 calls harvestNode:n1', api._calls.includes('harvestNode:n1'));
})();

// T5: baseline (combat_farm) когда нет специфичных целей
(function(){
  const api = makeMock({ ...base });
  const r = step(api);
  check('T5 delegatedToBaseline', r.delegatedToBaseline === true);
})();

// T6: priority — use_food (HP<60%) важнее sell_junk
(function(){
  const api = makeMock({ ...base, player:{...base.player, hp:100}, inventory:{ items:[{quality:0,count:3}], junkCount:3, slotsUsed:1 } });
  const r = step(api);
  check('T6 goal=use_food (priority)', r.goal === 'use_food');
})();

console.log(`\nRESULT: ${pass} passed, ${fail} failed`);
process.exit(fail === 0 ? 0 : 1);
