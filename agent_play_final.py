import json, urllib.request, websocket, time, math, sys

CDP = "http://127.0.0.1:9222/json"
def get_page():
    tabs = json.load(urllib.request.urlopen(CDP))
    return next(t for t in tabs if t.get('type')=='page' and 'worldofclaudecraft' in t.get('url',''))

class Game:
    def __init__(self):
        page=get_page()
        self.ws=websocket.create_connection(page['webSocketDebuggerUrl'],timeout=15)
        self._id=0; self.send("Runtime.enable")
    def send(self,method,params=None,cid=None):
        self._id+=1; cid=cid or self._id
        self.ws.send(json.dumps({"id":cid,"method":method,"params":params or {}}))
        while True:
            m=json.loads(self.ws.recv())
            if m.get('id')==cid: return m
    def ev(self,expr,cid=None):
        r=self.send("Runtime.evaluate",{"expression":expr,"returnByValue":True},cid)
        return r.get('result',{}).get('result',{}).get('value')
    def state(self):
        return self.ev("""(function(){var g=window.__game,p=g.sim.player;var ents=g.online.entities||{};var out=[];
        for(var k in ents){var e=ents[k];if(e&&e.pos){out.push({id:k,x:e.pos.x,y:e.pos.y,hostile:!!e.hostile,hp:e.hp,name:e.name,dist:Math.hypot(e.pos.x-p.pos.x,e.pos.y-p.pos.y)});}}
        return JSON.stringify({px:p.pos.x,py:p.pos.y,hp:p.hp,mp:p.mp,lvl:p.level,xp:g.online.xp,target:g.sim.targetId,ents:out});})()""")
    def face(self,a): self.send("Runtime.evaluate",{"expression":f"window.__game.controller.face({a})"})
    def fwd(self): self.send("Runtime.evaluate",{"expression":"window.__game.controller.move({forward:true})"})
    def stop(self): self.send("Runtime.evaluate",{"expression":"window.__game.controller.stop()"})
    def target(self,eid): self.send("Runtime.evaluate",{"expression":f"window.__game.sim.targetEntity('{eid}')"})
    def attack(self):
        self.send("Runtime.evaluate",{"expression":"window.__game.input.attackDown&&window.__game.input.attackDown()"})
        self.send("Runtime.evaluate",{"expression":"window.__game.input.attackUp&&window.__game.input.attackUp()"})
    def interact(self):
        self.send("Runtime.evaluate",{"expression":"window.__game.input.interactDown&&window.__game.input.interactDown()"})
        self.send("Runtime.evaluate",{"expression":"window.__game.input.interactUp&&window.__game.input.interactUp()"})
    def shot(self,p):
        r=self.send("Page.captureScreenshot",{"format":"png"})
        open(p,'wb').write(__import__('base64').b64decode(r.get('result',{}).get('data','')))

def nearest_hostile(st):
    best=None;bd=1e9
    for e in st['ents']:
        if e.get('hostile') and e['dist']<bd: bd=e['dist'];best=e
    return best

GOALS = [("Sableweb",-60,4,25), ("CopperDig",-84,-64,25), ("WolfRun",-2,70,25)]
def run(seconds=300):
    g=Game(); t0=time.time(); step=0
    while time.time()-t0<seconds:
        st=json.loads(g.state()); step+=1
        mb=nearest_hostile(st)
        if mb:
            ang=math.atan2(mb['y']-st['py'],mb['x']-st['px'])
            if mb['dist']>1.0:
                g.face(ang); g.fwd()
            else:
                g.stop(); g.target(mb['id']); g.attack()
                if step%3==0: g.interact()  # loot corpse
            sys.stdout.write(f"\r[{int(time.time()-t0)}s] FIGHT {mb['name']} d={mb['dist']:.1f} hp={st['hp']} lvl={st['lvl']} xp={st['xp']}")
            sys.stdout.flush()
        else:
            # pick nearest goal not yet satisfied (use distance as proxy)
            gx,gy=None,None
            for name,gx0,gy0,rad in GOALS:
                d=math.hypot(st['px']-gx0,st['py']-gy0)
                if d>rad: gx,gy=gx0,gy0; break
            if gx is None: gx,gy=-60,4  # default sableweb
            d_goal=math.hypot(st['px']-gx,st['py']-gy)
            if d_goal>8:
                ang=math.atan2(gy-st['py'],gx-st['px'])
            else:
                ang=(step*0.2)%(2*math.pi)  # patrol around spawn
            g.face(ang); g.fwd()
            if step%15==0: g.stop()
            sys.stdout.write(f"\r[{int(time.time()-t0)}s] ->goal ({gx},{gy}) d={d_goal:.0f} hp={st['hp']} lvl={st['lvl']} xp={st['xp']}")
            sys.stdout.flush()
        time.sleep(0.3)
    g.stop(); g.shot('cdp_final.png')

if __name__=='__main__':
    run(int(sys.argv[1]) if len(sys.argv)>1 else 300)
