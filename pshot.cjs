const pptr=require('puppeteer-core');
(async()=>{
  const browser=await pptr.connect({browserURL:'http://127.0.0.1:9222', defaultViewport:null});
  const pages=await browser.pages();
  const page=pages.find(p=>/worldofclaudecraft/i.test(p.url()));
  if(!page){console.log('no page, have:',pages.map(p=>p.url()).slice(0,5));process.exit(1);}
  console.log('page', page.url());
  await page.screenshot({path:'D:/world-of-claudecraft/game_shot.png'});
  console.log('shot OK');
  await browser.disconnect();
})().catch(e=>{console.error('ERR',e.message);process.exit(1);});
