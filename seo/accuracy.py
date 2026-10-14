"""`/acierto` — la página que puntúa al modelo contra lo que pasó de verdad.

Por qué existe: `seo/predictions.py` lleva desde agosto escribiendo cada 1X2
emitido en `data/<liga>/<season>/predictions.jsonl` y su desenlace en
`results.jsonl` — más de mil partidos resueltos, 21 ligas — y **no los leía
nadie**. `/acerca` ni siquiera mencionaba la palabra calibración. Ningún sitio
de predicciones en español publica su propio Brier, así que el expediente del
modelo es a la vez lo más honesto y lo más difícil de copiar que tiene el sitio.

**Solo se puntúa el modelo que está en producción (`model == "v3"`).** Las
filas con `model` `uniform` son el modo degenerado de pretemporada (todos los
equipos iguales: no es el modelo, es su ausencia), las `v2` son de un modelo
retirado y las que no llevan campo `model` son anteriores a que se registrara
y de procedencia incierta — ver `seo/quarantine_v1_predictions.py`, que ya
apartó un lote de filas que ningún modelo del sitio calculó. Mezclarlas
inflaría o hundiría la nota sin que signifique nada. El filtro está en
`MODEL`: cuando entre un v4, se cambia ahí y la página pasa a contar su
historial desde cero, que es lo correcto.

Las predicciones se congelan `PREDICTION_LEAD_DAYS` (8) días antes del
partido y el fichero es append-only: no se puede reescribir una predicción a
toro pasado, que es lo que hace creíble la cifra.

Corre dentro del cron SEO de 3 h (`seo/generate_site.py`), sin estado propio:
se recalcula entero leyendo los jsonl, igual que el sitemap.

Ver [[docs/seo]] · [[docs/modelo]].
"""

import glob
import json
import os
from pathlib import Path

from .chrome import crumbs, esc, page
from .config import DATA_DIR, SITE, league_by_slug
from .predictions import PREDICTION_LEAD_DAYS
from .textutil import num, pct as _pct_0_100


def pct(fraction):
    """`textutil.pct` formatea 0-100 y aquí TODO son fracciones 0-1 (brier,
    skill, aciertos, tramos). Un solo adaptador en vez de un `* 100` en cada
    uno de los siete sitios, que es donde se cuela el error."""
    return _pct_0_100(fraction * 100)


URL = "/acierto"
FILE = "acierto.html"
MODEL = "v3"
OUTCOMES = {"home": "p_home", "draw": "p_draw", "away": "p_away"}
# Brier multiclase de predecir 1/3 a todo, que es lo que puede hacer cualquiera
# sin modelo. Es el único baseline honesto: sin él, "0,63" no dice nada.
BASELINE = 3 * (1 / 3) ** 2 - 2 * (1 / 3) + 1   # = 2/3
MIN_LEAGUE_N = 15       # por debajo, la cifra por liga es ruido y no se lista
MIN_BIN_N = 10          # ídem por tramo: con 2 casos, un 50% no dice nada
BINS = 10               # tramos de 10 pp para la curva de fiabilidad


def _load():
    """{(liga, event_id): (prediccion, resultado)} de los partidos ya resueltos
    y emitidos por el modelo en producción."""
    preds = {}
    for f in glob.glob(str(DATA_DIR / "*" / "*" / "predictions.jsonl")):
        for line in _lines(f):
            if line.get("model") == MODEL:
                preds[(line["league"], line["event_id"])] = line
    out = {}
    for f in glob.glob(str(DATA_DIR / "*" / "*" / "results.jsonl")):
        liga = Path(f).parent.parent.name
        for line in _lines(f):
            key = (liga, line["event_id"])
            p = preds.get(key)
            if p and all(p.get(v) is not None for v in OUTCOMES.values()):
                out[key] = (p, line)
    return out


def _lines(path):
    """Una línea corrupta no debe tumbar el cron: el fichero es append-only y
    un write a medias deja la última línea partida."""
    try:
        with open(path, encoding="utf-8") as fh:
            for raw in fh:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    yield json.loads(raw)
                except ValueError:
                    continue
    except OSError:
        return


def _brier(probs, result):
    return sum((probs[o] - (1.0 if o == result else 0.0)) ** 2 for o in probs)


