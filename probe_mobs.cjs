const pptr=require('puppeteer-core');
(async()=>{
  const b=await pptr.connect({browserURL:'http://127.0.0.1:9222',defaultViewport:null});
  const pages=await b.pages();
  const page=pages.find(p=>/worldofclaudecraft/i.test(p.url()));
  if(!page){console.log('no page');process.exit(1);}
  const r=await page.evaluate(()=>{
    const s=window.__game.sim, p=s.player;
    let near=[];
    for(const e of s.entities.values()){
      if(e.kind==='mob'){
        const d=Math.hypot(e.pos.x-p.pos.x,e.pos.z-p.pos.z);
        if(d<60) near.push({id:e.id,kind:e.kind,hp:e.hp,dead:e.dead,hostile:e.hostile,dist:Math.round(d),name:e.name,x:Math.round(e.pos.x),z:Math.round(e.pos.z)});
      }
    }
    near.sort((a,b)=>a.dist-b.dist);
    return {pos:{x:Math.round(p.pos.x),z:Math.round(p.pos.z)},targetId:p.targetId,
            nearCount:near.length, sample:near.slice(0,8)};
  });
  console.log(JSON.stringify(r,null,1));
  await b.disconnect();
})().catch(e=>{console.error('ERR',e.message);process.exit(1);});
