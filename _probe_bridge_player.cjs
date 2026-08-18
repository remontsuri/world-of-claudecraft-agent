const http=require('http');
function postJson(url,body){return new Promise((res,rej)=>{const data=JSON.stringify(body||{});const u=new URL(url);const req=http.request({hostname:u.hostname,port:u.port,path:u.pathname,method:'POST',headers:{'Content-Type':'application/json','Content-Length':Buffer.byteLength(data)}},(r)=>{let d='';r.on('data',c=>d+=c);r.on('end',()=>{try{res(JSON.parse(d))}catch(e){rej(e)}});});req.on('error',rej);req.write(data);req.end();});}
(async()=>{
  const r = await postJson('http://127.0.0.1:8791/', {action:'snapshot'});
  const info = r.info || {};
  console.log('bridge player_pos:', info.player_pos);
  console.log('bridge killed? deaths=', info.deaths, 'kills=', info.kills);
  const npc = (info.nearby||[]).filter(n=>n.kind==='npc').slice(0,3);
  console.log('bridge npc sample:', npc.map(n=>({name:n.name, questIds:n.questIds, keys:Object.keys(n)})));
})().catch(e=>console.error('ERR',e.message));
