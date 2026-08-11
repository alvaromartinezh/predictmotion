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
  var BG_LABELS = { purple: 'Morado', green: 'Verde', blue: 'Azul', orange: 'Naranja', teal: 'Turquesa', rose: 'Rosa' };

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

    // Color de fondo (patrón de iconos)
    var bg = window.PMBgTheme ? window.PMBgTheme.current() : 'purple';
    var swatches = (window.PMBgTheme ? window.PMBgTheme.THEMES : ['purple', 'green', 'blue', 'orange', 'teal', 'rose'])
      .map(function (key) {
        return '<button type="button" class="bg-swatch' + (key === bg ? ' is-on' : '') + '" data-bg-theme-set="' + key
          + '" style="--sw:var(--bg-accent-' + key + ',#7c5cff)" aria-label="' + esc(BG_LABELS[key] || key) + '"></button>';
      }).join('');
    col.push(group('', '<div class="set-row"><span class="s-main"><span class="s-label">Color de fondo</span><span class="s-hint">Patrón del shell</span></span>'
      + '<span class="bg-swatches" id="set-bg-theme">' + swatches + '</span></div>'));

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
        var lg = L[slug] || { name: slug, logo: '', country: '' };
        rows += '<div class="pm-item"><a class="pm-item__go" href="/' + esc(slug) + '">' + (lg.logo ? '<img class="lg-logo" src="' + esc(lg.logo) + '" alt="">' : '<span class="crest-ph"></span>')
          + '<span class="pm-item__body"><span class="pm-item__title">' + esc(lg.name) + '</span>' + (lg.country ? '<span class="pm-item__sub">' + esc(lg.country) + '</span>' : '') + '</span></a>'
          + '<span class="pm-item__end"><button class="set-unfollow" data-unfollow-comp="' + esc(slug) + '" type="button">Dejar de seguir</button></span></div>';
      });
      var favId = s.f.favorite_team && String(s.f.favorite_team.espn_team_id);
      (s.f.teams || []).forEach(function (tm) {
        var lg = L[tm.league_slug] || {};
        rows += '<div class="pm-item pm-item--team"><a class="pm-item__go" href="/equipo?id=' + esc(tm.espn_team_id) + '&league=' + esc(tm.league_slug || '') + '&name=' + encodeURIComponent(tm.name || '') + '">' + crest(tm.espn_team_id, tm.name)
          + '<span class="pm-item__body"><span class="pm-item__title">' + (favId === String(tm.espn_team_id) ? '<span class="fav">★</span> ' : '') + esc(tm.name || 'Equipo') + '</span><span class="pm-item__sub">' + esc(lg.name || tm.league_slug || '') + '</span></span></a>'
          + '<span class="pm-item__end"><button class="set-unfollow" data-unfollow-team="' + esc(tm.espn_team_id) + '" type="button">Dejar de seguir</button></span></div>';
      });
      if (rows) {
        col.push('<div class="feed-sec"><h2 class="feed-sec__title">Tus seguidos</h2></div><section class="pm-list">' + rows + '</section>');
      } else {
        col.push(group('Tus seguidos', '<div class="set-row"><span class="s-main"><span class="s-hint">Aún no sigues nada. Usa la ☆ en las competiciones y equipos.</span></span></div>'));
      }
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
    var bgSeg = document.getElementById('set-bg-theme');
    if (bgSeg) bgSeg.addEventListener('click', function (e) {
      var b = e.target.closest('[data-bg-theme-set]'); if (!b || !window.PMBgTheme) return;
      var t = b.getAttribute('data-bg-theme-set');
      window.PMBgTheme.set(t);
      bgSeg.querySelectorAll('button').forEach(function (x) { x.classList.toggle('is-on', x.getAttribute('data-bg-theme-set') === t); });
      var a = acct();
      if (a.on) window.PMAccount.setBgTheme(t); // persiste en cuenta, cross-device
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
