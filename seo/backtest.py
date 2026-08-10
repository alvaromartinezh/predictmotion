"""Backtest de calibración OFFLINE (Fase 4). NUNCA se ejecuta en el cron.

Objetivo: medir si un prior de fuerza distinto (o el arreglo del empate) predice
MEJOR los resultados reales, ANTES de tocar el modelo en producción. No escribe
nada en el sitio; solo lee de ESPN (con caché en disco) e imprime métricas.

Método (retrodicción honesta, solo con datos ya completados):
  Para cada temporada pasada S y liga:
    1. Se construye el prior con la tabla FINAL de S-1 (como haría el cron en
       pretemporada de S).
    2. Se recorren TODOS los partidos de S en orden cronológico. Para cada uno se
       emite el 1X2 del modelo (con el prior + desvanecimiento vigentes en esa
       jornada) ANTES de saber el resultado, y se puntúa contra el resultado REAL.
  Métricas: Brier multiclase, log-loss y fiabilidad (ECE). Menor Brier/log-loss y
  menor ECE = mejor calibración.

Dos ejes que se comparan (el modelo VIVO es zscore + kappa=0):
  - rating: 'zscore' (z de puntos por división, el actual) vs 'absolute' (dif. de
    goles por partido, sin normalizar por liga → conserva la escala de dominancia).
  - kappa: encoge la prob. de empate al crecer |Δfuerza| (kappa=0 = empate fijo, el
    bug actual). kappa>0 = arreglo del empate.

Uso:
  python -m seo.backtest                 # compara modelo actual vs propuesto
  python -m seo.backtest --grid          # rejilla de (scale,kappa,level_gap)
  python -m seo.backtest --titles        # P(título) pretemporada vs mercado (sanity)
"""

import argparse
import json
import math
from datetime import datetime
from pathlib import Path

from . import espn
from .config import (STRENGTH_LADDERS, STRENGTH_SCALE, STRENGTH_LEVEL_GAP,
                     STRENGTH_FADE_FRACTION, DATA_DIR, league_by_slug, LEAGUES)
from .sim_table import fade_weight

# ── Caché en disco (data/_backtest_cache, gitignored) para iterar sin re-pegar a ESPN ──
_CACHE = DATA_DIR / "_backtest_cache"


def _cache_json(key, producer):
    _CACHE.mkdir(parents=True, exist_ok=True)
    p = _CACHE / (key + ".json")
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    val = producer()
    p.write_text(json.dumps(val, ensure_ascii=False), encoding="utf-8")
    return val


def table_cached(code, season):
    return _cache_json(f"table_{code}_{season}", lambda: espn.fetch_table(code, season=season))


def matches_cached(code, season_start):
    # Ventana de temporada europea: agosto de season_start → junio del año siguiente.
    a, b = f"{season_start}0801", f"{season_start + 1}0630"
    return _cache_json(f"matches_{code}_{season_start}",
                       lambda: espn.fetch_scoreboard_range(code, a, b))


# ── Priors de fuerza (dos esquemas) ──────────────────────────────────────────
def ladder_for(code):
    for lad in STRENGTH_LADDERS:
        if code in lad:
            return lad
    return [code]


def build_ratings(code, prev_season, scheme, level_gap):
    """{team_id: R} desde la tabla final de prev_season para toda la escalera del país."""
    ratings = {}
    for level, c in enumerate(ladder_for(code)):
        try:
            rows = table_cached(c, prev_season)
        except Exception:
            continue
        if len(rows) < 2:
            continue
        if scheme == "zscore":
            pts = [r["pts"] for r in rows]
            mean = sum(pts) / len(pts)
            std = (sum((p - mean) ** 2 for p in pts) / len(pts)) ** 0.5
            for r in rows:
                z = (r["pts"] - mean) / std if std > 0 else 0.0
                ratings[r["id"]] = z - level * level_gap
        elif scheme == "absolute":
            # Diferencia de goles por partido: medida ~absoluta de dominancia, NO
            # normalizada por la varianza de la liga (por eso conserva la ventaja de
            # los equipos que arrasan, que el z-score aplasta). Offset de nivel por
            # división en las MISMAS unidades (goles/partido).
            for r in rows:
                gp = max(r["gp"], 1)
                gdpg = (r["gf"] - r["gc"]) / gp
                ratings[r["id"]] = gdpg - level * level_gap
    return ratings


