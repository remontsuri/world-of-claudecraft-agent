
const puppeteer = require('puppeteer-core');
const sleep = (ms) => new Promise(r => setTimeout(r, ms));
(async () => {
  const b = await puppeteer.connect({ browserURL: 'http://127.0.0.1:9222' });
  const pages = await b.pages();
  let page = null;
  for (const p of pages) {
    const ok = await p.evaluate(() => !!window.__game).catch(() => false);
    if (ok) { page = p; break; }
  }
  const q0 = await page.evaluate(() => {
    const g = window.__game;
    return {
      qlog: [...g.sim.questLog.entries()].filter(([i,q]) => q.state==='ready').map(([i])=>i),
      pending: g.online && g.online.pendingQuestCommands ? [...g.online.pendingQuestCommands.entries()] : null,
    };
  });
  console.log('before:', JSON.stringify(q0));
  await page.evaluate(() => {
    const g = window.__game;
    const rid = [...g.sim.questLog.entries()].find(([i,q]) => q.state==='ready');
    if (rid) { g.sim.turnInQuest(String(rid[0])); }
  });
  for (let i=0;i<12;i++) {
    await sleep(500);
    const st = await page.evaluate(() => {
      const g = window.__game;
      const ev = (g.online && typeof g.online.drainEvents === 'function') ? g.online.drainEvents() : [];
      const simEv = (g.sim && typeof g.sim.drainEvents === 'function') ? g.sim.drainEvents() : [];
      return {
        ready: [...g.sim.questLog.entries()].filter(([id,q])=>q.state==='ready').map(([id])=>id),
        done: g.sim.questsDone ? [...g.sim.questsDone] : null,
        pending: g.online && g.online.pendingQuestCommands ? [...g.online.pendingQuestCommands.entries()] : null,
        evTypes: ev.map(e=>e.type),
        simEvTypes: simEv.map(e=>e.type),
        errors: ev.filter(e=>e.type==='error').map(e=>({t:e.text,r:e.reason})),
      };
    });
    if (i===0 || st.errors.length || (st.evTypes && st.evTypes.length)) console.log(i, JSON.stringify(st));
  }
  await b.disconnect();
})().catch(e => { console.error('FAIL', e.message); process.exit(1); });
