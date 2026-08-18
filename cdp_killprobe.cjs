const http=require('http');
const get=(path)=>new Promise((res,rej)=>{const r=http.request({host:'127.0.0.1',port:9222,path,method:'GET'},x=>{let d='';x.on('data',c=>d+=c);x.on('end',()=>res(d));});r.on('error',rej);r.end();});
const post=(path,body)=>new Promise((res,rej)=>{const b=JSON.stringify(body);const r=http.request({host:'127.0.0.1',port:9222,path,method:'POST',headers:{'content-type':'application/json',Accept:'application/json'}},x=>{let d='';x.on('data',c=>d+=c);x.on('end',()=>res(d));});r.on('error',rej);r.write(b);r.end();});
(async()=>{
  const targets=JSON.parse(await get('/json'));
  const tab=targets.find(t=>t.type==='page'&&/worldofclaudecraft/i.test(t.url||t.title));
  console.log('tab', tab.id, tab.url);
  await post(`/session/${tab.id}/Runtime/enable`,{});
  const expr=`(()=>{const g=window.__game;const s=g.sim;
    return {kills:s.counters?.kills, damage:s.counters?.damage, deaths:s.counters?.deaths,
            inCombat:s.player?.in_combat, auto:s.player?.auto_attack,
            targetId:s.player?.targetId, targetHp: s.player?.target?.hp,
            playerHp:s.player?.hp};})()`;
  const t0=JSON.parse(await post(`/session/${tab.id}/Runtime/evaluate`,{expression:expr,returnByValue:true})).result.value;
  console.log('T0', JSON.stringify(t0));
  await new Promise(r=>setTimeout(r,60000));
  const t1=JSON.parse(await post(`/session/${tab.id}/Runtime/evaluate`,{expression:expr,returnByValue:true})).result.value;
  console.log('T1(after 60s)', JSON.stringify(t1));
  console.log('DELTA kills', (t1.kills||0)-(t0.kills||0), 'damage', (t1.damage||0)-(t0.damage||0), 'deaths', (t1.deaths||0)-(t0.deaths||0));
})().catch(e=>{console.error('ERR',e.message);process.exit(1);});
