/* partidos.js — /partidos (feed de todos los partidos del día).
 *
 * Cubre los 3 bugs corregidos el 2026-10-13 (ver docs/app-shell.md):
 *  1. MLS/LPF duplicadas: mls-este/mls-oeste comparten código ESPN usa.1
 *     (D.scoreboard memoiza por código); loadDay ya NO pide scoreboard al
 *     slug `child` (FETCH). Si alguien revierte ese filtro, este test ve el
 *     partido dos veces en el HTML Y una llamada a scoreboard('mls-oeste',…).
 *  2. Título fusionado: con el child fuera, el grupo cae bajo el slug padre
 *     y su nombre pierde el sufijo " · Este" (sería falso para media lista);
 *     una liga sin hermano (laliga) conserva su nombre completo.
 *  3. Poll de 60s: no pide nada si no hay ningún `.pm-time.live` en el DOM;
 *     si lo hay, repite el fetch con fresh=true.
 *
 *   node scripts/test_partidos.js
 */
const fs = require('fs'), vm = require('vm'), path = require('path'), assert = require('assert');

const read = f => fs.readFileSync(path.join(__dirname, '..', 'assets', f), 'utf8');

// ── DOM mínimo: solo lo que partidos.js toca directamente (PMShell.mount
// está stubeado abajo, así que no hace falta simular #app/sidebar/appbar) ──
let liveInDom = false;
const doc = {
  readyState: 'complete',
  addEventListener() {},
  getElementById: () => null,
  querySelector: sel => (sel === '.pm-time.live' && liveInDom) ? {} : null,
};

// ── PMData falso: una lista de scoreboard por slug + log de llamadas ──
const calls = [];
function rawMatch(id, homeName, awayName) {
  return {
    id: id, date: '2026-10-13T20:00:00Z', state: 'pre', clock: '', detail: '',
    home: { id: '111', name: homeName, logo: '', score: null, winner: null },
    away: { id: '222', name: awayName, logo: '', score: null, winner: null },
  };
}
// mls-este Y mls-oeste devuelven la MISMA lista: es justo lo que pasa de
// verdad (comparten código ESPN usa.1, D.scoreboard memoiza por código) si
// alguien llega a pedírsela a los dos.
const SB = {
  'mls-este': [rawMatch('555', 'Inter Miami', 'LA Galaxy')],
  'mls-oeste': [rawMatch('555', 'Inter Miami', 'LA Galaxy')],
  laliga: [rawMatch('777', 'Real Madrid', 'Barcelona')],
};

let lastMain = '', onRenderFn = null;
let intervalFn = null;
const ctx = {
  console, setTimeout, clearTimeout,
  setInterval: (fn) => { intervalFn = fn; return 1; },   // capturado, no disparado solo
  clearInterval() {},
  requestAnimationFrame: fn => fn(),
  location: { search: '' },
  document: doc,
  window: {
    addEventListener() {},
    PMShell: {
      // Stub: no hace falta el shell real (sidebar/appbar/tema) para probar
      // partidos.js — solo que reciba el HTML del feed y dispare onRender.
      mount: function (opts) { lastMain = opts.main; onRenderFn = opts.onRender; if (onRenderFn) try { onRenderFn(); } catch (e) {} },
    },
    PMData: {
      scoreboard: function (slug, ymd, fresh) { calls.push({ slug: slug, fresh: !!fresh }); return Promise.resolve(SB[slug] || []); },
      parseEvent: function (e, slug) { var m = Object.assign({}, e); m.slug = slug; return m; },
    },
  },
};
ctx.window.window = ctx.window;
vm.createContext(ctx);
vm.runInContext(read('pm-leagues.js'), ctx);   // PM_LEAGUES/PM_LEAGUES_ORDER reales
vm.runInContext(read('partidos.js'), ctx);

setTimeout(function () {
  assert.ok(lastMain, 'se monta algo en el feed');

  // 1. Sin duplicados: mls-oeste (child) nunca se pide, y el partido de MLS
  // aparece una sola vez aunque mls-este/mls-oeste comparten código.
  assert.ok(!calls.some(function (c) { return c.slug === 'mls-oeste'; }),
    'nunca se pide scoreboard al slug child (mls-oeste)');
  const hits = (lastMain.match(/Inter Miami/g) || []).length;
  assert.strictEqual(hits, 1, 'el partido de MLS sale una sola vez, no duplicado (salió ' + hits + ')');

  // 2. Título fusionado (sin el sufijo de conferencia) para el slug con
  // hermano, y nombre intacto para uno sin hermano (laliga).
  assert.ok(lastMain.indexOf('MLS · Este') === -1, 'el grupo fusionado no lleva el sufijo " · Este"');
  assert.ok(lastMain.indexOf(' MLS<span class="btn-league__cta">') > -1, 'el grupo fusionado se titula "MLS"');
  assert.ok(lastMain.indexOf(' LaLiga<span class="btn-league__cta">') > -1, 'una liga sin hermano conserva su nombre completo');

  // 3. Poll de 60s: registrado, y gobernado por si hay `.pm-time.live` en el DOM.
  assert.ok(typeof intervalFn === 'function', 'el setInterval de 60s queda registrado');
  calls.length = 0;
  liveInDom = false;
  intervalFn();
  setTimeout(function () {
    assert.strictEqual(calls.length, 0, 'sin ningún .pm-time.live en el DOM, el poll no pide nada');

    liveInDom = true;
    intervalFn();
    setTimeout(function () {
      assert.ok(calls.length > 0, 'con un .pm-time.live en el DOM, el poll sí pide el scoreboard');
      assert.ok(calls.every(function (c) { return c.fresh === true; }), 'el poll pide siempre con fresh=true');

      console.log('OK');
    }, 50);
  }, 50);
}, 50);
