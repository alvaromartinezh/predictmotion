/* schedule(): el endpoint teams/{id}/schedule de ESPN puede venir NO vacío pero
 * sin ningún partido pendiente (visto en vivo el 2026-08-28: solo los 2 últimos
 * jugados, todos "post", sin el próximo) — hay que caer al calendario completo
 * de la liga igualmente, no solo cuando el array está vacío.
 *
 *   node scripts/test_pm_data_schedule.js
 */
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const src = fs.readFileSync(require('path').join(__dirname, '..', 'assets', 'pm-data.js'), 'utf8');

const now = Date.now(), days = n => new Date(now + n * 86400000).toISOString();
const teamSchedule = { events: [
  { id: 'e1', date: days(-2), status: { type: { state: 'post' } }, competitions: [{ competitors: [{ homeAway: 'home', team: { id: '86' } }, { homeAway: 'away', team: { id: '9' } }] }] },
  { id: 'e2', date: days(-6), status: { type: { state: 'post' } }, competitions: [{ competitors: [{ homeAway: 'home', team: { id: '9' } }, { homeAway: 'away', team: { id: '86' } }] }] },
] };
const seasonWide = { events: [
  ...teamSchedule.events,
  { id: 'e3', date: days(1), status: { type: { state: 'pre' } }, competitions: [{ competitors: [{ homeAway: 'home', team: { id: '86' } }, { homeAway: 'away', team: { id: '7' } }] }] },
] };
const scoreboard = { leagues: [{ calendar: ['2026-07-01T00:00Z', '2026-09-30T00:00Z'] }], events: [] };

function fetchMock(url) {
  const body = url.indexOf('/teams/86/schedule') > -1 ? teamSchedule
    : url.indexOf('?dates=') > -1 ? seasonWide
    : scoreboard;
  return Promise.resolve({ ok: true, json: () => Promise.resolve(body) });
}

const ctx = { window: { PM_LEAGUES: { laliga: { code: 'esp.1' } } }, fetch: fetchMock, console };
vm.createContext(ctx); vm.runInContext(src, ctx);
const D = ctx.window.PMData;

D.schedule('laliga', '86').then(function (evs) {
  assert.strictEqual(evs.length, 3, 'cae al calendario completo de la liga (3), no se queda con los 2 del endpoint por equipo');
  const upcoming = evs.filter(function (e) { return e.status.type.state === 'pre'; });
  assert.strictEqual(upcoming.length, 1, 'el partido pendiente está entre los devueltos');
  const picked = D.pickTeamMatch(evs, 'laliga');
  assert.strictEqual(picked.id, 'e3', 'con el próximo ya visible, pickTeamMatch lo elige en cuanto queda más cerca que el último jugado');
  console.log('OK');
}).catch(function (err) { console.error(err); process.exit(1); });
