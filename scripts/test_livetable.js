/* PMData.liveTable — clasificación REAL con los partidos en juego aplicados.
 *
 * Es lo que hace que las tablas del home (mini-tabla del equipo seguido,
 * clasificación de competiciones, rail) no enseñen la foto congelada del cron
 * mientras se está jugando. La aritmética (puntos provisionales, PJ, goles) y el
 * reordenado pts→DG→GF son fáciles de romper sin que se note hasta un domingo.
 *
 *   node scripts/test_livetable.js
 */
const assert = require('assert');
const path = require('path');

function entry(id, name, pts, gp, gf, gc) {
  return {
    team: { id, displayName: name, logo: '' },
    stats: [{ name: 'gamesPlayed', value: gp }, { name: 'points', value: pts },
            { name: 'pointsFor', value: gf }, { name: 'pointsAgainst', value: gc }],
  };
}
// Cuarto (local) va ganando 2-0 al Líder: debe sumar 3 provisionales y subir.
const standings = { children: [{ standings: { entries: [
  entry('1', 'Lider', 7, 3, 6, 1), entry('2', 'Segundo', 6, 3, 5, 2),
  entry('3', 'Tercero', 4, 3, 3, 3), entry('4', 'Cuarto', 3, 3, 2, 5),
] } }] };
const scoreboard = { events: [{
  id: 'evt1', date: '2026-08-15T18:00Z',
  status: { type: { state: 'in' }, displayClock: "62'" },
  competitions: [{ competitors: [
    { homeAway: 'home', score: '2', team: { id: '4', displayName: 'Cuarto' } },
    { homeAway: 'away', score: '0', team: { id: '1', displayName: 'Lider' } },
  ] }],
}] };

global.window = { PM_LEAGUES: { laliga: { code: 'esp.1' } } };
global.fetch = (url) => Promise.resolve({
  ok: true, json: () => Promise.resolve(/standings/.test(url) ? standings : scoreboard),
});
require(path.join(__dirname, '..', 'assets', 'pm-data.js'));

window.PMData.liveTable('laliga').then((rows) => {
  rows.forEach((t) => console.log(
    `${t.rank}. ${t.name.padEnd(8)} pts ${t.pts} pj ${t.gp}` + (t.live ? `  (en vivo: ${t.live.res})` : '')));
  const by = {}; rows.forEach((t) => { by[t.name] = t; });

  assert.strictEqual(by.Cuarto.pts, 6, 'el local ganando suma 3 provisionales');
  assert.strictEqual(by.Cuarto.gp, 4, 'y el partido en juego cuenta como jugado');
  assert.strictEqual(by.Lider.pts, 7, 'el visitante perdiendo no suma');
  assert.strictEqual(by.Lider.gp, 4);
  assert.strictEqual(by.Segundo.pts, 6, 'a quien no juega no se le toca');
  assert.strictEqual(by.Cuarto.live.res, 'win');
  assert.strictEqual(by.Lider.live.res, 'loss');
  assert.strictEqual(by.Segundo.live, null);
  // Segundo y Cuarto empatan a 6; manda la diferencia de goles (+3 vs −1).
  assert.deepStrictEqual(rows.map((t) => t.name), ['Lider', 'Segundo', 'Cuarto', 'Tercero'],
    'reordenado por pts → DG → GF');
  console.log('OK');
}).catch((e) => { console.error(e); process.exit(1); });
