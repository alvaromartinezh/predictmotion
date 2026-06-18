"""
Liga Hypermotion 2025-26 - Simulador de posibilidades de clasificación final
Monte Carlo: N simulaciones de las 5 jornadas restantes (38-42)
"""

import random
from collections import defaultdict
from copy import deepcopy

# ---------------------------------------------------------------------------
# CLASIFICACIÓN ACTUAL (tras jornada 37)
# nombre, PJ, PG, PE, PP, GF, GC, Pts
# ---------------------------------------------------------------------------
STANDINGS = [
    ("Racing Club",       37, 21, 6, 10, 75, 55, 69),
    ("UD Almería",        37, 20, 7, 10, 74, 56, 67),
    ("RC Deportivo",      37, 18, 11, 8, 57, 40, 65),
    ("CD Castellón",      37, 18, 10, 9, 64, 46, 64),
    ("UD Las Palmas",     37, 17, 12, 8, 49, 31, 63),
    ("Burgos CF",         37, 17, 10, 10, 44, 33, 61),
    ("SD Eibar",          37, 17, 10, 10, 45, 32, 61),
    ("Málaga CF",         37, 17, 9, 11, 62, 47, 60),
    ("FC Andorra",        37, 15, 10, 12, 56, 47, 55),
    ("Córdoba CF",        37, 15, 9, 13, 52, 55, 54),
    ("Real Sporting",     37, 15, 7, 15, 50, 47, 52),
    ("AD Ceuta FC",       37, 14, 9, 14, 44, 57, 51),
    ("Albacete BP",       37, 12, 11, 14, 48, 51, 47),
    ("Granada CF",        37, 11, 12, 14, 47, 49, 45),
    ("Real Valladolid",   37, 11, 10, 16, 40, 48, 43),
    ("CD Leganés",        37, 10, 12, 15, 40, 44, 42),
    ("R. Sociedad B",     37, 11, 8, 18, 46, 54, 41),
    ("Cádiz CF",          37, 10, 8, 19, 34, 53, 38),
    ("SD Huesca",         37,  9, 9, 19, 37, 55, 36),
    ("CD Mirandés",       37,  9, 9, 19, 40, 60, 36),
    ("Real Zaragoza",     37,  8, 11, 18, 33, 50, 35),
    ("Cultural Leonesa",  37,  8, 8, 21, 33, 60, 32),
]

# ---------------------------------------------------------------------------
# PARTIDOS RESTANTES CONOCIDOS
# Jornada 38 (completa) y jornada 42 (casi completa)
# Formato: (local, visitante)
# ---------------------------------------------------------------------------
J38 = [
    ("FC Andorra",       "Albacete BP"),
    ("RC Deportivo",     "CD Leganés"),
    ("Real Zaragoza",    "Granada CF"),
    ("Cultural Leonesa", "Cádiz CF"),
    ("CD Castellón",     "Córdoba CF"),
    ("SD Eibar",         "Málaga CF"),
    ("Racing Club",      "SD Huesca"),
    ("Real Sporting",    "AD Ceuta FC"),
    ("R. Sociedad B",    "Burgos CF"),
    ("UD Las Palmas",    "Real Valladolid"),
    ("UD Almería",       "CD Mirandés"),
]

J39_KNOWN = [
    ("Cádiz CF",         "RC Deportivo"),
    ("AD Ceuta FC",      "CD Castellón"),
    ("Albacete BP",      "Cultural Leonesa"),
    ("Burgos CF",        "UD Almería"),
    ("Real Valladolid",  "Real Zaragoza"),
    ("Málaga CF",        "Real Sporting"),
]

J42 = [
    ("CD Castellón",     "SD Eibar"),
    ("Córdoba CF",       "SD Huesca"),
    ("RC Deportivo",     "UD Las Palmas"),
    ("Granada CF",       "Real Sporting"),
    ("CD Leganés",       "CD Mirandés"),
    ("UD Almería",       "Real Valladolid"),
    ("AD Ceuta FC",      "Albacete BP"),
    ("Racing Club",      "Cádiz CF"),
    ("R. Sociedad B",    "Cultural Leonesa"),
    ("Real Zaragoza",    "Málaga CF"),
    ("FC Andorra",       "Burgos CF"),  # deducido
]


def complete_matchday(known_matches, all_teams):
    """Completa una jornada generando los partidos que faltan respetando
    que cada equipo juega exactamente una vez."""
    used = set()
    for h, a in known_matches:
        used.add(h)
        used.add(a)
    remaining = [t for t in all_teams if t not in used]
    random.shuffle(remaining)
    extra = []
    for i in range(0, len(remaining), 2):
        # aleatoriamente asignar quién es local
        if random.random() < 0.5:
            extra.append((remaining[i], remaining[i + 1]))
        else:
            extra.append((remaining[i + 1], remaining[i]))
    return known_matches + extra


def build_remaining_fixtures(all_teams):
    """Construye las 5 jornadas restantes con los datos conocidos
    y completando aleatoriamente las que faltan."""
    j38 = list(J38)
    j39 = complete_matchday(list(J39_KNOWN), all_teams)
    j42 = list(J42)

    # Para jornadas 40 y 41 generamos aleatoriamente round-robin válidos.
    # Se intenta respetar que un equipo no juegue más de una vez en la jornada.
    j40 = build_random_matchday(all_teams)
    j41 = build_random_matchday(all_teams)

    return [j38, j39, j40, j41, j42]


