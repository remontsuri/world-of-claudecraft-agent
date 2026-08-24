// src/bridge/quests_done.cjs
// Честный подсчёт сданных квестов. Вынесен отдельно, потому что ошибка здесь
// делала ВСЮ квестовую линию невидимой для агента.
//
// Замер 2026-08-24: online.questsDone — это Set(7) с реально сданными квестами
// (q_wolves, q_boars, q_bandits, q_murlocs, q_spiders,
//  q_prof_workorder_kitchens, q_prof_workorder_loom), но снапшот отдавал 0,
// потому что проверял `typeof questsDone === 'number'`. У Set typeof ===
// 'object', условие всегда ложно -> фоллбек на done.length, а ведро done в
// онлайне пустое (сервер не присылает историю). Верификатор считал каждую
// успешную сдачу провалом и учил агента, что квесты сдавать бесполезно.

/**
 * @param {object|null} online клиентский online-объект (может отсутствовать)
 * @param {Array} doneBucket ведро done из снапшота
 * @returns {number} число сданных квестов
 */
function questsDoneCount(online, doneBucket) {
  const fallback = Array.isArray(doneBucket) ? doneBucket.length : 0;
  const qd = online ? online.questsDone : undefined;
  let fromOnline = null;
  if (typeof qd === 'number') {
    fromOnline = qd;
  } else if (qd && typeof qd.size === 'number') {
    fromOnline = qd.size;                 // Set — основной случай в онлайне
  } else if (Array.isArray(qd)) {
    fromOnline = qd.length;
  }
  if (fromOnline === null) return fallback;
  // Берём максимум: офлайн-сим может знать done, которого ещё нет в online.
  return Math.max(fromOnline, fallback);
}

module.exports = { questsDoneCount };
