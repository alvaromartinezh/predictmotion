/* PMAccount — estado de cuenta + login en la topbar + API de follows.
 *
 * Componente compartido (patrón como PMFixtures/PMAds). Al cargar:
 *  - inyecta en la topbar un enlace a /cuenta ("Iniciar sesión" o el nombre del
 *    usuario) según haya sesión;
 *  - carga el estado (config → me → follows) y lo cachea;
 *  - expone helpers de follow que actualizan la caché y emiten eventos
 *    'pm-account-ready' y 'pm-follows-changed' para que la página reaccione.
 *
 * Degrada en silencio: si la feature está apagada o la API falla, la topbar
 * queda sin widget y la página se comporta como anónima. No rompe nada.
 */
(function () {
  // Mismo origen en producción (Caddy proxya /api/*). En dev (:8765) usamos el
  // MISMO host para :8771, para que la cookie SameSite=Lax viaje.
  var API = (location.port === '8765')
    ? (location.protocol + '//' + location.hostname + ':8771')
    : '';

  function api(path, opts) {
    opts = opts || {};
    opts.credentials = 'include';
    return fetch(API + path, opts).then(function (r) {
      return r.json().catch(function () { return {}; });
    });
  }

  var state = { loaded: false, enabled: false, user: null, follows: null, prefs: null };

  function _emit(name) { document.dispatchEvent(new CustomEvent(name)); }

  // Si la cuenta trae un bg_theme guardado (otro dispositivo), gana sobre el
  // valor local: reconcilia DOM + localStorage vía PMBgTheme (theme.js, cargado
  // antes que este script en todas las páginas). Aplica en CUALQUIER página, no
  // solo en Ajustes, para que el tema de fondo sea consistente en todo el shell.
  function _reconcileBgTheme() {
    var t = state.prefs && state.prefs.bg_theme;
    if (t && window.PMBgTheme && window.PMBgTheme.current() !== t) {
      window.PMBgTheme.set(t);
    }
  }

  function loadState() {
    return api('/api/auth/config').then(function (cfg) {
      state.enabled = !!(cfg && cfg.enabled);
      if (!state.enabled) { state.loaded = true; return state; }
      return api('/api/me').then(function (me) {
        state.user = (me && me.ok) ? me.user : null;
        if (!state.user) { state.follows = null; state.prefs = null; state.loaded = true; return state; }
        return Promise.all([api('/api/follows'), api('/api/prefs')]).then(function (r) {
          var f = r[0], p = r[1];
          state.follows = (f && f.ok)
            ? { favorite_team: f.favorite_team, teams: f.teams || [], competitions: f.competitions || [] }
            : { favorite_team: null, teams: [], competitions: [] };
          state.prefs = (p && p.ok) ? { bg_theme: p.bg_theme } : { bg_theme: null };
          _reconcileBgTheme();
          state.loaded = true;
          return state;
        });
      });
    }).catch(function () { state.loaded = true; return state; });
  }

  function firstName(n) { return (n || 'Mi cuenta').split(' ')[0]; }

  function renderWidget() {
    var el = document.getElementById('pm-account');
    if (!el) return;
    if (!state.enabled) { el.style.display = 'none'; return; }
    el.style.display = '';
    if (state.user) {
      var pic = state.user.picture
        ? '<img class="pm-account__pic" src="' + state.user.picture + '" alt="" referrerpolicy="no-referrer"/>'
        : '<span class="pm-account__pic pm-account__pic--ph" aria-hidden="true"></span>';
      el.innerHTML = pic + '<span class="pm-account__name">' + firstName(state.user.name) + '</span>';
      el.setAttribute('aria-label', 'Mi cuenta');
    } else {
      el.innerHTML = '<span class="pm-account__login">Iniciar sesión</span>';
      el.setAttribute('aria-label', 'Iniciar sesión');
    }
  }

  function injectWidget() {
    var right = document.querySelector('.topbar__right');
    if (!right || document.getElementById('pm-account')) return;
    var a = document.createElement('a');
    a.id = 'pm-account';
    a.className = 'pm-account';
    a.href = '/cuenta';
    a.style.display = 'none';  // se muestra cuando sepamos el estado
    right.insertBefore(a, right.firstChild);
  }

  function _reloadFollows() {
    return api('/api/follows').then(function (f) {
      if (f && f.ok) {
        state.follows = { favorite_team: f.favorite_team, teams: f.teams || [], competitions: f.competitions || [] };
      }
      _emit('pm-follows-changed');
      return state.follows;
    });
  }

  var PMAccount = {
    init: function () {
      injectWidget();
      return loadState().then(function () {
        renderWidget();
        _emit('pm-account-ready');
        return state;
      });
    },
    // Re-carga el estado de cuenta/follows desde el backend y re-emite los eventos
    // para que el shell y las vistas (home/siguiendo) se re-rendericen. Se usa (1)
    // al restaurar la página desde bfcache (botón atrás) y (2) tras login/logout en
    // /cuenta, para que la sesión/follows reales se reflejen SIN recargar a mano.
    refresh: function () {
      return loadState().then(function () {
        renderWidget();
        _emit('pm-account-ready');
        _emit('pm-follows-changed');
        return state;
      });
    },
    isReady: function () { return state.loaded; },
    isEnabled: function () { return state.enabled; },
    isLoggedIn: function () { return !!state.user; },
    user: function () { return state.user; },
    follows: function () { return state.follows; },
    loginUrl: '/cuenta',

    followsCompetition: function (slug) {
      return !!(state.follows && state.follows.competitions.indexOf(slug) >= 0);
    },
    followsTeam: function (id) {
      id = String(id);
      return !!(state.follows && state.follows.teams.some(function (t) { return t.espn_team_id === id; }));
    },
    isFavorite: function (id) {
      return !!(state.follows && state.follows.favorite_team && state.follows.favorite_team.espn_team_id === String(id));
    },

    followCompetition: function (slug) {
      return api('/api/follows/competitions/' + encodeURIComponent(slug), { method: 'POST' }).then(_reloadFollows);
    },
    unfollowCompetition: function (slug) {
      return api('/api/follows/competitions/' + encodeURIComponent(slug), { method: 'DELETE' }).then(_reloadFollows);
    },
    followTeam: function (id, slug, name) {
      return api('/api/follows/teams', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ espn_team_id: String(id), league_slug: slug, name: name || '' }),
      }).then(_reloadFollows);
    },
    unfollowTeam: function (id) {
      return api('/api/follows/teams/' + encodeURIComponent(id), { method: 'DELETE' }).then(_reloadFollows);
    },
    setFavorite: function (id, slug, name) {
      return api('/api/follows/favorite-team', {
        method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ espn_team_id: String(id), league_slug: slug, name: name || '' }),
      }).then(_reloadFollows);
    },
    clearFavorite: function () {
      return api('/api/follows/favorite-team', { method: 'DELETE' }).then(_reloadFollows);
    },

    bgTheme: function () { return state.prefs && state.prefs.bg_theme; },
    setBgTheme: function (theme) {
      return api('/api/prefs', {
        method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ bg_theme: theme }),
      }).then(function (p) {
        if (p && p.ok) state.prefs = { bg_theme: p.bg_theme };
        return state.prefs;
      });
    },
  };

  window.PMAccount = PMAccount;
  if (document.readyState !== 'loading') PMAccount.init();
  else document.addEventListener('DOMContentLoaded', function () { PMAccount.init(); });

  // bfcache (botón atrás/adelante): el navegador restaura un snapshot del DOM y del
  // estado JS ANTERIOR a acciones hechas en otra página (p. ej. seguir un equipo).
  // Al restaurar (event.persisted), re-cargamos el estado real para que los follows
  // y la sesión no se queden obsoletos. En una carga normal (persisted=false) no
  // hace nada: init() ya cargó el estado.
  window.addEventListener('pageshow', function (e) {
    if (e.persisted && window.PMAccount) PMAccount.refresh();
  });
})();
