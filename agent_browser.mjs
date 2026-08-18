// Browser agent for worldofclaudecraft (online), driven via puppeteer-core CDP.
// Pattern from scripts/smoke_browser.mjs: keyboard holds for movement,
// window.__game.sim for target/attack/loot. No teleport (online = server-authoritative).
// ADDED: death handling (Release Spirit), low-HP retreat/heal, quest-aware goals.
import { connect } from 'puppeteer-core';

const CDP = 'http://127.0.0.1:9222';
const GOALS = [
  { name: 'Sableweb', x: -60, z: 4 },
  { name: 'CopperDig', x: -84, z: -64 },
  { name: 'WolfRun', x: -2, z: 70 },
];

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

async function main() {
  const browser = await connect({ browserURL: CDP });
  let page = null;
  for (const p of await browser.pages()) {
    const u = (typeof p.url === 'function') ? p.url() : (p.url || '');
    if (u.includes('worldofclaudecraft')) { page = p; break; }
  }
  if (!page) { console.log('NO GAME TAB'); await browser.disconnect(); return; }
  await page.bringToFront();

  const state = () => page.evaluate(`(function(){
    const g=window.__game,p=g.sim.player;
    const e=g.online.entities||{};const out=[];
    for(const k in e){const ent=e[k];if(ent&&ent.pos){out.push({id:k,x:ent.pos.x,y:ent.pos.y,hostile:!!ent.hostile,hp:ent.hp,name:ent.name,dist:Math.hypot(ent.pos.x-p.pos.x,ent.pos.y-p.pos.y)});}}
    let dead=false;try{dead=p.hp<=0;}catch(e){}
    return JSON.stringify({x:p.pos.x,z:p.pos.y,hp:p.hp,maxHp:p.maxHp,lvl:p.level,xp:g.online.xp,dead,ents:out});
  })()`);

  const clickRevive = () => page.evaluate(`(function(){
    const b=[...document.querySelectorAll('button')].find(x=>/resurrect|release|revive|spirit|reborn|respawn/i.test((x.textContent||x.innerText||'')));
    if(b){b.click();return true;}return false;
  })()`);

  const t0 = Date.now();
  let holding = null;
  async function hold(key) {
    if (holding === key) return;
    if (holding) await page.keyboard.up(holding);
    holding = key;
    if (key) await page.keyboard.down(key);
  }
  async function release() { if (holding) { await page.keyboard.up(holding); holding = null; } }

  let lastAng = null;
  while (Date.now() - t0 < 240000) {
    const s = JSON.parse(await state());
    // DEATH: click Release Spirit, wait for respawn
    if (s.dead) {
      await release();
      const clicked = await clickRevive();
      console.log(`[${((Date.now()-t0)/1000)|0}s] DEAD -> revive clicked=${clicked}`);
      await sleep(3000);
      continue;
    }
    const hostile = s.ents.filter(e => e.hostile).sort((a,b)=>a.dist-b.dist)[0];
    if (hostile) {
      const hpPct = s.hp / s.maxHp;
      if (hpPct < 0.4 && hostile.dist > 1.5) {
        // retreat: back away + turn around
        await hold('s');
        await sleep(600);
        console.log(`[${((Date.now()-t0)/1000)|0}s] LOW HP ${s.hp}/${s.maxHp} retreating`);
        continue;
      }
      await release();
      await page.evaluate((id) => {
        const g = window.__game, p = g.sim.player;
        const t = g.online.entities[id];
        p.facing = Math.atan2(t.pos.x - p.pos.x, t.pos.y - p.pos.y);
        g.input.camYaw = p.facing;
        g.sim.targetEntity(id);
        if (!p.autoAttack) g.sim.startAutoAttack();
      }, hostile.id);
      await page.keyboard.press('1');
      if (hostile.dist < 1.5) await page.keyboard.press('f');
      console.log(`[${((Date.now()-t0)/1000)|0}s] FIGHT ${hostile.name} d=${hostile.dist.toFixed(1)} hp=${s.hp}/${s.maxHp} lvl=${s.lvl} xp=${s.xp}`);
      await sleep(700);
    } else {
      let gx=null, gz=null;
      for (const go of GOALS) {
        if (Math.hypot(s.x-go.x, s.z-go.z) > 20) { gx=go.x; gz=go.z; break; }
      }
      if (gx===null) { gx=-60; gz=4; }
      const ang = Math.atan2(gx - s.x, gz - s.z);
      // always hold W toward goal; tap A/D briefly to steer (never replace W)
      await hold('w');
      if (lastAng !== null && Math.abs(((ang-lastAng+Math.PI)%(2*Math.PI))-Math.PI) > 0.3) {
        const turn = ang > lastAng ? 'd' : 'a';
        await page.keyboard.press(turn);
        lastAng = ang;
      }
      if (((Date.now()-t0)/1000)|0 % 10 === 0)
        console.log(`[${((Date.now()-t0)/1000)|0}s] ->(${gx},${gz}) d=${Math.hypot(s.x-gx,s.z-gz).toFixed(0)} hp=${s.hp}/${s.maxHp} lvl=${s.lvl} xp=${s.xp}`);
      await sleep(400);
    }
  }
  await release();
  await browser.disconnect();
  console.log('DONE');
}
main().catch(e => { console.error(e); process.exit(1); });