def _match_day(e):
    return datetime.strptime((e["kickoff"] or e["date"])[:10], "%Y-%m-%d").toordinal()


def build_ratings_recency(code, prev_season, level_gap, half_life_days):
    """Rating 'absolute' pero desde los PARTIDOS de prev_season con decaimiento de
    recencia, no desde el agregado de la tabla final.

    R(equipo) = media de diferencia de goles por partido PONDERADA por recencia:
    cada partido pesa 0.5**(edad_en_días / half_life_days) respecto al último
    partido de esa temporada. Así el nivel de FINAL de temporada (forma real
    reciente) pesa más que el arranque. Mismos datos que ya bajamos
    (matches_cached); mismas unidades (goles/partido) → el offset de nivel por
    división (level_gap) es idéntico al del esquema 'absolute'.

    half_life_days = math.inf → peso uniforme = MEDIA de GDPG por partido, que es
    exactamente el GDPG agregado de la tabla → ancla de paridad con el 'absolute'
    actual (salvo partidos aplazados que la tabla y el scoreboard cuenten distinto).
    """
    ratings = {}
    for level, c in enumerate(ladder_for(code)):
        try:
            evs = [e for e in matches_cached(c, prev_season)
                   if e["state"] == "post" and e["home_score"] is not None]
        except Exception:
            continue
        if len(evs) < 2:
            continue
        ref = max(_match_day(e) for e in evs)
        wsum, wgd = {}, {}
        for e in evs:
            age = ref - _match_day(e)
            w = 0.5 ** (age / half_life_days) if half_life_days != math.inf else 1.0
            gd = e["home_score"] - e["away_score"]
            for tid, g in ((e["home"]["id"], gd), (e["away"]["id"], -gd)):
                wsum[tid] = wsum.get(tid, 0.0) + w
                wgd[tid] = wgd.get(tid, 0.0) + w * g
        for tid in wsum:
            ratings[tid] = wgd[tid] / wsum[tid] - level * level_gap
    return ratings


def _ratings_for(code, prev_season, scheme, level_gap, half_life):
    """half_life None → esquema de tabla (build_ratings); si no, recencia por partido."""
    if half_life is None:
        return build_ratings(code, prev_season, scheme, level_gap)
    return build_ratings_recency(code, prev_season, level_gap, half_life)


# ── Modelo de partido (kappa=0 == modelo vivo actual, verificado) ────────────
def predict(Rh, Ra, w, p_home, p_draw, scale, kappa):
    p_away = 1.0 - p_home - p_draw
    m = p_home + p_away
    s0 = min(1 - 1e-9, max(1e-9, p_home / m if m > 0 else 0.5))
    logit = math.log(s0 / (1 - s0))
    d = w * scale * (Rh - Ra)
    s = 1.0 / (1.0 + math.exp(-(logit + d)))
    draw = p_draw * math.exp(-kappa * abs(d))   # kappa=0 → empate fijo (modelo actual)
    nondraw = 1.0 - draw
    return nondraw * s, draw, nondraw * (1.0 - s)


# ── Acumulador de métricas ───────────────────────────────────────────────────
class Metrics:
    def __init__(self):
        self.n = 0
        self.brier = 0.0
        self.logloss = 0.0
        # fiabilidad: bins de 10 sobre la prob. asignada al resultado home-win
        self.bins = [[0.0, 0.0, 0] for _ in range(10)]  # [sum_pred, sum_actual, count]

    def add(self, ph, pd, pa, result):
        self.n += 1
        yh, yd, ya = (result == "home"), (result == "draw"), (result == "away")
        self.brier += (ph - yh) ** 2 + (pd - yd) ** 2 + (pa - ya) ** 2
        p_act = max(1e-12, ph if yh else pd if yd else pa)
        self.logloss += -math.log(p_act)
        b = min(9, int(ph * 10))
        self.bins[b][0] += ph
        self.bins[b][1] += 1.0 if yh else 0.0
        self.bins[b][2] += 1

    def merge(self, o):
        self.n += o.n; self.brier += o.brier; self.logloss += o.logloss
        for i in range(10):
            for j in range(3):
                self.bins[i][j] += o.bins[i][j]

    @property
    def brier_mean(self):  return self.brier / self.n if self.n else float("nan")
    @property
    def logloss_mean(self): return self.logloss / self.n if self.n else float("nan")
    @property
    def ece(self):
        # Expected Calibration Error sobre la prob. de victoria local.
        tot = sum(b[2] for b in self.bins) or 1
        e = 0.0
        for pred_sum, act_sum, c in self.bins:
            if c:
                e += (c / tot) * abs(pred_sum / c - act_sum / c)
        return e


