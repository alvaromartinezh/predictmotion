"""Paridad motor Python (cron) ↔ motor JS (fallback en cliente).

El 2026-08-14 los dashboards enseñaron porcentajes disparatados durante un partido
en vivo: el cron llevaba desde el 2026-08-10 con el modelo de fuerza v2 (rating
absoluto) y `assets/league-engine.js` seguía aplicando v1 con el parámetro v1 que
publicaba el snapshot, así que el fallback en cliente simulaba con ~1/5 de la
fuerza (Albacete 1,5% → 6,1% de ascenso). Ambos motores son ports uno del otro y
NADA avisaba de la divergencia.

Esta prueba corre los dos sobre la misma tabla y compara. Los PRNG no van
sincronizados (el JS baraja todas las jornadas por adelantado y el Python jornada
a jornada), así que la comparación es estadística, no bit a bit.

    python3 -m seo.test_engine_parity        # necesita node en el PATH
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path

from . import sim_table
from .config import (STRENGTH_SCALE, STRENGTH_FADE_FRACTION, USE_ABSOLUTE_RATING,
                     STRENGTH_SCALE_ABS, DRAW_SHRINK_KAPPA, PROJECTION_HORIZON_FADE)

ROOT = Path(__file__).resolve().parent.parent
SIM_N, P_HOME, P_DRAW, TOLERANCIA = 20000, 0.42, 0.27, 2.0   # puntos porcentuales

# Tabla sintética: 22 equipos, jornada 1 jugada (el prior pesa casi todo) y fuerzas
# repartidas de fondo de tabla a favorito claro, que es donde más se notó el fallo.
ROWS = [{"id": str(100 + i), "name": "Equipo %02d" % i, "rank": i + 1,
         "gp": 1, "pts": (i % 4), "gf": (i % 3), "gc": ((i + 1) % 3)}
        for i in range(22)]
RATINGS = {r["id"]: -1.9 + 1.75 * (i / 21) for i, r in enumerate(ROWS)}


def _js(snapshot, standings):
    """Corre el motor del navegador en node y devuelve {equipo: P(top2) en %}."""
    script = """
      const E = require(process.argv[1]);
      const {snapshot, standings, simN, pHome, pDraw} = JSON.parse(process.argv[2]);
      const ctx = E.buildStrengthCtx(snapshot, standings, pHome, pDraw);
      const res = E.simulate(standings, {pHome, pDraw, simN, sc: ctx});
      const out = {};
      standings.forEach(t => out[t.name] = E.zoneProb(res.posHist[t.name], 1, 2, res.simN));
      console.log(JSON.stringify(out));
    """
    payload = json.dumps({"snapshot": snapshot, "standings": standings,
                          "simN": SIM_N, "pHome": P_HOME, "pDraw": P_DRAW})
    p = subprocess.run(["node", "-e", script, "--",
                        str(ROOT / "assets" / "league-engine.js"), payload],
                       capture_output=True, text=True, check=True)
    return json.loads(p.stdout)


def _temporada_terminada():
    """Con la temporada acabada manda el `rank` oficial de ESPN, no la diferencia
    de goles: LaLiga y Serie A desempatan por enfrentamiento directo, y este
    snapshot se congela al 100% y se sirve como rows.html sin JS."""
    rows = [
        {"id": "1", "name": "GanoElH2H", "rank": 1, "gp": 38, "pts": 80, "gf": 70, "gc": 40},
        {"id": "2", "name": "MejorDG",   "rank": 2, "gp": 38, "pts": 80, "gf": 90, "gc": 30},
    ] + [{"id": str(i), "name": "Relleno%02d" % i, "rank": i, "gp": 38,
          "pts": 40 - i, "gf": 40, "gc": 40} for i in range(3, 21)]
    sim = sim_table.simulate(rows, P_HOME, P_DRAW, sim_n=100)
    campeon = [n for n, r in sim.items() if r["pos_hist"][0] == 100][0]
    assert campeon == "GanoElH2H", (
        "temporada terminada: manda el rank de ESPN, no la diferencia de goles "
        "(salió campeón %s)" % campeon)
    print("temporada terminada: respeta el desempate oficial")


def _consumidores_del_modelo():
    """Los OTROS consumidores del modelo, que no pasan por league-engine.js.

    `predictions.py` tenía una copia literal de la fórmula v1 y siguió escribiendo
    con ella cuando el cron pasó a v2: su fichero es append-only e inmutable, así
    que cada fila desde el 2026-08-10 mide un modelo que no existe — y su único
    propósito es calibrar el que sí. `live_tracker/strength.py` aplicaba la fórmula
    compilada a cualquier snapshot sin mirar `strength_model`."""
    from . import predictions
    from .config import league_by_slug

    lg = league_by_slug("laliga")
    snapshot = {
        "jornada": 0, "total_md": 38,
        "strength_model": "v2" if USE_ABSOLUTE_RATING else "v1",
        "strength_scale": STRENGTH_SCALE,
        "teams": [{"id": "H", "strength": 1.5}, {"id": "A", "strength": -1.2}],
    }
    sc = sim_table.snapshot_context(snapshot, lg["p_home"], lg["p_draw"])
    esperado = sim_table._match_ph_pd(sc, "H", "A", lg["p_draw"], sc["w"])
    ph, pd, _ = predictions._match_probs(sc, "H", "A", lg["p_home"], lg["p_draw"])
    assert abs(ph - esperado[0]) < 1e-4 and abs(pd - esperado[1]) < 1e-4, (
        "el registro de predicciones no usa la fórmula de la simulación "
        "(%.4f/%.4f vs %.4f/%.4f)" % (ph, pd, esperado[0], esperado[1]))

    # Modelo desconocido o snapshot de un cron anterior → sin contexto, nadie
    # multiplica ratings de una escala por la constante de otra.
    assert sim_table.snapshot_context(dict(snapshot, strength_model="v9"), .46, .26) is None
    assert sim_table.snapshot_context({k: v for k, v in snapshot.items()
                                       if k != "strength_model"}, .46, .26) is None
    print("consumidores del modelo: predictions y live_tracker usan _match_ph_pd")


def _registros_cliente():
    """Las tablas de liga que viven en el cliente deben cuadrar con config.py.

    `equipo.html` re-simula cuando el snapshot no cuadra con la tabla (partido en
    vivo o resultado que el cron aún no recogió), así que sus p_home/p_draw tienen
    que ser los del cron o la página de equipo y su dashboard dan números distintos
    para el mismo equipo. LaLiga llevaba pDraw 0.25 contra el 0.26 de config."""
    import re
    from .config import LEAGUES

    texto = (ROOT / "equipo.html").read_text(encoding="utf-8")
    vistos = {m[0]: (float(m[1]), float(m[2])) for m in re.findall(
        r"^\s{2}(\w+): \{\n(?:.*?\n)*?\s{4}pHome: ([\d.]+), pDraw: ([\d.]+)",
        texto, re.M)}
    for lg in LEAGUES:
        par = vistos.get(lg["slug"])
        assert par is not None, "equipo.html no conoce la liga %s" % lg["slug"]
        assert par == (lg["p_home"], lg["p_draw"]), (
            "equipo.html %s tiene pHome/pDraw %s y seo/config.py %s"
            % (lg["slug"], par, (lg["p_home"], lg["p_draw"])))
    print("registros cliente: equipo.html cuadra con config.py en las %d ligas"
          % len(LEAGUES))


def _notas_de_zona():
    """El mapeo nota de ESPN → zona debe ser el MISMO en el cron y en las plantillas
    de dashboard. El "relegation playoff" (puesto 16 en ger.1/fra.1/ned.1/por.1) no
    es descenso: `seo/espn.py` lo dejó de contar y `top1.html` siguió contándolo, así
    que el cliente pintaba de rojo un puesto más que el % del cron y que el
    rows.html servido sin JS."""
    from .espn import _note_to_zone

    casos = {"Relegation playoff": "none", "Relegation playoffs": "none",
             "Relegation": "relega", "Relegated": "relega",
             "Champions League": "promo", "Europa League": "europa"}
    for nota, zona in casos.items():
        assert _note_to_zone(nota) == zona, "espn.py: %r → %s" % (nota, _note_to_zone(nota))
    for plantilla in ("top1", "tier2"):
        js = (ROOT / "seo" / "dashboards" / f"{plantilla}.html").read_text(encoding="utf-8")
        linea = [l for l in js.splitlines() if "'relegat'" in l or '"relegat"' in l]
        assert linea and "playoff" in linea[0], (
            "%s.html cuenta el 'relegation playoff' como descenso y espn.py no" % plantilla)
    print("notas de zona: el 'relegation playoff' no es descenso en cron ni cliente")


def main():
    _temporada_terminada()
    _consumidores_del_modelo()
    _registros_cliente()
    _notas_de_zona()
    if not shutil.which("node"):
        print("node no está en el PATH — prueba omitida")
        return 0
    sim = sim_table.simulate(ROWS, P_HOME, P_DRAW, sim_n=SIM_N, ratings=RATINGS)
    py = {r["name"]: 100.0 * sum(sim[r["name"]]["pos_hist"][:2]) / SIM_N for r in ROWS}

    # Snapshot como el que publica seo/snapshots.py (parámetros del modelo ACTIVO).
    snapshot = {
        "total_md": 2 * (len(ROWS) - 1),
        "strength_model": "v2" if USE_ABSOLUTE_RATING else "v1",
        "strength_scale": STRENGTH_SCALE,
        "strength_fade_fraction": STRENGTH_FADE_FRACTION,
        "teams": [dict(r, strength=RATINGS[r["id"]]) for r in ROWS],
    }
    if USE_ABSOLUTE_RATING:
        snapshot.update(strength_scale_abs=STRENGTH_SCALE_ABS,
                        draw_shrink_kappa=DRAW_SHRINK_KAPPA,
                        projection_horizon_fade=PROJECTION_HORIZON_FADE)
    js = _js(snapshot, ROWS)

    peor, quien = 0.0, None
    for r in ROWS:
        d = abs(js[r["name"]] - py[r["name"]])
        if d > peor:
            peor, quien = d, r["name"]
        print("  %-12s cron %5.1f%%   JS %5.1f%%" % (r["name"], py[r["name"]], js[r["name"]]))
    print("\nmodelo %s · mayor diferencia: %.1f puntos (%s)" %
          (snapshot["strength_model"], peor, quien))
    assert peor <= TOLERANCIA, (
        "el fallback JS no reproduce el precálculo del cron (%.1f > %.1f puntos en %s): "
        "¿cambió el modelo en config.py sin portarlo a assets/league-engine.js?"
        % (peor, TOLERANCIA, quien))

    # El motor debe NEGARSE a simular un modelo que no conoce (si no, volvería a
    # inventar porcentajes con otra fórmula).
    futuro = dict(snapshot, strength_model="v3-futuro")
    viejo = {k: v for k, v in snapshot.items() if k != "strength_model"}  # cron anterior
    check = subprocess.run(
        ["node", "-e",
         "const E=require(process.argv[1]);"
         "console.log(JSON.stringify(process.argv.slice(2).map("
         "a => E.canSimulate(JSON.parse(a)))));",
         "--", str(ROOT / "assets" / "league-engine.js"),
         json.dumps(snapshot), json.dumps(futuro), json.dumps(viejo), "null"],
        capture_output=True, text=True, check=True)
    actual, futuro_ok, viejo_ok, sin_snap = json.loads(check.stdout)
    assert actual and sin_snap and not futuro_ok and not viejo_ok, \
        "canSimulate() no discrimina el modelo"
    print("canSimulate: modelo actual sí · desconocido no · snapshot viejo no · sin snapshot sí")
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
