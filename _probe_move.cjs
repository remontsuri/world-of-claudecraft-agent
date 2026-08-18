const { connect } = require('puppeteer-core');
const CDP = 'http://127.0.0.1:9222';
(async () => {
  const browser = await connect({ browserURL: CDP });
  let page=null;
  for (const p of await browser.pages()){const u=(typeof p.url==='function')?p.url():(p.url||'');if(u.includes('worldofclaudecraft')){page=p;break;}}
  await page.bringToFront();
  await page.waitForFunction('!!window.__game && !!window.__game.sim', {timeout:15000});
  const before = await page.evaluate(() => {
    const p = window.__game.sim.player;
    return { x: p.pos.x, z: p.pos.z, dead: !!p.dead, hp: p.hp,
             hasOnline: !!window.__game.online,
             setMove: typeof (window.__game.online && window.__game.online.setMoveInput),
             ctrlMove: typeof (window.__game.controller && window.__game.controller.move),
             ctrlStop: typeof (window.__game.controller && window.__game.controller.stop) };
  });
  // try setMoveInput
  let r1 = await page.evaluate(() => { try { window.__game.online.setMoveInput({forward:1}); return 'ok'; } catch(e){ return 'ERR:'+e.message; } });
  await new Promise(r=>setTimeout(r,2500));
  let after1 = await page.evaluate(() => { const p=window.__game.sim.player; return {x:p.pos.x,z:p.pos.z}; });
  let d1 = Math.hypot(after1.x-before.x, after1.z-before.z);
  await page.evaluate(() => { try { window.__game.online.setMoveInput({forward:0}); } catch(_){} });
  // try controller.move
  let r2 = await page.evaluate(() => { try { window.__game.controller.move({forward:true}); return 'ok'; } catch(e){ return 'ERR:'+e.message; } });
  await new Promise(r=>setTimeout(r,2500));
  let after2 = await page.evaluate(() => { const p=window.__game.sim.player; return {x:p.pos.x,z:p.pos.z}; });
  let d2 = Math.hypot(after2.x-after1.x, after2.z-after1.z);
  await page.evaluate(() => { try { window.__game.controller.stop(); } catch(_){} });
  console.log('BEFORE', JSON.stringify(before));
  console.log('setMoveInput:', r1, '| moved', d1.toFixed(2));
  console.log('controller.move:', r2, '| moved', d2.toFixed(2));
  await browser.disconnect();
})().catch(e=>{console.error('ERR',e.message);process.exit(1);});
