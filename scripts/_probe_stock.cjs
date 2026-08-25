const WebSocket = require("ws");
const ws = new WebSocket("ws://127.0.0.1:9222/devtools/page/46F5617BDB91BA72951EB307C6DE30C5");
// Ищем РЕАЛЬНОЕ имя axe-инструмента: у кого что продаётся, все предметы всех вендоров
ws.on("open", () => ws.send(JSON.stringify({id:1, method:"Runtime.evaluate", params:{
  expression: `JSON.stringify((function(){
    var sim=window.__game.sim;
    var all={};
    for (var e of sim.entities.values()) {
      if((e.kind==='npc') && Array.isArray(e.vendorItems) && e.vendorItems.length>0){
        all[e.name]=e.vendorItems;
      }
    }
    return all;
  })())`,
  returnByValue:true}})));
ws.on("message", (d) => { var m=JSON.parse(d); if(m.id===1){console.log(m.result.result.value);ws.close();} });
