#!/usr/bin/env node
/*
 * fake_cdp.cjs - фальшивый Chrome DevTools Protocol: две вкладки игры, одна из
 * которых "мертва" (контекст потерян), плюс однократный сбой evaluate.
 *
 * Нужен, чтобы транспорт CdpClient проверялся без браузера и без игры:
 * именно здесь видно, что клиент выбирает ЖИВУЮ вкладку, а не первую по списку,
 * и что после сбоя он пере-захватывает вкладку, а не возвращает null.
 *
 * Запуск: node tools/fake_cdp.cjs [httpPort] [wsPort]   (9231 / 9232)
 * WebSocket реализован вручную - зависимостей нет намеренно.
 */
const http = require('http');
const crypto = require('crypto');

const HTTP_PORT = Number(process.argv[2] || process.env.FAKE_CDP_HTTP || 9231);
const WS_PORT = Number(process.argv[3] || process.env.FAKE_CDP_WS || 9232);
const MAGIC = '258EAFA5-E914-47DA-95CA-C5AB0DC85B11';
const GAME_URL = 'http://localhost:5173/';

let retryServed = false;          // "RETRY_ONCE" падает только в первый раз

// У вкладок должны быть РАЗНЫЕ url: иначе тест не может проверить, что клиент выбрал
// живую вкладку (обе выглядят одинаково), и проверка "выбрана живая" вырождается в
// "выбрана любая". Мёртвая идёт первой — как в реальном браузере со старыми вкладками.
const targets = [
  { id: 'DEAD', live: false, url: GAME_URL },
  { id: 'LIVE', live: true, url: GAME_URL + 'live' },
];

const httpServer = http.createServer((req, res) => {
  if (req.url === '/json/list') {
    const list = targets.map(t => ({
      id: t.id, type: 'page', title: 'World of Claudecraft (' + t.id + ')',
      url: t.url,
      webSocketDebuggerUrl: 'ws://127.0.0.1:' + WS_PORT + '/devtools/page/' + t.id,
    }));
    res.writeHead(200, { 'content-type': 'application/json' });
    return res.end(JSON.stringify(list));
  }
  res.writeHead(404, { 'content-type': 'application/json' });
  res.end('{"ok":false}');
});

function handleRpc(tabId, msg) {
  const id = msg.id;
  if (msg.method === 'Runtime.enable') return { id, result: {} };
  if (msg.method !== 'Runtime.evaluate') return { id, result: {} };
  const expr = String((msg.params || {}).expression || '');
  const tab = targets.find(t => t.id === tabId);

  // Проба «в этой вкладке живёт игрок» (LIVE_PROBE из CdpClient)
  if (expr.includes('return !!e;')) {
    return { id, result: { result: { type: 'boolean', value: !!(tab && tab.live) } } };
  }
  // Потеря контекста: один раз отвечаем протокольной ошибкой
  if (expr.includes('RETRY_ONCE')) {
    if (!retryServed) {
      retryServed = true;
      return { id, error: { code: -32000, message: 'Cannot find context with specified id' } };
    }
    return { id, result: { result: { type: 'string', value: 'recovered' } } };
  }
  if (expr.includes('controller.stop')) {
    return { id, result: { result: { type: 'boolean', value: true } } };
  }
  // Готовые ответы вместо исполнения JS: 40+2 и a+b
  if (expr.includes('40+2') || expr.includes('return a+b')) {
    return { id, result: { result: { type: 'number', value: 42 } } };
  }
  return { id, result: { result: { type: 'undefined' } } };
}

// ------------------------------------------------------------------ WS (сервер)

function encodeFrame(text) {
  const payload = Buffer.from(text, 'utf8');
  const len = payload.length;
  let header;
  if (len < 126) header = Buffer.from([0x81, len]);
  else if (len < 65536) { header = Buffer.alloc(4); header[0] = 0x81; header[1] = 126; header.writeUInt16BE(len, 2); }
  else { header = Buffer.alloc(10); header[0] = 0x81; header[1] = 127; header.writeBigUInt64BE(BigInt(len), 2); }
  return Buffer.concat([header, payload]);
}

function decodeFrame(buf) {
  if (buf.length < 2) return null;
  const opcode = buf[0] & 0x0f;
  const masked = (buf[1] & 0x80) !== 0;
  let len = buf[1] & 0x7f;
  let offset = 2;
  if (len === 126) { if (buf.length < 4) return null; len = buf.readUInt16BE(2); offset = 4; }
  else if (len === 127) { if (buf.length < 10) return null; len = Number(buf.readBigUInt64BE(2)); offset = 10; }
  let maskKey = null;
  if (masked) { if (buf.length < offset + 4) return null; maskKey = buf.slice(offset, offset + 4); offset += 4; }
  if (buf.length < offset + len) return null;
  const payload = Buffer.from(buf.slice(offset, offset + len));
  if (maskKey) for (let i = 0; i < payload.length; i++) payload[i] ^= maskKey[i % 4];
  return { opcode, payload, total: offset + len };
}

const wsServer = http.createServer();
wsServer.on('upgrade', (req, socket) => {
  const key = req.headers['sec-websocket-key'];
  if (!key) { socket.destroy(); return; }
  const accept = crypto.createHash('sha1').update(key + MAGIC).digest('base64');
  socket.write('HTTP/1.1 101 Switching Protocols\r\n'
    + 'Upgrade: websocket\r\nConnection: Upgrade\r\n'
    + 'Sec-WebSocket-Accept: ' + accept + '\r\n\r\n');
  const tabId = decodeURIComponent((req.url || '').split('/').pop() || '');
  let buf = Buffer.alloc(0);
  socket.on('data', chunk => {
    buf = Buffer.concat([buf, chunk]);
    for (;;) {
      const frame = decodeFrame(buf);
      if (!frame) break;
      buf = buf.slice(frame.total);
      if (frame.opcode === 0x8) { socket.end(); return; }
      if (frame.opcode !== 0x1) continue;
      let msg;
      try { msg = JSON.parse(frame.payload.toString('utf8')); } catch (e) { continue; }
      const resp = handleRpc(tabId, msg);
      if (resp) socket.write(encodeFrame(JSON.stringify(resp)));
    }
  });
  socket.on('error', () => {});
});

httpServer.listen(HTTP_PORT, '127.0.0.1', () => {
  console.log('[fake_cdp] /json/list on :' + HTTP_PORT + '  ws on :' + WS_PORT
    + '  (tabs: DEAD, LIVE)');
});
wsServer.listen(WS_PORT, '127.0.0.1');
