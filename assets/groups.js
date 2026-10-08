/* Competiciones de selecciones — una página por competición con TODAS las tablas
 * de grupo (con probabilidades) y TODOS los partidos.
 *
 * Por qué no son dashboards del cron SEO: ESPN sirve estas competiciones como N
 * grupos de 3-6 selecciones (14 en la Nations League, 12 en la clasificación de
 * la Copa África), y el pipeline de `seo/` es una tabla = un snapshot = una
 * página. Catorce páginas de grupos de cuatro no son producto. Así que estas
 * páginas se resuelven EN CLIENTE: ESPN en vivo + el Monte Carlo compartido
 * (`league-engine.js`, el mismo motor que el fallback de los dashboards). Sin
 * cron, sin snapshot y sin nada que lanzar a mano (Principio 2): ESPN rueda de
 * ciclo y la página le sigue.
 *
 * Cada página solo declara `window.PM_GROUPS_SLUG`; el formato (zonas, partidos
 * por equipo, medias p_home/p_draw) vive aquí, en COMPS.
 */
(function () {
  'use strict';

  // ── Formato por competición ───────────────────────────────────────────────
  // bands(n) → columnas de probabilidad del grupo, en orden. lo/hi son posiciones
  // 1-based inclusive; `kind` es la píldora del sistema de diseño (up/po/down) y
  // también la franja de zona de la fila (data-zone).
  // tier(name) → liga/escalera a la que pertenece el grupo ('' si la competición
  // no tiene escaleras); agrupa las tablas bajo un encabezado.
  // mpt(n) → partidos por equipo en el grupo. Por defecto el doble round-robin
  // 2·(n−1); se declara solo donde el formato NO lo es.
  function band(label, kind, lo, hi) { return { label: label, kind: kind, lo: lo, hi: hi }; }

  var COMPS = {
    // Nations League: 14 grupos (A1-A4, B1-B4, C1-C4, D1-D2), doble round-robin.
    // Zonas confirmadas contra las notas de ESPN ("A: Qualifies for QFs; B-D:
    // Promotion", "A, B: Relegation playoffs", …), que ESPN solo rellena en
    // algunos grupos y por eso no se derivan de ahí.
    'nations-league': {
      name: 'Nations League', pHome: 0.42, pDraw: 0.26, simN: 20000,
      tier: function (nm) { return (nm.match(/([A-D])\d/) || [])[1] || ''; },
      tierLabel: function (t) { return 'Liga ' + t; },
      groupLabel: function (nm) { return nm.replace(/^Group\s+/i, 'Grupo '); },
      bands: function (n, t) {
        if (t === 'A') return [band('Cuartos', 'up', 1, 2), band('Play-off permanencia', 'po', 3, 3), band('Descenso', 'down', n, n)];
        if (t === 'D') return [band('Ascenso', 'up', 1, 1), band('Play-off ascenso', 'po', 2, 2)];
        return [band('Ascenso', 'up', 1, 1), band('Play-off ascenso', 'po', 2, 2),
                band(t === 'C' ? 'Descenso o play-off' : 'Descenso', 'down', n, n)];
      },
    },
    // Concacaf Nations League: 9 grupos en tres ligas. Cada selección juega 4
    // partidos, NO el doble round-robin (los grupos de la Liga A son de seis).
    'concacaf-nations': {
      name: 'Concacaf Nations League', pHome: 0.44, pDraw: 0.26, simN: 20000,
      mpt: function () { return 4; },
      tier: function (nm) { return (nm.match(/League\s+([A-C])/i) || [])[1] || ''; },
      tierLabel: function (t) { return 'Liga ' + t; },
      groupLabel: function (nm) { return nm.replace(/^League\s+[A-C],\s*Group\s+/i, 'Grupo '); },
      bands: function (n, t) {
        if (t === 'A') return [band('Cuartos', 'up', 1, 2), band('Descenso', 'down', n - 1, n)];
        if (t === 'C') return [band('Ascenso', 'up', 1, 1), band('Posible ascenso', 'po', 2, 2)];
        return [band('Ascenso', 'up', 1, 1), band('Descenso', 'down', n, n)];
      },
    },
    // Clasificación para la Copa África 2027: 12 grupos de cuatro, pasan los dos
    // primeros. ESPN no sirve notas de zona en esta competición.
    'copa-africa-clasificacion': {
      name: 'Clasificación Copa África', pHome: 0.45, pDraw: 0.28, simN: 20000,
      groupLabel: function (nm) { return nm.replace(/^Group\s+/i, 'Grupo '); },
      bands: function (n) { return [band('Clasifica', 'up', 1, 2), band('Eliminada', 'down', 3, n)]; },
    },
    // Amistosos: ESPN no sirve clasificación (no hay tabla que simular). La
    // página es solo calendario y resultados; la pestaña de clasificación se
    // retira sola al no llegar ningún grupo.
    'amistosos': { name: 'Amistosos', pHome: 0.42, pDraw: 0.26, simN: 20000 },
  };

  var slug = window.PM_GROUPS_SLUG;
  var cfg = COMPS[slug];
  if (!cfg) return;
  var D = window.PMData, E = window.PMEngine;

  function esc(s) {
    return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }
  function initials(nm) { return String(nm || '').split(' ').slice(0, 2).map(function (w) { return w[0]; }).join('').toUpperCase(); }
  window.PMGroupsCrestFallback = function (img) {
    var box = img.parentNode; if (!box) return;
    box.classList.add('fallback');
    box.textContent = img.getAttribute('data-ab') || '?';
  };

  // Píldora de probabilidad del sistema de diseño (réplica de la de los
  // dashboards: mismas clases is-null / is-lock y mismo redondeo).
  function probPill(pct, kind, label) {
    var head = '<td class="col-prob"><span class="prob-label">' + esc(label) + '</span>';
    if (!pct || pct <= 0) return head + '<span class="prob ' + kind + ' is-null"><span class="prob__val">—</span></span></td>';
    var r = Math.round(pct), disp = (r === 0 && pct > 0) ? '&lt;1' : String(r);
    if (pct >= 99.5) return head + '<span class="prob ' + kind + ' is-lock"><span class="prob__val">' + disp + '<span class="pct">%</span></span></span></td>';
    var w = Math.max(2, Math.min(100, pct));
    return head + '<span class="prob ' + kind + '"><span class="prob__fill" style="width:' + w + '%"></span>'
      + '<span class="prob__val">' + disp + '<span class="pct">%</span></span></span></td>';
  }

  // ── Simulación de un grupo ────────────────────────────────────────────────
  // ¿Le quedan partidos al grupo? `mpt` declara los partidos por equipo cuando el
  // formato NO es el doble round-robin (la Liga A de Concacaf son grupos de seis
  // con 4 partidos cada uno).
  function isFinished(g) {
    var n = g.rows.length;
    var totalMd = (cfg.mpt && cfg.mpt(n, g.name)) || 2 * (n - 1);
    return { done: !g.rows.some(function (t) { return t.gp < totalMd; }), totalMd: totalMd };
  }
  // Grupo TERMINADO → NO se simula: las zonas salen del `rank` OFICIAL de ESPN
  // (100/0). Simularlo daría también 100/0 pero con NUESTRO desempate (pts→DG→GF),
  // que no es el de la competición (en la UEFA manda el enfrentamiento directo):
  // una selección empatada a puntos salía clasificada al 100% y 3ª en la tabla.
  function simGroup(g, st) {
    if (st.done || !E) return null;
    return E.simulate(g.rows, { pHome: cfg.pHome, pDraw: cfg.pDraw, simN: cfg.simN, totalMd: st.totalMd });
  }
  // % de que `t` acabe en la banda: del histograma si se ha simulado; de su
  // posición final real si el grupo ya ha terminado. Sin una cosa ni la otra (el
  // motor no cargó) la píldora se queda vacía — mejor que un 100% inventado.
  function bandPct(sim, done, t, b) {
    if (sim) return E.zoneProb(sim.posHist[t.name] || [], b.lo, b.hi, sim.simN);
    return done ? ((t.rank >= b.lo && t.rank <= b.hi) ? 100 : 0) : 0;
  }

  // ── Render ────────────────────────────────────────────────────────────────
  function groupHTML(g, i) {
    var t = cfg.tier ? cfg.tier(g.name) : '';
    var bands = cfg.bands ? cfg.bands(g.rows.length, t) : [];
    var st = isFinished(g);
    var sim = bands.length ? simGroup(g, st) : null;
    var label = cfg.groupLabel ? cfg.groupLabel(g.name) : g.name;

    var head = '<tr><th class="col-pos" scope="col">#</th><th class="col-team" scope="col">Selección</th>'
      + '<th class="col-pj" scope="col">PJ</th><th scope="col">Pts</th>'
      + bands.map(function (b) { return '<th class="col-prob" scope="col">' + esc(b.label) + '</th>'; }).join('')
      + '</tr>';

    var body = g.rows.map(function (r, ri) {
      var zone = '';
      bands.forEach(function (b) { if (!zone && r.rank >= b.lo && r.rank <= b.hi) zone = b.kind; });
      var ab = initials(r.name), id = 'gav' + i + '-' + ri;
      var crest = r.logo
        ? '<span class="team__crest-box" id="' + id + '"><img class="team__crest" src="' + esc(r.logo) + '" alt="'
          + esc(r.name) + '" loading="lazy" data-ab="' + esc(ab) + '" onerror="PMGroupsCrestFallback(this)"></span>'
        : '<span class="team__crest-box fallback" id="' + id + '">' + esc(ab) + '</span>';
      return '<tr' + (zone ? ' data-zone="' + zone + '"' : '') + '>'
        + '<td class="col-pos"><span class="pos-badge">' + r.rank + '</span></td>'
        + '<td class="col-team"><span class="team">' + crest
        + '<a class="team__name team-link" href="/equipo?id=' + encodeURIComponent(r.id)
        + '&name=' + encodeURIComponent(r.name) + '&league=' + encodeURIComponent(slug) + '">' + esc(r.name) + '</a>'
        + (r.live ? '<a class="live-dot-link" href="/partido?league=' + encodeURIComponent(slug) + '&id='
          + encodeURIComponent(r.live.eventId) + '" title="En juego" aria-label="En juego"><span class="live-dot '
          + r.live.res + '"></span></a>' : '')
        + '</span></td>'
        + '<td class="col-pj col-dim"><span class="num">' + r.gp + '</span></td>'
        + '<td class="col-pts' + (r.live ? ' pts-live' : '') + '"><span class="num">' + r.pts + '</span></td>'
        + bands.map(function (b) { return probPill(bandPct(sim, st.done, r, b), b.kind, b.label); }).join('')
        + '</tr>';
    }).join('');

    return '<section class="grp">'
      + '<h3 class="grp__title">' + esc(label) + (st.done ? ' <span class="grp__done">Fase terminada</span>' : '') + '</h3>'
      + '<div class="table-card"><div class="table-scroll">'
      + '<table class="table-clasif" aria-label="' + esc(label) + '"><thead>' + head + '</thead><tbody>' + body + '</tbody></table>'
      + '</div></div></section>';
  }

  function renderGroups(groups, season) {
    var mount = document.getElementById('groups');
    if (!mount) return;
    if (!groups.length) return;
    var html = '', lastTier = null;
    groups.forEach(function (g, i) {
      var t = cfg.tier ? cfg.tier(g.name) : '';
      if (t && t !== lastTier) { html += '<h2 class="grp-tier">' + esc(cfg.tierLabel(t)) + '</h2>'; lastTier = t; }
      html += groupHTML(g, i);
    });
    mount.innerHTML = html;

    // Jornada = partidos jugados por el grupo más adelantado.
    var md = 0;
    groups.forEach(function (g) { g.rows.forEach(function (r) { if (r.gp > md) md = r.gp; }); });
    var badge = document.getElementById('badge-jornada');
    if (badge) badge.textContent = md || '—';
    // Temporada/ciclo: lo que sirva ESPN, no lo que diga el HTML (Principio 2: la
    // página no hay que tocarla cuando cambia el ciclo).
    var sel = document.getElementById('league-season');
    if (sel && season) sel.textContent = season;

    // Animación de las barras, igual que en los dashboards.
    requestAnimationFrame(function () {
      setTimeout(function () {
        mount.querySelectorAll('.prob__fill').forEach(function (el) {
          var w = el.style.width;
          el.style.width = '0%';
          requestAnimationFrame(function () { el.style.transition = 'width 1.1s cubic-bezier(.16,1,.3,1)'; el.style.width = w; });
        });
      }, 60);
    });
  }

  // Sin clasificación en ESPN (amistosos): se retira la pestaña y su sección, y
  // la página abre directamente en los partidos.
  function dropStandingsTab() {
    var tab = document.querySelector('.page-tab[data-section="clasificacion"]');
    var sec = document.querySelector('.tab-section[data-section="clasificacion"]');
    if (tab) tab.remove();
    if (sec) sec.remove();
    var first = document.querySelector('.page-tab');
    var firstSec = document.querySelector('.tab-section');
    if (first) first.classList.add('active');
    if (firstSec) firstSec.hidden = false;
  }

  function liveStrip(fresh) {
    if (!D) return;
    D.scoreboard(slug, null, fresh).then(function (evs) {
      var live = (evs || []).map(function (e) { return D.parseEvent(e, slug); })
        .filter(function (m) { return m && m.state === 'in'; })
        .map(function (m) {
          return {
            eventId: m.id, clock: m.clock || m.detail || '',
            homeName: m.home.name, homeLogo: m.home.logo, homeScore: m.home.score == null ? 0 : m.home.score,
            awayName: m.away.name, awayLogo: m.away.logo, awayScore: m.away.score == null ? 0 : m.away.score,
          };
        });
      if (window.PMLiveStrip) window.PMLiveStrip.render('#live-strip', live, slug);
    });
  }

  // Calendario completo: se pide al abrir la pestaña (el de la temporada son 1-3
  // llamadas gordas a ESPN), igual que en los dashboards.
  function initFixtures() {
    var code = ((window.PM_LEAGUES || {})[slug] || {}).code;
    if (window.PMFixtures && code) window.PMFixtures.init(code, '#fx-mount');
  }

  function load() {
    var mount = document.getElementById('groups');
    if (!D) return;
    D.groupTables(slug).then(function (r) {
      if (!r.groups.length) { dropStandingsTab(); initFixtures(); return; }
      renderGroups(r.groups, r.season);
    }).catch(function () {
      if (mount) mount.innerHTML = '<div class="fx-empty">No se pudo cargar la clasificación.</div>';
    });
    liveStrip();
    // Mientras haya algo en juego, refrescar tablas y marcadores cada 60 s (mismo
    // criterio que los dashboards: sin directos, sin polling).
    setInterval(function () {
      if (!document.querySelector('#live-strip .lm')) return;
      liveStrip(true);
      D.groupTables(slug, true).then(function (r) { renderGroups(r.groups, r.season); });
    }, 60000);
  }

  function start() {
    if (window.PMTabs) window.PMTabs.init();
    window.addEventListener('pmtab', function (e) { if (e.detail === 'partidos') initFixtures(); });
    load();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start); else start();
})();
