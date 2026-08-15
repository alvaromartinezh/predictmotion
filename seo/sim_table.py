"""Monte Carlo para ligas regulares — port fiel de simulate() de index.html.

Diferencias respecto al JS, todas neutrales para los porcentajes:
  - Acumula el histograma completo de posición final por equipo, en vez de
    contar sólo zonas fijas. Así las bandas de zona (que varían por liga) se
    derivan en config sin tocar el simulador.
  - SIM_N por defecto más bajo (muestreo); resultado dentro del ruido.

El modelo de partido, el desempate (pts → DG → GF) y la simulación del play-off
a doble partido son idénticos al navegador.
"""

import math

from .config import (SIM_N_TABLE, STRENGTH_SCALE, STRENGTH_FADE_FRACTION,
                     USE_ABSOLUTE_RATING, STRENGTH_SCALE_ABS, DRAW_SHRINK_KAPPA,
                     PROJECTION_HORIZON_FADE)
from .prng import make_rng, standings_seed


def _two_legs(rng, p_home, p_draw, home, away):
    """Eliminatoria a doble partido. Port de simTwoLegs()."""
    h = a = 0
    r1 = rng()
    if r1 < p_home:
        h += (int(rng() * 2)) + 1 + int(rng() * 2); a += int(rng() * 2)
    elif r1 < p_home + p_draw:
        g = int(rng() * 2); h += g; a += g
    else:
        h += int(rng() * 2); a += int(rng() * 2) + 1 + int(rng() * 2)
    r2 = rng()
    if r2 < p_home:
        a += int(rng() * 2) + 1 + int(rng() * 2); h += int(rng() * 2)
    elif r2 < p_home + p_draw:
        g = int(rng() * 2); h += g; a += g
    else:
        a += int(rng() * 2); h += int(rng() * 2) + 1 + int(rng() * 2)
    if h > a:
        return home
    if a > h:
        return away
    return home if rng() < 0.5 else away


def _shuffle(rng, arr):
    for i in range(len(arr) - 1, 0, -1):
        j = int(rng() * (i + 1))
        arr[i], arr[j] = arr[j], arr[i]
    return arr


def resolve_strengths(rows, ratings):
    """{team_id: R} para los equipos de esta tabla, con default de FONDO DE TABLA
    (mínimo rating conocido) para los que no tienen histórico (decisión 1).
    Devuelve None si no hay ratings o ninguno de estos equipos aparece en ellos.
    Usado por la sim y por el snapshot para que ambos vean la misma fuerza."""
    if not ratings:
        return None
    known = [ratings[r["id"]] for r in rows if r["id"] in ratings]
    if not known:
        return None
    default = min(known)
    return {r["id"]: ratings.get(r["id"], default) for r in rows}


def fade_weight(jornada, total_md):
    """Peso del prior: 1 en jornada 0 → 0 a media temporada (STRENGTH_FADE_FRACTION)."""
    span = STRENGTH_FADE_FRACTION * total_md
    if span <= 0:
        return 0.0
    return max(0.0, min(1.0, 1.0 - jornada / span))


def _strength_context(rows, ratings, p_home, p_draw, total_md):
    """Prepara el prior de fuerza para la sim. Devuelve None si no aplica (sin
    ratings o a media temporada ya desvanecido) → la sim usa el modelo uniforme
    de siempre, bit-idéntico al histórico. En otro caso devuelve un dict con:
      w        : peso del prior (1 en jornada 0 → 0 a media temporada)
      logit_s0 : logit de la cuota de victoria local en el reparto medio
      m        : masa no-empate (p_home + p_away), constante
      strength : {name: rating} para los equipos de esta tabla (default fondo)
    """
    by_id = resolve_strengths(rows, ratings)
    if by_id is None:
        return None
    w = fade_weight(max(r["gp"] for r in rows), total_md)
    if w <= 0.0:
        return None
    strength = {r["name"]: by_id[r["id"]] for r in rows}
    p_away = 1.0 - p_home - p_draw
    m = p_home + p_away
    s0 = p_home / m if m > 0 else 0.5
    s0 = min(1 - 1e-9, max(1e-9, s0))
    return {"w": w, "logit_s0": math.log(s0 / (1 - s0)), "m": m, "strength": strength}