# Primeras jornadas: ventana donde el prior está a plena potencia (antes de
# desvanecerse). Es donde vive la calibración del favorito dominante; la métrica
# global la diluye con los cientos de partidos de media/final de temporada, donde el
# prior ya se apagó y ambos modelos convergen.
EARLY_MD = 6


# ── Backtest de una liga-temporada ───────────────────────────────────────────
def backtest_one(league, season_start, scheme, scale, kappa, level_gap, fade,
                 half_life=None):
    code, p_home, p_draw = league["espn_code"], league["p_home"], league["p_draw"]
    ratings = _ratings_for(code, season_start - 1, scheme, level_gap, half_life)
    default = min(ratings.values()) if ratings else 0.0

    evs = [e for e in matches_cached(code, season_start)
           if e["state"] == "post" and e["home_score"] is not None]
    evs.sort(key=lambda e: e["kickoff"] or e["date"])
    # nº de equipos y jornadas totales, para el peso de desvanecimiento
    ids = set()
    for e in evs:
        ids.add(e["home"]["id"]); ids.add(e["away"]["id"])
    n = len(ids) or 20
    total_md = 2 * (n - 1)

    gp = {i: 0 for i in ids}
    m, early = Metrics(), Metrics()
    for e in evs:
        hid, aid = e["home"]["id"], e["away"]["id"]
        jornada = (gp[hid] + gp[aid]) / 2.0
        w = fade_weight(jornada, total_md * (fade / STRENGTH_FADE_FRACTION)) if fade else 0.0
        Rh = ratings.get(hid, default); Ra = ratings.get(aid, default)
        ph, pd, pa = predict(Rh, Ra, w, p_home, p_draw, scale, kappa)
        hs, as_ = e["home_score"], e["away_score"]
        result = "home" if hs > as_ else "away" if as_ > hs else "draw"
        m.add(ph, pd, pa, result)
        if jornada < EARLY_MD:
            early.add(ph, pd, pa, result)
        gp[hid] += 1; gp[aid] += 1
    return m, early


def run_config(leagues, seasons, scheme, scale, kappa, level_gap, fade, half_life=None):
    total, early = Metrics(), Metrics()
    for lg in leagues:
        for s in seasons:
            f, e = backtest_one(lg, s, scheme, scale, kappa, level_gap, fade, half_life)
            total.merge(f); early.merge(e)
    return total, early


# ── Modo comparación ─────────────────────────────────────────────────────────
DEFAULT_LEAGUE_SLUGS = ["laliga", "premier", "seriea", "bundesliga", "ligue1",
                        "primeira", "eredivisie"]
DEFAULT_SEASONS = [2022, 2023, 2024, 2025]


def _leagues(slugs):
    return [league_by_slug(s) for s in slugs if league_by_slug(s)]


