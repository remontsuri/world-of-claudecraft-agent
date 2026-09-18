import { defineConfig } from 'vitest/config';

// Таймауты щедрые намеренно: тесты гоняют НАСТОЯЩУЮ симуляцию игры (одно решение
// агента = цикл мировых действий) и настоящий env-сервер upstream за бриджем,
// а не моки. Быстрый тест ценой пропуска проверки — плохая сделка.
//
// Параллелизм выключен: машина с 2 ГБ RAM, а каждый мир (in-process Sim или
// процесс env_server) — это вся симуляция целиком. Параллельные прогоны дают
// OOM-kill, который выглядит как «тесты упали», хотя код цел.
export default defineConfig({
  test: {
    include: ['tests/**/*.test.ts'],
    testTimeout: 180_000,
    hookTimeout: 120_000,
    fileParallelism: false,
    maxWorkers: 1,
    minWorkers: 1,
  },
});