def _match_ph_pd(sc, h, a, p_draw, w_md):
    """1X2 (ph, pd) para un partido dado el contexto de fuerza. Separado para que la
    ruta v2 (rating absoluto + encogido de empate + fade de proyección) conviva con
    la ruta ACTUAL sin tocarla (USE_ABSOLUTE_RATING=False ⇒ fórmula idéntica)."""
    if USE_ABSOLUTE_RATING:
        d = w_md * STRENGTH_SCALE_ABS * (sc["strength"][h] - sc["strength"][a])
        s = 1.0 / (1.0 + math.exp(-(sc["logit_s0"] + d)))
        draw = p_draw * math.exp(-DRAW_SHRINK_KAPPA * abs(d))
        return (1.0 - draw) * s, draw
    delta = STRENGTH_SCALE * (sc["strength"][h] - sc["strength"][a])
    s = 1.0 / (1.0 + math.exp(-(sc["logit_s0"] + sc["w"] * delta)))
    return sc["m"] * s, p_draw


def simulate(rows, p_home, p_draw, playoff_top=None, sim_n=SIM_N_TABLE, ratings=None,
             matches_per_team=None):
    """Devuelve dict slug->resultados. rows: tabla de fetch_table().

    ratings: {team_id: R} opcional (prior de fuerza de la temporada anterior). Se
    aplica en pretemporada y se desvanece a media temporada; None/{} o temporada
    avanzada → modelo uniforme de siempre.

    matches_per_team: nº de partidos que juega cada equipo en la temporada. None →
    doble round-robin `2·(n−1)` (ligas regulares). Se pasa explícito para formatos
    que NO son round-robin, como la fase de liga UEFA (36 equipos, 8 partidos).

    Resultado por equipo:
      pos_hist: lista (len = numTeams) con conteo de veces en cada posición.
      pSemi/pFinal/pWin: probabilidades de play-off (si playoff_top).
      finished: True si la temporada ya terminó (posiciones reales).
    """
    n = len(rows)
    total_md = matches_per_team or 2 * (n - 1)
    names = [r["name"] for r in rows]
    team_gp = {r["name"]: r["gp"] for r in rows}
    min_gp = min(r["gp"] for r in rows)

    pos_hist = {name: [0] * n for name in names}
    psf = {name: 0 for name in names}
    pf  = {name: 0 for name in names}
    pw  = {name: 0 for name in names}

    # Temporada terminada → posiciones reales. Se usa el `rank` OFICIAL de ESPN,
    # que ya aplica el desempate de cada liga (LaLiga y Serie A rompen empates por
    # enfrentamiento directo, no por diferencia de goles). Reordenar aquí por
    # pts→DG→GF colocaba mal a equipos empatados a puntos y congelaba ese error en
    # el snapshot al 100%: los dashboards ya lo corrigieron en SU rama de temporada
    # terminada, pero leen este snapshot cuando la tabla cuadra, y el rows.html que
    # se sirve sin JS sale de aquí. Sin rank (tabla sintética) se cae al orden por
    # puntos, que dentro del Monte Carlo sí es el único criterio disponible.
    if min_gp >= total_md:
        if all(t.get("rank") for t in rows):
            ordered = sorted(rows, key=lambda t: t["rank"])
        else:
            ordered = sorted(rows, key=lambda t: (t["pts"], t["gf"] - t["gc"], t["gf"]),
                             reverse=True)
        for idx, t in enumerate(ordered):
            pos_hist[t["name"]][idx] = sim_n
        return _finalize(names, pos_hist, psf, pf, pw, sim_n, finished=True)

    sc = _strength_context(rows, ratings, p_home, p_draw, total_md)

    rng = make_rng(standings_seed(rows))

    for _ in range(sim_n):
        pts = {r["name"]: r["pts"] for r in rows}
        gd  = {r["name"]: r["gf"] - r["gc"] for r in rows}
        gf  = {r["name"]: r["gf"] for r in rows}

        md_num = min_gp
        for _md in range(min_gp + 1, total_md + 1):
            md_num += 1
            # Peso del prior para esta jornada proyectada. OFF (o sin fade de
            # proyección) → constante sc["w"], como siempre. v2 con horizonte → el
            # prior decae dentro de la temporada proyectada (mejor P(campeón) real).
            if sc is None:
                w_md = 0.0
            elif USE_ABSOLUTE_RATING and PROJECTION_HORIZON_FADE:
                proj_i = _md - (min_gp + 1)
                w_md = sc["w"] * max(0.0, 1.0 - proj_i / (PROJECTION_HORIZON_FADE * total_md))
            else:
                w_md = sc["w"]
            order = _shuffle(rng, list(names))
            for k in range(0, len(order) - 1, 2):
                h, a = order[k], order[k + 1]
                if team_gp[h] >= md_num or team_gp[a] >= md_num:
                    continue
                # Prior de fuerza: sesga la cuota local por el rating (con
                # desvanecimiento). Sin prior aplicable → p_home/p_draw de siempre.
                if sc is None:
                    ph, pd_ = p_home, p_draw
                else:
                    ph, pd_ = _match_ph_pd(sc, h, a, p_draw, w_md)
                r = rng()
                if r < ph:
                    hp, ap = 3, 0
                    hg = int(rng() * 2) + 1 + int(rng() * 2); ag = int(rng() * 2)
                elif r < ph + pd_:
                    hp = ap = 1
                    hg = ag = int(rng() * 2)
                else:
                    hp, ap = 0, 3
                    hg = int(rng() * 2); ag = int(rng() * 2) + 1 + int(rng() * 2)
                pts[h] += hp; pts[a] += ap
                gd[h] += hg - ag; gd[a] += ag - hg
                gf[h] += hg; gf[a] += ag

        ranking = sorted(names, key=lambda nm: (pts[nm], gd[nm], gf[nm]), reverse=True)
        for idx, nm in enumerate(ranking):
            pos_hist[nm][idx] += 1

        # Play-off de ascenso: 3º vs 6º y 4º vs 5º (port exacto). Los índices 2 y 3
        # dan por hecho 2 ascensos directos: vale para Hypermotion, la única liga
        # con playoff_top. Si otra liga con play-off tuviera otro número de plazas
        # directas, esto hay que parametrizarlo (el motor JS ya lo hace con
        # opts.promoSlots).
        if playoff_top and len(ranking) >= playoff_top:
            sf1h = ranking[2]; sf1a = ranking[playoff_top - 1]
            sf2h = ranking[3]; sf2a = ranking[playoff_top - 2]
            for t in (sf1h, sf1a, sf2h, sf2a):
                psf[t] += 1
            w1 = _two_legs(rng, p_home, p_draw, sf1h, sf1a)
            w2 = _two_legs(rng, p_home, p_draw, sf2h, sf2a)
            pf[w1] += 1; pf[w2] += 1
            wf = _two_legs(rng, p_home, p_draw, w1, w2)
            pw[wf] += 1

    return _finalize(names, pos_hist, psf, pf, pw, sim_n, finished=False)


def _finalize(names, pos_hist, psf, pf, pw, sim_n, finished):
    out = {}
    for nm in names:
        out[nm] = {
            "pos_hist": pos_hist[nm],
            "pSemi":  round(psf[nm] / sim_n * 100, 1),
            "pFinal": round(pf[nm] / sim_n * 100, 1),
            "pWin":   round(pw[nm] / sim_n * 100, 1),
            "finished": finished,
        }
    return out


def zone_prob(pos_hist, lo, hi, sim_n):
    """Probabilidad (%) de terminar entre las posiciones lo..hi (1-based, incl.)."""
    c = sum(pos_hist[lo - 1:hi])
    return round(c / sim_n * 100, 1)
