/* Pestañas + "Próximos partidos" — compartido por los dashboards de liga.
   Sin dependencias. Datos en vivo de la API pública de ESPN. */
(function () {
  'use strict';
  var ESPN = 'https://site.api.espn.com/apis/site/v2/sports/soccer/';

  // ── Pestañas (mostrar/ocultar secciones) ──────────────────────────────────
  // Botones: <button class="page-tab" data-section="x">. Secciones:
  // <div class="tab-section" data-section="x">. Emite 'pmtab' al cambiar.
  window.PMTabs = {
    init: function () {
      var tabs = document.querySelectorAll('.page-tab');
      var secs = document.querySelectorAll('.tab-section');
      tabs.forEach(function (btn) {
        btn.addEventListener('click', function () {
          var s = btn.dataset.section;
          tabs.forEach(function (t) { t.classList.toggle('active', t === btn); });
          secs.forEach(function (sec) { sec.hidden = sec.dataset.section !== s; });
          window.dispatchEvent(new CustomEvent('pmtab', { detail: s }));
        });
      });
    }
  };

  // ── Próximos partidos ─────────────────────────────────────────────────────
  function ymd(d) {
    return '' + d.getUTCFullYear() +
      String(d.getUTCMonth() + 1).padStart(2, '0') +
      String(d.getUTCDate()).padStart(2, '0');
  }
  function getJSON(u) {
    return fetch(u, { cache: 'no-store' }).then(function (r) {
      if (!r.ok) throw new Error('ESPN ' + r.status); return r.json();
    });
  }
  function logo(t) { return (t && t.logo) || ((t && t.logos && t.logos[0] && t.logos[0].href)) || ''; }

  function matchCard(ev) {
    var c = (ev.competitions && ev.competitions[0]) || {};
    var cs = c.competitors || [];
    var home = cs.find(function (x) { return x.homeAway === 'home'; }) || cs[0] || {};
    var away = cs.find(function (x) { return x.homeAway === 'away'; }) || cs[1] || {};
    var st = (ev.status && ev.status.type && ev.status.type.state) || 'pre';
    var ht = home.team || {}, at = away.team || {};
    var mid, state = '';
    if (st === 'pre') {
      var dt = new Date(ev.date);
      var dd = dt.toLocaleDateString('es-ES', { weekday: 'short', day: '2-digit', month: 'short' });
      var tt = dt.toLocaleTimeString('es-ES', { hour: '2-digit', minute: '2-digit' });
      mid = '<div class="fx-time">' + dd.charAt(0).toUpperCase() + dd.slice(1) + ' · ' + tt + '</div>';
      state = '<span class="fx-state pre">Por jugar</span>';
    } else {
      mid = '<div class="fx-score">' + (home.score || '0') + ' – ' + (away.score || '0') + '</div>';
      if (st === 'in') state = '<span class="fx-state live">' + ((ev.status && ev.status.displayClock) || 'En vivo') + '</span>';
      else state = '<span class="fx-state post">Final</span>';
    }
    function side(t, cls) {
      var l = logo(t);
      var img = l ? '<img src="' + l + '" alt="" loading="lazy">' : '';
      return '<div class="fx-team ' + cls + '">' +
        (cls === 'home' ? '<span class="nm">' + (t.displayName || t.shortDisplayName || '') + '</span>' + img
          : img + '<span class="nm">' + (t.displayName || t.shortDisplayName || '') + '</span>') +
        '</div>';
    }
    return '<div class="fx-match">' + side(ht, 'home') +
      '<div class="fx-mid">' + mid + state + '</div>' + side(at, 'away') + '</div>';
  }

  function evTime(ev) { return new Date(ev.date).getTime(); }

  // Agrupa los partidos de toda la temporada en jornadas. ESPN no expone el
  // número de jornada, así que ordenamos por fecha y troceamos en bloques de
  // (nº de equipos / 2) partidos = una jornada.
  function buildRounds(events) {
    events = (events || []).filter(function (ev) {
      var c = (ev.competitions && ev.competitions[0]) || {};
      return (c.competitors || []).length === 2;
    });
    if (!events.length) return [];
    events.sort(function (a, b) { return evTime(a) - evTime(b); });

    var teams = {};
    events.forEach(function (ev) {
      (ev.competitions[0].competitors || []).forEach(function (c) {
        if (c.team && c.team.id != null) teams[c.team.id] = 1;
      });
    });
    var perRound = Math.max(1, Math.floor(Object.keys(teams).length / 2));

    var rounds = [];
    for (var i = 0; i < events.length; i += perRound) rounds.push(events.slice(i, i + perRound));
    return rounds;
  }

  window.PMFixtures = {
    init: function (code, mountSelector) {
      var el = document.querySelector(mountSelector);
      if (!el || el.dataset.loaded) return;
      el.dataset.loaded = '1';
      el.innerHTML = '<div class="fx-loading">Cargando partidos…</div>';

      getJSON(ESPN + code + '/scoreboard').then(function (sb) {
        var cal = (((sb.leagues || [])[0] || {}).calendar || []).filter(function (x) { return typeof x === 'string'; });
        if (!cal.length) {
          render(buildRounds(sb.events || []));
          return;
        }
        var start = ymd(new Date(cal[0]));
        var end = ymd(new Date(cal[cal.length - 1]));
        return getJSON(ESPN + code + '/scoreboard?dates=' + start + '-' + end + '&limit=700')
          .then(function (d) { render(buildRounds(d.events || [])); });
      }).catch(function () {
        el.dataset.loaded = '';
        el.innerHTML = '<div class="fx-empty">No se pudieron cargar los partidos.</div>';
      });

      function render(rounds) {
        if (!rounds.length) {
          el.innerHTML = '<div class="fx-empty">No hay partidos disponibles.</div>';
          return;
        }
        // Jornada actual: la primera con algún partido sin terminar; si todas
        // han terminado, la última.
        var idx = rounds.findIndex(function (r) {
          return r.some(function (ev) {
            var s = (ev.status && ev.status.type && ev.status.type.state) || 'pre';
            return s !== 'post';
          });
        });
        if (idx < 0) idx = rounds.length - 1;

        el.innerHTML =
          '<div class="fx-nav">' +
          '<button class="fx-btn" data-d="prev">← Anterior</button>' +
          '<div class="fx-label"></div>' +
          '<button class="fx-btn" data-d="next">Siguiente →</button>' +
          '</div><div class="fx-list"></div>';
        var prev = el.querySelector('[data-d="prev"]');
        var next = el.querySelector('[data-d="next"]');
        var label = el.querySelector('.fx-label');
        var list = el.querySelector('.fx-list');

        function show() {
          prev.disabled = idx <= 0;
          next.disabled = idx >= rounds.length - 1;
          label.textContent = 'Jornada ' + (idx + 1);
          list.innerHTML = rounds[idx].map(matchCard).join('');
        }
        prev.addEventListener('click', function () { if (idx > 0) { idx--; show(); } });
        next.addEventListener('click', function () { if (idx < rounds.length - 1) { idx++; show(); } });
        show();
      }
    }
  };
})();
