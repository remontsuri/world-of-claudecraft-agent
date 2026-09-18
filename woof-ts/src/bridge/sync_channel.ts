/**
 * sync_channel.ts — СИНХРОННЫЙ канал «запрос → ответ» к дочернему процессу.
 *
 * Зачем он вообще нужен: интерфейс World синхронный (stepAction/observe), а мир
 * за бриджем — отдельный процесс (headless env server upstream) с асинхронным
 * stdin/stdout. Читать pipe синхронно в Node напрямую нельзя: libuv переводит
 * pipe в неблокирующий режим, и fs.readSync отдаёт EAGAIN (проверено). Поэтому
 * процессом владеет воркер, а обмен идёт через SharedArrayBuffer + Atomics.wait:
 * основной поток пишет запрос, засыпает на атомике и просыпается от notify,
 * когда воркер положил строку ответа в общий буфер.
 *
 * Замерено на прототипе: ~0.17 мс на круг (3001 запрос за 503 мс) — на порядки
 * быстрее, чем нужно env-серверу (тысячи шагов за секунды).
 *
 * Код воркера — строка, исполняемая через `new Worker(code, { eval: true })`:
 * так канал остаётся одним файлом и переживает сборку esbuild в один бандл
 * (отдельный worker-файл в бандле пришлось бы искать по пути, чего мы не хотим).
 */
import { Worker } from 'node:worker_threads';

export interface SpawnSpec {
  command: string;
  args: string[];
  cwd?: string;
  env?: NodeJS.ProcessEnv;
}

export interface SyncChannelOptions {
  /** Размер буфера одной строки ответа, байт. obs-ответ env ≈ 12 КБ. */
  replyBytes?: number;
  /** Сколько хвоста stderr держать для диагностики. */
  stderrBytes?: number;
  /** Таймаут ожидания ответа, мс. */
  timeoutMs?: number;
}

const LAYOUT = {
  ctlOffset: 0,
  ctlLen: 8, // [1] = флаг ответа: 0 жду, 1 есть ответ, 2 процесс умер, 3 ответ не влез
  replyLenOffset: 32,
  payloadOffset: 64,
  exitCodeSlot: 3,
} as const;

const WORKER_SOURCE = `
const { spawn } = require('node:child_process');
const { parentPort, workerData: d } = require('node:worker_threads');
const { createInterface } = require('node:readline');

const ctl = new Int32Array(d.sab, d.ctlOffset, d.ctlLen);
const replyLen = new Int32Array(d.sab, d.replyLenOffset, 1);
const reply = new Uint8Array(d.sab, d.payloadOffset, d.replyBytes);
const stderrLen = new Int32Array(d.sab, d.payloadOffset + d.replyBytes, 1);
const stderrView = new Uint8Array(d.sab, d.payloadOffset + d.replyBytes + 8, d.stderrBytes);

function putStderr(text) {
  const b = Buffer.from(text, 'utf8');
  const n = Math.min(b.length, stderrView.length);
  stderrView.set(b.subarray(0, n));
  Atomics.store(stderrLen, 0, n);
}

const child = spawn(d.spec.command, d.spec.args, {
  cwd: d.spec.cwd,
  env: d.spec.env,
  stdio: ['pipe', 'pipe', 'pipe'],
});

child.stderr.setEncoding('utf8');
let tail = '';
child.stderr.on('data', (chunk) => {
  tail = (tail + chunk).slice(-d.stderrBytes);
  putStderr(tail);
});
child.on('error', (e) => {
  putStderr(tail + '\\n[spawn error] ' + e.message);
  Atomics.store(ctl, d.exitCodeSlot, -2);
  Atomics.store(ctl, 1, 2);
  Atomics.notify(ctl, 1);
});
child.on('exit', (code) => {
  Atomics.store(ctl, d.exitCodeSlot, code === null ? -1 : code);
  Atomics.store(ctl, 1, 2);   // будим ждущего по тому же индексу, что и ответ
  Atomics.notify(ctl, 1);
});

const rl = createInterface({ input: child.stdout });
rl.on('line', (line) => {
  const b = Buffer.from(line, 'utf8');
  if (b.length > reply.length) {
    Atomics.store(ctl, 1, 3);
    Atomics.notify(ctl, 1);
    return;
  }
  reply.set(b);
  Atomics.store(replyLen, 0, b.length);
  Atomics.store(ctl, 1, 1);
  Atomics.notify(ctl, 1);
});

parentPort.on('message', (m) => {
  if (m.t === 'w') { child.stdin.write(m.s); return; }
  if (m.t === 'c') {
    try { child.stdin.end(); } catch {}
    try { child.kill('SIGTERM'); } catch {}
    return;
  }
});
`;

