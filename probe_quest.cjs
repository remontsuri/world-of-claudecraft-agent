const pptr=require('puppeteer-core');
(async()=>{
  const b=await pptr.connect({browserURL:'http://127.0.0.1:9222',defaultViewport:null});
  const pages=await b.pages();
  const page=pages.find(p=>/worldofclaudecraft/i.test(p.url()));
  if(!page){console.log('no page');process.exit(1);}
  const r=await page.evaluate(()=>{
    const W=(window).__game?.WOC_OBS;
    const s=(window).__game?.sim;
    if(!W||!s) return {err:'no WOC_OBS or sim'};
    const out={hasQuestOrder: !!W.QUEST_ORDER, orderLen: W.QUEST_ORDER?.length,
      hasQuests: !!W.QUESTS, hasQuestState: typeof s.questState, hasQuestLog: typeof s.questLog?.get};
    // read current quest snapshot like the bridge does
    try {
      let done=0,have=0,required=0;
      for(const qid of W.QUEST_ORDER){
        const st=s.questState? s.questState(qid): null;
        if(st==='done'){done++;continue;}
        const qp=s.questLog? s.questLog.get(qid): null;
        if(qp&&W.QUESTS&&W.QUESTS[qid]){
          W.QUESTS[qid].objectives.forEach((_o,i)=>{
            const req = W.questObjectiveRequired ? W.questObjectiveRequired(W.QUESTS[qid],qp,i):1;
            required+=req; have+=Math.min(qp.counts[i]??0,req);
          });
        }
      }
      out.snapshot={done,have,required};
    } catch(e){ out.snapErr=e.message; }
    return out;
  });
  console.log(JSON.stringify(r,null,1));
  await b.disconnect();
})().catch(e=>{console.error('ERR',e.message);process.exit(1);});
