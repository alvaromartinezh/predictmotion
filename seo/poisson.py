"""Modelo de marcadores Poisson (v3) — el núcleo del Monte Carlo.

Sustituye el sorteo W/D/L + goles 0/1/2 por dos Poisson independientes:

    λ_local  = base + hfa + k_att·a_h + k_def·d_a
    λ_visita = base      + k_att·a_a + k_def·d_h

con a_t = ataque_t − media_ataque_liga (goles a favor/partido, blend
multi-temporada real) y d_t = defensa_t − media_defensa_liga (goles en
contra/partido; **positivo = recibe más = defensa peor**, así que la defensa
mala del RIVAL SUBE la λ propia). Las marginales 1X2 emergen de la bivariada
(agregación cerrada, sin RNG) — misma utilidad que live_tracker/winprob.py.

El desvanecimiento del prior (fade) escala las desviaciones a_t/d_t, igual que en
v2: a media temporada el modelo vuelve a la base de la liga (uniforme) y manda la
tabla real. Parámetros en seo/config.py (POISSON_*, heurísticos).
"""

import math


def pmf(k, lam):
    """P(X = k) para Poisson(lam)."""
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    return math.exp(-lam) * lam ** k / math.factorial(k)


def cdf(lam, max_goals):
    """CDF truncada: P(X ≤ k) para k = 0..max_goals."""
    out = []
    acc = 0.0
    for k in range(max_goals + 1):
        acc += pmf(k, lam)
        out.append(min(1.0, acc))
    return out


def sample(rng, cdf_vec):
    """Muestrea un nº de goles desde la CDF precomputada (1 rng + barrido corto)."""
    r = rng()
    for k, v in enumerate(cdf_vec):
        if r < v:
            return k
    return len(cdf_vec) - 1


def league_base(rows, fallback=1.35):
    """Goles esperados por equipo y partido de la liga (media gf/partido).

    `fallback` es un valor por defecto para ligas sin partidos (pretemporada o
    fase de liga UEFA antes del arranque). Los goles van simétricos: la media de
    gf ≈ media de gc para el total de la liga.
    """
    total_gp = sum(r["gp"] for r in rows)
    if not total_gp:
        return fallback
    return (sum(r["gf"] + r["gc"] for r in rows)) / (2 * total_gp)


def league_adjust(goal_strengths, rows):
    """{name: {"att": a, "def": d}} en DESVIACIÓN de la media de la liga.

    `goal_strengths`: {team_id: {"att":…, "def":…}} blend multi-temporada REAL de
    gf/gp y gc/gp (ver seo/espn.py:build_attack_defense). Los equipos sin
    histórico caen a la media (a = d = 0). Devuelve None si no hay ningún
    goal_strength → el llamador usa el modelo uniforme (solo base + hfa).
    """
    known = {r["id"]: goal_strengths.get(r["id"]) for r in rows}
    known = {k: v for k, v in known.items() if v is not None}
    if not known:
        return None
    ma = sum(g["att"] for g in known.values()) / len(known)
    md = sum(g["def"] for g in known.values()) / len(known)
    out = {}
    for r in rows:
        g = goal_strengths.get(r["id"])
        if g is None:
            out[r["name"]] = {"att": 0.0, "def": 0.0}
        else:
            out[r["name"]] = {"att": g["att"] - ma, "def": g["def"] - md}
    return out


def match_lambdas(adj, h, a, base, hfa, k_att, k_def, w):
    """λ_local/λ_visita para el par (h,a) con el peso de desvanecimiento `w`
    aplicado a las desviaciones. `adj` None (sin fuerzas) → uniforme (base+hfa)."""
    if adj is None:
        return max(base + hfa, 0.0), max(base, 0.0)
    ah = w * adj[h]["att"]; aa = w * adj[a]["att"]
    dh = w * adj[h]["def"]; da = w * adj[a]["def"]
    lam_h = base + hfa + k_att * ah + k_def * da
    lam_a = base + k_att * aa + k_def * dh
    return max(lam_h, 0.0), max(lam_a, 0.0)


def score_probs(lam_h, lam_a, max_goals=8):
    """(P local, P empate, P visita) de la bivariada Poisson — agregación cerrada,
    sin RNG. La misma marginal que usa el Monte Carlo (los puntos salen del
    marcador), para que el registro de predicciones mida EXACTAMENTE el modelo."""
    ph = pd = pa = 0.0
    hp = [pmf(i, lam_h) for i in range(max_goals + 1)]
    ap = [pmf(j, lam_a) for j in range(max_goals + 1)]
    for i in range(max_goals + 1):
        for j in range(max_goals + 1):
            p = hp[i] * ap[j]
            if i > j:
                ph += p
            elif i == j:
                pd += p
            else:
                pa += p
    tot = ph + pd + pa or 1.0
    return ph / tot, pd / tot, pa / tot


def p_over(lam_h, lam_a, max_goals=8, line=2.5):
    """P(total de goles > line) de la bivariada Poisson — agregación cerrada,
    sin RNG. Lo usa el "dato curioso" kind=over_25 del generador de artículos."""
    hp = [pmf(i, lam_h) for i in range(max_goals + 1)]
    ap = [pmf(j, lam_a) for j in range(max_goals + 1)]
    return sum(
        hp[i] * ap[j]
        for i in range(max_goals + 1)
        for j in range(max_goals + 1)
        if i + j > line
    )


def p_btts(lam_h, lam_a):
    """P(gol del local Y gol del visitante) = (1−P_h(0))·(1−P_a(0)) — Poisson
    independientes (misma hipótesis que el Monte Carlo). kind=ambos_marcan."""
    return (1.0 - pmf(0, lam_h)) * (1.0 - pmf(0, lam_a))


def top_score(lam_h, lam_a, max_goals=8):
    """(marcador, prob) exacto más probable de la bivariada — la celda de mayor
    masa conjunta (p. ej. (1, 0), (0, 0)…). Lo usa kind=marcador_jornada."""
    hp = [pmf(i, lam_h) for i in range(max_goals + 1)]
    ap = [pmf(j, lam_a) for j in range(max_goals + 1)]
    best, best_p = (0, 0), 0.0
    for i in range(max_goals + 1):
        for j in range(max_goals + 1):
            p = hp[i] * ap[j]
            if p > best_p:
                best, best_p = (i, j), p
    return best, best_p