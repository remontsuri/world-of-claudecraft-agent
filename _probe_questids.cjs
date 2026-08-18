const { connect } = require('puppeteer-core');
const CDP = 'http://127.0.0.1:9222';
(async () => {
  const browser = await connect({ browserURL: CDP });
  let page=null;
  for (const p of await browser.pages()){const u=(typeof p.url==='function')?p.url():(p.url||'');if(u.includes('worldofclaudecraft')){page=p;break;}}
  await page.bringToFront();
  await page.waitForFunction('!!window.__game && !!window.__game.sim', {timeout:15000});
  const out = await page.evaluate(() => {
    const sim = window.__game.sim;
    const npcs=[];
    for (const e of sim.entities.values()) {
      if (e.kind === 'npc') {
        npcs.push({
          name: e.name,
          questIds: e.questIds || null,
          questId: e.questId || null,
          // is questIds an own-enumerable property?
          hasOwn_questIds: Object.prototype.hasOwnProperty.call(e, 'questIds'),
          descriptor: (() => { try { const d = Object.getOwnPropertyDescriptor(e, 'questIds'); return d ? (d.get?'getter':'value:'+JSON.stringify(d.value)) : 'inherited'; } catch(err){ return 'err:'+err.message; } })(),
        });
      }
    }
    return npcs.slice(0,5);
  });
  console.log(JSON.stringify(out, null, 2));
  await browser.disconnect();
})().catch(e=>{console.error('ERR',e.message);process.exit(1);});
