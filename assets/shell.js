/* PMShell — app-shell del rediseño (CP-R1): barra lateral (desktop) / pestañas
 * inferiores (móvil) / topbar (móvil), con estado de sesión y follows LEÍDOS DE
 * PMAccount (API real /api/follows), NO de datos mock.
 *
 * Tema: NO gestiona tema propio. Reutiliza theme.js (único sistema); tras montar,
 * llama a PMTheme.wire() para cablear su botón [data-theme-toggle] inyectado.
 *
 * Uso: PMShell.mount({ active: 'home'|'matches'|..., main: '<...html...>' }).
 * El shell se re-renderiza solo ante 'pm-account-ready' / 'pm-follows-changed'.
 *
 * Degrada: sin PMAccount o feature apagada → vista anónima. Nunca rompe la página.
 */
(function () {
  'use strict';

  // Catálogo de competiciones: fuente única en assets/pm-leagues.js (window.PM_LEAGUES).
  var LEAGUES = window.PM_LEAGUES || {};

  // ---- helpers ----
  window.PMShellCrestFallback = function (img) {
    var d = document.createElement('div');
    d.className = 'crest-ph'; d.textContent = img.getAttribute('data-ab') || '?';
    img.parentNode.replaceChild(d, img);
  };
  function initials(name) {
    var p = (name || '').trim().split(/\s+/).filter(Boolean);
    return ((p[0] || '?')[0] + (p.length > 1 ? p[p.length - 1][0] : '')).toUpperCase();
  }
  function teamCrest(t) {
    var id = t.espn_team_id, ab = initials(t.name);
    if (!id) return '<div class="crest-ph">' + ab + '</div>';
    return '<img class="crest" loading="lazy" alt="" src="https://a.espncdn.com/i/teamlogos/soccer/500/' + id + '.png"'
      + ' data-ab="' + ab + '" onerror="PMShellCrestFallback(this)">';
  }
  function svg(p) { return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round">' + p + '</svg>'; }
  var IC = {
    home: '<path d="M3 10.5 12 3l9 7.5"/><path d="M5 9.5V21h14V9.5"/><path d="M9.5 21v-6h5v6"/>',
    star: '<path d="M12 3.5l2.6 5.3 5.9.9-4.3 4.1 1 5.8L12 17l-5.2 2.6 1-5.8-4.3-4.1 5.9-.9z"/>',
    ball: '<circle cx="12" cy="12" r="9"/><path d="M12 7.5l3.6 2.6-1.4 4.2H9.8L8.4 10.1z"/>',
    search: '<circle cx="11" cy="11" r="7"/><path d="M20 20l-3.2-3.2"/>',
    gear: '<circle cx="12" cy="12" r="3"/><path d="M19 12a7 7 0 0 0-.1-1.3l2-1.6-2-3.4-2.4 1a7 7 0 0 0-2.2-1.3L14 2h-4l-.3 2.1a7 7 0 0 0-2.2 1.3l-2.4-1-2 3.4 2 1.6A7 7 0 0 0 5 12c0 .4 0 .9.1 1.3l-2 1.6 2 3.4 2.4-1a7 7 0 0 0 2.2 1.3L10 22h4l.3-2.1a7 7 0 0 0 2.2-1.3l2.4 1 2-3.4-2-1.6c.1-.4.1-.9.1-1.3Z"/>',
    bell: '<path d="M18 8a6 6 0 1 0-12 0c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.7 21a2 2 0 0 1-3.4 0"/>',
    moon: '<path d="M21 12.8A8.5 8.5 0 1 1 11.2 3a6.5 6.5 0 0 0 9.8 9.8Z"/>',
    sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>'
  };
  // ready:false = la página de esa pestaña aún no existe (Partidos → CP-R5, Buscar →
  // CP-R4). Se OCULTAN hasta entonces para no llevar a un 404 (regla del plan: una
  // pestaña visible siempre resuelve a una página real). Al aterrizar su fase, ready:true.
  var NAV = [
    { id: 'home', label: 'Inicio', href: '/', icon: IC.home, ready: true },
    { id: 'follow', label: 'Siguiendo', href: '/cuenta', icon: IC.star, ready: true },
    { id: 'matches', label: 'Partidos', href: '/partidos', icon: IC.ball, ready: false },
    { id: 'search', label: 'Buscar', href: '#', icon: IC.search, ready: false },
    { id: 'settings', label: 'Ajustes', href: '/cuenta', icon: IC.gear, ready: true }
  ];
  function navItems() { return NAV.filter(function (n) { return n.ready; }); }
  var LOGIN = '/cuenta';

  function themeToggle() {
    return '<button class="iconbtn pm-theme-toggle" data-theme-toggle type="button" aria-label="Cambiar tema" title="Tema claro / oscuro">'
      + '<span class="tt-dark" aria-hidden="true">' + svg(IC.moon) + '</span>'
      + '<span class="tt-light" aria-hidden="true">' + svg(IC.sun) + '</span></button>';
  }

  // Estado de sesión (real). Degrada a anónimo si no hay PMAccount o está apagado.
  function acct() {
    var a = window.PMAccount;
    if (!a || (a.isEnabled && !a.isEnabled())) return { on: false, user: null, f: { competitions: [], teams: [], favorite_team: null } };
    return {
      on: !!(a.isLoggedIn && a.isLoggedIn()),
      user: (a.user && a.user()) || null,
      f: (a.follows && a.follows()) || { competitions: [], teams: [], favorite_team: null }
    };
  }

  function avatar(user) {
    if (user && user.picture) return '<span class="avatar"><img src="' + user.picture + '" alt="" referrerpolicy="no-referrer"></span>';
    return '<span class="avatar">' + initials(user && user.name) + '</span>';
  }

  function tabbar(active) {
    return '<nav class="tabbar" aria-label="Navegación">' + navItems().map(function (n) {
      return '<a class="tabbar__item ' + (n.id === active ? 'is-active' : '') + '" href="' + n.href + '">' + svg(n.icon) + '<span>' + n.label + '</span></a>';
    }).join('') + '</nav>';
  }

  function appbar(s) {
    var right = s.on
      ? themeToggle() + '<button class="iconbtn" aria-label="Notificaciones">' + svg(IC.bell) + '</button>'
        + '<a href="' + LOGIN + '" aria-label="Mi cuenta">' + avatar(s.user) + '</a>'
      : themeToggle() + '<a class="btn btn--primary" style="padding:8px 16px;font-size:var(--fs-13)" href="' + LOGIN + '">Entrar</a>';
    return '<header class="appbar"><a class="appbar__brand" href="/"><span class="dot"></span>Predict<b>Motion</b></a>'
      + '<span class="appbar__spacer"></span>' + right + '</header>';
  }

  function sidebar(s, active) {
    var items = navItems().map(function (n) {
      return '<a class="navitem ' + (n.id === active ? 'is-active' : '') + '" href="' + n.href + '">' + svg(n.icon) + '<span>' + n.label + '</span></a>';
    }).join('');

    var follows;
    if (s.on) {
      var favId = s.f.favorite_team && String(s.f.favorite_team.espn_team_id);
      var comps = (s.f.competitions || []).map(function (slug) {
        var L = LEAGUES[slug] || { name: slug, logo: '' };
        return '<a class="side-follow" href="/' + slug + '">' + (L.logo ? '<img class="crest" src="' + L.logo + '" alt="" style="background:transparent;border:none">' : '<span class="crest-ph"></span>') + '<span>' + L.name + '</span></a>';
      }).join('');
      var teams = (s.f.teams || []).map(function (t) {
        return '<a class="side-follow" href="/equipo?id=' + t.espn_team_id + '&league=' + (t.league_slug || '') + '&name=' + encodeURIComponent(t.name || '') + '">'
          + teamCrest(t) + '<span>' + (t.name || 'Equipo') + '</span>'
          + (favId === String(t.espn_team_id) ? '<span class="star">★</span>' : '') + '</a>';
      }).join('');
      follows = (comps ? '<div class="sidenav__label eyebrow">Tus competiciones</div><div class="sidenav__follows">' + comps + '</div>' : '')
        + (teams ? '<div class="sidenav__label eyebrow">Tus equipos</div><div class="sidenav__follows">' + teams + '</div>' : '');
    } else {
      // Orden EXPLÍCITO de prioridad (PM_LEAGUES_ORDER: ligas top primero), no el
      // orden de iteración del objeto. Visible para visitantes anónimos (la mayoría).
      var order = (window.PM_LEAGUES_ORDER || Object.keys(LEAGUES)).filter(function (s) { return LEAGUES[s]; });
      follows = '<div class="sidenav__label eyebrow">Competiciones</div><div class="sidenav__follows">'
        + order.slice(0, 8).map(function (slug) {
          var L = LEAGUES[slug];
          return '<a class="side-follow" href="/' + slug + '"><img class="crest" src="' + L.logo + '" alt="" style="background:transparent;border:none"><span>' + L.name + '</span></a>';
        }).join('') + '</div>';
    }

    // El botón de tema NO va dentro del <a> de cuenta (interactivo dentro de
    // interactivo). Va como hermano dentro del contenedor flex.
    var user = s.on
      ? '<div class="sidenav__user"><a class="sidenav__me" href="' + LOGIN + '">' + avatar(s.user)
        + '<span class="who"><span class="n">' + ((s.user && s.user.name) || 'Mi cuenta') + '</span><span class="e">Ver cuenta</span></span></a>' + themeToggle() + '</div>'
      : '<div class="sidenav__user" style="justify-content:space-between"><a class="btn btn--primary" href="' + LOGIN + '" style="flex:1">Crear cuenta</a>' + themeToggle() + '</div>';

    return '<aside class="sidenav"><a class="sidenav__brand" href="/"><span class="dot"></span>Predict<b>M</b></a>'
      + items + follows + '<div class="sidenav__spacer"></div>' + user + '</aside>';
  }

  var last = null;
  function render() {
    if (!last) return;
    var s = acct();
    var appEl = document.getElementById('app');
    if (!appEl) return;
    appEl.innerHTML = sidebar(s, last.active) + '<div class="app__main">' + appbar(s) + last.main + '</div>';
    var tb = document.getElementById('shell-tabbar');
    if (tb) tb.innerHTML = tabbar(last.active);
    if (window.PMTheme && window.PMTheme.wire) window.PMTheme.wire();
    if (last.onRender) try { last.onRender(); } catch (e) {}
  }

  function mount(opts) {
    last = { active: opts.active || 'home', main: opts.main || '', onRender: opts.onRender || null };
    render();
  }

  // Re-render cuando PMAccount conoce/actualiza el estado
  document.addEventListener('pm-account-ready', render);
  document.addEventListener('pm-follows-changed', render);

  window.PMShell = { mount: mount, LEAGUES: LEAGUES };
})();
