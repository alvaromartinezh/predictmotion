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
// Ventana del calendario RELATIVA a hoy: con fechas fijas el test caducaba
// (los eventos se generan a partir de `now`, así que a partir del último día
// fijo quedaban todos fuera del rango y seasonEvents devolvía 0).
const scoreboard = { leagues: [{ calendar: [days(-30), days(30)] }], events: [] };

function fetchMock(url) {
  const body = url.indexOf('/teams/86/schedule') > -1 ? teamSchedule
    : url.indexOf('?dates=') > -1 ? seasonWide
    : scoreboard;
  return Promise.resolve({ ok: true, json: () => Promise.resolve(body) });
}

const ctx = { window: { PM_LEAGUES: { laliga: { code: 'esp.1' } } }, fetch: fetchMock, console };
vm.createContext(ctx); vm.runInContext(src, ctx);
const D = ctx.window.PMData;

// seasonEvents(): las UEFA y las competiciones de selecciones sirven el `calendar`
// como "list" (fases: fase de liga, cuartos…), SIN fechas sueltas. Filtrando solo
// strings quedaba vacío y se caía a los partidos del día, así que el calendario
// completo no salía nunca. Sin fechas en el calendar, el rango es el de `season`.
function listCalendarCase() {
  const sb = {
    leagues: [{
      calendarType: 'list',
      calendar: [{ label: 'Fase de liga', entries: [] }],
      season: { startDate: days(-30), endDate: days(30) },
    }],
    events: [],
  };
  const ctx2 = {
    window: { PM_LEAGUES: { champions: { code: 'uefa.champions' } } },
    fetch: function (url) {
      const body = url.indexOf('?dates=') > -1 ? seasonWide : sb;
      return Promise.resolve({ ok: true, json: () => Promise.resolve(body) });
    },
    console,
  };
  vm.createContext(ctx2); vm.runInContext(src, ctx2);
  return ctx2.window.PMData.seasonEvents('champions').then(function (evs) {
    assert.strictEqual(evs.length, 3,
      'con calendar de tipo "list" el rango sale de season y se baja la temporada entera');
  });
}

D.schedule('laliga', '86').then(function (evs) {
  assert.strictEqual(evs.length, 3, 'cae al calendario completo de la liga (3), no se queda con los 2 del endpoint por equipo');
  const upcoming = evs.filter(function (e) { return e.status.type.state === 'pre'; });
  assert.strictEqual(upcoming.length, 1, 'el partido pendiente está entre los devueltos');
  const picked = D.pickTeamMatch(evs, 'laliga');
  assert.strictEqual(picked.id, 'e3', 'con el próximo ya visible, pickTeamMatch lo elige en cuanto queda más cerca que el último jugado');
  return listCalendarCase();
}).then(function () {
  // seasonLabel(): con `lang=es` ESPN deja de servir el "2026-27" del displayName
  // inglés, así que la etiqueta se reconstruye del año + mes de inicio.
  assert.strictEqual(D.seasonLabel({ year: 2026, startDate: '2026-06-01T04:00Z' }), '2026-27',
    'temporada que arranca a mitad de año → cruza dos años');
  assert.strictEqual(D.seasonLabel({ year: 2026, startDate: '2026-01-01T05:00Z' }), '2026',
    'temporada que arranca en enero → un solo año');
  assert.strictEqual(D.seasonLabel({ year: 2029, startDate: '2029-08-01T04:00Z' }), '2029-30',
    'el segundo año va a dos dígitos con cero por delante cuando toca');
  assert.strictEqual(D.seasonLabel({}), '', 'sin datos de temporada, sin etiqueta');
}).then(function () {
  console.log('OK');
}).catch(function (err) { console.error(err); process.exit(1); });
