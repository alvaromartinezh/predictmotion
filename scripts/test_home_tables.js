/* Tablas del home: los caminos DEGRADADOS, que son los que se rompen sin ruido.
 *
 * `rowsOf` pinta la tabla real de ESPN cuando la hay y el snapshot del cron cuando
 * no. Faltaba el caso cruzado —tabla sí, snapshot no (404 de /data/<slug>/latest.json:
 * liga recién añadida, dev local, offseason)— que reventaba con "Cannot read
 * properties of null (reading 'bands')" y dejaba el feed clavado.
 *
 *   node scripts/test_home_tables.js
 */
const fs = require('fs'), vm = require('vm');
const src = fs.readFileSync(require('path').join(__dirname, '..', 'assets', 'home.js'), 'utf8')
  .replace(/\}\)\(\);\s*$/, '  module.exports = { miniTable: miniTable, competitionCard: competitionCard, rowsOf: rowsOf };\n})();\n');
const module_ = { exports: {} };
const ctx = { module: module_, window: { PMData: {}, PM_LEAGUES: { hypermotion: { name: 'Hypermotion', logo: '' } } },
  document: { readyState: 'loading', addEventListener() {} }, console };
vm.createContext(ctx); vm.runInContext(src, ctx);
const H = module_.exports;

const table = [
  { id: '1', name: 'Uno', logo: '', rank: 1, gp: 2, pts: 6, live: { res: 'win' } },
  { id: '2', name: 'Dos', logo: '', rank: 2, gp: 2, pts: 3, live: null },
];
const assert = require('assert');
// 1) sin snapshot pero con tabla: debe pintar, no lanzar
const mt = H.miniTable(null, '1', 'Uno', table, 'hypermotion');
assert(mt.indexOf('Uno') > 0 && mt.indexOf('Hypermotion') > 0, 'mini-tabla sin snapshot');
assert(mt.indexOf('var(--live)') > 0, 'marca los puntos en vivo');
assert(H.competitionCard('hypermotion', null, table).indexOf('Uno') > 0, 'tarjeta sin snapshot');
// 2) sin nada: no revienta y no pinta
assert.strictEqual(H.miniTable(null, '1', 'Uno', null, 'hypermotion'), '');
assert.strictEqual(H.competitionCard('hypermotion', null, null), '');
// 3) cambio de temporada: la tabla de ESPN casi no casa con el snapshot → manda el snapshot
const snapVieja = { league: 'hypermotion', bands: [], teams: [
  { id: '90', name: 'Descendido', rank: 1, gp: 42, pts: 90, prob: {} },
  { id: '91', name: 'Otro', rank: 2, gp: 42, pts: 80, prob: {} }] };
const rows = H.rowsOf(snapVieja, table);
assert.deepStrictEqual(rows.map(t => t.name), ['Descendido', 'Otro'], 'ignora la tabla de otra temporada');
// 4) misma temporada: manda la tabla en vivo
const snapOk = { league: 'hypermotion', bands: [], teams: [
  { id: '1', name: 'Uno', rank: 2, gp: 1, pts: 3, prob: { ascenso: 10 } },
  { id: '2', name: 'Dos', rank: 1, gp: 2, pts: 3, prob: { ascenso: 20 } }] };
const rows2 = H.rowsOf(snapOk, table);
assert.deepStrictEqual(rows2.map(t => t.pts), [6, 3], 'usa los puntos provisionales');
assert.strictEqual(rows2[0].prob.ascenso, 10, 'y las probabilidades del snapshot');
console.log('OK');
