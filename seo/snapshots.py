"""Snapshots: construcción, persistencia y series históricas.

Un snapshot = estado de probabilidades de una liga en una fecha. Se guarda uno
por día (se sobreescribe el del mismo día). El histórico crece de forma
orgánica jornada a jornada; no se inventa nada del pasado.
"""

import json
import os
from datetime import datetime, timezone
from html import escape
from urllib.parse import quote

from .config import DATA_DIR, STRENGTH_SCALE, STRENGTH_FADE_FRACTION
from .sim_table import zone_prob, resolve_strengths
from .textutil import slugify


# ── Construcción ────────────────────────────────────────────────────────────

def derive_bands_from_notes(bands, rows):
    """Deriva lo/hi de cada banda desde las notas de zona de ESPN, replicando
    deriveSlots() del dashboard: caminata CONTIGUA desde la cabeza para las zonas
    de arriba (una plaza no contigua —p. ej. la de Copa del Rey que ESPN marca a
    media tabla— no ensancha el rango) y desde el fondo para el descenso. Cada
    banda se empareja por su `zone`. Si una zona no tiene notas (inicio de
    temporada), la banda conserva su lo/hi de fallback. Muta `bands` y lo devuelve.
    """
    by_rank = sorted(rows, key=lambda r: r["rank"])
    n = len(by_rank)
    zone_of = [r.get("zone", "none") for r in by_rank]   # índice 0 = rank 1
    cursor = 0
    for b in bands:                                        # zonas de arriba, en orden
        if not b.get("zone") or b["zone"] == "relega":
            continue
        start = cursor
        while cursor < n and zone_of[cursor] == b["zone"]:
            cursor += 1
        if cursor > start:                                # hubo notas para esta zona
            b["lo"], b["hi"] = start + 1, cursor
    releg = next((b for b in bands if b.get("zone") == "relega"), None)
    if releg is not None:
        cnt, j = 0, n - 1
        while j >= 0 and zone_of[j] == "relega":
            cnt += 1; j -= 1
        if cnt > 0:
            releg["lo"], releg["hi"] = n - cnt + 1, n
    return bands


def build_table_snapshot(league, rows, sim, sim_n, today, league_logo=None,
                         season=None, ratings=None):
    n = len(rows)
    bands = league["bands"](n)
    if league.get("bands_from_notes"):
        bands = derive_bands_from_notes(bands, rows)
    jornada = max(r["gp"] for r in rows)
    # matches_per_team: formatos que no son round-robin (fase de liga UEFA: 36
    # equipos, 8 partidos). None → doble vuelta de siempre.
    total_md = league.get("matches_per_team") or 2 * (n - 1)

    # Fuerza por equipo (misma resolución que la sim) para que el fallback JS de
    # los dashboards aplique el mismo prior sin re-derivarlo. None → no se guarda.
    strengths = resolve_strengths(rows, ratings)

    teams = []
    for r in rows:
        res = sim[r["name"]]
        prob = {}
        for b in bands:
            prob[b["key"]] = zone_prob(res["pos_hist"], b["lo"], b["hi"], sim_n)
        # Prob. de título (acabar 1º): la pinta el dashboard de LaLiga (píldora
        # "Título") y no coincide con ninguna banda (Champions es 1-4). Inofensiva
        # para las ligas que no la muestran.
        prob["first"] = zone_prob(res["pos_hist"], 1, 1, sim_n)
        if league.get("playoff_top"):
            prob["pSemi"] = res["pSemi"]
            prob["pFinal"] = res["pFinal"]
            prob["pWin"] = res["pWin"]
        team = {
            "slug":   slugify(r["name"]),
            "rank":   r["rank"],
            "id":     r["id"],
            "name":   r["name"],
            "logo":   r["logo"],
            "gp":     r["gp"], "pts": r["pts"],
            "gf":     r["gf"], "gc": r["gc"],
            "wins":   r["wins"], "draws": r["draws"], "losses": r["losses"],
            "prob":   prob,
        }
        if strengths is not None:
            team["strength"] = round(strengths[r["id"]], 4)
        teams.append(team)

    snap = {
        "league":   league["slug"],
        "kind":     "table",
        "name":     league["name"],
        "season":   season or league["season"],
        "date":     today,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "league_logo": league_logo,
        "jornada":  jornada,
        "total_md": total_md,
        "num_teams": n,
        "finished": all(sim[r["name"]]["finished"] for r in rows),
        "bands":    bands,
        "has_playoff": bool(league.get("playoff_top")),
        "teams":    teams,
    }
    # Parámetros del prior de fuerza para que el fallback JS aplique la MISMA
    # fórmula (solo si hay fuerzas; si no, el fallback usa el modelo uniforme).
    if strengths is not None:
        snap["strength_scale"] = STRENGTH_SCALE
        snap["strength_fade_fraction"] = STRENGTH_FADE_FRACTION
    # Filas de tabla servidas sin JS (Caddy inyecta rows.html en el tbody).
    snap["rows_html"] = render_rows_html(league, snap)
    return snap