def score(pairs=None):
    """Nota global, por liga y curva de fiabilidad. Sin red ni estado."""
    pairs = _load() if pairs is None else pairs
    by_league = {}
    bins = [{"n": 0, "pred": 0.0, "hits": 0} for _ in range(BINS)]
    total = {"n": 0, "brier": 0.0, "hits": 0}
    first = last = None

    for (liga, _), (p, r) in sorted(pairs.items()):
        probs = {o: p[v] for o, v in OUTCOMES.items()}
        b = _brier(probs, r["result"])
        hit = max(probs, key=probs.get) == r["result"]
        total["n"] += 1
        total["brier"] += b
        total["hits"] += hit
        lg = by_league.setdefault(liga, {"n": 0, "brier": 0.0, "hits": 0})
        lg["n"] += 1
        lg["brier"] += b
        lg["hits"] += hit
        for o, pr in probs.items():
            # min(..., BINS-1) mete el 100% exacto en el último tramo en vez de
            # desbordar el índice.
            s = bins[min(int(pr * BINS), BINS - 1)]
            s["n"] += 1
            s["pred"] += pr
            s["hits"] += (o == r["result"])
        k = p.get("kickoff")
        if k:
            first = k if first is None or k < first else first
            last = k if last is None or k > last else last

    def avg(d):
        return {"n": d["n"], "brier": d["brier"] / d["n"], "hit": d["hits"] / d["n"]} \
            if d["n"] else {"n": 0, "brier": None, "hit": None}

    return {
        "total": avg(total),
        "skill": (1 - (total["brier"] / total["n"]) / BASELINE) if total["n"] else None,
        "leagues": {k: avg(v) for k, v in by_league.items()},
        "bins": [{"lo": i / BINS, "hi": (i + 1) / BINS, "n": s["n"],
                  "pred": s["pred"] / s["n"], "real": s["hits"] / s["n"]}
                 for i, s in enumerate(bins) if s["n"]],
        "first": first, "last": last,
    }


# ── Render ──────────────────────────────────────────────────────────────────

def _stat(value, label, cls, fill=None):
    """Tarjeta de cifra reusando el CSS `.stat` de chrome.py. No se usa
    `chrome.stat_card` porque ese formatea SIEMPRE como porcentaje (`pct`) y
    aquí dos de las tres cifras no lo son: el Brier y el recuento de partidos.
    `fill` (0-100) es la barra inferior; sin ella, no se pinta."""
    u = f'<div class="u" style="width:{min(max(fill, 0), 100):.1f}%"></div>' if fill is not None else ""
    return (f'<div class="stat {cls}"><div class="v">{esc(value)}</div>'
            f'<div class="l">{esc(label)}</div>{u}</div>')


def _bar(value, color):
    w = max(2, round(value * 100))
    return (f'<div style="height:6px;border-radius:3px;background:#1f2636;overflow:hidden">'
            f'<div style="height:6px;width:{w}%;border-radius:3px;background:{color}"></div></div>')


def _calibration_table(bins):
    rows = ""
    for b in bins:
        # Los tramos extremos acumulan poquísimos casos (el modelo rara vez
        # anuncia 85%): pintarlos daría un "50% real" con n=2 que parece un
        # fallo de calibración y solo es ruido muestral.
        if b["n"] < MIN_BIN_N:
            continue
        gap = b["real"] - b["pred"]
        # Verde cuando lo prometido y lo ocurrido casan dentro de 5 pp. Es el
        # criterio que define "calibrado", no el acierto.
        color = "#00c97a" if abs(gap) <= 0.05 else "#f5a623"
        rows += (f'<tr><td>{b["lo"]:.0%} – {b["hi"]:.0%}</td>'
                 f'<td class="r muted">{b["n"]}</td>'
                 f'<td class="r">{pct(b["pred"])}</td>'
                 f'<td class="r ptsv">{pct(b["real"])}</td>'
                 f'<td style="min-width:120px">{_bar(b["real"], color)}</td></tr>')
    return ('<div class="table-scroll"><table><thead><tr>'
            '<th>Probabilidad anunciada</th><th class="r">Casos</th>'
            '<th class="r">Media anunciada</th><th class="r">Ocurrió</th><th></th>'
            '</tr></thead><tbody>' + rows + '</tbody></table></div>')


