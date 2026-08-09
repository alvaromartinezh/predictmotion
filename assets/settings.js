/* Ajustes (CP-R4) — hub de configuración del rediseño: tema, cuenta, gestión de
 * seguidos (unfollow real vía PMAccount) y enlaces (noticias, privacidad, contacto).
 * Se monta en el shell (PMShell), pestaña 'settings'. Agrega/enlaza; no duplica /cuenta. */
(function () {
  'use strict';
  var L = window.PM_LEAGUES || {};

  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) { return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]; }); }
  function initials(n) { var p = (n || '').trim().split(/\s+/).filter(Boolean); return ((p[0] || '?')[0] + (p.length > 1 ? p[p.length - 1][0] : '')).toUpperCase(); }
  window.PMSetCrestFallback = function (img) { var d = document.createElement('div'); d.className = 'crest-ph'; d.textContent = img.getAttribute('data-ab') || '?'; img.parentNode.replaceChild(d, img); };
  function crest(id, name) {
    var ab = initials(name);
    if (!id) return '<div class="crest-ph">' + ab + '</div>';
    return '<img class="crest" loading="lazy" alt="" src="https://a.espncdn.com/i/teamlogos/soccer/500/' + id + '.png" data-ab="' + ab + '" onerror="PMSetCrestFallback(this)">';
  }

  function acct() {
    var a = window.PMAccount;
    if (!a || (a.isEnabled && !a.isEnabled())) return { avail: false, on: false, user: null, f: { competitions: [], teams: [], favorite_team: null } };
    return { avail: true, on: !!(a.isLoggedIn && a.isLoggedIn()), user: (a.user && a.user()) || null, f: (a.follows && a.follows()) || { competitions: [], teams: [], favorite_team: null } };
  }
  function curTheme() { return document.documentElement.getAttribute('data-theme') === 'light' ? 'light' : 'dark'; }

  function group(title, rowsHTML) {
    return (title ? '<div class="feed-sec"><h2 class="feed-sec__title">' + esc(title) + '</h2></div>' : '') + '<section class="set-group">' + rowsHTML + '</section>';
  }
  function linkRow(href, label, hint, ext) {
    return '<a class="set-row" href="' + esc(href) + '"' + (ext ? ' target="_blank" rel="noopener"' : '') + '><span class="s-main"><span class="s-label">' + esc(label) + '</span>' + (hint ? '<span class="s-hint">' + esc(hint) + '</span>' : '') + '</span><span class="s-arrow">›</span></a>';
  }

  function mainHTML(s) {
    var col = ['<div class="feed-sec" style="margin-top:var(--sp-2)"><h2 class="feed-sec__title">Ajustes</h2></div>'];

    // Tema
    var t = curTheme();
    col.push(group('', '<div class="set-row"><span class="s-main"><span class="s-label">Tema</span><span class="s-hint">Claro u oscuro</span></span>'
      + '<span class="seg" id="set-theme"><button type="button" data-theme-set="light" class="' + (t === 'light' ? 'is-on' : '') + '">Claro</button>'
      + '<button type="button" data-theme-set="dark" class="' + (t === 'dark' ? 'is-on' : '') + '">Oscuro</button></span></div>'));

    // Cuenta
    if (s.on) {
      col.push(group('Cuenta', '<a class="set-row" href="/cuenta"><span class="avatar">' + initials(s.user && s.user.name) + '</span>'
        + '<span class="s-main"><span class="s-label">' + esc((s.user && s.user.name) || 'Mi cuenta') + '</span><span class="s-hint">Gestionar cuenta</span></span><span class="s-arrow">›</span></a>'));
    } else {
      col.push(group('Cuenta', linkRow('/cuenta', s.avail ? 'Inicia sesión o crea tu cuenta' : 'Cuentas no disponibles', s.avail ? 'Sigue equipos y personaliza tu portada' : 'Vuelve más tarde')));
    }

    // Seguidos (solo con sesión)
    if (s.on) {
      var rows = '';
      (s.f.competitions || []).forEach(function (slug) {
        var lg = L[slug] || { name: slug, logo: '' };
        rows += '<div class="set-row">' + (lg.logo ? '<img class="lg-logo" src="' + esc(lg.logo) + '" alt="">' : '<span class="crest-ph"></span>')
          + '<span class="s-main"><span class="s-label">' + esc(lg.name) + '</span></span>'
          + '<button class="set-unfollow" data-unfollow-comp="' + esc(slug) + '" type="button">Dejar de seguir</button></div>';
      });
      var favId = s.f.favorite_team && String(s.f.favorite_team.espn_team_id);
      (s.f.teams || []).forEach(function (tm) {
        rows += '<div class="set-row">' + crest(tm.espn_team_id, tm.name)
          + '<span class="s-main"><span class="s-label">' + (favId === String(tm.espn_team_id) ? '★ ' : '') + esc(tm.name || 'Equipo') + '</span></span>'
          + '<button class="set-unfollow" data-unfollow-team="' + esc(tm.espn_team_id) + '" type="button">Dejar de seguir</button></div>';
      });
      if (!rows) rows = '<div class="set-row"><span class="s-main"><span class="s-hint">Aún no sigues nada. Usa la ☆ en las competiciones y equipos.</span></span></div>';
      col.push(group('Tus seguidos', rows));
    }

    // Enlaces
    col.push(group('Más', linkRow('/noticias', 'Noticias') + linkRow('/privacy', 'Privacidad') + linkRow('mailto:contact@predictmotion.com', 'Contacto', 'contact@predictmotion.com', true)));

    return '<div class="feed"><div class="feed__col">' + col.join('') + '</div><div class="feed__rail"></div></div>';
  }

  // El control de tema (#set-theme) se recrea en cada render → se recablea aquí.
  function wire() {
    var seg = document.getElementById('set-theme');
    if (seg) seg.addEventListener('click', function (e) {
      var b = e.target.closest('[data-theme-set]'); if (!b) return;
      if (curTheme() !== b.getAttribute('data-theme-set') && window.PMTheme) window.PMTheme.toggle();
      seg.querySelectorAll('button').forEach(function (x) { x.classList.toggle('is-on', x.getAttribute('data-theme-set') === curTheme()); });
    });
  }

  // Unfollow: delegación en document UNA sola vez (evita apilar handlers en #app,
  // que persiste entre renders). Emite pm-follows-changed → re-render.
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

  function render() { window.PMShell.mount({ active: 'settings', main: mainHTML(acct()), onRender: wire }); }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', render); else render();
  document.addEventListener('pm-account-ready', render);
  document.addEventListener('pm-follows-changed', render);
})();
