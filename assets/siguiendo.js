/* Siguiendo (fix bug 4) — vista de lo que sigue el usuario: competiciones + equipos
 * (+ favorito), con enlace a su dashboard/página y opción de dejar de seguir. NUNCA
 * muestra la cuenta del usuario como "seguido". Se monta en el shell, pestaña 'follow'. */
(function () {
  'use strict';
  var L = window.PM_LEAGUES || {};

  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) { return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]; }); }
  function initials(n) { var p = (n || '').trim().split(/\s+/).filter(Boolean); return ((p[0] || '?')[0] + (p.length > 1 ? p[p.length - 1][0] : '')).toUpperCase(); }
  window.PMSigCrestFallback = function (img) { var d = document.createElement('div'); d.className = 'crest-ph'; d.textContent = img.getAttribute('data-ab') || '?'; img.parentNode.replaceChild(d, img); };
  function teamCrest(id, name) { var ab = initials(name); if (!id) return '<div class="crest-ph">' + ab + '</div>'; return '<img class="crest" loading="lazy" alt="" src="https://a.espncdn.com/i/teamlogos/soccer/500/' + id + '.png" data-ab="' + ab + '" onerror="PMSigCrestFallback(this)">'; }
  function lname(s) { return (L[s] || {}).name || s; }
  function acct() {
    var a = window.PMAccount;
    if (!a || (a.isEnabled && !a.isEnabled())) return { avail: false, on: false, f: { competitions: [], teams: [], favorite_team: null } };
    return { avail: true, on: !!(a.isLoggedIn && a.isLoggedIn()), f: (a.follows && a.follows()) || { competitions: [], teams: [], favorite_team: null } };
  }

  function group(title, rows) { return (title ? '<div class="feed-sec"><h2 class="feed-sec__title">' + esc(title) + '</h2></div>' : '') + '<section class="set-group">' + rows + '</section>'; }
  function compRow(slug) {
    var lg = L[slug] || { name: slug, logo: '' };
    return '<div class="set-row"><a class="s-go" href="/' + slug + '">' + (lg.logo ? '<img class="lg-logo" src="' + esc(lg.logo) + '" alt="">' : '<span class="crest-ph"></span>')
      + '<span class="s-main"><span class="s-label">' + esc(lg.name) + '</span><span class="s-hint">Clasificación y probabilidades</span></span></a>'
      + '<button class="set-unfollow" data-unfollow-comp="' + esc(slug) + '" type="button">Dejar de seguir</button></div>';
  }
  function teamRow(t, fav) {
    return '<div class="set-row"><a class="s-go" href="/equipo?id=' + t.espn_team_id + '&league=' + (t.league_slug || '') + '&name=' + encodeURIComponent(t.name || '') + '">'
      + teamCrest(t.espn_team_id, t.name) + '<span class="s-main"><span class="s-label">' + (fav ? '★ ' : '') + esc(t.name || 'Equipo') + '</span><span class="s-hint">' + esc(lname(t.league_slug)) + '</span></span></a>'
      + '<button class="set-unfollow" data-unfollow-team="' + esc(t.espn_team_id) + '" type="button">Dejar de seguir</button></div>';
  }

  function mainHTML(s) {
    var col = ['<div class="feed-sec" style="margin-top:var(--sp-2)"><h2 class="feed-sec__title">Siguiendo</h2></div>'];
    if (!s.on) {
      col.push('<section class="cta-card"><h3>Sigue a los tuyos</h3><p>' + (s.avail ? 'Inicia sesión para seguir equipos y competiciones y verlos aquí y en tu portada.' : 'Las cuentas no están disponibles ahora mismo.') + '</p>'
        + (s.avail ? '<div class="btns"><a class="btn btn--primary" href="/cuenta">Entrar</a><a class="btn btn--ghost" href="/buscar">Explorar</a></div>' : '') + '</section>');
      return '<div class="feed"><div class="feed__col">' + col.join('') + '</div><div class="feed__rail"></div></div>';
    }
    var f = s.f, favId = f.favorite_team && String(f.favorite_team.espn_team_id);
    if (!((f.competitions || []).length || (f.teams || []).length)) {
      col.push('<section class="cta-card"><h3>Aún no sigues nada</h3><p>Usa Buscar para seguir competiciones y equipos; aparecerán aquí y en tu portada.</p><div class="btns"><a class="btn btn--primary" href="/buscar">Buscar</a></div></section>');
    } else {
      if ((f.competitions || []).length) col.push(group('Competiciones', f.competitions.map(compRow).join('')));
      var teams = (f.teams || []).slice();
      teams.sort(function (a, b) { return (String(b.espn_team_id) === favId) - (String(a.espn_team_id) === favId); });
      if (teams.length) col.push(group('Equipos', teams.map(function (t) { return teamRow(t, favId === String(t.espn_team_id)); }).join('')));
      col.push('<div class="feed-sec"><a class="feed-sec__more" href="/buscar">+ Seguir más</a></div>');
    }
    return '<div class="feed"><div class="feed__col">' + col.join('') + '</div><div class="feed__rail"></div></div>';
  }

  // Dejar de seguir: delegación en document UNA vez (no apila handlers en #app).
  document.addEventListener('click', function (e) {
    var c = e.target.closest && e.target.closest('[data-unfollow-comp]');
    var t = e.target.closest && e.target.closest('[data-unfollow-team]');
    if (!c && !t) return;
    e.preventDefault();
    var a = window.PMAccount; if (!a) return;
    var btn = c || t; btn.disabled = true;
    var p = c ? a.unfollowCompetition(c.getAttribute('data-unfollow-comp')) : a.unfollowTeam(t.getAttribute('data-unfollow-team'));
    (p || Promise.resolve()).catch(function () { btn.disabled = false; });
  });

  function render() { window.PMShell.mount({ active: 'follow', main: mainHTML(acct()) }); }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', render); else render();
  document.addEventListener('pm-account-ready', render);
  document.addEventListener('pm-follows-changed', render);
})();
