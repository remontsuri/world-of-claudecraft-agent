const { connect } = require('puppeteer-core');
const CDP = 'http://127.0.0.1:9222';
async function moved(page, fn, label) {
  const b = await page.evaluate(() => { const p=window.__game.sim.player; return [p.pos.x,p.pos.z]; });
  await page.evaluate(fn);
  await new Promise(r=>setTimeout(r,2000));
  const a = await page.evaluate(() => { const p=window.__game.sim.player; return [p.pos.x,p.pos.z]; });
  console.log(label, 'moved', Math.hypot(a[0]-b[0],a[1]-b[1]).toFixed(2));
}
(async () => {
  const browser = await connect({ browserURL: CDP });
  let page=null;
  for (const p of await browser.pages()){const u=(typeof p.url==='function')?p.url():(p.url||'');if(u.includes('worldofclaudecraft')){page=p;break;}}
  await page.bringToFront();
  await page.waitForFunction('!!window.__game && !!window.__game.sim', {timeout:15000});
  // 1: setMoveInput forward only
  await moved(page, () => { try{ window.__game.online.setMoveInput({forward:1}); }catch(e){return 'ERR:'+e.message;} }, 'setMoveInput(fwd)');
  await page.evaluate(() => { try{ window.__game.online.setMoveInput({forward:0}); }catch(_){} });
  // 2: setMoveInput full (skill code)
  await moved(page, () => { try{ window.__game.online.setMoveInput({forward:1,back:1,strafeLeft:1,strafeRight:1,turnLeft:1,turnRight:1,jump:1}); }catch(e){return 'ERR:'+e.message;} }, 'setMoveInput(full)');
  await page.evaluate(() => { try{ window.__game.online.setMoveInput({forward:0,back:0,strafeLeft:0,strafeRight:0,turnLeft:0,turnRight:0,jump:0}); }catch(_){} });
  // 3: controller.move
  await moved(page, () => { try{ window.__game.controller.stop(); window.__game.controller.move({forward:true}); }catch(e){return 'ERR:'+e.message;} }, 'controller.move');
  await page.evaluate(() => { try{ window.__game.controller.stop(); }catch(_){} });
  await browser.disconnect();
})().catch(e=>{console.error('ERR',e.message);process.exit(1);});
