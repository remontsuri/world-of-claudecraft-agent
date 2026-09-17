// browser_bridge.cjs — entrypoint for the WoC <-> Python agent bridge (HTTP).
//
// Thin by design: all game/transport logic lives in src/bridge/*.
// This file ONLY: builds the GameClient, wires command handlers, defines the
// dispatch table, and serves HTTP. Every handler returns ONE shape:
//   { ok: true,  info: <flat snapshot>, ...extra }
//   { ok: false, error: <string> }
// `info` is ALWAYS the flat observation (from snapshot.js). No nesting.
//
// Run:  node browser_bridge.cjs
// Point python BrowserEnv at http://127.0.0.1:8791

const http = require('http');
const fs = require('fs');
const { GameClient } = require('./src/bridge/game_client.cjs');
const { buildSnapshot } = require('./src/bridge/snapshot.cjs');
const { createActions } = require('./src/bridge/actions.cjs');
const { createCmdQueue } = require('./src/bridge/cmd_queue.cjs');

const CDP = process.env.WOC_CDP || 'http://127.0.0.1:9222';
const PORT = parseInt(process.env.WOC_PORT || '8791', 10);
const TICK_MS = 220;

// ---- never crash on a transient error; surface it ----
process.on('uncaughtException', (e) => {
  console.error('[bridge] uncaughtException:', e && e.message);
  try { fs.writeFileSync('bridge_crash.txt', 'uncaughtException: ' + (e && e.stack || e) + '\n'); } catch (_) {}
});
process.on('unhandledRejection', (e) => {
  console.error('[bridge] unhandledRejection:', e && e.message);
});

// ---- graceful shutdown: stop the character so it doesn't run in circles ----
const client = new GameClient({ cdpUrl: CDP, tickMs: TICK_MS });
async function shutdown(code) {
  try { await client.releaseInputs(); } catch (_) {}
  process.exit(code);
}
process.on('SIGTERM', () => shutdown(0));
process.on('SIGINT', () => shutdown(0));

// ---- build handlers ----
const actions = createActions({ gameClient: client, buildSnapshot, tickMs: TICK_MS });

// Single dispatch table — the ONLY place mapping action -> handler.
const HANDLERS = {
  snapshot: actions.snapshot,
  step: actions.step,
  navigate: actions.navigate,
  raw_move: actions.raw_move,
  respawn: actions.respawn,
  explore: actions.explore,
};

async function dispatch(cmd) {
  const h = HANDLERS[cmd && cmd.action];
  if (!h) return { ok: false, error: 'unknown action: ' + (cmd && cmd.action) };
  try {
    return await h(cmd);
  } catch (e) {
    return { ok: false, error: e && e.message ? e.message : String(e) };
  }
}

// ---- bounded command queue (план 2026-08-24, пункт 2) ----
// CMD_TIMEOUT_MS: каждая команда получает собственный watchdog. Зависший
// handler (напр. farm застрял на мёртвой вкладке) отбрасывается, ответ
// ok:false/timeout уходит питону, а очередь НЕ копится бесконечно.
// Recovery использует СУЩЕСТВУЮЩИЙ механизм game_client: сброс кэша page
// (следующий safeEval сам пере-приобретёт вкладку / переподключится).
// Очередь продолжается только после успешной client.health().
const CMD_TIMEOUT_MS = parseInt(process.env.WOC_CMD_TIMEOUT_MS || '90000', 10);
function recoverAfterTimeout() {
  console.error('[bridge] cmd timeout -> dropping cached page handle for re-acquire');
  client.page = null; // существующий путь recovery: acquirePage/connect в safeEval
}
const queue = createCmdQueue({
  cmdTimeoutMs: CMD_TIMEOUT_MS,
  onTimeout: recoverAfterTimeout,
  healthCheck: async () => {
    try {
      const h = await client.health();
      return !!(h && h.bridge && h.page);
    } catch (_) { return false; }
  },
});

// ---- HTTP server ----
// All mutations to the single live game tab run through the bounded queue
// (a farm() holds the tab ~17s; concurrent calls would corrupt the world).
// See createCmdQueue above: per-command watchdog + freshPage-style recovery.

const server = http.createServer((req, res) => {
  if (req.method === 'GET' || req.method === 'HEAD') {
    const url = (req.url || '/').split('?')[0];
    if (url === '/health') {
      // Honest health: prove the bridge drives a LIVE game tab, not just that
      // the socket is open.
      client.health().then((health) => {
        res.writeHead(200, { 'content-type': 'application/json' });
        res.end(JSON.stringify(Object.assign({ ok: true }, health)));
      }).catch(() => {
        res.writeHead(200, { 'content-type': 'application/json' });
        res.end(JSON.stringify({ ok: false, bridge: false, page: false, game: false }));
      });
      return;
    }
    res.writeHead(200, { 'content-type': 'application/json' });
    res.end(JSON.stringify({ ok: true, alive: true }));
    return;
  }
  if (req.method !== 'POST') { res.writeHead(405); res.end('use POST'); return; }

  let body = '';
  req.on('data', (c) => (body += c));
  req.on('end', () => {
    let cmd;
    try { cmd = JSON.parse(body || '{}'); } catch (_) { cmd = {}; }
    queue.submit(async () => {
      const resp = await dispatch(cmd);
      res.writeHead(200, { 'content-type': 'application/json' });
      res.end(JSON.stringify(resp));
    }).catch((e) => {
      try {
        res.writeHead(200, { 'content-type': 'application/json' });
        res.end(JSON.stringify({ ok: false, error: e && e.message ? e.message : String(e) }));
      } catch (_) {}
    });
  });
});

async function main() {
  if (!await client.connect().then(() => true).catch(() => false)) {
    console.error('[bridge] initial connect failed — is Chrome on ' + CDP + '?');
    process.exit(1);
  }
  console.log('[bridge] connected to game; serving on :' + PORT);
  server.on('error', (e) => {
    console.error('[bridge] server error:', e.code || e.message);
    process.exit(e.code === 'EADDRINUSE' ? 2 : 1);
  });
  server.listen(PORT);
}

main().catch((e) => { console.error('FATAL', e && e.message); process.exit(1); });