def cmd_compare(args):
    leagues = _leagues(args.leagues or DEFAULT_LEAGUE_SLUGS)
    seasons = args.seasons or DEFAULT_SEASONS
    print(f"Backtest: {len(leagues)} ligas × {len(seasons)} temporadas "
          f"({', '.join(str(s) for s in seasons)})\n")

    configs = [
        ("ACTUAL  (zscore, kappa=0)",
         dict(scheme="zscore", scale=STRENGTH_SCALE, kappa=0.0,
              level_gap=STRENGTH_LEVEL_GAP, fade=STRENGTH_FADE_FRACTION)),
        ("PROPUESTO (absolute + draw-fix)",
         dict(scheme="absolute", scale=args.scale, kappa=args.kappa,
              level_gap=args.level_gap, fade=args.fade)),
    ]
    print("TODOS los partidos:")
    print(f"  {'Config':32} {'Brier':>8} {'LogLoss':>9} {'ECE':>7} {'N':>7}")
    print("  " + "-" * 66)
    early_rows = []
    for name, cfg in configs:
        m, e = run_config(leagues, seasons, **cfg)
        print(f"  {name:32} {m.brier_mean:8.4f} {m.logloss_mean:9.4f} {m.ece:7.4f} {m.n:7d}")
        early_rows.append((name, e))
    print(f"\nSolo primeras {EARLY_MD} jornadas (donde el prior manda):")
    print(f"  {'Config':32} {'Brier':>8} {'LogLoss':>9} {'ECE':>7} {'N':>7}")
    print("  " + "-" * 66)
    for name, e in early_rows:
        print(f"  {name:32} {e.brier_mean:8.4f} {e.logloss_mean:9.4f} {e.ece:7.4f} {e.n:7d}")
    print("\n(Menor Brier / LogLoss / ECE = mejor. El PROPUESTO no toca producción.)")


def cmd_grid(args):
    leagues = _leagues(args.leagues or DEFAULT_LEAGUE_SLUGS)
    seasons = args.seasons or DEFAULT_SEASONS
    base, base_e = run_config(leagues, seasons, "zscore", STRENGTH_SCALE, 0.0,
                              STRENGTH_LEVEL_GAP, STRENGTH_FADE_FRACTION)
    print(f"Baseline ACTUAL: Brier={base.brier_mean:.4f} LogLoss={base.logloss_mean:.4f} "
          f"ECE={base.ece:.4f}  | early LogLoss={base_e.logloss_mean:.4f}\n")
    print(f"{'scale':>6} {'kappa':>6} {'lvlgap':>7} {'Brier':>8} {'LogLoss':>9} {'ECE':>7} {'earlyLL':>8}")
    print("-" * 60)
    best = None
    for scale in [0.8, 1.0, 1.3, 1.6, 2.0]:
        for kappa in [0.0, 0.15, 0.3, 0.45]:
            for lg in [1.5, 2.0, 2.5]:
                m, e = run_config(leagues, seasons, "absolute", scale, kappa, lg,
                                  STRENGTH_FADE_FRACTION)
                if best is None or m.logloss_mean < best[0]:
                    best = (m.logloss_mean, scale, kappa, lg, m.brier_mean, m.ece, e.logloss_mean)
                print(f"{scale:6.2f} {kappa:6.2f} {lg:7.1f} {m.brier_mean:8.4f} "
                      f"{m.logloss_mean:9.4f} {m.ece:7.4f} {e.logloss_mean:8.4f}")
    print(f"\nMejor por LogLoss: scale={best[1]} kappa={best[2]} level_gap={best[3]} "
          f"→ Brier={best[4]:.4f} LogLoss={best[0]:.4f} ECE={best[5]:.4f} earlyLL={best[6]:.4f}")


# ── Sanity check: P(título) pretemporada vs mercado ──────────────────────────
# NO es objetivo de ajuste (nos calibramos contra RESULTADOS, no contra el mercado);
# solo comprobamos que los favoritos dominantes dejan de salir absurdamente bajos.
import random

MARKET_TITLE = {   # P(título) implícita de mercado (aprox., pretemporada 2026-27)
    "bundesliga": ("Bayern Munich", 0.88),
    "ligue1":     ("Paris Saint-Germain", 0.90),
    "laliga":     ("Real Madrid / Barcelona", 0.55),  # repartido entre los dos
}


