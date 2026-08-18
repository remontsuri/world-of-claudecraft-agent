// Live инъекция + loop-проверка v1-адаптера (Step 6).
// Через puppeteer-core.connect (НЕ close — disconnect только).
const puppeteer = require('puppeteer-core');
const fs = require('fs');

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

(async () => {
  const bundle = fs.readFileSync('dist-tools/agent_v1.iife.js', 'utf8');
  const browser = await puppeteer.connect({ browserURL: 'http://localhost:9222' });
  const pages = await browser.pages();
  const page = pages.find((p) => /claudecraft/i.test(p.url() || '')) || pages[0];
  await page.waitForFunction('window.__game && window.__game.sim && window.__game.sim.player', { timeout: 15000 });

  // инъекция бандла (IIFE -> window.__agentV1)
  await page.evaluate(bundle);
  const ready = await page.evaluate(() => !!window.__agentV1);
  console.log('READY:', ready);
  if (!ready) { console.log('inject failed'); await browser.disconnect(); process.exit(1); }

  const caps = await page.evaluate(() => window.__agentV1.capabilities().map((c) => c.name + (c.supported ? '' : '(unsupported)')));
  console.log('CAPS:', caps.join(', '));

  const ws = await page.evaluate(() => window.__agentV1.worldState());
  console.log('WORLD: lvl', ws.player.level, 'hp', ws.player.hp + '/' + ws.player.hpMax,
    'copper', ws.player.copper, 'x', ws.player.x?.toFixed(1), 'z', ws.player.z?.toFixed(1),
    'questsActive', ws.quests.active.length, 'questsDone', ws.quests.done.length,
    'nearby', JSON.stringify(ws.nearby.map((o) => o.type + (o.known ? '*' : '') + ':' + (o.dist ? o.dist.toFixed(0) : '?'))));

  // loopTick x3 (понаблюдаем за решениями агента, не дольше 6с)
  for (let i = 0; i < 3; i++) {
    const r = await page.evaluate(() => window.__agentV1.loopTick());
    console.log(`LOOP[${i}]`, JSON.stringify({ goal: r.goal, skill: r.skill, del: r.delegatedToB1, ver: r.verification, nav: r.nav ? r.nav.dist?.toFixed(0) : null, note: r.note }));
    await sleep(1500);
  }

  // навыки (stats)
  const skills = await page.evaluate(() => window.__agentV1.skills);
  console.log('SKILLS:', skills.map((s) => `${s.name}:${s.stats.runs}/${s.stats.successes}/${s.stats.failures}`).join(' '));

  await browser.disconnect();
  console.log('DONE (browser left running)');
})().catch((e) => { console.error('ERR', e.message); process.exit(1); });