def _leagues_table(leagues):
    rows = ""
    for slug, d in sorted(leagues.items(), key=lambda kv: -kv[1]["n"]):
        if d["n"] < MIN_LEAGUE_N:
            continue
        lg = league_by_slug(slug)
        name = lg["name"] if lg else slug
        href = lg["dashboard"] if lg else None
        cell = f'<a class="tname" href="{href}">{esc(name)}</a>' if href else esc(name)
        rows += (f'<tr><td>{cell}</td><td class="r muted">{d["n"]}</td>'
                 f'<td class="r">{num(d["brier"], 3)}</td>'
                 f'<td class="r ptsv">{pct(d["hit"])}</td></tr>')
    if not rows:
        return ""
    return ('<div class="table-scroll"><table><thead><tr><th>Competición</th>'
            '<th class="r">Partidos</th><th class="r">Brier</th>'
            '<th class="r">Favorito acertado</th></tr></thead><tbody>'
            + rows + '</tbody></table></div>')


def render(data=None):
    """(ruta_fichero, html). None si aún no hay partidos puntuables."""
    d = score() if data is None else data
    t = d["total"]
    if not t["n"]:
        return None

    skill_txt = pct(abs(d["skill"]))
    mejor = "mejor" if d["skill"] > 0 else "peor"
    cards = ('<div class="stat-grid">'
             # La barra del Brier es el skill: lo que recorta sobre el reparto
             # ciego. Que salga corta es el dato, no un fallo de diseño.
             + _stat(pct(t["hit"]), "Favorito acertado", "green", t["hit"] * 100)
             + _stat(num(t["brier"], 3), f"Brier · azar = {num(BASELINE, 3)}", "blue",
                     max(d["skill"], 0) * 100)
             + _stat(str(t["n"]), "Partidos puntuados", "violet")
             + '</div>')

    lede = (f'<p class="lede">Cada predicción 1X2 que publica PredictMotion se guarda '
            f'<b>{PREDICTION_LEAD_DAYS} días antes</b> del partido y ya no se puede tocar. '
            f'Cuando el partido acaba, se apunta lo que pasó. Esta página es el recuento: '
            f'<b>{t["n"]} partidos</b> ya resueltos'
            + (f' entre el {esc(d["first"])} y el {esc(d["last"])}' if d["first"] else '')
            + '.</p>')

    explica = (
        f'<p>El <b>Brier</b> mide el error: 0 sería acertar siempre con total seguridad, '
        f'y <b>{num(BASELINE, 3)}</b> es lo que saca quien reparte un tercio a cada '
        f'resultado sin mirar. El modelo marca <b>{num(t["brier"], 3)}</b>, un '
        f'<b>{skill_txt} {mejor}</b> que ese reparto ciego. Es una ventaja real pero '
        f'modesta, y así se publica: el fútbol es ruidoso y cualquiera que prometa '
        f'mucho más está midiendo mal.</p>'
        f'<p>Lo que de verdad importa en un pronóstico no es acertar más, es que un '
        f'<b>60% signifique 60%</b>. Eso es la tabla de abajo: a la izquierda lo que '
        f'anunció el modelo, a la derecha lo que ocurrió. Los tramos con menos de '
        f'{MIN_BIN_N} casos no se listan: con esa muestra, el porcentaje real es '
        f'ruido.</p>')

    metodo = (
        '<h2>Cómo se calcula</h2>'
        '<ul>'
        '<li>Se puntúan solo las predicciones del modelo que está en producción. Las de '
        'modelos retirados y las de pretemporada (cuando aún no hay datos y todos los '
        'equipos salen iguales) quedan fuera: contarlas maquillaría el resultado.</li>'
        f'<li>El registro es <b>append-only</b> y la predicción se congela {PREDICTION_LEAD_DAYS} días antes '
        'del partido. No se puede reescribir a toro pasado.</li>'
        '<li>El resultado lo pone la API pública de ESPN al terminar el encuentro.</li>'
        '<li>El Brier multiclase suma el error de las tres opciones (1, X y 2), así que va '
        f'de 0 a 2 y el reparto ciego vale {num(BASELINE, 3)}.</li>'
        '<li>La tabla se rehace entera en cada actualización, cada tres horas.</li>'
        '</ul>'
        '<p class="muted">Más sobre el modelo en <a href="/acerca">cómo funciona</a>.</p>')

    ligas = _leagues_table(d["leagues"])
    ligas_html = (f'<h2>Por competición</h2>'
                  f'<p class="muted">Solo las que llevan al menos {MIN_LEAGUE_N} partidos '
                  f'resueltos; con menos, la cifra es ruido.</p>{ligas}') if ligas else ""

    body = (
        crumbs([("Inicio", "/"), ("¿Acierta el modelo?", None)])
        + '<div class="card"><div class="card-pad">' + lede + '</div>'
        + cards
        + f'<div class="card-pad">{explica}</div>'
        + _calibration_table(d["bins"])
        + '</div>'
        + (f'<div class="card"><div class="card-pad">{ligas_html}</div></div>' if ligas_html else "")
        + f'<div class="card"><div class="card-pad">{metodo}</div></div>'
    )

    title = "¿Acierta el modelo? · Brier y calibración · PredictMotion"
    desc = (f'Expediente público del modelo de PredictMotion: Brier de {num(t["brier"], 3)} '
            f'y {pct(t["hit"])} de acierto en el favorito sobre {t["n"]} partidos ya '
            f'resueltos, con la curva de fiabilidad completa.')
    ld = {
        "@context": "https://schema.org", "@type": "Dataset",
        "name": "Precisión y calibración del modelo de PredictMotion",
        "description": desc, "url": SITE + URL,
        "creator": {"@type": "Organization", "name": "PredictMotion"},
        "license": "https://predictmotion.com/acerca",
        "variableMeasured": ["Brier score", "Acierto del favorito", "Curva de fiabilidad"],
    }
    if d["first"]:
        ld["temporalCoverage"] = f'{d["first"]}/{d["last"]}'
    return FILE, page(title, desc, URL, body, heading="¿Acierta el modelo?",
                      badge="Calibración", json_ld=[ld])


