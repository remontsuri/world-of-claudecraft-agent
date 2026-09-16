// probe_game_shape.ts — спрашивает у самой игры её размеры obs и действий.
//
// Зачем: раскладка obs зависит от числа способностей и числа квестов, а они
// меняются от версии к версии (см. obs_layout.py). Регулярки по исходнику
// ошибаются на спредах и на переносах кода — этот пробник исполняет игровые
// модули и печатает фактические размеры.
//
// Запуск (в клоне levy-street/world-of-claudecraft, нужен src/sim):
//   npx --yes esbuild probe_game_shape.ts --bundle --platform=node \
//       --format=cjs --outfile=/tmp/probe.cjs && node /tmp/probe.cjs
//
// Замеры, снятые этим пробником на тегах (используются в тестах):
//   v0.30.0/v0.31.0  344 /  59 действий / 46 способностей /  96 квестов
//   v0.32.0-v0.35.0  556 /  59           / 46             / 202
//   v0.36.0-v0.39.0  567 /  61           / 48             / 204
//   v0.40.0          587 /  61           / 48             / 214
//   v0.41.0          593 /  61           / 48             / 217
//   v0.42.2          607 /  61           / 48             / 224
import { QUEST_ORDER, QUESTS } from './src/sim/data';
import { ACTIONS, obsSize } from './src/sim/obs';

const abilityActions = ACTIONS.filter((a) => a.startsWith('ability_'));
console.log(JSON.stringify({
  obs_size: obsSize(),
  actions: ACTIONS.length,
  ability_slots: abilityActions.length,
  base_actions: ACTIONS.length - abilityActions.length,
  quest_order: QUEST_ORDER.length,
  quests_defined: Object.keys(QUESTS).length,
  quest_base_derived: 16 + abilityActions.length * 2 + 9 + 30 + 5,
}, null, 1));
