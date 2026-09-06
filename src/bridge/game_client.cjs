// src/bridge/game_client.js
// CDP transport for the live World of Claudecraft browser tab.
// Responsibility: connect to an already-running Chrome (--remote-debugging-port=9222),
// acquire the live game page, evaluate code in its context with auto-reconnect,
// and report health. NO game logic here — that lives in snapshot.js / actions.js.

const puppeteer = require('puppeteer-core');

const DEFAULT_CDP = 'http://127.0.0.1:9222';
const DEFAULT_TICK_MS = 220;

// Какая вкладка считается игровой. Онлайн — worldofclaudecraft, офлайн-дев —
// localhost:5173 (vite). Настраивается через WOC_TAB_MATCH (список через
// запятую), чтобы НЕ держать второй форк моста ради одной строки фильтра.
const DEFAULT_TAB_MATCH = (process.env.WOC_TAB_MATCH
  || 'worldofclaudecraft,localhost:5173,127.0.0.1:5173').split(',')
  .map((s) => s.trim()).filter(Boolean);

function tabMatches(url, patterns) {
  const u = url || '';
  return (patterns || DEFAULT_TAB_MATCH).some((p) => u.includes(p));
}

class GameClient {
  constructor({ cdpUrl = DEFAULT_CDP, tickMs = DEFAULT_TICK_MS,
                tabMatch = DEFAULT_TAB_MATCH } = {}) {
    this.cdpUrl = cdpUrl;
    this.tickMs = tickMs;
    this.tabMatch = tabMatch;
    this.browser = null;
    this.page = null;
  }

  // Connect to the existing browser. Throws if unreachable — caller decides
  // whether to exit. We never force disconnect/reconnect in a loop here; the
  // page re-acquisition in acquirePage() handles SPA reloads.
  async connect() {
    this.browser = await puppeteer.connect({ browserURL: this.cdpUrl });
    return this.browser;
  }

  // Pick the FIRST tab whose execution context actually has a live player.
  // A simple url match is NOT enough: after a character switch there can be two
  // worldofclaudecraft tabs, one dead. Re-acquiring every call is correct
  // (browser.pages() is a cheap CDP target-list call, ms-scale).
  async acquirePage() {
    if (!this.browser) this.browser = await this.connect();
    let targets;
    try {
      targets = await this.browser.targets();
    } catch (_) {
      this.browser = null;
      this.browser = await this.connect();
      targets = await this.browser.targets();
    }
    for (const t of targets) {
      if (t.type() !== 'page') continue;
      let u = (typeof t.url === 'function') ? await t.url() : (t.url || '');
      if (!tabMatches(u, this.tabMatch)) continue;
      const p = t.page ? await t.page() : t;
      try {
        const live = await p.evaluate(() => {
          const g = window.__game;
          if (!g || !g.sim) return false;
          const sim = g.sim;
          const pid = sim.primaryId;
          if (typeof pid !== 'number' && typeof pid !== 'string') return false;
          const ent = sim.entities?.get ? sim.entities.get(pid) : (sim.entities && sim.entities[pid]);
          if (!ent) return false;
          return typeof ent.hp === 'number' || typeof ent.level === 'number' || typeof ent.pos === 'object';
        });
        if (live) { this.page = p; return p; }
      } catch (_) { /* context dead, try next */ }
    }
    this.page = null;
    return null;
  }

  // Evaluate `fn` in the live game page context. Retries 3x; on failure
  // re-acquires a fresh page handle (SPA reload destroys cached context).
  // Returns the eval result, or null if all attempts fail.
  async safeEval(fn, ...args) {
    for (let attempt = 0; attempt < 3; attempt++) {
      try {
        if (!this.page) this.page = await this.acquirePage();
        if (!this.page) { await this.connect().catch(() => {}); this.page = await this.acquirePage(); }
        if (!this.page) return null;
        try { await this.page.bringToFront(); } catch (_) {}
        return await this.page.evaluate(fn, ...args);
      } catch (e) {
        console.error('[game_client] eval error (attempt ' + attempt + '):', e.message);
        try { this.page = await this.acquirePage(); } catch (_) {}
        if (!this.page) { try { await this.connect(); } catch (_) {} }
      }
    }
    return null;
  }

  // Thin wrapper used by action code (clearer name than safeEval).
  evaluate(fn, ...args) {
    return this.safeEval(fn, ...args);
  }

  async health() {
    const out = { bridge: !!this.browser, page: false, game: false };
    if (!this.browser) {
      try { this.browser = await this.connect(); } catch (_) { return out; }
    }
    out.bridge = true;
    try {
      const targets = await this.browser.targets();
      for (const t of targets) {
        if (t.type() !== 'page') continue;
        let u = (typeof t.url === 'function') ? await t.url() : (t.url || '');
        if (!tabMatches(u, this.tabMatch)) continue;
        const p = t.page ? await t.page() : t;
        out.page = true;
        try {
          out.game = await p.evaluate(() => {
            const g = window.__game;
            if (!g || !g.sim) return false;
            const sim = g.sim;
            const pid = sim.primaryId;
            if (typeof pid !== 'number' && typeof pid !== 'string') return false;
            const ent = sim.entities?.get ? sim.entities.get(pid) : (sim.entities && sim.entities[pid]);
            return !!ent;
          });
        } catch (_) { out.game = false; }
        if (out.game) { this.page = p; break; }
      }
    } catch (_) { out.page = false; out.game = false; }
    return out;
  }

  // Release held controller inputs so the character stops on bridge death.
  async releaseInputs() {
    try {
      if (!this.browser) this.browser = await this.connect();
      const targets = await this.browser.targets();
      for (const t of targets) {
        if (t.type() !== 'page') continue;
        let u = (typeof t.url === 'function') ? await t.url() : (t.url || '');
        if (!tabMatches(u, this.tabMatch)) continue;
        const p = t.page ? await t.page() : t;
        try { await p.evaluate(() => { try { window.__game.controller.stop(); } catch (_) {} }); } catch (_) {}
      }
    } catch (_) {}
  }
}

module.exports = { GameClient, DEFAULT_CDP, DEFAULT_TICK_MS };
