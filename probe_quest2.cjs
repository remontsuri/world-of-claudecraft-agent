const pptr=require('puppeteer-core');
(async()=>{
  const b=await pptr.connect({browserURL:'http://127.0.0.1:9222',defaultViewport:null});
  const pages=await b.pages();
  const page=pages.find(p=>/worldofclaudecraft/i.test(p.url()));
  const r=await page.evaluate(()=>{
    const W=window.WOC_OBS, sim=window.__game.sim;
    const out={};
    out.hasWOC = !!W;
    out.questOrder = W && W.QUEST_ORDER ? (Array.isArray(W.QUEST_ORDER)?W.QUEST_ORDER.slice(0,8):typeof W.QUEST_ORDER) : null;
    out.questsKeys = W && W.QUESTS ? Object.keys(W.QUESTS).slice(0,8) : null;
    out.questStateType = sim && typeof sim.questState;
    // pick first quest id
    const qid = W && W.QUEST_ORDER ? W.QUEST_ORDER[0] : (W&&W.QUESTS?Object.keys(W.QUESTS)[0]:null);
    out.firstQid = qid;
    if(qid && sim){
      try{ out.state = sim.questState(qid); }catch(e){ out.state='ERR '+e.message; }
      const qp = W.QUESTS[qid];
      out.qp = qp ? {id:qp.id, title:qp.title, objectivesLen: qp.objectives?qp.objectives.length:null, counts: qp.counts, obj0: qp.objectives?qp.objectives[0]:null} : null;
      out.qorType = typeof W.questObjectiveRequired;
      if(qp && qp.objectives){
        try{ out.req0 = W.questObjectiveRequired ? W.questObjectiveRequired(qp, qp, 0) : 'no_fn'; }catch(e){ out.req0='ERR '+e.message; }
      }
    }
    return out;
  });
  console.log(JSON.stringify(r,null,1));
  await b.disconnect();
})().catch(e=>{console.error('ERR',e.message);process.exit(1);});
