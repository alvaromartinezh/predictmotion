"""Registro de calibración de probabilidades de ZONA por jornada completa.

Complementa a `predictions.py` (Brier 1X2 por partido). Aquí guardamos, una vez
por jornada, las probabilidades de zona de ese momento (ascenso/playoff/descenso
y título, o champions/europa/conference/descenso/título según la liga) para poder
medir MÁS ADELANTE si esas probabilidades de zona calibran bien con el tiempo.

Fichero por temporada:  data/<slug>/<season>/zone_predictions.jsonl
  — una fila por jornada N (= max(gp)), con los % de zona de cada equipo.

Disparador (opción C, "upsert"):
  - N = max(gp), N >= 1  (snap["jornada"]).
  - "Calma": ningún partido `in` (en juego) ahora y ningún saque en la próxima
    hora. Margen pequeño (KICKOFF_MARGIN_MINUTES) ligado a la cadencia del cron
    (cada 3h), NO a una asunción sobre el calendario de fútbol (que es asimétrico
    y cambia cada semana por Copa/competición europea/TV).
  - En cada pasada de calma se REESCRIBE (upsert) la fila de N con los % actuales.

Por qué upsert y no append-inmutable: una jornada se reparte de viernes a lunes,
así que max(gp) llega a N en cuanto TERMINA EL PRIMER partido de la jornada; la
primera calma (p. ej. sábado de madrugada) sería a MITAD de jornada. Reescribiendo
en cada calma, la última foto antes de que max(gp) avance a N+1 es la de fin de
ronda (o "lo más completa posible" si hay un aplazado en el aire — Supercopa, etc.,
donde el desajuste de gp dura meses y es la norma, no la excepción).

Cierre inmutable: max(gp) es monótono no decreciente, así que en cuanto avanza a
N+1 ninguna pasada futura vuelve a tener max(gp)==N → la fila N queda CONGELADA.
Garantías: exactamente una fila por jornada (upsert por N), nunca cero salvo huecos
de calma de pocas horas (que alguna pasada de 3h captura), nunca más de una.

Todo dentro del pipeline del cron, best-effort (si ESPN falla, no escribe ni rompe).
"""

import json
from datetime import datetime, timezone, timedelta

from . import espn, snapshots
from .config import DATA_DIR, SIM_N_TABLE

# Margen de seguridad ligado a la cadencia del cron (3h), no al calendario: si hay
# un saque dentro de esta ventana, la ronda podría estar arrancando → esperamos.
KICKOFF_MARGIN_MINUTES = 60


def _season_dir(slug, season):
    d = DATA_DIR / slug / season
    d.mkdir(parents=True, exist_ok=True)
    return d


def _parse_kickoff(s):
    """ISO de ESPN ('2026-02-01T13:00Z') → datetime tz-aware. None si no parsea."""
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def _is_calm(espn_code):
    """True si no hay ningún partido en juego ahora ni ningún saque en la próxima
    hora. Rango de 3 días (ayer..mañana) para cubrir directos y saques cercanos con
    holgura de zona horaria.

    Si el scoreboard FALLA, NO es calma. Se invoca tras un fetch_table OK, pero ese
    va a /apis/v2/…/standings y este a /apis/site/v2/…/scoreboard: el incidente del
    2026-08-05 mostró que ESPN puede tirar una ruta y no la otra. Como
    fetch_scoreboard_range devuelve [] ante cualquier error, un 403 se leía como
    'no hay partidos' y se escribía la fila con probabilidades de media jornada —
    que queda CONGELADA para siempre si max(gp) avanza justo después."""
    now = datetime.now(timezone.utc)
    today = now.date()
    fmt = lambda d: d.strftime("%Y%m%d")
    try:
        events = espn.fetch_scoreboard_range(
            espn_code, fmt(today - timedelta(days=1)), fmt(today + timedelta(days=1)),
            strict=True)
    except Exception as e:
        print(f"[zone_predictions] {espn_code}: scoreboard no disponible ({e}); "
              f"no se toca la fila de esta jornada")
        return False
    margin = now + timedelta(minutes=KICKOFF_MARGIN_MINUTES)
    for ev in events:
        if ev.get("state") == "in":
            return False
        if ev.get("state") == "pre":
            ko = _parse_kickoff(ev.get("kickoff"))
            if ko is not None and ko <= margin:
                return False
    return True


def _load_rows(path):
    """{jornada: fila} desde el .jsonl (últimas ganan si hubiera duplicados)."""
    rows = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                rows[obj["jornada"]] = obj
            except Exception:
                continue
    return rows


def _write_rows(path, rows_by_jornada):
    """Reescribe el fichero ordenado por jornada. Las filas de jornadas distintas de
    la que se está upsertando se conservan tal cual (congeladas)."""
    lines = [json.dumps(rows_by_jornada[j], ensure_ascii=False)
             for j in sorted(rows_by_jornada)]
    # Atómica (tmp+rename): es una reescritura ENTERA del fichero en cada pasada de
    # calma, y sus filas de jornadas pasadas están congeladas y no se pueden
    # regenerar. Morir a mitad de write_text (OOM del pool de 4, kill del cron,
    # disco lleno) se llevaba por delante el histórico de calibración de la
    # temporada, sin aviso.
    snapshots._write_atomic(path, "\n".join(lines) + ("\n" if lines else ""))


def record_jornada(league, snap):
    """Upsert de la fila de la jornada N (= max(gp)) con los % de zona actuales, si
    estamos en un hueco de calma. Best-effort. Solo ligas de tabla (kind 'table')."""
    if snap.get("kind") != "table":
        return
    slug, season = league["slug"], snap["season"]
    n = snap.get("jornada", 0)
    if n < 1:
        return
    if not _is_calm(league["espn_code"]):
        return

    # Zonas = bandas de la clasificación + título (acabar 1º). Se excluye el interno
    # del play-off (pSemi/pFinal/pWin), que no son zonas de clasificación.
    zone_keys = [b["key"] for b in snap.get("bands", [])] + ["first"]
    teams = []
    for t in snap["teams"]:
        prob = t.get("prob", {})
        teams.append({
            "id": t["id"], "name": t["name"], "rank": t["rank"], "pts": t["pts"],
            "prob": {k: prob.get(k, 0.0) for k in zone_keys},
        })

    row = {
        "jornada": n,
        "season": season,
        "league": slug,
        "recorded_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sim_n": SIM_N_TABLE,
        "teams": teams,
    }

    path = _season_dir(slug, season) / "zone_predictions.jsonl"
    rows = _load_rows(path)
    existed = n in rows
    rows[n] = row                       # upsert (se congela cuando max(gp) avance)
    _write_rows(path, rows)
    print(f"  zona: jornada {n} {'actualizada' if existed else 'nueva'} "
          f"({len(teams)} equipos)")