def build_random_matchday(all_teams):
    teams = list(all_teams)
    random.shuffle(teams)
    matches = []
    for i in range(0, len(teams), 2):
        matches.append((teams[i], teams[i + 1]))
    return matches


# ---------------------------------------------------------------------------
# PROBABILIDADES DE RESULTADO
# Home win / Draw / Away win   (medias históricas Segunda División)
# ---------------------------------------------------------------------------
P_HOME_WIN = 0.42
P_DRAW     = 0.27
P_AWAY_WIN = 0.31

GOALS_AVG = {
    "home_win":  (2.1, 0.8),
    "draw":      (1.1, 1.1),
    "away_win":  (0.8, 2.1),
}


def simulate_match():
    """Devuelve (goles_local, goles_visitante)."""
    r = random.random()
    if r < P_HOME_WIN:
        outcome = "home_win"
    elif r < P_HOME_WIN + P_DRAW:
        outcome = "draw"
    else:
        outcome = "away_win"
    mu_h, mu_a = GOALS_AVG[outcome]
    gh = max(0, round(random.gauss(mu_h, 0.8)))
    ga = max(0, round(random.gauss(mu_a, 0.8)))
    if outcome == "home_win" and gh <= ga:
        gh = ga + 1
    elif outcome == "away_win" and ga <= gh:
        ga = gh + 1
    elif outcome == "draw":
        ga = gh
    return gh, ga


def run_simulation(base_standings, all_teams, n=50_000):
    """Monte Carlo: simula n temporadas y cuenta porcentajes."""

    zone_counts = {
        t: {"top2": 0, "top6": 0, "bottom4": 0, "mid": 0}
        for t in all_teams
    }

    for _ in range(n):
        # Construir fixture list (jornadas 39-41 varían cada iteración)
        fixtures = build_remaining_fixtures(all_teams)

        # Copiar tabla de puntos actual
        pts   = {row[0]: row[7] for row in base_standings}
        gf    = {row[0]: row[5] for row in base_standings}
        gc    = {row[0]: row[6] for row in base_standings}

        # Simular partidos
        for matchday in fixtures:
            for home, away in matchday:
                gh, ga = simulate_match()
                gf[home] += gh; gc[home] += ga
                gf[away] += ga; gc[away] += gh
                if gh > ga:
                    pts[home] += 3
                elif gh == ga:
                    pts[home] += 1
                    pts[away] += 1
                else:
                    pts[away] += 3

        # Clasificar (criterio: pts → diferencia de goles → goles a favor)
        ranking = sorted(
            all_teams,
            key=lambda t: (pts[t], gf[t] - gc[t], gf[t]),
            reverse=True
        )

        for pos, team in enumerate(ranking, 1):
            if pos <= 2:
                zone_counts[team]["top2"]    += 1
            elif pos <= 6:
                zone_counts[team]["top6"]    += 1
            elif pos >= 19:
                zone_counts[team]["bottom4"] += 1
            else:
                zone_counts[team]["mid"]     += 1

    # Convertir a porcentajes
    results = {}
    for team, counts in zone_counts.items():
        results[team] = {k: round(v / n * 100, 1) for k, v in counts.items()}

    return results


def print_results(results, base_standings):
    # Ordenar por posición actual
    teams_ordered = [row[0] for row in base_standings]

    header = f"{'Pos':>3}  {'Equipo':<22} {'Pts':>3}  {'Ascenso directo':>16}  {'Play-off':>8}  {'Descenso':>8}"
    sep    = "-" * len(header)
    print("\n" + "=" * len(header))
    print("  LIGA HYPERMOTION 2025-26 — Probabilidades tras jornada 37")
    print("=" * len(header))
    print(header)
    print(sep)

    for i, row in enumerate(base_standings, 1):
        team = row[0]
        pts  = row[7]
        r    = results[team]
        zone = ""
        if i <= 2:
            zone = "++"
        elif i <= 6:
            zone = "+ "
        elif i >= 19:
            zone = "--"
        else:
            zone = "  "

        print(
            f"{i:>3}{zone} {team:<22} {pts:>3}  "
            f"{r['top2']:>14.1f}%  "
            f"{r['top6']:>6.1f}%  "
            f"{r['bottom4']:>6.1f}%"
        )
        if i in (2, 6, 18):
            print(sep)

    print("=" * len(header))
    print("  Zonas: Top 1-2 = ascenso directo | Top 3-6 = play-off | Últimos 4 = descenso")
    print(f"  Simulaciones: 50.000  |  Jornadas restantes: 5 (38-42)")
    print("=" * len(header) + "\n")


if __name__ == "__main__":
    all_teams = [row[0] for row in STANDINGS]

    print("Ejecutando simulación Monte Carlo (50.000 iteraciones)...")
    results = run_simulation(STANDINGS, all_teams, n=50_000)
    print_results(results, STANDINGS)