def sim_titles(names, ratings, default, p_home, p_draw, scale, kappa, level_gap,
               fade, n_sim=3000, seed=12345, hfrac=None):
    """P(acabar 1º) por equipo proyectando la temporada entera desde la jornada
    actual (pretemporada aquí).

    hfrac (horizonte de desvanecimiento del prior DENTRO de la proyección):
      None → prior CONGELADO en todos los partidos proyectados (comportamiento vivo
             actual; sobre-confía en el favorito porque compone 34 partidos).
      x>0  → el peso del prior decae linealmente a 0 a lo largo de x·temporada de la
             proyección: los partidos proyectados lejanos pesan menos (un prior de
             hace una temporada predice peor la forma de mayo). Doma el exceso de los
             dominantes sin tocar la calibración por-partido (que se puntúa aparte
             con resultados reales)."""
    ids = list(names.keys())
    n = len(ids)
    total_md = 2 * (n - 1)
    rng = random.Random(seed)
    firsts = {i: 0 for i in ids}
    # Peso del prior por resultados REALES acumulados (pretemporada → w0=1).
    w0 = fade_weight(0, total_md * (fade / STRENGTH_FADE_FRACTION)) if fade else 0.0
    for _ in range(n_sim):
        pts = {i: 0 for i in ids}
        for md in range(total_md):
            w = w0 if hfrac is None else w0 * max(0.0, 1.0 - md / (hfrac * total_md))
            order = ids[:]; rng.shuffle(order)
            for k in range(0, n - 1, 2):
                h, a = order[k], order[k + 1]
                ph, pd, pa = predict(ratings.get(h, default), ratings.get(a, default),
                                     w, p_home, p_draw, scale, kappa)
                r = rng.random()
                if r < ph: pts[h] += 3
                elif r < ph + pd: pts[h] += 1; pts[a] += 1
                else: pts[a] += 3
        win = max(ids, key=lambda i: (pts[i], rng.random()))
        firsts[win] += 1
    return {i: firsts[i] / n_sim for i in ids}


def champion_backtest(leagues, seasons, scale, kappa, level_gap, fade, hfrac,
                      n_sim=800, half_life=None):
    """Valida la PROYECCIÓN contra resultados REALES: proyecta cada temporada pasada
    desde pretemporada (prior de S-1) y puntúa P(campeón) contra quién ganó de verdad.
    Devuelve (logloss_campeón, brier_campeón) sobre todas las liga-temporadas."""
    ll = brier = 0.0
    cnt = 0
    for lg in leagues:
        code = lg["espn_code"]
        for s in seasons:
            final = table_cached(code, s)
            if len(final) < 2:
                continue
            names = {r["id"]: r["name"] for r in final}
            champ = min(final, key=lambda r: r["rank"])["id"]   # rank 1 = campeón real
            ratings = _ratings_for(code, s - 1, "absolute", level_gap, half_life)
            default = min(ratings.values()) if ratings else 0.0
            P = sim_titles(names, ratings, default, lg["p_home"], lg["p_draw"],
                           scale, kappa, level_gap, fade, n_sim=n_sim, hfrac=hfrac)
            ll += -math.log(max(1e-6, P.get(champ, 0.0)))
            brier += sum((P.get(i, 0.0) - (1.0 if i == champ else 0.0)) ** 2 for i in names)
            cnt += 1
    return (ll / cnt, brier / cnt) if cnt else (float("nan"), float("nan"))


def cmd_titles(args):
    slugs = args.leagues or ["bundesliga", "ligue1", "laliga"]
    for slug in slugs:
        lg = league_by_slug(slug)
        if not lg:
            continue
        code = lg["espn_code"]
        cur = espn.fetch_current_season_year(code)
        rows = espn.fetch_table(code)                 # tabla actual (pretemporada, gp=0)
        names = {r["id"]: r["name"] for r in rows}
        prev = cur - 1
        r_z = build_ratings(code, prev, "zscore", STRENGTH_LEVEL_GAP)
        r_a = build_ratings(code, prev, "absolute", args.level_gap)
        d_z = min(r_z.values()) if r_z else 0.0
        d_a = min(r_a.values()) if r_a else 0.0
        p_z = sim_titles(names, r_z, d_z, lg["p_home"], lg["p_draw"], STRENGTH_SCALE,
                         0.0, STRENGTH_LEVEL_GAP, STRENGTH_FADE_FRACTION)
        p_a = sim_titles(names, r_a, d_a, lg["p_home"], lg["p_draw"], args.scale,
                         args.kappa, args.level_gap, STRENGTH_FADE_FRACTION)
        mk = MARKET_TITLE.get(slug)
        print(f"\n== {lg['name']} {cur}-{str(cur+1)[2:]} (pretemporada) ==")
        if mk:
            print(f"   mercado ≈ {mk[1]*100:.0f}%  ({mk[0]})")
        top = sorted(names, key=lambda i: -p_a[i])[:4]
        print(f"   {'Equipo':24} {'ACTUAL':>8} {'PROPUESTO':>10}")
        for i in top:
            print(f"   {names[i][:24]:24} {p_z[i]*100:7.1f}% {p_a[i]*100:9.1f}%")


