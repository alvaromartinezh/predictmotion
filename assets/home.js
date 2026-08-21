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
    cls = cls || ''; var ab = initials(name), sid = String(id || '');
    var src = (window.PM_TEAM_LOGOS && window.PM_TEAM_LOGOS[sid])
      || logo || (id ? 'https://a.espncdn.com/i/teamlogos/soccer/500/' + sid + '.png' : '');
    if (!src) return '<div class="crest-ph ' + cls + '">' + ab + '</div>';
    return '<img class="crest ' + cls + '" loading="lazy" alt="" src="' + esc(src) + '" data-ab="' + ab + '" onerror="PMHomeCrestFallback(this)">';
  }
  function pct(v) { if (v == null) return null; return Math.round(v); }
  function ago(iso) { var m = Math.max(0, (Date.now() - new Date(iso)) / 60000); return m < 60 ? Math.round(m) + ' min' : (m < 1440 ? Math.round(m / 60) + ' h' : Math.round(m / 1440) + ' d'); }
  function kick(iso) { try { var d = new Date(iso); var day = d.toLocaleDateString('es-ES', { weekday: 'short', day: 'numeric', month: 'short' }); var time = d.toLocaleTimeString('es-ES', { hour: '2-digit', minute: '2-digit' }); return day + ' · ' + time; } catch (e) { return ''; } }
  function lname(slug) { return (L[slug] || {}).name || slug; }
  function llogo(slug) { return (L[slug] || {}).logo || ''; }
  function bandForRank(snap, rank) { return (((snap && snap.bands) || [])).filter(function (b) { return rank >= b.lo && rank <= b.hi; })[0] || null; }
  function zoneClass(band) { if (!band) return ''; return band.color === 'green' ? 'up' : band.color === 'red' ? 'down' : 'po'; }
  function zoneVar(band) { return band && band.color === 'green' ? '--up' : band && band.color === 'red' ? '--down' : '--po'; }

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
  function matchHref(m) { return m.id ? '/partido?league=' + encodeURIComponent(m.slug) + '&id=' + encodeURIComponent(m.id) : ''; }
  function resultCard(m, followed) {
    var loseH = m.state === 'post' && !m.home.winner, loseA = m.state === 'post' && !m.away.winner;
    var sc = m.state === 'pre'
      ? '<div class="match__score" style="font-size:var(--fs-22)">' + esc(kick(m.date)) + '</div>'
      : '<div class="match__score">' + (m.home.score == null ? '-' : m.home.score) + '<span class="sep">–</span>' + (m.away.score == null ? '-' : m.away.score) + '</div>';
    var href = matchHref(m), tag = href ? 'a' : 'article';
    return '<' + tag + ' class="card card--link"' + (href ? ' href="' + esc(href) + '"' : '') + '>'
      + leagueHead(m.slug, followed ? '<span class="followed">★ SIGUES</span>' : '')
      + '<div class="match">'
      + '<div class="match__team ' + (loseH ? 'lose' : '') + '">' + crest(m.home.logo, m.home.name, m.home.id) + '<span class="name">' + esc(m.home.name) + '</span></div>'
      + '<div style="text-align:center">' + sc + '<span class="match__status">' + statusHTML(m) + '</span></div>'
      + '<div class="match__team ' + (loseA ? 'lose' : '') + '">' + crest(m.away.logo, m.away.name, m.away.id) + '<span class="name">' + esc(m.away.name) + '</span></div>'
      + '</div></' + tag + '>';
  }
  // Filas de clasificación a pintar: la tabla REAL de ESPN con los partidos en juego
  // ya aplicados (PMData.liveTable) cuando la tenemos, y si no el snapshot del cron,
  // que se queda congelado mientras se juega. Las probabilidades salen SIEMPRE del
  // snapshot: aquí no se re-simula (ver el modelo de fuerza en league-engine.js).
  function rowsOf(snap, table) {
    var teams = ((snap && snap.teams) || []).slice().sort(function (a, b) { return a.rank - b.rank; });
    if (!table || !table.length) return teams;
    var prob = {}; teams.forEach(function (t) { prob[String(t.id)] = t.prob || {}; });
    // Cambio de temporada: ESPN ya trae la nueva y el snapshot sigue siendo el de la
    // acabada. Los ascendidos no casarían por id y saldrían con prob vacía (un rail de
    // "favoritos" todo a 0%). Si apenas coinciden los equipos, manda el snapshot.
    if (teams.length) {
      var hit = 0;
      table.forEach(function (t) { if (String(t.id) in prob) hit++; });
      if (hit < table.length * 0.8) return teams;
    }
    return table.map(function (t) {
      return { id: t.id, name: t.name, logo: t.logo, rank: t.rank, gp: t.gp, pts: t.pts,
               prob: prob[String(t.id)] || {}, live: t.live };
    });
  }
  // Puntos en color "en vivo" mientras el partido de ese equipo está en juego.
  function ptsCell(t) {
    return '<span class="pts num"' + (t.live ? ' style="color:var(--live)"' : '') + '>' + t.pts + '</span>';
  }

  // ±2 posiciones alrededor del equipo + TODAS las probabilidades de zona >10%
  // (no solo la de su zona actual).
  function miniTable(snap, teamId, teamName, table, slug) {
    var teams = rowsOf(snap, table);
    if (!teams.length) return '';
    var idx = teams.findIndex(function (t) { return String(t.id) === String(teamId); });
    if (idx < 0) return '';
    var lo = Math.max(0, idx - 2), hi = Math.min(teams.length, idx + 3);
    var rows = teams.slice(lo, hi).map(function (t) {
      var band = bandForRank(snap, t.rank);
      return '<div class="mini__row ' + (String(t.id) === String(teamId) ? 'is-me' : '') + '" data-zone="' + zoneClass(band) + '">'
        + '<span class="pos num">' + t.rank + '</span>' + crest(t.logo, t.name, t.id)
        + '<span class="name">' + esc(t.name) + '</span><span class="pj num">' + t.gp + '</span>' + ptsCell(t) + '</div>';
    }).join('');
    var me = teams[idx];
    var pills = ((snap && snap.bands) || []).map(function (b) {
      var p = pct(me.prob && me.prob[b.key]);
      if (p == null || p < 10) return '';
      return '<span class="prob-pill" style="color:var(' + zoneVar(b) + ');background:transparent;border-color:currentColor">' + p + '% ' + esc(b.label) + '</span>';
    }).join('');
    var lg = slug || (snap && snap.league);
    return '<a class="card card--link" href="/' + esc(lg) + '">' + leagueHead(lg, '<span style="color:var(--faint);font-family:var(--font-mono);font-size:var(--fs-11)">Clasificación</span>')
      + '<div class="mini">' + rows + '</div>'
      + '<div class="mini__foot"><span>' + esc(teamName || me.name) + ' · ' + me.rank + 'º</span>'
      + (pills ? '<span style="display:flex;gap:var(--sp-2);flex-wrap:wrap;justify-content:flex-end">' + pills + '</span>' : '') + '</div></a>';
  }
  function newsCard(it) {
    var lslug = (it.leagues || [])[0], hue = { laliga: 150, hypermotion: 195, premier: 265, seriea: 210, champions: 220 }[lslug] || 205;
    var thumb = 'background:linear-gradient(135deg,hsl(' + hue + ' 55% 22%),hsl(' + ((hue + 40) % 360) + ' 45% 12%));';
    var chips = '', t0 = (it.teams || [])[0];
    if (t0) chips += '<span class="chip chip--accent">' + esc(t0.name || t0.id) + '</span>';
    if (lslug) chips += '<span class="chip">' + esc(lname(lslug)) + '</span>';
    var thumbBody = t0 ? crest(null, t0.name, t0.id, 'news__thumb-crest') : '';
    return '<a class="card card--link news" href="' + esc(it.link) + '" target="_blank" rel="noopener noreferrer nofollow">'
      + '<div class="news__thumb' + (t0 ? ' has-team' : '') + '" style="' + thumb + '">' + thumbBody + '<span class="src">' + esc(it.source) + '</span></div>'
      + '<div class="news__body"><div class="news__title">' + esc(it.title) + '</div>'
      + '<div class="news__meta"><span class="time">' + (it.published ? ago(it.published) : '') + '</span></div>'
      + '<div class="news__chips">' + chips + '</div></div></a>';
  }
  // Raya 1X2 (probabilidad de victoria local / empate / visitante) de UN partido
  // concreto — coloreada por equipo. Viene del live_tracker (mismo modelo/endpoint
  // que /partido: prior de fuerza + desvanecimiento), no del snapshot de temporada.
  var WINBAR_FALLBACK = ['#2ec98a', '#4a90ff', '#e0a13a', '#a855f7', '#ff556b', '#13c4c4'];
  function winbarHTML(lm) {
    if (!lm || !lm.winProbability) return '';
    var wp = lm.winProbability;
    var h = (lm.home && lm.home.color) || WINBAR_FALLBACK[0];
    var aRaw = lm.away && lm.away.color;
    var a = (aRaw && aRaw.toLowerCase() !== h.toLowerCase()) ? aRaw
      : (WINBAR_FALLBACK.filter(function (c) { return c.toLowerCase() !== h.toLowerCase(); })[0] || WINBAR_FALLBACK[1]);
    var hn = (lm.home && (lm.home.abbr || lm.home.name)) || '', an = (lm.away && (lm.away.abbr || lm.away.name)) || '';
    return '<div class="winbar" aria-label="Probabilidad de resultado">'
      + '<div class="winbar__track">'
      + '<span class="winbar__seg h" style="width:' + wp.pHome + '%;background:' + esc(h) + '"></span>'
      + '<span class="winbar__seg d" style="width:' + wp.pDraw + '%"></span>'
      + '<span class="winbar__seg a" style="width:' + wp.pAway + '%;background:' + esc(a) + '"></span>'
      + '</div>'
      + '<div class="winbar__legend"><b>' + esc(hn) + ' ' + wp.pHome + '%</b>'
      + '<span class="mid">Empate ' + wp.pDraw + '%</span>'
      + '<b>' + esc(an) + ' ' + wp.pAway + '%</b></div></div>';
  }
  function hero(m, pill, winbar) {
    var mid = m.state === 'pre' ? esc(kick(m.date)) : (m.state === 'in' ? esc(m.clock || 'EN VIVO') : ((m.home.score == null ? '' : m.home.score) + '–' + (m.away.score == null ? '' : m.away.score)));
    var sub = m.state === 'post' ? 'Final' : (m.state === 'in' ? 'En vivo' : esc(lname(m.slug)));
    var href = matchHref(m), tag = href ? 'a' : 'section';
    return '<' + tag + ' class="hero-match"' + (href ? ' href="' + esc(href) + '"' : '') + '><p class="eyebrow hero-match__eyebrow">Destacado para ti</p>'
      + '<div class="hero-match__row">'
      + '<div class="hero-match__team">' + crest(m.home.logo, m.home.name, m.home.id) + '<span class="name">' + esc(m.home.name) + '</span></div>'
      + '<div class="hero-match__vs"><span class="kick">' + mid + '</span>' + sub + '</div>'
      + '<div class="hero-match__team">' + crest(m.away.logo, m.away.name, m.away.id) + '<span class="name">' + esc(m.away.name) + '</span></div>'
      + '</div>' + (pill ? '<div style="text-align:center;margin-top:var(--sp-5)">' + pill + '</div>' : '') + (winbar || '') + '</' + tag + '>';
  }
  // Rail de seguidos: competiciones (con logo) + equipos (con escudo) + añadir.
  // Líderes de una competición. En PRETEMPORADA o con datos inestables (prob.first
  // degenerada: varios equipos a ~100%) muestra la CLASIFICACIÓN real (pts); en
  // temporada, los favoritos al título (prob.first). Evita el rail sin sentido.
  function leaders(snap, n, table) {
    var rows_ = rowsOf(snap, table);
    var byProb = rows_.slice().map(function (t) { return { t: t, p: pct(t.prob && t.prob.first) || 0 }; }).sort(function (a, b) { return b.p - a.p; });
    var degenerate = (snap.jornada || 0) < 3 || byProb.filter(function (r) { return r.p >= 99; }).length >= 2;
    if (degenerate) return { mode: 'std', rows: rows_.slice(0, n).map(function (t) { return { t: t, val: t.pts, num: t.rank }; }) };
    return { mode: 'prob', rows: byProb.slice(0, n).map(function (r, i) { return { t: r.t, val: r.p + '%', num: i + 1 }; }) };
  }
  function leadersRail(snap, slug, table) {
    if (!snap || !snap.teams) return '';
    var L = leaders(snap, 5, table), title = (L.mode === 'std' ? 'Clasificación · ' : 'Favoritos al título · ') + lname(slug);
    var rows = L.rows.map(function (r) { return '<div class="trend"><span class="rank num">' + r.num + '</span>' + crest(r.t.logo, r.t.name, r.t.id) + '<span class="name">' + esc(r.t.name) + '</span><span class="val">' + r.val + '</span></div>'; }).join('');
    return '<a class="rail-card" href="/' + esc(slug) + '"><h4>' + esc(title) + '</h4>' + rows + '</a>';
  }
  function leadersCard(snap, slug, table) {
    if (!snap || !snap.teams) return '';
    var L = leaders(snap, 5, table), head = (L.mode === 'std' ? 'Clasificación · ' : 'Favoritos al título · Monte Carlo · ') + lname(slug);
    var rows = L.rows.map(function (r) { return '<div class="mini__row"><span class="pos num">' + r.num + '</span>' + crest(r.t.logo, r.t.name, r.t.id) + '<span class="name">' + esc(r.t.name) + '</span><span class="pj"></span><span class="pts" style="color:var(--up)">' + r.val + '</span></div>'; }).join('');
    return '<a class="card card--link" href="/' + esc(slug) + '"><div class="card__head"><span class="lg-name">' + esc(head) + '</span></div><div class="mini">' + rows + '</div></a>';
  }
  function feedSec(title, moreTxt, moreHref, tagHTML) {
    return '<div class="feed-sec"><h2 class="feed-sec__title">' + esc(title) + (tagHTML || '') + '</h2>'
      + (moreTxt ? '<a class="feed-sec__more" href="' + (moreHref || '#') + '">' + esc(moreTxt) + '</a>' : '') + '</div>';
  }
  function articleLeagueSlug(url) { var m = (url || '').match(/articulos\/([a-z0-9]+)-resumen/); return m ? m[1] : ''; }
  function fechaLarga(iso) { try { var p = String(iso || '').split('-'); return new Date(+p[0], +p[1] - 1, +p[2]).toLocaleDateString('es-ES', { weekday: 'long', day: 'numeric', month: 'long' }); } catch (e) { return iso || ''; } }
  function articleCard(a) {
    if (!a || !a.url) return '';
    var slug = articleLeagueSlug(a.url), leagueName = lname(slug) || 'Hypermotion';
    return '<a class="card card--link bscard" href="' + esc(a.url) + '">'
      + '<div class="bscard__top"><span class="bscard__kicker">Broadsheet diario</span>'
      + '<span class="bscard__league"><img src="' + esc(llogo(slug)) + '" alt="">' + esc(leagueName) + '</span></div>'
      + '<h3 class="bscard__title">' + esc((a.title || '').replace(' | PredictMotion', '')) + '</h3>'
      + '<div class="bscard__foot"><span class="bscard__date">' + esc(fechaLarga(a.fecha)) + '</span>'
      + '<span class="bscard__cta">Leer la edición →</span></div></a>';
  }

  // ── builder PURO del feed logueado (sin fetch) ──
  // Foco en el equipo FAVORITO: su partido más cercano (con probabilidades) + su
  // clasificación (±2 y todas las probabilidades de zona >10%) + su última noticia. Debajo, el resto
  // de noticias de lo que sigue — sin más tablas ni partidos.
  function buildUserHTML(f, matches, snaps, allNews, tables, liveMatchDetail, article) {
    matches = matches || {}; tables = tables || {};
    var teams = (f.teams || []).slice(0, 4), favId = f.favorite_team && String(f.favorite_team.espn_team_id);
    teams.sort(function (a, b) { return (String(b.espn_team_id) === favId) - (String(a.espn_team_id) === favId); });
    var fav = teams[0];

    var fLeagues = {}; teams.forEach(function (t) { fLeagues[t.league_slug] = 1; }); (f.competitions || []).forEach(function (s) { fLeagues[s] = 1; });
    var fTeamIds = {}; teams.forEach(function (t) { fTeamIds[String(t.espn_team_id)] = 1; });
    var relNews = (allNews || []).filter(function (it) {
      return (it.leagues || []).some(function (l) { return fLeagues[l]; }) || (it.teams || []).some(function (t) { return fTeamIds[String(t.id)]; });
    });
    var usedLinks = {};
    function nextNews(pred) {
      for (var i = 0; i < relNews.length; i++) { var it = relNews[i]; if (usedLinks[it.link]) continue; if (!pred || pred(it)) { usedLinks[it.link] = 1; return newsCard(it); } }
      return '';
    }

    var col = [];
    var favM = fav && matches[fav.espn_team_id], favSnap = fav && snaps[fav.league_slug];
    if (favM) {
      var pill = '';
      if (favSnap) {
        var ft = (favSnap.teams || []).filter(function (x) { return String(x.id) === String(fav.espn_team_id); })[0];
        if (ft) { var b = bandForRank(favSnap, ft.rank), p = b && pct(ft.prob[b.key]); if (b && p != null) pill = '<span class="prob-pill" style="color:var(' + zoneVar(b) + ');background:transparent;border-color:currentColor">' + esc(fav.name) + ' · ' + p + '% ' + esc(b.label) + '</span>'; }
      }
      col.push(hero(favM, pill, winbarHTML(liveMatchDetail)));
    }
    if (fav) {
      var mt = miniTable(favSnap, fav.espn_team_id, fav.name, tables[fav.league_slug], fav.league_slug);
      if (mt) col.push(mt);
      var teamNews = nextNews(function (it) { return (it.teams || []).some(function (x) { return String(x.id) === String(fav.espn_team_id); }); });
      if (teamNews) col.push(teamNews);
    }
    if (article && fLeagues[articleLeagueSlug(article.url)]) col.push(articleCard(article));

    var rest = relNews.filter(function (it) { return !usedLinks[it.link]; });
    if (rest.length) { col.push(feedSec('Más noticias')); rest.slice(0, 8).forEach(function (it) { col.push(newsCard(it)); }); }

    col.push('<section class="methodology-callout"><h3>Cómo funciona</h3><p>Probabilidades recalculadas cada día con simulación Monte Carlo sobre 40.000 temporadas virtuales. Con cada resultado real, la tabla se actualiza y las probabilidades se recalculan automáticamente.</p></section>');

    var primary = fav ? fav.league_slug : (f.competitions || [])[0];
    var rail = (primary && snaps[primary] ? leadersRail(snaps[primary], primary, tables[primary]) : '');
    return { col: col.join(''), rail: rail };
  }

  // ── feed anónimo ──
  function buildAnon() {
    var today = new Date(); var ymd = today.getFullYear() + ('0' + (today.getMonth() + 1)).slice(-2) + ('0' + today.getDate()).slice(-2);
    return Promise.all([D.scoreboard('laliga', ymd), D.snapshot('laliga'), D.news(), D.liveTable('laliga')]).then(function (res) {
      var events = (res[0] || []).map(function (e) { return D.parseEvent(e, 'laliga'); }).filter(Boolean);
      var snap = res[1], allNews = res[2] || [], table = res[3], col = [];
      var featured = events.filter(function (e) { return e.state === 'in'; })[0] || events.filter(function (e) { return e.state === 'pre'; })[0] || events[0];
      if (featured) col.push(hero(featured));
      col.push(feedSec('Elige tu competición'));
      col.push('<div class="league-chips">' + ORDER.map(function (s) { return '<a class="league-chip" href="/' + s + '"><img src="' + esc(llogo(s)) + '" alt="">' + esc(lname(s)) + '</a>'; }).join('') + '</div>');
      if (events.length) { col.push(feedSec('Partidos de hoy', 'Ver todos', '/partidos')); events.slice(0, 4).forEach(function (m) { col.push(resultCard(m, false)); }); }
      if (snap) { col.push(feedSec('Predicciones que suenan')); col.push(leadersCard(snap, 'laliga', table)); }
      col.push('<section class="cta-card"><h3>Sigue a los tuyos</h3><p>Crea tu cuenta gratis y tu portada se llena con los resultados, la clasificación y las noticias de tus equipos.</p><div class="btns"><a class="btn btn--primary" href="/cuenta">Crear cuenta</a><a class="btn btn--ghost" href="/cuenta">Entrar</a></div></section>');
      if (allNews.length) { col.push(feedSec('Lo último', 'Más', '/kiosco')); allNews.slice(0, 4).forEach(function (it) { col.push(newsCard(it)); }); }
      col.push('<section class="methodology-callout"><h3>Cómo funciona</h3><p>Probabilidades recalculadas cada día con simulación Monte Carlo sobre 40.000 temporadas virtuales. Con cada resultado real, la tabla se actualiza y las probabilidades se recalculan automáticamente.</p></section>');
      return { col: col.join(''), rail: (snap ? leadersRail(snap, 'laliga', table) : '') };
    });
  }

  // ── estado + montaje ──
  function acct() {
    var a = window.PMAccount, empty = { competitions: [], teams: [], favorite_team: null };
    if (!a) return { on: false, pending: false, f: empty };
    if (a.isReady && !a.isReady()) {
      // Estado aún por resolver (/api/me): con sesión probable (cookie hint) mantener el
      // skeleton (no montar el feed anónimo un instante); anónimo probable → feed ya.
      if (a.pending && a.pending()) return { on: false, pending: true, f: empty };
      return { on: false, pending: false, f: empty };
    }
    if (a.isEnabled && !a.isEnabled()) return { on: false, pending: false, f: empty };
    return { on: !!(a.isLoggedIn && a.isLoggedIn()), pending: false, f: (a.follows && a.follows()) || empty };
  }
  function skeleton() { return shellMain('<div class="card" style="height:180px"></div><div class="card" style="height:240px"></div>', ''); }
  function shellMain(colHTML, railHTML) { return '<div class="feed"><div class="feed__col">' + colHTML + '<div class="ad-wrap" data-ad-slot="box"></div></div><div class="feed__rail">' + railHTML + '</div></div>'; }
  function mount(out) { window.PMShell.mount({ active: 'home', main: shellMain(out.col, out.rail) }); }
  function fail() { window.PMShell.mount({ active: 'home', main: shellMain('<div class="card"><div style="padding:var(--sp-6);color:var(--text-2)">No se pudo cargar el feed. Reintenta en unos segundos.</div></div>', '') }); }

  var token = 0;
  function refresh() {
    var my = ++token, s = acct();
    // Sesión probable (cookie hint) pero /api/me sin resolver: mantener el skeleton;
    // 'pm-account-ready' re-dispara refresh con el estado real (nunca montar el feed
    // anónimo un instante para un usuario que sí sigue a alguien).
    if (s.pending) return;
    if (!s.on) { buildAnon().then(function (o) { if (my === token) mount(o); }).catch(fail); return; }

    var f = s.f, favId = f.favorite_team && String(f.favorite_team.espn_team_id);
    var teams = (f.teams || []).slice(0, 4).sort(function (a, b) { return (String(b.espn_team_id) === favId) - (String(a.espn_team_id) === favId); });
    var fav = teams[0], primary = fav ? fav.league_slug : (f.competitions || [])[0];
    // Solo el equipo favorito lleva partido/tabla en el feed: se pide únicamente
    // la liga y el equipo que realmente se van a pintar.
    Promise.all([D.news(), D.articles(), primary ? D.snapshot(primary) : Promise.resolve(null)]).then(function (r) {
      if (my !== token) return;
      var news = r[0] || [], article = r[1], snaps = {}; if (primary) snaps[primary] = r[2];
      mount(buildUserHTML(f, {}, snaps, news, {}, null, article));
      // Fase 2: partido del favorito (ESPN) + tabla en vivo de su liga.
      Promise.all([
        fav ? D.schedule(fav.league_slug, fav.espn_team_id).then(function (ev) { return D.pickTeamMatch(ev, fav.league_slug); }) : Promise.resolve(null),
        primary ? D.liveTable(primary) : Promise.resolve(null),
      ]).then(function (r2) {
          if (my !== token) return;
          var matches = {}; if (fav && r2[0]) matches[fav.espn_team_id] = r2[0];
          var tables = {}; if (primary && r2[1]) tables[primary] = r2[1];
          mount(buildUserHTML(f, matches, snaps, news, tables, null, article));
          // Fase 3: probabilidad 1X2 + colores del partido del favorito (live_tracker).
          var favM = fav && matches[fav.espn_team_id];
          if (favM && favM.id) {
            D.liveMatch(fav.league_slug, favM.id).then(function (lm) {
              if (my !== token || !lm) return;
              mount(buildUserHTML(f, matches, snaps, news, tables, lm, article));
            });
          }
        }).catch(fail);
    }).catch(fail);
  }

  function start() { window.PMShell.mount({ active: 'home', main: skeleton() }); refresh(); }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start); else start();
  document.addEventListener('pm-account-ready', refresh);
  document.addEventListener('pm-follows-changed', refresh);
})();
