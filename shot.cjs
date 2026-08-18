const http=require('http'), fs=require('fs');
const get=(p)=>new Promise((res,rej)=>{const r=http.request({host:'127.0.0.1',port:9222,path:p,method:'GET'},x=>{let d='';x.on('data',c=>d+=c);x.on('end',()=>res(d));});r.on('error',rej);r.end();});
const post=(p,b)=>new Promise((res,rej)=>{const body=JSON.stringify(b);const r=http.request({host:'127.0.0.1',port:9222,path:p,method:'POST',headers:{'content-type':'application/json'}},x=>{let d='';x.on('data',c=>d+=c);x.on('end',()=>res(d));});r.on('error',rej);r.write(body);r.end();});
(async()=>{
  const tabs=JSON.parse(await get('/json'));
  const tab=tabs.find(t=>/worldofclaudecraft/i.test(t.url||t.title)&&t.type==='page');
  console.log('tab', tab.id);
  const r=await post(`/session/${tab.id}/Page.captureScreenshot`,{format:'png'});
  const j=JSON.parse(r);
  if(j.error){console.log('ERR',JSON.stringify(j.error));process.exit(1);}
  fs.writeFileSync('D:/world-of-claudecraft/game_shot.png', Buffer.from(j.result.data,'base64'));
  console.log('shot saved', j.result.data.length, 'bytes');
})().catch(e=>{console.error('ERR',e.message);process.exit(1);});