def cmd_champion(args):
    """Barre el horizonte de desvanecimiento de la proyección (hfrac) y muestra:
    (1) log-loss/Brier de P(campeón) contra los campeones REALES de las 4 temporadas
    y (2) P(título) pretemporada actual de los dominantes vs mercado (sanity)."""
    leagues = _leagues(args.leagues or DEFAULT_LEAGUE_SLUGS)
    seasons = args.seasons or DEFAULT_SEASONS
    sc, kp, lg_ = args.scale, args.kappa, args.level_gap
    print(f"Proyección: scale={sc} kappa={kp} level_gap={lg_}  "
          f"(campeón real de {len(leagues)}×{len(seasons)} liga-temporadas)\n")
    print(f"{'hfrac (horizonte)':22} {'ChampLogLoss':>13} {'ChampBrier':>11}")
    print("-" * 48)
    for hfrac in [None, 1.0, 0.75, 0.5, 0.35]:
        ll, br = champion_backtest(leagues, seasons, sc, kp, lg_,
                                   STRENGTH_FADE_FRACTION, hfrac)
        label = "congelado (actual)" if hfrac is None else f"decae en {hfrac}·temp."
        print(f"{label:22} {ll:13.4f} {br:11.4f}")

    print("\nSanity de mercado — P(título) pretemporada actual por horizonte:")
    dominants = {"bundesliga": "Bayern Munich", "ligue1": "Paris Saint-Germain",
                 "laliga": "Barcelona"}
    for slug, team in dominants.items():
        lg = league_by_slug(slug)
        if not lg or lg not in leagues:
            continue
        code = lg["espn_code"]; cur = espn.fetch_current_season_year(code)
        rows = espn.fetch_table(code)
        names = {r["id"]: r["name"] for r in rows}
        tid = next((i for i, nm in names.items() if nm == team), None)
        rats = build_ratings(code, cur - 1, "absolute", lg_)
        default = min(rats.values()) if rats else 0.0
        cells = []
        for hfrac in [None, 1.0, 0.75, 0.5]:
            P = sim_titles(names, rats, default, lg["p_home"], lg["p_draw"], sc, kp,
                           lg_, STRENGTH_FADE_FRACTION, n_sim=2000, hfrac=hfrac)
            cells.append(f"{P.get(tid, 0)*100:5.1f}%")
        mk = MARKET_TITLE.get(slug)
        print(f"  {team:22} congelado={cells[0]}  h1.0={cells[1]}  h0.75={cells[2]}  "
              f"h0.5={cells[3]}   mercado≈{int(mk[1]*100) if mk else '?'}%")


# ── Barrido de recencia (half-life del prior por partido) ────────────────────
# Recipe v2 ON (validada en --grid/--champion). El barrido de recencia se hace
# SOBRE esta receta: solo cambia de dónde sale el rating (agregado de tabla vs
# media ponderada por recencia de los partidos de la temporada previa).
RECENCY_RECIPE = dict(scale=1.5, kappa=0.15, level_gap=1.5, hfrac=1.0)


