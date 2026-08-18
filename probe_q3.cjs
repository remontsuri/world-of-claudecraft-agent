const pptr=require('puppeteer-core');
(async()=>{
  const b=await pptr.connect({browserURL:'http://127.0.0.1:9222',defaultViewport:null});
  const pages=await b.pages();
  const page=pages.find(p=>/worldofclaudecraft/i.test(p.url()));
  const r=await page.evaluate(()=>{
    const sim=window.__game.sim;
    const out={};
    out.questLogKeys = Object.keys(sim.questLog||{});
    out.questsDoneKeys = Object.keys(sim.questsDone||{});
    // sample a questLog entry
    const qid = out.questLogKeys[0];
    if(qid){
      const q=sim.questLog[qid];
      out.qSampleKeys = Object.keys(q);
      out.qSample = JSON.parse(JSON.stringify({
        id:q.id, title:q.title, state:q.state,
        objectives:q.objectives, counts:q.counts, progress:q.progress
      })).catch?undefined:undefined;
      // safe dump
      try{ out.qSample = {id:q.id,title:q.title,state:q.state,
        obj: Array.isArray(q.objectives)? q.objectives.map(o=>typeof o==='object'?Object.keys(o):o).slice(0,5):typeof q.objectives,
        counts: q.counts, progress:q.progress}; }catch(e){ out.qSample='ERR '+e.message; }
      // call questState
      try{ out.questStateRet = sim.questState(qid); }catch(e){ out.questStateRet='ERR '+e.message; }
      try{ out.questStateRet2 = sim.questState(q); }catch(e){ out.questStateRet2='ERR '+e.message; }
    }
    // try a done quest
    const did = out.questsDoneKeys[0];
    if(did){ out.doneSample = {id:sim.questsDone[did]?.id, title:sim.questsDone[did]?.title}; 
      try{ out.doneState = sim.questState(did); }catch(e){ out.doneState='ERR'; } }
    return out;
  }).catch(async(e)=>{ await b.disconnect(); return {evaluateErr:e.message}; });
  console.log(JSON.stringify(r,null,1));
  await b.disconnect();
})().catch(e=>{console.error('ERR',e.message);process.exit(1);});
