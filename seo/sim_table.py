"""Monte Carlo para ligas regulares — port fiel de simulate() de index.html.

Diferencias respecto al JS, todas neutrales para los porcentajes:
  - Acumula el histograma completo de posición final por equipo, en vez de
    contar sólo zonas fijas. Así las bandas de zona (que varían por liga) se
    derivan en config sin tocar el simulador.
  - SIM_N por defecto más bajo (muestreo); resultado dentro del ruido.

El modelo de partido, el desempate (pts → DG → GF) y la simulación del play-off
a doble partido son idénticos al navegador.
"""

from .config import SIM_N_TABLE
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


def simulate(rows, p_home, p_draw, playoff_top=None, sim_n=SIM_N_TABLE):
    """Devuelve dict slug->resultados. rows: tabla de fetch_table().

    Resultado por equipo:
      pos_hist: lista (len = numTeams) con conteo de veces en cada posición.
      pSemi/pFinal/pWin: probabilidades de play-off (si playoff_top).
      finished: True si la temporada ya terminó (posiciones reales).
    """
    n = len(rows)
    total_md = 2 * (n - 1)
    names = [r["name"] for r in rows]
    team_gp = {r["name"]: r["gp"] for r in rows}
    min_gp = min(r["gp"] for r in rows)

    pos_hist = {name: [0] * n for name in names}
    psf = {name: 0 for name in names}
    pf  = {name: 0 for name in names}
    pw  = {name: 0 for name in names}

    # Temporada terminada → posiciones reales (port del cortocircuito JS).
    if min_gp >= total_md:
        ordered = sorted(rows, key=lambda t: (t["pts"], t["gf"] - t["gc"], t["gf"]),
                         reverse=True)
        for idx, t in enumerate(ordered):
            pos_hist[t["name"]][idx] = sim_n
        return _finalize(names, pos_hist, psf, pf, pw, sim_n, finished=True)

    rng = make_rng(standings_seed(rows))

    for _ in range(sim_n):
        pts = {r["name"]: r["pts"] for r in rows}
        gd  = {r["name"]: r["gf"] - r["gc"] for r in rows}
        gf  = {r["name"]: r["gf"] for r in rows}

        md_num = min_gp
        for _md in range(min_gp + 1, total_md + 1):
            md_num += 1
            order = _shuffle(rng, list(names))
            for k in range(0, len(order) - 1, 2):
                h, a = order[k], order[k + 1]
                if team_gp[h] >= md_num or team_gp[a] >= md_num:
                    continue
                r = rng()
                if r < p_home:
                    hp, ap = 3, 0
                    hg = int(rng() * 2) + 1 + int(rng() * 2); ag = int(rng() * 2)
                elif r < p_home + p_draw:
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

        # Play-off de ascenso: 3º vs 6º y 4º vs 5º (port exacto).
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
