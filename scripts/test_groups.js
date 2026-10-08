/* groups.js — páginas de competiciones de selecciones (tablas de TODOS los grupos).
 *
 * Cubre lo que se rompería en silencio:
 *  1. Grupo CON partidos pendientes → probabilidades del Monte Carlo (no 100/0).
 *  2. Grupo TERMINADO → NO se simula: las zonas salen 100/0 por el `rank` OFICIAL
 *     de ESPN (simularlo usaría nuestro desempate, que no es el de la UEFA).
 *  3. Bandas por escalera: la Liga A juega cuartos y la Liga B asciende, así que
 *     las columnas de probabilidad NO son las mismas; y cada escalera lleva su
 *     encabezado.
 *  4. Jornada y temporada de la cabecera salen de los datos, no del HTML.
 *
 *   node scripts/test_groups.js
 */
const fs = require('fs'), vm = require('vm'), path = require('path'), assert = require('assert');

const read = f => fs.readFileSync(path.join(__dirname, '..', 'assets', f), 'utf8');

// ── DOM mínimo: solo lo que groups.js toca ──
const els = {};
function el(id) {
  if (!els[id]) els[id] = {
    id: id, innerHTML: '', textContent: '',
    querySelectorAll: () => [], remove() {}, classList: { add() {} },
  };
  return els[id];
}
const doc = {
  readyState: 'complete',
  addEventListener() {},
  getElementById: el,
  querySelector: () => null,
  querySelectorAll: () => [],
};

function team(rank, name, pts, gp, gf, gc) {
  return { rank: rank, id: String(1000 + rank), name: name, logo: '', pts: pts, gp: gp, gf: gf, gc: gc, live: null };
}
// A1: 4 jugadas de 6 → quedan partidos, se simula.
const A1 = { name: 'Group A1', rows: [
  team(1, 'Francia', 10, 4, 7, 2), team(2, 'Italia', 7, 4, 8, 5),
  team(3, 'Bélgica', 6, 4, 6, 5),  team(4, 'Türkiye', 0, 4, 2, 11),
] };
// B1: 6 de 6 → grupo terminado, zonas por rank oficial.
const B1 = { name: 'Group B1', rows: [
  team(1, 'Gales', 13, 6, 10, 4), team(2, 'Islandia', 11, 6, 9, 6),
  team(3, 'Irlanda', 7, 6, 6, 8), team(4, 'Georgia', 3, 6, 4, 11),
] };

const ctx = {
  console, setTimeout, clearTimeout,
  setInterval: () => 0,                       // sin polling en el test
  requestAnimationFrame: fn => fn(),
  document: doc,
  window: {
    addEventListener() {},
    PM_GROUPS_SLUG: 'nations-league',
    PM_LEAGUES: { 'nations-league': { name: 'Nations League', code: 'uefa.nations' } },
    PMData: {
      groupTables: () => Promise.resolve({ season: '2026-27', groups: [A1, B1] }),
      scoreboard: () => Promise.resolve([]),
      parseEvent: () => null,
    },
  },
};
ctx.window.window = ctx.window;
vm.createContext(ctx);
vm.runInContext(read('league-engine.js'), ctx);   // PMEngine real: se prueba la integración
vm.runInContext(read('groups.js'), ctx);

setTimeout(function () {
  const html = els.groups.innerHTML;
  assert.ok(html, 'se pinta algo en #groups');

  // 3. Encabezados de escalera y columnas distintas por liga
  assert.ok(html.indexOf('>Liga A<') > -1 && html.indexOf('>Liga B<') > -1,
    'cada escalera lleva su encabezado (Liga A / Liga B)');
  const a1 = html.slice(html.indexOf('Grupo A1'), html.indexOf('Liga B'));
  const b1 = html.slice(html.indexOf('Grupo B1'));
  assert.ok(a1.indexOf('Cuartos') > -1 && a1.indexOf('Play-off permanencia') > -1,
    'la Liga A juega cuartos y play-off de permanencia');
  assert.ok(b1.indexOf('Ascenso') > -1 && b1.indexOf('Cuartos') === -1,
    'la Liga B asciende: no tiene columna de cuartos');

  // Fila de un equipo dentro de un trozo de tabla.
  const row = (frag, name) => frag.split('<tr').filter(r => r.indexOf('>' + name + '<') > -1)[0] || '';

  // 2. Grupo terminado: sin simular, 100/0 por rank oficial
  assert.ok(b1.indexOf('Fase terminada') > -1, 'el grupo terminado se marca como tal');
  assert.ok(/prob up is-lock[\s\S]*?100/.test(row(b1, 'Gales')),
    'la 1ª del grupo terminado asciende al 100%');
  assert.ok(/prob down is-lock[\s\S]*?100/.test(row(b1, 'Georgia')),
    'la última del grupo terminado desciende al 100%');
  assert.ok(row(b1, 'Irlanda').indexOf('is-lock') === -1,
    'la 3ª del grupo terminado no está en ninguna zona (ni 100 ni 0 con candado)');

  // 1. Grupo con partidos pendientes: probabilidades intermedias, no 100/0
  assert.ok(a1.indexOf('Fase terminada') === -1, 'el grupo con partidos pendientes no está terminado');
  const pcts = (a1.match(/prob__val">(\d+)</g) || []).map(m => +m.match(/(\d+)/)[1]);
  assert.ok(pcts.length >= 6, 'hay píldoras con porcentaje en el grupo simulado');
  assert.ok(pcts.some(v => v > 0 && v < 100), 'el Monte Carlo da probabilidades intermedias, no solo 100/0');
  // La líder con +10 puntos y 2 jornadas por jugar debe tener más cuartos que la
  // colista con 0. `firstPct` lee la PRIMERA píldora de la fila (la de cuartos);
  // '—' (is-null) cuenta como 0, que es lo que significa.
  const firstPct = r => { const m = /prob__val">(\d+|—)/.exec(r); return (!m || m[1] === '—') ? 0 : +m[1]; };
  const fr = firstPct(row(a1, 'Francia')), tr = firstPct(row(a1, 'Türkiye'));
  assert.ok(fr > tr, 'la líder tiene más probabilidad de cuartos que la colista (' + fr + ' vs ' + tr + ')');

  // 4. Cabecera desde los datos
  assert.strictEqual(els['badge-jornada'].textContent, 6, 'la jornada es la del grupo más adelantado');
  assert.strictEqual(els['league-season'].textContent, '2026-27', 'la temporada la pone ESPN, no el HTML');

  console.log('OK');
}, 50);