def cmd_recency(args):
    leagues = _leagues(args.leagues or DEFAULT_LEAGUE_SLUGS)
    seasons = args.seasons or DEFAULT_SEASONS
    sc = RECENCY_RECIPE["scale"]; kp = RECENCY_RECIPE["kappa"]
    lgp = RECENCY_RECIPE["level_gap"]; hf = RECENCY_RECIPE["hfrac"]
    print(f"Recencia del prior: {len(leagues)} ligas × {len(seasons)} temporadas | "
          f"receta v2 ON (scale={sc} kappa={kp} level_gap={lgp} hfrac={hf})")
    print("half_life = vida media en DÍAS del peso de cada partido de la temporada previa "
          "(inf = uniforme = agregado de tabla).\n")

    # None = agregado de tabla (v2 ON actual, el ancla); inf = uniforme por partido
    # (debe ≈ al ancla → verifica que la ruta por-partido es equivalente); resto = decae.
    hls = [None, math.inf, 240, 180, 120, 90, 60]
    print(f"  {'rating':22} {'Brier':>8} {'LogLoss':>9} {'ECE':>7} "
          f"{'earlyLL':>8} {'earlyECE':>9} {'champLL':>8} {'champBr':>8}")
    print("  " + "-" * 84)
    for hl in hls:
        m, e = run_config(leagues, seasons, "absolute", sc, kp, lgp,
                          STRENGTH_FADE_FRACTION, half_life=hl)
        cll, cbr = champion_backtest(leagues, seasons, sc, kp, lgp,
                                     STRENGTH_FADE_FRACTION, hf, half_life=hl)
        label = ("tabla (v2 ON)" if hl is None else
                 "uniforme/partido" if hl == math.inf else f"half-life {hl}d")
        print(f"  {label:22} {m.brier_mean:8.4f} {m.logloss_mean:9.4f} {m.ece:7.4f} "
              f"{e.logloss_mean:8.4f} {e.ece:9.4f} {cll:8.4f} {cbr:8.4f}")
    print("\n(Menor todo = mejor. earlyLL/earlyECE = primeras 6 jornadas, donde el prior manda.)")

    # Sanity de mercado: P(título) pretemporada ACTUAL de los dominantes por half-life.
    print("\nSanity de mercado — P(título) pretemporada actual por half-life:")
    dominants = {"bundesliga": "Bayern Munich", "ligue1": "Paris Saint-Germain",
                 "laliga": "Barcelona"}
    for slug, team in dominants.items():
        lg = league_by_slug(slug)
        if not lg or lg not in leagues:
            continue
        code = lg["espn_code"]; cur = espn.fetch_current_season_year(code)
        rows = espn.fetch_table(code)
        names = {r["id"]: r["name"] for r in rows}
        tid = next((i for i, nm in names.items() if nm == team), None)
        cells = []
        for hl in hls:
            rats = _ratings_for(code, cur - 1, "absolute", lgp, hl)
            default = min(rats.values()) if rats else 0.0
            P = sim_titles(names, rats, default, lg["p_home"], lg["p_draw"], sc, kp,
                           lgp, STRENGTH_FADE_FRACTION, n_sim=2000, hfrac=hf)
            cells.append(P.get(tid, 0) * 100)
        mk = MARKET_TITLE.get(slug)
        hdr = "  ".join(f"{('tabla' if h is None else 'unif' if h==math.inf else f'{h}d')}={c:4.1f}%"
                        for h, c in zip(hls, cells))
        print(f"  {team:22} {hdr}   mercado≈{int(mk[1]*100) if mk else '?'}%")


def main():
    ap = argparse.ArgumentParser(description="Backtest de calibración offline (Fase 4).")
    ap.add_argument("--grid", action="store_true", help="rejilla de parámetros del propuesto")
    ap.add_argument("--titles", action="store_true", help="P(título) pretemporada vs mercado (sanity)")
    ap.add_argument("--champion", action="store_true", help="barrido del horizonte de proyección vs campeones reales")
    ap.add_argument("--recency", action="store_true", help="barrido de la vida media (half-life) del prior por partido")
    ap.add_argument("--leagues", nargs="*", help="slugs (por defecto: 1as europeas)")
    ap.add_argument("--seasons", nargs="*", type=int, help="años de inicio (2022 2023 …)")
    ap.add_argument("--scale", type=float, default=0.8)
    ap.add_argument("--kappa", type=float, default=0.3)
    ap.add_argument("--level-gap", dest="level_gap", type=float, default=2.5)
    ap.add_argument("--fade", type=float, default=STRENGTH_FADE_FRACTION)
    args = ap.parse_args()
    if args.grid:
        cmd_grid(args)
    elif args.recency:
        cmd_recency(args)
    elif args.champion:
        cmd_champion(args)
    elif args.titles:
        cmd_titles(args)
    else:
        cmd_compare(args)


if __name__ == "__main__":
    main()