# ── Filas de tabla servidas (SEO sin JavaScript) ─────────────────────────────
# Replica el `render()` de los dashboards (mismo markup de <tr>, mismas clases
# de píldora, mismo data-zone) para que la clasificación sea VÁLIDA para crawlers
# SIN JS. El cron escribe las filas en `data/<slug>/rows.html` (gitignored) y
# Caddy las inyecta en `<tbody id="tbody">` vía `templates` ({{readFile}}). Los
# valores salen del snapshot, así que cuadran con el precálculo que lee el JS.

# Paleta de fallback de escudo por plantilla (COLOR_PALETTE de cada dashboard).
_PALETTES = {
    "top1": ['#e11d48', '#7c3aed', '#2563eb', '#0891b2', '#059669', '#ca8a04', '#ea580c',
             '#db2777', '#4f46e5', '#0284c7', '#16a34a', '#d97706', '#dc2626', '#9333ea',
             '#0369a1', '#15803d', '#b45309', '#be185d', '#6d28d9', '#0e7490'],
    "top2": ['#e11d48', '#7c3aed', '#2563eb', '#0891b2', '#059669', '#ca8a04', '#ea580c',
             '#db2777', '#4f46e5', '#0284c7', '#16a34a', '#d97706', '#dc2626', '#9333ea',
             '#0369a1', '#15803d', '#b45309', '#be185d', '#6d28d9', '#0e7490', '#166534', '#92400e'],
}

# Columnas de probabilidad por plantilla: (clave del prob del snapshot, clase de
# la píldora, etiqueta). Mismo orden que los ${probPill(...)} del render() JS.
_PILLS = {
    "top1": [("first", "gold", "Título"),
             ("champions", "up", "Champions"),
             ("europa", "eu", "Europa"),
             ("conference", "cf", "Conference"),
             ("descenso", "down", "Descenso")],
    "top2": [("ascenso", "up", "Ascenso"),
             ("playoff", "po", "Play-off"),
             ("descenso", "down", "Descenso")],
    "tier2": [("ascenso", "up", "Ascenso"),
              ("playoff", "po", "Play-off"),
              ("descenso", "down", "Descenso")],
    "uefa": [("octavos", "up", "Octavos"),
             ("playoff", "po", "Play-off"),
             ("eliminado", "down", "Eliminado")],
}

_ZONE_DATA = {"promo": "up", "playoff": "po", "europa": "eu", "conf": "cf", "relega": "down"}
# Zona por índice de banda cuando la banda no trae `zone` (Hypermotion: zonas
# fijas, sin notas de ESPN). Misma lógica que zoneOf() del dashboard.
_BAND_ZONE_BY_INDEX = ("promo", "playoff", "relega")


def _prob_pill(pct, kind, label):
    """Réplica de probPill() del dashboard: misma marca para píldora vacía,
    bloqueada (>=99.5) o con barra. Sin JS, sin animación (solo el HTML)."""
    if not pct or pct <= 0:
        return (f'<td class="col-prob"><span class="prob-label">{label}</span>'
                f'<span class="prob {kind} is-null"><span class="prob__val">—</span></span></td>')
    lock = pct >= 99.5
    r = int(pct + 0.5)                       # Math.round() (positivos)
    disp = '&lt;1' if (r == 0 and pct > 0) else str(r)
    if lock:
        return (f'<td class="col-prob"><span class="prob-label">{label}</span>'
                f'<span class="prob {kind} is-lock"><span class="prob__val">{disp}'
                f'<span class="pct">%</span></span></span></td>')
    w = max(2, min(100, pct))
    return (f'<td class="col-prob"><span class="prob-label">{label}</span>'
            f'<span class="prob {kind}"><span class="prob__fill" style="width:{w}%"></span>'
            f'<span class="prob__val">{disp}<span class="pct">%</span></span></span></td>')


