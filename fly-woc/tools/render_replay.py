#!/usr/bin/env python3
"""render_replay.py — превратить запись прогона (record_replay.py) в одну HTML-анимацию.

Зачем: смотреть на числа бенчмарка и «видеть, как муха бегает» — разные вещи. Здесь
из replay.json собирается самодостаточный HTML (без внешних файлов и сети, чтобы
открывался и в предпросмотре, и просто двойным щелчком):

  * окно вокруг мухи (масштаб ~±220 юнитов): видно, что она делает шаг за шагом;
  * мини-карта всего мира с пройденным путём — видно, куда её занесло;
  * радар: ближайшие мобы по дистанции и пеленгу (мобов в obs дают без мировых
    координат, поэтому они рисуются относительно мухи — это честно и так задумано);
  * метка цели квеста: стрелка на краю окна + дистанция (из оракула);
  * панель: действие, награда, уровень/xp/киллы/смерти/квесты, hp, GCD;
  * 13 входных каналов (то, что муха «видит») и 82 нисходящих нейрона (то, что
    читаут превращает в действие) — полоски обновляются на каждом кадре;
  * управление: пауза/пуск, скорость, перемотка, покадрово.

Запуск:
    python3 tools/render_replay.py replay.json replay.html
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

HTML = """<!doctype html>
<html lang="ru">
<meta charset="utf-8">
<title>Муха играет в World of Claudecraft — прогон {policy}</title>
<style>
  :root {{ --bg:#0d1117; --panel:#161b22; --line:#30363d; --fg:#e6edf3; --dim:#8b949e;
           --acc:#58a6ff; --good:#3fb950; --warn:#d29922; --bad:#f85149; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--fg);
          font:13px/1.45 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace; }}
  header {{ padding:10px 14px; border-bottom:1px solid var(--line); display:flex;
            gap:18px; align-items:baseline; flex-wrap:wrap; }}
  header b {{ color:var(--acc); }}
  .wrap {{ display:grid; grid-template-columns:minmax(420px,1fr) 380px; gap:12px; padding:12px; }}
  .card {{ background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:10px; }}
  canvas {{ display:block; width:100%; border-radius:6px; background:#0b0f14; }}
  .row {{ display:flex; justify-content:space-between; gap:8px; margin:3px 0; }}
  .dim {{ color:var(--dim); }}
  .big {{ font-size:20px; color:var(--acc); }}
  .bar {{ height:9px; background:#0b0f14; border:1px solid var(--line); border-radius:5px; overflow:hidden; }}
  .bar i {{ display:block; height:100%; background:var(--acc); }}
  .chans {{ display:grid; grid-template-columns:1fr 1fr; gap:4px 10px; margin-top:6px; }}
  .chan {{ font-size:11px; }}
  .dn {{ display:flex; gap:1px; margin-top:6px; }}
  .dn i {{ flex:1; height:26px; background:#0b0f14; }}
  .ctl {{ display:flex; gap:8px; align-items:center; margin-top:10px; flex-wrap:wrap; }}
  button {{ background:#21262d; color:var(--fg); border:1px solid var(--line); border-radius:6px;
            padding:5px 10px; cursor:pointer; font:inherit; }}
  button:hover {{ border-color:var(--acc); }}
  input[type=range] {{ width:150px; }}
  .legend {{ font-size:11px; color:var(--dim); margin-top:6px; }}
  .k {{ color:var(--good); }} .b {{ color:var(--bad); }} .w {{ color:var(--warn); }}
</style>
<header>
  <b>Муха играет: {policy}</b>
  <span class="dim">чек-инт {checkpoint} · сид {seed} · {encoder}-энкодер</span>
  <div class="dim" style="font-size:11px;margin-top:4px">{aux}</div>
  <span class="dim">{brain}</span>
</header>
<div class="wrap">
  <div>
    <div class="card">
      <canvas id="view" width="900" height="560"></canvas>
      <div class="ctl">
        <button id="play">⏸ пауза</button>
        <button id="prev">◀ кадр</button>
        <button id="next">кадр ▶</button>
        <label class="dim">скорость <input id="speed" type="range" min="1" max="60" value="24"></label>
        <label class="dim">кадр <input id="scrub" type="range" min="0" max="{last}" value="0" style="width:220px"></label>
        <span id="tinfo" class="dim"></span>
      </div>
      <div class="legend">
        <span class="k">■</span> муха · <span class="w">■</span> мобы (радар: дистанция+пеленг) ·
        <span class="b">■</span> цель квеста · <span class="dim">■</span> интеракт-объект · след = путь
      </div>
    </div>
    <div class="card" style="margin-top:12px">
      <div class="dim" style="font-size:11px">мини-карта мира (весь путь) — {world} · метка: куда ведёт выбранная цель</div>
      <canvas id="map" width="900" height="240"></canvas>
    </div>
  </div>
  <div>
    <div class="card">
      <div class="big" id="act">—</div>
      <div class="row"><span class="dim">шаг</span><span id="step">0</span></div>
      <div class="row"><span class="dim">награда</span><span id="rew">0</span></div>
      <div class="row"><span class="dim">уровень / xp</span><span id="lvl">1 / 0</span></div>
      <div class="row"><span class="dim">киллы / смерти</span><span id="kd">0 / 0</span></div>
      <div class="row"><span class="dim">квесты сдано</span><span id="q">0</span></div>
      <div class="row"><span class="dim">до цели квеста</span><span id="qd">—</span></div>
      <div class="row"><span class="dim">цель (<b>кортекс</b>)</span><span id="gq">—</span></div>
      <div class="row"><span class="dim">режим / действие</span><span id="gm">—</span></div>
      <div class="row"><span class="dim">кто выбрал</span><span id="gs">—</span></div>
      <div class="row"><span class="dim">здоровье</span><span id="hpv">—</span></div>
      <div class="bar"><i id="hp" style="background:var(--good)"></i></div>
      <div class="row"><span class="dim">GCD (тик — способности в откате)</span><span id="gcdv">—</span></div>
      <div class="bar"><i id="gcd" style="background:var(--warn)"></i></div>
    </div>
    <div class="card" style="margin-top:12px">
      <div class="dim" style="font-size:11px">13 входных каналов — то, что муха «видит»</div>
      <div class="chans" id="chans"></div>
    </div>
    <div class="card" style="margin-top:12px">
      <div class="dim" style="font-size:11px">82 нисходящих нейрона — выход схемы, вход читаута</div>
      <div class="dn" id="dn"></div>
      <div class="dim" style="font-size:11px;margin-top:6px">
        яркость = активность клетки (в 1/1000), красная черта = максимум по прогону
      </div>
    </div>
  </div>
</div>
<script>
const DATA = {data};
const F = DATA.frames, M = DATA.meta;
const A = M.actions, CH = M.feature_names.length ? M.feature_names : F[0].ch.map((_,i)=>"ch"+i);
const VIEW = 220;                       // полуразмер окна вокруг мухи, юнитов
const vw = 900, vh = 560;
let i = 0, playing = true, last = performance.now(), acc = 0;

// максимум по DN за прогон — для нормировки полосок
const dnMax = new Array(82).fill(1);
for (const f of F) for (let k=0;k<82;k++) if (f.dn[k] > dnMax[k]) dnMax[k] = f.dn[k];

const chans = document.getElementById("chans");
CH.forEach(nm => {{
  const d = document.createElement("div"); d.className = "chan";
  d.innerHTML = `<span class="dim">${{nm}}</span><div class="bar"><i></i></div>`;
  chans.appendChild(d);
}});
const dnEl = document.getElementById("dn");
for (let k=0;k<82;k++) dnEl.appendChild(document.createElement("i"));

function draw(cv, w, h) {{
  const c = cv.getContext("2d");
  c.clearRect(0,0,w,h);
  const f = F[i];
  // --- окно вокруг мухи
  const sx = w / (2*VIEW);
  const cx = w/2, cy = h/2;
  const P = (dx, dz) => [cx + dx*sx, cy - dz*sx*(vw/vh)];   // x вправо, z вверх (экранные пропорции)
  const proj = (wx, wz) => P((wx - f.x), (wz - f.z));

  // сетка 50 юнитов
  c.strokeStyle = "#182030"; c.lineWidth = 1;
  const step = 50;
  for (let g = Math.ceil((f.x-VIEW)/step)*step; g <= f.x+VIEW; g += step) {{
    const [X] = proj(g, f.z); c.beginPath(); c.moveTo(X,0); c.lineTo(X,h); c.stroke();
  }}
  for (let g = Math.ceil((f.z-VIEW)/step)*step; g <= f.z+VIEW; g += step) {{
    const [,Y] = proj(f.x, g); c.beginPath(); c.moveTo(0,Y); c.lineTo(w,Y); c.stroke();
  }}

  // --- след
  c.lineWidth = 2;
  for (let k = Math.max(0, i-260); k < i; k++) {{
    const a = (k - Math.max(0,i-260)) / 260;
    const [x1,y1] = proj(F[k].x, F[k].z), [x2,y2] = proj(F[k+1].x, F[k+1].z);
    c.strokeStyle = `rgba(88,166,255,${{0.06 + 0.5*a}})`;
    c.beginPath(); c.moveTo(x1,y1); c.lineTo(x2,y2); c.stroke();
  }}

  // --- мобы (радар: дистанция + пеленг; мировых координат у них нет)
  for (const [d, b, hp, aggro] of f.mobs) {{
    const ang = f.facing + b;
    const px = f.x + d*Math.sin(ang), pz = f.z + d*Math.cos(ang);
    const [X,Y] = proj(px, pz);
    if (X<-20||X>w+20||Y<-20||Y>h+20) continue;
    c.fillStyle = aggro > 0.5 ? "#d29922" : "#8b949e";
    c.beginPath(); c.arc(X, Y, 5, 0, 7); c.fill();
    c.fillStyle = "#e6edf3"; c.font = "10px monospace";
    c.fillText(`${{d.toFixed(0)}}м`, X+7, Y+3);
  }}

  // --- интеракт-объект (exists, distance, type)
  if (f.inter[0] > 0.5) {{
    const d = f.inter[1], ang = f.facing;
    const [X,Y] = proj(f.x + d*Math.sin(ang), f.z + d*Math.cos(ang));
    c.fillStyle = "#6e7681"; c.fillRect(X-4, Y-4, 8, 8);
  }}

  // --- цель квеста: если в окне — точка, иначе стрелка на краю
  if (f.qtarget) {{
    const [tx, tz] = f.qtarget;
    const dx = tx - f.x, dz = tz - f.z;
    const [X,Y] = proj(tx, tz);
    if (X>10 && X<w-10 && Y>10 && Y<h-10) {{
      c.strokeStyle = "#f85149"; c.lineWidth = 2;
      c.beginPath(); c.arc(X, Y, 9, 0, 7); c.stroke();
      c.beginPath(); c.moveTo(X-13,Y); c.lineTo(X+13,Y); c.moveTo(X,Y-13); c.lineTo(X,Y+13); c.stroke();
    }} else {{
      const ang = Math.atan2(dx, -dz);
      const R = Math.min(w,h)/2 - 26;
      const ax = cx + R*Math.cos(ang-Math.PI/2), ay = cy + R*Math.sin(ang-Math.PI/2);
      c.fillStyle = "#f85149";
      c.beginPath();
      c.moveTo(ax + 12*Math.cos(ang), ay + 12*Math.sin(ang));
      c.lineTo(ax + 12*Math.cos(ang+2.5), ay + 12*Math.sin(ang+2.5));
      c.lineTo(ax + 12*Math.cos(ang-2.5), ay + 12*Math.sin(ang-2.5));
      c.fill();
      c.font = "11px monospace";
      c.fillText(`${{f.qkind}} ${{f.qdist ? f.qdist.toFixed(0)+"м" : ""}}`,
                 ax + 16*Math.cos(ang) - 30, ay + 16*Math.sin(ang));
    }}
  }}

  // --- муха
  c.save(); c.translate(cx, cy);
  // экранный угол: facing=0 смотрит в +z (вверх); вправо — (-cos, sin)
  c.rotate(-f.facing);
  c.fillStyle = "#3fb950";
  c.beginPath(); c.moveTo(0,-11); c.lineTo(7,9); c.lineTo(0,4); c.lineTo(-7,9); c.closePath(); c.fill();
  c.restore();

  // --- подписи окна
  c.fillStyle = "#8b949e"; c.font = "12px monospace";
  c.fillText(`x=${{f.x.toFixed(0)}} z=${{f.z.toFixed(0)}} курс=${{(f.facing*57.3).toFixed(0)}}° шаг ${{f.t}}`, 10, 18);
  c.fillText(`окно ±${{VIEW}} юнитов, сетка 50`, 10, h-10);
}}

function drawMap() {{
  const cv = document.getElementById("map");
  const c = cv.getContext("2d"), w = cv.width, h = cv.height;
  const W = M.world;
  c.clearRect(0,0,w,h);
  const X = x => (x - W.minX) / (W.maxX - W.minX) * (w-20) + 10;
  const Y = z => h - 10 - (z - W.minZ) / (W.maxZ - W.minZ) * (h-20);
  c.strokeStyle = "#1f2a37"; c.strokeRect(10,10,w-20,h-20);
  c.strokeStyle = "#58a6ff"; c.lineWidth = 1.5; c.beginPath();
  F.forEach((f,k) => k ? c.lineTo(X(f.x), Y(f.z)) : c.moveTo(X(f.x), Y(f.z)));
  c.stroke();
  if (F[i].qtarget) {{
    c.fillStyle = "#f85149";
    c.beginPath(); c.arc(X(F[i].qtarget[0]), Y(F[i].qtarget[1]), 4, 0, 7); c.fill();
  }}
  c.fillStyle = "#3fb950";
  c.beginPath(); c.arc(X(F[i].x), Y(F[i].z), 4, 0, 7); c.fill();
  c.fillStyle = "#8b949e"; c.font = "11px monospace";
  c.fillText("мир: x " + W.minX.toFixed(0) + "…" + W.maxX.toFixed(0) + ", z " + W.minZ.toFixed(0) + "…" + W.maxZ.toFixed(0), 14, 20);
}}

function drawPanels() {{
  const f = F[i];
  document.getElementById("act").textContent = f.a + " — " + (A[f.a] || "?");
  document.getElementById("step").textContent = f.t;
  document.getElementById("rew").textContent = f.r.toFixed(2);
  document.getElementById("lvl").textContent = f.level + " / " + f.xp;
  document.getElementById("kd").textContent = f.kills + " / " + f.deaths;
  document.getElementById("q").textContent = f.quests_done;
  document.getElementById("qd").textContent = f.qdist ? f.qdist.toFixed(0) + " (" + f.qkind + ")" : "—";
  document.getElementById("hpv").textContent = (f.hp*100).toFixed(0) + "%";
  document.getElementById("hp").style.width = (f.hp*100).toFixed(1) + "%";
  document.getElementById("gcdv").textContent = f.gcd.toFixed(2);
  document.getElementById("gcd").style.width = Math.min(100, f.gcd*100).toFixed(1) + "%";
  const bars = document.querySelectorAll("#chans .chan i");
  bars.forEach((b,k) => {{
    const v = Math.max(0, Math.min(1, f.ch[k]));
    b.style.width = (v*100).toFixed(0) + "%";
    b.style.background = v > 0.66 ? "#3fb950" : v > 0.33 ? "#d29922" : "#58a6ff";
  }});
  const dn = document.querySelectorAll("#dn i");
  dn.forEach((d,k) => {{
    const v = Math.max(-1, Math.min(1, f.dn[k]/1000));
    const a = Math.abs(v);
    d.style.background = v >= 0
      ? `rgba(63,185,80,${{0.12 + 0.88*a}})`
      : `rgba(248,81,73,${{0.12 + 0.88*a}})`;
    d.style.height = (8 + 22*Math.min(1, a/(dnMax[k]/1000 || 1))) + "px";
    d.style.alignSelf = "flex-end";
  }});
  // кто выбрал цель: llm — модель, fallback — правила (сбой/таймаут), stale — устарела
  const g = f.goal || null;
  const src = g ? g.source : "нет (только оракул)";
  const srcCol = !g ? "#8b949e" : (g.source === "llm" ? "#3fb950"
                 : g.source === "fallback" ? "#d29922" : "#f85149");
  document.getElementById("gq").textContent = g && g.quest ? g.quest : "—";
  document.getElementById("gm").textContent = g ? `${{g.mode}} / ${{g.go}}` : "—";
  const gsEl = document.getElementById("gs");
  gsEl.textContent = src; gsEl.style.color = srcCol;
  document.getElementById("tinfo").textContent = `${{i+1}}/${{F.length}}`;
  document.getElementById("scrub").value = i;
}}

function frame(now) {{
  if (playing) {{
    const speed = +document.getElementById("speed").value;
    acc += speed / 60;
    while (acc >= 1) {{ i = Math.min(F.length-1, i+1); acc -= 1; }}
    if (i >= F.length-1) {{ playing = false; document.getElementById("play").textContent = "▶ пуск"; }}
  }}
  draw(document.getElementById("view"), vw, vh);
  drawMap(); drawPanels();
  requestAnimationFrame(frame);
}}

document.getElementById("play").onclick = e => {{
  playing = !playing; e.target.textContent = playing ? "⏸ пауза" : "▶ пуск";
}};
document.getElementById("next").onclick = () => {{ i = Math.min(F.length-1, i+1); }};
document.getElementById("prev").onclick = () => {{ i = Math.max(0, i-1); }};
document.getElementById("scrub").oninput = e => {{ i = +e.target.value; }};
requestAnimationFrame(frame);
</script>
</html>
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("replay", type=Path)
    ap.add_argument("out", type=Path)
    args = ap.parse_args()

    payload = json.loads(args.replay.read_text())
    meta = payload["meta"]
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    world = meta["world"]
    html = HTML.format(
        policy=meta["policy"], checkpoint=meta.get("checkpoint") or "—",
        seed=meta["seed"], encoder=meta["feature_encoder"], brain=meta.get("brain", ""),
        last=len(payload["frames"]) - 1,
        world=f'x {world["minX"]:.0f}…{world["maxX"]:.0f}, z {world["minZ"]:.0f}…{world["maxZ"]:.0f}',
        aux=("цель задаёт LLM-кортекс (роль: ЧТО делать; коннектом — КАК)"
             if meta.get("aux") == "cortex" else
             ("цель — вектор оракула (база)" if meta.get("aux") == "oracle" else
              "без бокового канала цели")),
        data=data,
    )
    args.out.write_text(html)
    print(f"{args.out}: {args.out.stat().st_size / 2**20:.2f} МБ, кадров {len(payload['frames'])}, "
          f"политика {meta['policy']}, чек-инт {meta.get('checkpoint')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
