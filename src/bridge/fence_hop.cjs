// src/bridge/fence_hop.cjs
// Чистая логика «перепрыгнуть забор впереди». Вынесена отдельно и покрыта
// тестами (test_fence_jump.cjs), потому что это КОРНЕВАЯ причина застревания
// агента, а не косметика.
//
// ПРАВИЛА ИГРЫ (проверены по исходникам, не догадки):
//   src/sim/player_motion.ts:432  clearFences = !p.onGround && p.jumping
//       -> забор игнорируется коллизией ТОЛЬКО в прыжке;
//   src/sim/colliders.ts:1735     if (ignoreFences && c.isFence) continue;
//   src/sim/player_motion.ts:637  inp.jump && (p.onGround || coyote) -> прыжок
//       -> прыгать имеет смысл только СТОЯ НА ЗЕМЛЕ;
//   src/main.ts:3959-3965         рабочий пример (клик-мышью): каждый кадр
//       pathCrossesFence(pos, ahead) -> mi.jump = true.
//
// Наш навигатор в actions.cjs слова "jump" не содержал вообще: при застревании
// он поворачивал на 120° и толкался — уходил ВДОЛЬ забора, не преодолевая его.
// Отсюда «агент упёрся в забор» и позиция, не меняющаяся десятки шагов.

// Насколько далеко вперёд смотреть, ищя забор. main.ts использует
// CLICK_MOVE_FENCE_JUMP_LOOKAHEAD; держим тот же порядок величины.
const FENCE_LOOKAHEAD = 1.5;

/**
 * @param {{x:number,z:number}} pos позиция игрока
 * @param {number} facing текущий курс (рад); facing=0 -> +Z
 * @param {boolean} fenceAhead результат pathCrossesFence(pos -> ahead)
 * @param {boolean} onGround стоит ли персонаж на земле
 * @returns {{ahead:{x:number,z:number}, jump:boolean, forward:boolean}}
 */
function fenceHopPlan(pos, facing, fenceAhead, onGround) {
  const ahead = {
    x: pos.x + Math.sin(facing) * FENCE_LOOKAHEAD,
    z: pos.z + Math.cos(facing) * FENCE_LOOKAHEAD,
  };
  // Прыжок только когда забор реально впереди И мы на земле: в воздухе
  // sim всё равно отвергнет (inp.jump && (onGround || coyote)).
  const jump = Boolean(fenceAhead && onGround);
  return { ahead, jump, forward: true };
}

module.exports = { fenceHopPlan, FENCE_LOOKAHEAD };
