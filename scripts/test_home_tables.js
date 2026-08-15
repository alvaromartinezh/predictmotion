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
  .replace(/\}\)\(\);\s*$/, '  module.exports = { miniTable: miniTable, rowsOf: rowsOf, buildUserHTML: buildUserHTML };\n})();\n');
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
// 2) sin nada: no revienta y no pinta
assert.strictEqual(H.miniTable(null, '1', 'Uno', null, 'hypermotion'), '');
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
// 5) mini-tabla: pinta TODAS las probabilidades de zona >10%, no solo la de la zona actual
const snapMulti = {
  league: 'laliga',
  bands: [
    { key: 'champions', label: 'Champions League', color: 'green', lo: 1, hi: 5 },
    { key: 'europa', label: 'Europa League', color: 'blue', lo: 6, hi: 6 },
    { key: 'descenso', label: 'Descenso', color: 'red', lo: 18, hi: 20 },
  ],
  teams: [{ id: '1', name: 'Uno', logo: '', rank: 3, gp: 10, pts: 20, prob: { champions: 45, europa: 12, descenso: 3 } }],
};
const mtMulti = H.miniTable(snapMulti, '1', 'Uno', null, 'laliga');
assert(mtMulti.indexOf('45% Champions League') > 0, 'pinta la probabilidad por encima del 10%');
assert(mtMulti.indexOf('12% Europa League') > 0, 'pinta TODAS las zonas >10%, no solo la principal');
assert(mtMulti.indexOf('Descenso') < 0, 'omite las zonas por debajo del 10%');

// 6) feed logueado: solo el equipo FAVORITO lleva partido+tabla; el resto de
// seguidos (otro equipo + una competición) solo aportan noticias, sin más tablas.
const f = {
  favorite_team: { espn_team_id: '1', name: 'Uno' },
  teams: [{ espn_team_id: '1', name: 'Uno', league_slug: 'laliga' }, { espn_team_id: '2', name: 'Dos', league_slug: 'premier' }],
  competitions: ['seriea'],
};
const favMatch = { id: 'm1', slug: 'laliga', date: new Date().toISOString(), state: 'pre',
  home: { id: '1', name: 'Uno', logo: '' }, away: { id: '9', name: 'Rival', logo: '' } };
const allNews = [
  { link: 'a', title: 'Noticia de Uno', teams: [{ id: '1', name: 'Uno' }], leagues: ['laliga'], published: new Date().toISOString() },
  { link: 'b', title: 'Otra de Uno', teams: [{ id: '1', name: 'Uno' }], leagues: ['laliga'], published: new Date().toISOString() },
  { link: 'c', title: 'De Dos', teams: [{ id: '2', name: 'Dos' }], leagues: ['premier'], published: new Date().toISOString() },
  { link: 'd', title: 'De Serie A', teams: [], leagues: ['seriea'], published: new Date().toISOString() },
  { link: 'e', title: 'Sin relación', teams: [], leagues: ['bundesliga'], published: new Date().toISOString() },
];
const out = H.buildUserHTML(f, { '1': favMatch }, { laliga: snapMulti }, allNews, {});
assert(out.col.indexOf('Destacado para ti') > 0, 'pinta el partido del favorito');
assert((out.col.match(/class="mini"/g) || []).length === 1, 'una sola tabla en todo el feed (la del favorito)');
assert(out.col.indexOf('Noticia de Uno') > 0, 'la última noticia del favorito sale pegada a su tabla');
assert(out.col.indexOf('De Dos') > 0 && out.col.indexOf('De Serie A') > 0, 'noticias del resto de seguidos, sin tabla propia');
assert(out.col.indexOf('Sin relación') < 0, 'no cuela noticias de lo que no se sigue');

// 7) el partido destacado enlaza a /partido y la tabla del favorito enlaza a /<liga>
assert(out.col.indexOf('href="/partido?league=laliga&amp;id=m1"') > 0, 'el hero enlaza al partido');
assert(out.col.indexOf('href="/laliga"') > 0, 'la mini-tabla enlaza a la clasificación de la liga');

// 8) con detalle del live_tracker: raya 1X2 de 3 colores (uno por equipo + empate)
const liveDetail = {
  home: { name: 'Uno', abbr: 'UNO', color: '#111111' },
  away: { name: 'Rival', abbr: 'RIV', color: '#222222' },
  winProbability: { pHome: 55, pDraw: 25, pAway: 20, note: 'Probabilidad estimada' },
};
const outWithProb = H.buildUserHTML(f, { '1': favMatch }, { laliga: snapMulti }, allNews, {}, liveDetail);
assert(outWithProb.col.indexOf('class="winbar"') > 0, 'pinta la raya de probabilidades 1X2');
assert(outWithProb.col.indexOf('background:#111111') > 0 && outWithProb.col.indexOf('background:#222222') > 0, 'cada color de la raya es el de su equipo');
assert(outWithProb.col.indexOf('UNO 55%') > 0 && outWithProb.col.indexOf('RIV 20%') > 0 && outWithProb.col.indexOf('Empate 25%') > 0, 'pinta las 3 probabilidades');
console.log('OK');
