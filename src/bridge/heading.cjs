// src/bridge/heading.cjs
// ЧИСТАЯ логика выбора поворота при ходьбе к цели. Вынесена отдельно, потому
// что это единственное место, где рождалось рыскание камеры.
//
// БАГ (замечен пользователем 2026-08-24): navigateToCoord каждый тик сравнивал
// |off| с ОДНИМ порогом 0.2 рад (~11°). Поворот идёт вместе с forward, поэтому
// курс проскакивает мимо нуля, |off| снова превышает порог с другим знаком —
// и агент дёргает камеру влево-вправо на каждом тике (bang-bang oscillation).
//
// ЛЕЧЕНИЕ — гистерезис (зона нечувствительности) + память состояния:
//   * начинаем поворот только при |off| > TURN_START (0.35 рад ~ 20°)
//   * продолжаем, пока |off| > TURN_STOP (0.10 рад ~ 6°)  <-- разные пороги
//   * при очень большом отклонении (> TURN_ONLY) поворачиваем БЕЗ forward,
//     иначе агент описывает круг вокруг цели вместо доворота на месте
// Состояние (turning) хранит вызывающий и передаёт обратно — модуль чистый.

const TURN_START = 0.35;   // рад: порог входа в поворот (~20°)
const TURN_STOP = 0.10;    // рад: порог выхода из поворота (~6°)
const TURN_ONLY = 1.20;    // рад: круче этого — доворот на месте (~69°)

/** Нормализация угла в диапазон (-pi, pi]. */
function normalizeAngle(a) {
  return ((a + Math.PI) % (2 * Math.PI) + 2 * Math.PI) % (2 * Math.PI) - Math.PI;
}

/**
 * @param {number} off нормализованная ошибка курса (рад), >0 = нужно turnLeft
 * @param {boolean} wasTurning поворачивали ли на прошлом тике
 * @returns {{turnLeft:boolean, turnRight:boolean, forward:boolean, turning:boolean}}
 */
function decideTurn(off, wasTurning) {
  const mag = Math.abs(off);
  const threshold = wasTurning ? TURN_STOP : TURN_START;
  if (mag <= threshold) {
    // курс достаточно точен: идём прямо и НЕ трогаем камеру
    return { turnLeft: false, turnRight: false, forward: true, turning: false };
  }
  const left = off > 0;
  // очень крутой доворот делаем без движения вперёд, чтобы не орбитировать
  const forward = mag <= TURN_ONLY;
  return {
    turnLeft: left, turnRight: !left, forward, turning: true,
  };
}

module.exports = { decideTurn, normalizeAngle, TURN_START, TURN_STOP, TURN_ONLY };