# ── Comprobación ────────────────────────────────────────────────────────────

def _self_check():
    """Lo no trivial es el scoring: que el Brier y los tramos midan lo que dicen."""
    def pair(ph, pd, pa, res, liga="laliga", eid="1", kick="2026-09-01"):
        return ((liga, eid), ({"league": liga, "event_id": eid, "model": MODEL,
                               "kickoff": kick, "p_home": ph, "p_draw": pd, "p_away": pa},
                              {"event_id": eid, "result": res}))

    # Un acierto perfecto: Brier 0, skill máximo.
    d = score(dict([pair(1.0, 0.0, 0.0, "home")]))
    assert d["total"]["brier"] == 0.0 and d["total"]["hit"] == 1.0, d
    assert abs(d["skill"] - 1.0) < 1e-9, d["skill"]

    # El reparto ciego debe dar EXACTAMENTE el baseline y skill 0 — si esto se
    # rompe, la frase "un X% mejor que el azar" de la página miente.
    d = score(dict([pair(1 / 3, 1 / 3, 1 / 3, "draw")]))
    assert abs(d["total"]["brier"] - BASELINE) < 1e-12, d["total"]["brier"]
    assert abs(d["skill"]) < 1e-12, d["skill"]

    # Fallo total: Brier 2 (el máximo), skill negativo.
    d = score(dict([pair(0.0, 0.0, 1.0, "home")]))
    assert abs(d["total"]["brier"] - 2.0) < 1e-9, d["total"]["brier"]
    assert d["skill"] < 0

    # Tramos: p=0.6 cae en 60-70 y p=1.0 en el último (no desborda el índice).
    d = score(dict([pair(0.6, 0.2, 0.2, "home"), pair(1.0, 0.0, 0.0, "home", eid="2")]))
    lo = {round(b["lo"], 1) for b in d["bins"]}
    assert 0.6 in lo and 0.9 in lo, lo
    assert sum(b["n"] for b in d["bins"]) == 6, d["bins"]   # 2 partidos × 3 opciones

    # Agregación por liga y rango de fechas.
    d = score(dict([pair(0.5, 0.3, 0.2, "home", liga="laliga", eid="1", kick="2026-09-01"),
                    pair(0.5, 0.3, 0.2, "away", liga="premier", eid="2", kick="2026-10-05")]))
    assert d["leagues"]["laliga"]["n"] == 1 and d["leagues"]["premier"]["n"] == 1
    assert d["first"] == "2026-09-01" and d["last"] == "2026-10-05"

    # Sin datos: render devuelve None en vez de publicar una página vacía.
    assert render(score({})) is None

    # Una línea corrupta no debe reventar la lectura.
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as fh:
        fh.write('{"a":1}\n{roto\n\n{"a":2}\n')
        tmp = fh.name
    assert [x["a"] for x in _lines(tmp)] == [1, 2]
    os.unlink(tmp)
    assert list(_lines("/no/existe.jsonl")) == []
    print("ok: scoring, tramos, baseline y lectura tolerante")


if __name__ == "__main__":
    import sys
    if "--self-check" in sys.argv:
        _self_check()
    else:
        d = score()
        print(json.dumps({"total": d["total"], "skill": d["skill"],
                          "bins": d["bins"], "first": d["first"], "last": d["last"]},
                         indent=1, ensure_ascii=False))
