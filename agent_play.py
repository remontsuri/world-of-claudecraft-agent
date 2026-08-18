import json, urllib.request, websocket, time, math, base64, sys

CDP = "http://127.0.0.1:9222/json"

def get_page():
    tabs = json.load(urllib.request.urlopen(CDP))
    return next(t for t in tabs if t.get('type') == 'page' and 'worldofclaudecraft' in t.get('url', ''))

class Game:
    def __init__(self):
        self.tabs = json.load(urllib.request.urlopen(CDP))
        page = get_page()
        self.ws = websocket.create_connection(page['webSocketDebuggerUrl'], timeout=15)
        self._id = 0
        self.send("Runtime.enable")
    def send(self, method, params=None, cid=None):
        self._id += 1
        cid = cid or self._id
        self.ws.send(json.dumps({"id": cid, "method": method, "params": params or {}}))
        while True:
            m = json.loads(self.ws.recv())
            if m.get('id') == cid:
                return m
    def ev(self, expr, cid=None):
        r = self.send("Runtime.evaluate", {"expression": expr, "returnByValue": True}, cid)
        return r.get('result', {}).get('result', {}).get('value')
    def state(self):
        return self.ev("""(function(){
          var g=window.__game, p=g.sim.player;
          var ents=g.online.entities||{}; var out=[];
          for(var k in ents){var e=ents[k]; if(e&&e.pos){out.push({id:k,x:e.pos.x,y:e.pos.y,hostile:!!e.hostile,hp:e.hp,name:e.name});}}
          return JSON.stringify({px:p.pos.x,py:p.pos.y,hp:p.hp,mp:p.mp,lvl:p.level,xp:g.online.xp,
            target:g.sim.targetId, ents:out});
        })()""")
    def move(self, fx, fy, ang):
        self.send("Runtime.evaluate", {"expression": f"window.__game.controller.move({{forward:true}})"})
        self.send("Runtime.evaluate", {"expression": f"window.__game.controller.face({ang})"})
    def stop(self):
        self.send("Runtime.evaluate", {"expression": "window.__game.controller.stop()"})
    def target(self, eid):
        self.send("Runtime.evaluate", {"expression": f"window.__game.sim.targetEntity('{eid}')"})
    def attack(self):
        # right-click attack: set input.attack held then release
        self.send("Runtime.evaluate", {"expression": "window.__game.input.attackDown&&window.__game.input.attackDown()"})
        self.send("Runtime.evaluate", {"expression": "window.__game.input.attackUp&&window.__game.input.attackUp()"})
    def interact(self):
        self.send("Runtime.evaluate", {"expression": "window.__game.input.interactDown&&window.__game.input.interactDown()"})
        self.send("Runtime.evaluate", {"expression": "window.__game.input.interactUp&&window.__game.input.interactUp()"})
    def shot(self, path):
        r = self.send("Page.captureScreenshot", {"format": "png"})
        open(path, 'wb').write(base64.b64decode(r.get('result', {}).get('data', '')))

def nearest_hostile(st):
    best = None; bd = 1e9
    for e in st['ents']:
        if e.get('hostile'):
            d = math.hypot(e['x'] - st['px'], e['y'] - st['py'])
            if d < bd:
                bd = d; best = e; best['d'] = d
    return best

def run(seconds=60):
    g = Game()
    t0 = time.time(); step = 0; kills_est = 0
    while time.time() - t0 < seconds:
        st = json.loads(g.state())
        step += 1
        mb = nearest_hostile(st)
        if mb:
            ang = math.atan2(mb['y'] - st['py'], mb['x'] - st['px'])
            if mb['d'] > 1.2:
                g.move(mb['x'], mb['y'], ang)
            else:
                g.stop(); g.target(mb['id']); g.attack()
            sys.stdout.write(f"\r[{int(time.time()-t0)}s] hostile {mb['name']} d={mb['d']:.1f} hp={st['hp']} lvl={st['lvl']} xp={st['xp']}")
            sys.stdout.flush()
        else:
            # wander: forward + occasional turn
            ang = (step * 0.3) % (2 * math.pi)
            g.move(0, 0, ang)
            if step % 8 == 0:
                g.stop()
            sys.stdout.write(f"\r[{int(time.time()-t0)}s] exploring px={st['px']:.1f} py={st['py']:.1f} hp={st['hp']} lvl={st['lvl']} xp={st['xp']}")
            sys.stdout.flush()
        time.sleep(0.4)
    g.stop()
    g.shot('cdp_play.png')
    print("\nDONE -> cdp_play.png")

if __name__ == '__main__':
    run(int(sys.argv[1]) if len(sys.argv) > 1 else 60)
