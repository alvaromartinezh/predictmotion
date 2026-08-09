/* Home Editorial (CP-R2) — construye el feed con datos REALES (PMData) y lo monta
 * en el shell (PMShell). Logueado → feed personalizado por follows; anónimo → feed
 * general con selector de competición. Sin 1X2 por partido (D3): la predicción sale
 * de las probabilidades de temporada del snapshot. Degrada si una fuente falla.
 *
 * Render en DOS FASES (logueado): primero con datos LOCALES rápidos (snapshots +
 * noticias → mini-tablas, tendencias, noticias) y luego se re-monta añadiendo los
 * resultados/próximos de ESPN (schedule) cuando llegan. Así la portada nunca se
 * queda en esqueleto esperando a ESPN. */
(function () {
  'use strict';
  var D = window.PMData, L = window.PM_LEAGUES || {}, ORDER = window.PM_LEAGUES_ORDER || [];

  // ── helpers ──
  window.PMHomeCrestFallback = function (img) {
    var d = document.createElement('div'); d.className = img.className.replace('crest', 'crest-ph');
    d.textContent = img.getAttribute('data-ab') || '?'; img.parentNode.replaceChild(d, img);
  };
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) { return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]; }); }
  function initials(n) { var p = (n || '').trim().split(/\s+/).filter(Boolean); return ((p[0] || '?')[0] + (p.length > 1 ? p[p.length - 1][0] : '')).toUpperCase(); }
  function crest(logo, name, id, cls) {
    cls = cls || ''; var ab = initials(name);
    var src = logo || (id ? 'https://a.espncdn.com/i/teamlogos/soccer/500/' + id + '.png' : '');
    if (!src) return '<div class="crest-ph ' + cls + '">' + ab + '</div>';
    return '<img class="crest ' + cls + '" loading="lazy" alt="" src="' + esc(src) + '" data-ab="' + ab + '" onerror="PMHomeCrestFallback(this)">';
  }
  function pct(v) { if (v == null) return null; return Math.round(v <= 1 ? v * 100 : v); }
  function ago(iso) { var m = Math.max(0, (Date.now() - new Date(iso)) / 60000); return m < 60 ? Math.round(m) + ' min' : (m < 1440 ? Math.round(m / 60) + ' h' : Math.round(m / 1440) + ' d'); }
  function kick(iso) { try { return new Date(iso).toLocaleTimeString('es-ES', { hour: '2-digit', minute: '2-digit' }); } catch (e) { return ''; } }
  function lname(slug) { return (L[slug] || {}).name || slug; }
  function llogo(slug) { return (L[slug] || {}).logo || ''; }
  function bandForRank(snap, rank) { return (snap.bands || []).filter(function (b) { return rank >= b.lo && rank <= b.hi; })[0] || null; }
  function zoneClass(band) { if (!band) return ''; return band.color === 'green' ? 'up' : band.color === 'red' ? 'down' : 'po'; }
  function zoneVar(band) { return band && band.color === 'green' ? '--up' : band && band.color === 'red' ? '--down' : '--po'; }
  function uniqLeagues(f) { var s = {}; (f.teams || []).forEach(function (t) { s[t.league_slug] = 1; }); (f.competitions || []).forEach(function (c) { s[c] = 1; }); return Object.keys(s); }

  // ── componentes ──
  function leagueHead(slug, right) {
    return '<div class="card__head"><img class="lg-logo" src="' + esc(llogo(slug)) + '" alt="">'
      + '<span class="lg-name">' + esc(lname(slug)) + '</span><span class="spacer"></span>' + (right || '') + '</div>';
  }
  function statusHTML(m) {
    if (m.state === 'in') return '<span class="badge-live"><i></i>' + esc(m.clock || m.detail || 'EN VIVO') + '</span>';
    if (m.state === 'post') return 'Final';
    return esc(kick(m.date) || m.detail || 'Próx.');
  }
  function resultCard(m, followed) {
    var loseH = m.state === 'post' && !m.home.winner, loseA = m.state === 'post' && !m.away.winner;
    var sc = m.state === 'pre'
      ? '<div class="match__score" style="font-size:var(--fs-22)">' + esc(kick(m.date)) + '</div>'
      : '<div class="match__score">' + (m.home.score == null ? '-' : m.home.score) + '<span class="sep">–</span>' + (m.away.score == null ? '-' : m.away.score) + '</div>';
    return '<article class="card card--link">'
      + leagueHead(m.slug, followed ? '<span class="followed">★ SIGUES</span>' : '')
      + '<div class="match">'
      + '<div class="match__team ' + (loseH ? 'lose' : '') + '">' + crest(m.home.logo, m.home.name, m.home.id) + '<span class="name">' + esc(m.home.name) + '</span></div>'
      + '<div style="text-align:center">' + sc + '<span class="match__status">' + statusHTML(m) + '</span></div>'
      + '<div class="match__team ' + (loseA ? 'lose' : '') + '">' + crest(m.away.logo, m.away.name, m.away.id) + '<span class="name">' + esc(m.away.name) + '</span></div>'
      + '</div></article>';
  }
  function miniTable(snap, teamId, teamName) {
    if (!snap || !snap.teams) return '';
    var teams = snap.teams.slice().sort(function (a, b) { return a.rank - b.rank; });
    var idx = teams.findIndex(function (t) { return String(t.id) === String(teamId); });
    if (idx < 0) return '';
    var lo = Math.max(0, idx - 3), hi = Math.min(teams.length, idx + 4);
    var rows = teams.slice(lo, hi).map(function (t) {
      var band = bandForRank(snap, t.rank);
      return '<div class="mini__row ' + (String(t.id) === String(teamId) ? 'is-me' : '') + '" data-zone="' + zoneClass(band) + '">'
        + '<span class="pos num">' + t.rank + '</span>' + crest(t.logo, t.name, t.id)
        + '<span class="name">' + esc(t.name) + '</span><span class="pj num">' + t.gp + '</span><span class="pts num">' + t.pts + '</span></div>';
    }).join('');
    var me = teams[idx], mb = bandForRank(snap, me.rank), pill = '';
    if (mb) { var p = pct(me.prob && me.prob[mb.key]); if (p != null) pill = '<span class="prob-pill" style="color:var(' + zoneVar(mb) + ');background:transparent;border-color:currentColor">' + p + '% ' + esc(mb.label) + '</span>'; }
    return '<article class="card">' + leagueHead(snap.league, '<span style="color:var(--faint);font-family:var(--font-mono);font-size:var(--fs-11)">Clasificación</span>')
      + '<div class="mini">' + rows + '</div>'
      + '<div class="mini__foot"><span>' + esc(teamName || me.name) + ' · ' + me.rank + 'º</span>' + pill + '</div></article>';
  }
  function newsCard(it) {
    var lslug = (it.leagues || [])[0], hue = { laliga: 150, hypermotion: 195, premier: 265, seriea: 210, champions: 220 }[lslug] || 205;
    var thumb = 'background:linear-gradient(135deg,hsl(' + hue + ' 55% 22%),hsl(' + ((hue + 40) % 360) + ' 45% 12%));';
    var chips = '', t0 = (it.teams || [])[0];
    if (t0) chips += '<span class="chip chip--accent">' + esc(t0.name || t0.id) + '</span>';
    if (lslug) chips += '<span class="chip">' + esc(lname(lslug)) + '</span>';
    return '<a class="card card--link news" href="' + esc(it.link) + '" target="_blank" rel="noopener noreferrer nofollow">'
      + '<div class="news__thumb" style="' + thumb + '"><span class="src">' + esc(it.source) + '</span></div>'
      + '<div class="news__body"><div class="news__title">' + esc(it.title) + '</div>'
      + '<div class="news__meta"><span class="time">' + (it.published ? ago(it.published) : '') + '</span></div>'
      + '<div class="news__chips">' + chips + '</div></div></a>';
  }
  function hero(m, pill) {
    var mid = m.state === 'pre' ? esc(kick(m.date)) : (m.state === 'in' ? esc(m.clock || 'EN VIVO') : ((m.home.score == null ? '' : m.home.score) + '–' + (m.away.score == null ? '' : m.away.score)));
    var sub = m.state === 'post' ? 'Final' : (m.state === 'in' ? 'En vivo' : esc(lname(m.slug)));
    return '<section class="hero-match"><p class="eyebrow hero-match__eyebrow">Destacado para ti</p>'
      + '<div class="hero-match__row">'
      + '<div class="hero-match__team">' + crest(m.home.logo, m.home.name, m.home.id) + '<span class="name">' + esc(m.home.name) + '</span></div>'
      + '<div class="hero-match__vs"><span class="kick">' + mid + '</span>' + sub + '</div>'
      + '<div class="hero-match__team">' + crest(m.away.logo, m.away.name, m.away.id) + '<span class="name">' + esc(m.away.name) + '</span></div>'
      + '</div>' + (pill ? '<div style="text-align:center;margin-top:var(--sp-5)">' + pill + '</div>' : '') + '</section>';
  }
  function followRail(f) {
    var favId = f.favorite_team && String(f.favorite_team.espn_team_id);
    var pills = (f.teams || []).map(function (t) {
      return '<a class="follow-pill" href="/equipo?id=' + t.espn_team_id + '&league=' + (t.league_slug || '') + '&name=' + encodeURIComponent(t.name || '') + '">'
        + crest('', t.name, t.espn_team_id) + '<span class="lbl">' + (favId === String(t.espn_team_id) ? '★ ' : '') + esc((t.name || '').split(' ').slice(-1)[0]) + '</span></a>';
    }).join('');
    pills += '<a class="follow-pill add" href="#"><div class="crest-ph">+</div><span class="lbl">Añadir</span></a>';
    return '<div class="rail">' + pills + '</div>';
  }
  function trendingCard(snap, title) {
    if (!snap || !snap.teams) return '';
    var top = snap.teams.slice().map(function (t) { return { t: t, p: pct(t.prob && t.prob.first) || 0 }; })
      .sort(function (a, b) { return b.p - a.p; }).slice(0, 5);
    var rows = top.map(function (r, i) {
      return '<div class="trend"><span class="rank num">' + (i + 1) + '</span>' + crest(r.t.logo, r.t.name, r.t.id)
        + '<span class="name">' + esc(r.t.name) + '</span><span class="val">' + r.p + '%</span></div>';
    }).join('');
    return '<div class="rail-card"><h4>' + esc(title || 'Favoritos al título') + '</h4>' + rows + '</div>';
  }
  function feedSec(title, moreTxt, moreHref, tagHTML) {
    return '<div class="feed-sec"><h2 class="feed-sec__title">' + esc(title) + (tagHTML || '') + '</h2>'
      + (moreTxt ? '<a class="feed-sec__more" href="' + (moreHref || '#') + '">' + esc(moreTxt) + '</a>' : '') + '</div>';
  }
  var AD = '<div class="ad-slot">Publicidad · 300×250 / 320×50</div>';
  var AD_RAIL = '<div class="ad-slot">Publicidad · 300×250</div>';

  // ── builder PURO del feed logueado (sin fetch) ──
  function buildUserHTML(f, matches, snaps, allNews) {
    matches = matches || {};
    var teams = (f.teams || []).slice(0, 4), favId = f.favorite_team && String(f.favorite_team.espn_team_id);
    teams.sort(function (a, b) { return (String(b.espn_team_id) === favId) - (String(a.espn_team_id) === favId); });

    var fLeagues = {}; teams.forEach(function (t) { fLeagues[t.league_slug] = 1; }); (f.competitions || []).forEach(function (s) { fLeagues[s] = 1; });
    var fTeamIds = {}; teams.forEach(function (t) { fTeamIds[String(t.espn_team_id)] = 1; });
    var relNews = (allNews || []).filter(function (it) {
      return (it.leagues || []).some(function (l) { return fLeagues[l]; }) || (it.teams || []).some(function (t) { return fTeamIds[String(t.id)]; });
    });

    var col = [];
    col.push(feedSec('Siguiendo', 'Editar', '/cuenta', ' <span class="tag">' + teams.length + '</span>'));
    col.push(followRail(f));

    var fav = teams[0], favM = fav && matches[fav.espn_team_id], favSnap = fav && snaps[fav.league_slug];
    if (favM) {
      var pill = '';
      if (favSnap) {
        var ft = (favSnap.teams || []).filter(function (x) { return String(x.id) === String(fav.espn_team_id); })[0];
        if (ft) { var b = bandForRank(favSnap, ft.rank), p = b && pct(ft.prob[b.key]); if (b && p != null) pill = '<span class="prob-pill" style="color:var(' + zoneVar(b) + ');background:transparent;border-color:currentColor">' + esc(fav.name) + ' · ' + p + '% ' + esc(b.label) + '</span>'; }
      }
      col.push(hero(favM, pill));
    }

    col.push(feedSec('Tu día', 'Ver todo', '/partidos'));
    var newsUsed = 0;
    teams.slice(0, 3).forEach(function (t, i) {
      var m = matches[t.espn_team_id]; if (m) col.push(resultCard(m, true));
      var mt = miniTable(snaps[t.league_slug], t.espn_team_id, t.name); if (mt) col.push(mt);
      if (relNews[newsUsed]) { col.push(newsCard(relNews[newsUsed])); newsUsed++; }
      if (i === 1) col.push(AD);
    });
    if (relNews.length > newsUsed) {
      col.push(feedSec('Más noticias'));
      relNews.slice(newsUsed, newsUsed + 4).forEach(function (it) { col.push(newsCard(it)); });
    }
    var rail = (favSnap ? trendingCard(favSnap, 'Favoritos · ' + lname(fav.league_slug)) : '') + AD_RAIL;
    return { col: col.join(''), rail: rail };
  }

  // ── feed anónimo ──
  function buildAnon() {
    var today = new Date(); var ymd = today.getFullYear() + ('0' + (today.getMonth() + 1)).slice(-2) + ('0' + today.getDate()).slice(-2);
    return Promise.all([D.scoreboard('laliga', ymd), D.snapshot('laliga'), D.news()]).then(function (res) {
      var events = (res[0] || []).map(function (e) { return D.parseEvent(e, 'laliga'); }).filter(Boolean);
      var snap = res[1], allNews = res[2] || [], col = [];
      var featured = events.filter(function (e) { return e.state === 'in'; })[0] || events.filter(function (e) { return e.state === 'pre'; })[0] || events[0];
      if (featured) col.push(hero(featured));
      col.push(feedSec('Elige tu competición'));
      col.push('<div class="league-chips">' + ORDER.map(function (s) { return '<a class="league-chip" href="/' + s + '"><img src="' + esc(llogo(s)) + '" alt="">' + esc(lname(s)) + '</a>'; }).join('') + '</div>');
      if (events.length) { col.push(feedSec('Partidos de hoy', 'Ver todos', '/partidos')); events.slice(0, 4).forEach(function (m) { col.push(resultCard(m, false)); }); }
      if (snap) {
        col.push(feedSec('Predicciones que suenan'));
        col.push('<article class="card"><div class="card__head"><span class="lg-name">Favoritos al título · Monte Carlo · ' + esc(lname('laliga')) + '</span></div><div class="mini">'
          + snap.teams.slice().map(function (t) { return { t: t, p: pct(t.prob && t.prob.first) || 0 }; }).sort(function (a, b) { return b.p - a.p; }).slice(0, 5)
            .map(function (r, i) { return '<div class="mini__row"><span class="pos num">' + (i + 1) + '</span>' + crest(r.t.logo, r.t.name, r.t.id) + '<span class="name">' + esc(r.t.name) + '</span><span class="pj"></span><span class="pts" style="color:var(--up)">' + r.p + '%</span></div>'; }).join('')
          + '</div></article>');
      }
      col.push('<section class="cta-card"><h3>Sigue a los tuyos</h3><p>Crea tu cuenta gratis y tu portada se llena con los resultados, la clasificación y las noticias de tus equipos.</p><div class="btns"><a class="btn btn--primary" href="/cuenta">Crear cuenta</a><a class="btn btn--ghost" href="/cuenta">Entrar</a></div></section>');
      if (allNews.length) { col.push(feedSec('Lo último', 'Más', '/noticias')); allNews.slice(0, 4).forEach(function (it) { col.push(newsCard(it)); }); }
      col.push(AD);
      return { col: col.join(''), rail: (snap ? trendingCard(snap, 'Favoritos · LaLiga') : '') + AD_RAIL };
    });
  }

  // ── estado + montaje ──
  function acct() {
    var a = window.PMAccount;
    if (!a || (a.isEnabled && !a.isEnabled())) return { on: false, f: { competitions: [], teams: [], favorite_team: null } };
    return { on: !!(a.isLoggedIn && a.isLoggedIn()), f: (a.follows && a.follows()) || { competitions: [], teams: [], favorite_team: null } };
  }
  function skeleton() { return shellMain('<div class="card" style="height:180px"></div><div class="card" style="height:240px"></div>', ''); }
  function shellMain(colHTML, railHTML) { return '<div class="feed"><div class="feed__col">' + colHTML + '</div><div class="feed__rail">' + railHTML + '</div></div>'; }
  function mount(out) { window.PMShell.mount({ active: 'home', main: shellMain(out.col, out.rail) }); }
  function fail() { window.PMShell.mount({ active: 'home', main: shellMain('<div class="card"><div style="padding:var(--sp-6);color:var(--text-2)">No se pudo cargar el feed. Reintenta en unos segundos.</div></div>', '') }); }

  var token = 0;
  function refresh() {
    var my = ++token, s = acct();
    if (!s.on) { buildAnon().then(function (o) { if (my === token) mount(o); }).catch(fail); return; }

    var f = s.f, slugs = uniqLeagues(f);
    // Fase 1: datos LOCALES (snapshots + noticias) → portada poblada al instante.
    Promise.all([D.news()].concat(slugs.map(function (s) { return D.snapshot(s); }))).then(function (r) {
      if (my !== token) return;
      var news = r[0] || [], snaps = {}; slugs.forEach(function (sl, i) { snaps[sl] = r[1 + i]; });
      mount(buildUserHTML(f, {}, snaps, news));
      // Fase 2: resultados/próximos de ESPN → re-monta con las tarjetas de partido.
      var teams = (f.teams || []).slice(0, 4);
      Promise.all(teams.map(function (t) { return D.schedule(t.league_slug, t.espn_team_id).then(function (ev) { return D.pickTeamMatch(ev, t.league_slug); }); }))
        .then(function (ms) {
          if (my !== token) return;
          var matches = {}; teams.forEach(function (t, i) { matches[t.espn_team_id] = ms[i]; });
          mount(buildUserHTML(f, matches, snaps, news));
        });
    }).catch(fail);
  }

  function start() { window.PMShell.mount({ active: 'home', main: skeleton() }); refresh(); }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start); else start();
  document.addEventListener('pm-account-ready', refresh);
  document.addEventListener('pm-follows-changed', refresh);
})();
