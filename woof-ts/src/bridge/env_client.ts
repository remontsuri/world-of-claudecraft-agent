/**
 * env_client.ts — клиент NDJSON-контракта headless env server игры.
 *
 * Контракт взят ИЗ ДЕРЕВА ИГРЫ (headless/env_server.ts, шапка файла):
 *   -> {"cmd":"info"}                                   <- {"obs_size","num_actions","actions"}
 *   -> {"cmd":"reset","seed","player_class","player_level","config"}  <- {"obs","info"}
 *   -> {"cmd":"step","action":N}                        <- {"obs","reward","terminated","truncated","info"}
 *   -> {"cmd":"close"}
 * один запрос — ровно одна строка ответа; `info` = {level, xp, hp, kills, deaths,
 * quests_done, copper, step}. Ошибки приходят как {"error": "..."} — мы их
 * бросаем исключением вместе с хвостом stderr, а не глотаем.
 *
 * Размеры НЕ захардкожены: obs_size/num_actions/actions спрашиваем у мира и
 * сверяем с фактами игры (gameFacts) — расхождение означает, что мир не тот,
 * за кого себя выдаёт, и прогон обязан упасть до первого измерения.
 */
import { gameFacts } from '../facts';
import { SyncChannel, type SpawnSpec, type SyncChannelOptions } from './sync_channel';

export interface EnvInfoDict {
  level: number;
  xp: number;
  hp: number;
  kills: number;
  deaths: number;
  quests_done: number;
  copper: number;
  step: number;
}

export interface EnvInfoReply {
  obs_size: number;
  num_actions: number;
  actions: string[];
}

export interface EnvResetReply {
  obs: number[];
  info: EnvInfoDict;
}

export interface EnvStepReply extends EnvResetReply {
  reward: number;
  terminated: boolean;
  truncated: boolean;
}

/** Конфиг эпизода (env принимает его в reset; значения по умолчанию — из DEFAULT_CONFIG игры). */
export interface EnvEpisodeConfig {
  frameSkip?: number;
  maxSteps?: number;
  respawnSeconds?: number;
  terminateOnDeath?: boolean;
  rewards?: Record<string, number>;
}

export interface EnvClientOptions extends SyncChannelOptions {
  spec: SpawnSpec;
  /** Сверять info/obs_size/actions с фактами игры при старте (по умолчанию да). */
  verifyFacts?: boolean;
}

export class EnvClient {
  private readonly channel: SyncChannel;
  private started = false;
  readonly info: EnvInfoReply;

  private constructor(opts: EnvClientOptions) {
    this.channel = SyncChannel.spawn(opts.spec, opts);
    const raw = this.request({ cmd: 'info' }) as unknown as EnvInfoReply;
    if (typeof raw.obs_size !== 'number' || typeof raw.num_actions !== 'number' || !Array.isArray(raw.actions)) {
      throw new Error(`мир ответил на info не тем, что обещает контракт: ${JSON.stringify(raw).slice(0, 200)}`);
    }
    this.info = raw;
    if (opts.verifyFacts !== false) {
      const f = gameFacts();
      if (raw.obs_size !== f.obsSize || raw.num_actions !== f.numActions) {
        throw new Error(
          `мир не совпадает с деревом игры: obs_size=${raw.obs_size} (у нас ${f.obsSize}), ` +
            `num_actions=${raw.num_actions} (у нас ${f.numActions}) — соберите env из того же чекаута (tools/build_env.sh)`,
        );
      }
      for (let i = 0; i < f.actions.length; i++) {
        if (raw.actions[i] !== f.actions[i]) {
          throw new Error(`словарь действий мира расходится с игрой на позиции ${i}: "${raw.actions[i]}" != "${f.actions[i]}"`);
        }
      }
    }
    this.started = true;
  }

  static spawn(opts: EnvClientOptions): EnvClient {
    return new EnvClient(opts);
  }

  private request(msg: Record<string, unknown>): Record<string, unknown> {
    const line = this.channel.request(JSON.stringify(msg));
    let parsed: Record<string, unknown>;
    try {
      parsed = JSON.parse(line) as Record<string, unknown>;
    } catch (e) {
      throw new Error(`мир прислал не-JSON: ${line.slice(0, 200)} (${(e as Error).message})`);
    }
    if (parsed.error !== undefined) {
      throw new Error(
        `мир отказал: ${String(parsed.error)} (запрос: ${JSON.stringify(msg).slice(0, 160)})` +
          (this.channel.stderrTail() ? `;\nstderr:\n${this.channel.stderrTail()}` : ''),
      );
    }
    return parsed;
  }

  reset(req: {
    seed: number;
    playerClass?: string;
    playerLevel?: number;
    config?: EnvEpisodeConfig;
    talents?: Record<string, unknown>;
  }): EnvResetReply {
    const msg: Record<string, unknown> = { cmd: 'reset', seed: req.seed };
    if (req.playerClass) msg.player_class = req.playerClass;
    if (req.playerLevel && req.playerLevel !== 1) msg.player_level = req.playerLevel;
    if (req.config) msg.config = req.config;
    if (req.talents) msg.talents = req.talents;
    const reply = this.request(msg) as unknown as EnvResetReply;
    if (!Array.isArray(reply.obs)) throw new Error('reset вернул ответ без obs');
    return reply;
  }

  step(action: number): EnvStepReply {
    const reply = this.request({ cmd: 'step', action }) as unknown as EnvStepReply;
    if (!Array.isArray(reply.obs)) throw new Error(`step вернул ответ без obs: ${JSON.stringify(reply).slice(0, 200)}`);
    return reply;
  }

  /** Хвост stderr процесса мира (для диагностики падений). */
  stderrTail(): string {
    return this.channel.stderrTail();
  }

  get alive(): boolean {
    return this.started && this.channel.exitCode() === null;
  }

  /** Закрыть мир. Контракт upstream не обещает ответа на {cmd:"close"}, поэтому
   *  ждать строку нельзя (иначе блок до таймаута): закрываем stdin и шлём SIGTERM. */
  close(): void {
    if (!this.started) return;
    this.started = false;
    this.channel.close();
  }
}