def render_rows_html(league, snap):
    """HTML de las <tr> de la clasificación tal como las pintaría render() del
    dashboard (sin badge de en vivo: el fragmento es el estado del precálculo).
    Sin equipos (snapshot de offseason) devuelve '' → tbody vacío."""
    template = league.get("dashboard_template", "top2")
    pills = _PILLS.get(template)
    palette = _PALETTES.get(template, _PALETTES["top2"])
    slug = league["slug"]
    teams = sorted(snap.get("teams", []), key=lambda t: t["rank"])
    if not teams:
        return ""
    bands = sorted(snap.get("bands", []), key=lambda b: (b["lo"], b["hi"]))

    def zone_of(rank):
        for idx, b in enumerate(bands):
            if b["lo"] <= rank <= b["hi"]:
                return b.get("zone") or _BAND_ZONE_BY_INDEX[min(idx, len(_BAND_ZONE_BY_INDEX) - 1)]
        return None

    rows = []
    for i, t in enumerate(teams):
        rank = t["rank"]
        z = zone_of(rank)
        dz = f' data-zone="{_ZONE_DATA[z]}"' if z in _ZONE_DATA else ""
        name_html = escape(str(t["name"]))
        name_esc = str(t["name"]).replace("'", "\\'")
        name_enc = quote(str(t["name"]), safe="")
        color = palette[i % len(palette)]
        logo = escape(t.get("logo") or "", quote=True)
        prob = t.get("prob") or {}
        pills_html = "".join(
            "\n      " + _prob_pill(prob.get(key, 0) or 0, kind, label)
            for key, kind, label in pills
        )
        rows.append(
            f'<tr{dz}>\n'
            f'      <td class="col-pos"><span class="pos-badge">{rank}</span></td>\n'
            f'      <td class="col-team">\n'
            f'        <span class="team">\n'
            f'          <span class="team__crest-box" id="av{i}">\n'
            f'            <img class="team__crest" src="{logo}" alt="{name_html}" loading="lazy"\n'
            f'              onerror="fallbackAvatar({i},\'{name_esc}\',\'{color}\')" />\n'
            f'          </span>\n'
            f'          <a class="team__name team-link" href="/equipo?id={t["id"]}&name={name_enc}&league={slug}">{name_html}</a>\n'
            f'          \n'
            f'        </span>\n'
            f'      </td>\n'
            f'      <td class="col-pj col-dim"><span class="num">{t["gp"]}</span></td>\n'
            f'      <td class="col-pts"><span class="num">{t["pts"]}</span></td>\n'
            f'{pills_html}\n'
            f'    </tr>'
        )
    return "\n".join(rows)


# ── Persistencia ────────────────────────────────────────────────────────────
# Los snapshots se PARTICIONAN por temporada: data/<slug>/<season>/snapshots/.
# Así el histórico/evolución de una temporada no se mezcla con el de otra (2025-26
# jornada 38 vs 2026-27 jornada 0). El `latest.json` de la temporada viva se
# mantiene ADEMÁS en la raíz data/<slug>/latest.json — ese es el contrato que leen
# los dashboards (/data/<slug>/latest.json), no se toca.

def _season_dir(slug, season):
    d = DATA_DIR / slug / season
    (d / "snapshots").mkdir(parents=True, exist_ok=True)
    return d


def _write_atomic(path, text):
    """Escritura atómica (tmp + rename) para que lectores concurrentes (Caddy
    templates, fetch de los dashboards) nunca vean el fichero a medias."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def save_snapshot(snap):
    d = _season_dir(snap["league"], snap["season"])
    path = d / "snapshots" / f"{snap['date']}.json"
    payload = json.dumps(snap, ensure_ascii=False, indent=1)
    _write_atomic(path, payload)
    _write_atomic(d / "latest.json", payload)                # latest de la temporada
    _write_atomic(DATA_DIR / snap["league"] / "latest.json", payload)  # latest vivo (dashboards)
    _write_atomic(DATA_DIR / snap["league"] / "rows.html", snap.get("rows_html", ""))
    return path


def save_offseason_latest(slug, snap):
    """Escribe SOLO el latest.json raíz (contrato de los dashboards) con un snapshot
    de temporada fuera de temporada (offseason). No crea histórico por temporada:
    la competición que viene aún no existe en ESPN, así que no hay nada que archivar
    ni de qué llevar histórico. Sustituye a la tabla congelada de la temporada
    anterior (Principio 1: una competición terminada no se congela)."""
    (DATA_DIR / slug).mkdir(parents=True, exist_ok=True)
    payload = json.dumps(snap, ensure_ascii=False, indent=1)
    _write_atomic(DATA_DIR / slug / "latest.json", payload)
    # rows.html VACÍO (o el tbody serviría la tabla de la temporada acabada).
    _write_atomic(DATA_DIR / slug / "rows.html", snap.get("rows_html", ""))


def load_all(slug, season):
    """Snapshots de UNA temporada de una liga, ordenados por fecha ascendente."""
    d = DATA_DIR / slug / season / "snapshots"
    if not d.exists():
        return []
    snaps = []
    for f in sorted(d.glob("*.json")):
        try:
            snaps.append(json.loads(f.read_text(encoding="utf-8")))
        except Exception:
            continue
    return snaps


def per_period_series(snaps, key):
    """Un snapshot por periodo (jornada/matchday): el último de cada valor.

    Devuelve lista [(periodo, snapshot)] ordenada por periodo ascendente.
    """
    by_period = {}
    for s in snaps:
        by_period[s[key]] = s  # el último visto (orden por fecha) gana
    return [(p, by_period[p]) for p in sorted(by_period)]
