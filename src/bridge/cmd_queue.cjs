// cmd_queue.cjs — bounded command queue с per-command watchdog.
//
// План 2026-08-24, пункт 2: очередь команд моста не должна превращаться
// в бесконечную. Каждая команда получает собственный timeout:
//   - зависший handler отбрасывается (Promise.race), ответ ok:false/timeout;
//   - вызывается onTimeout() — recovery через СУЩЕСТВУЮЩИЙ freshPage()
//     (никакого второго механизма reconnect);
//   - следующая команда стартует только после проверки bridge/page
//     (healthCheck), иначе — честный ok:false.
//
// Чистый модуль без HTTP/CDP — тестируется моками.

function sleep(ms) { return new Promise((r) => setTimeout(r, ms)); }

/**
 * createCmdQueue({ cmdTimeoutMs, onTimeout, healthCheck })
 *   cmdTimeoutMs — watchdog на каждую команду (default 60_000);
 *   onTimeout    — async recovery после timeout (напр. () => freshPage());
 *   healthCheck  — async () => bool; перед продолжением очереди после
 *                  timeout мост должен доказать, что bridge/page живы.
 */
function createCmdQueue({ cmdTimeoutMs = 60_000, onTimeout = null, healthCheck = null } = {}) {
  let chain = Promise.resolve();
  let dropped = 0;

  function withWatchdog(fn) {
    let timer;
    const timeoutP = new Promise((resolve) => {
      timer = setTimeout(() => resolve({ __timeout: true }), cmdTimeoutMs);
    });
    const work = fn().finally(() => clearTimeout(timer));
    return Promise.race([work, timeoutP]).then(
      (r) => {
        if (r && r.__timeout) return { ok: false, error: `command timeout after ${cmdTimeoutMs}ms` };
        return r;
      },
      (e) => ({ ok: false, error: e && e.message ? e.message : String(e) }),
    );
  }

  /**
   * submit(fn) -> Promise<response>
   * fn: async () => { ok, ... } — один handler команды.
   */
  function submit(fn) {
    const run = chain.then(async () => {
      const r = await withWatchdog(fn);
      if (r.ok === false && /timeout/i.test(r.error || '')) {
        dropped++;
        // recovery: существующий механизм (freshPage), затем проверка здоровья
        if (onTimeout) {
          try { await onTimeout(); } catch (e) {
            return { ok: false, error: 'timeout recovery failed: ' + (e && e.message || e) };
          }
        }
        if (healthCheck) {
          let healthy = false;
          try { healthy = await healthCheck(); } catch (_) { healthy = false; }
          if (!healthy) {
            return { ok: false, error: 'bridge unhealthy after command timeout' };
          }
        }
      }
      return r;
    });
    // цепочка живёт на "завершении шага" (успех или ошибка не рвут её)
    chain = run.then(() => undefined, () => undefined);
    return run;
  }

  /** Дождаться опустошения очереди. */
  function idle() { return chain; }

  return { submit, idle, stats: () => ({ dropped }) };
}

module.exports = { createCmdQueue };