export class SyncChannel {
  private readonly worker: Worker;
  private readonly ctl: Int32Array;
  private readonly replyLen: Int32Array;
  private readonly reply: Uint8Array;
  private readonly stderrLen: Int32Array;
  private readonly stderrView: Uint8Array;
  private readonly timeoutMs: number;
  private closed = false;

  private constructor(
    private readonly spec: SpawnSpec,
    sab: SharedArrayBuffer,
    replyBytes: number,
    stderrBytes: number,
    timeoutMs: number,
  ) {
    this.ctl = new Int32Array(sab, LAYOUT.ctlOffset, LAYOUT.ctlLen);
    this.replyLen = new Int32Array(sab, LAYOUT.replyLenOffset, 1);
    this.reply = new Uint8Array(sab, LAYOUT.payloadOffset, replyBytes);
    this.stderrLen = new Int32Array(sab, LAYOUT.payloadOffset + replyBytes, 1);
    this.stderrView = new Uint8Array(sab, LAYOUT.payloadOffset + replyBytes + 8, stderrBytes);
    this.timeoutMs = timeoutMs;
    this.worker = new Worker(WORKER_SOURCE, {
      eval: true,
      workerData: {
        sab,
        spec,
        replyBytes,
        stderrBytes,
        ctlOffset: LAYOUT.ctlOffset,
        ctlLen: LAYOUT.ctlLen,
        replyLenOffset: LAYOUT.replyLenOffset,
        payloadOffset: LAYOUT.payloadOffset,
        exitCodeSlot: LAYOUT.exitCodeSlot,
      },
    });
    // Воркер не должен держать процесс живым, если основной поток падает.
    this.worker.unref();
  }

  static spawn(spec: SpawnSpec, opts: SyncChannelOptions = {}): SyncChannel {
    const replyBytes = opts.replyBytes ?? 1 << 21; // 2 МБ: obs-строка env ~12 КБ, с запасом
    const stderrBytes = opts.stderrBytes ?? 1 << 16;
    const sab = new SharedArrayBuffer(LAYOUT.payloadOffset + replyBytes + 8 + stderrBytes);
    return new SyncChannel(spec, sab, replyBytes, stderrBytes, opts.timeoutMs ?? 30_000);
  }

  /** Отправить строку и блокирующе дождаться одной строки ответа. */
  request(line: string): string {
    if (this.closed) throw new Error(`канал к миру закрыт (процесс: ${this.spec.command} ${this.spec.args.join(' ')})`);
    Atomics.store(this.ctl, 1, 0);
    this.worker.postMessage({ t: 'w', s: line.endsWith('\n') ? line : `${line}\n` });

    const deadline = Date.now() + this.timeoutMs;
    for (;;) {
      Atomics.wait(this.ctl, 1, 0, Math.max(1, deadline - Date.now()));
      const st = Atomics.load(this.ctl, 1);
      if (st === 1) break;
      if (st === 2) {
        throw new Error(
          `процесс мира завершился (code=${Atomics.load(this.ctl, LAYOUT.exitCodeSlot)}) до ответа на "${line.slice(0, 80)}"` +
            (this.stderrTail() ? `;\nstderr:\n${this.stderrTail()}` : ''),
        );
      }
      if (st === 3) throw new Error(`ответ мира длиннее буфера канала (${this.reply.length} байт)`);
      if (Date.now() > deadline) {
        throw new Error(
          `таймаут ${this.timeoutMs} мс: мир не ответил на "${line.slice(0, 80)}"` +
            (this.stderrTail() ? `;\nstderr:\n${this.stderrTail()}` : ''),
        );
      }
    }
    // ВАЖНО: Buffer.from(typedArray, off, len) offset/length ИГНОРИРУЕТ и копирует
    // весь view (ловушка, на которую мы наткнулись в прототипе) — нужен subarray.
    const n = Atomics.load(this.replyLen, 0);
    return Buffer.from(this.reply.subarray(0, n)).toString('utf8');
  }

  /** Хвост stderr процесса мира: ошибки upstream не прячем (python-клиент игры их глушит — мы нет). */
  stderrTail(): string {
    const n = Atomics.load(this.stderrLen, 0);
    return Buffer.from(this.stderrView.subarray(0, n)).toString('utf8');
  }

  /** Код завершения процесса мира, если он уже умер. */
  exitCode(): number | null {
    const code = Atomics.load(this.ctl, LAYOUT.exitCodeSlot);
    return code === 0 ? null : code;
  }

  close(): void {
    if (this.closed) return;
    this.closed = true;
    try {
      this.worker.postMessage({ t: 'c' });
    } catch {
      /* воркер уже мёртв — закрывать нечего */
    }
    void this.worker.terminate();
  }
}
