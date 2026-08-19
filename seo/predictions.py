"""Registro append-only de predicciones 1X2 por partido (para Brier / calibración).

Lo escribe el mismo cron que genera los snapshots. Dos ficheros por temporada
(diseño append-only puro, opción A), unidos por `event_id`:

  data/<slug>/<season>/predictions.jsonl  — una fila INMUTABLE por partido, emitida
      UNA vez mientras el partido está por jugar (state 'pre'), con la prob. 1X2 del
      modelo (que ya incorpora el prior de fuerza y el desvanecimiento vigentes) y
      la fuerza de cada equipo. Nunca se reescribe.
  data/<slug>/<season>/results.jsonl      — una fila por partido ya jugado con el
      resultado real. Se añade una vez cuando ESPN lo marca 'post'.

Para calcular el Brier: cargar ambos, unir por `event_id`, comparar (p_home,
p_draw, p_away) con el resultado one-hot. Con esto se calibrarán STRENGTH_SCALE,
STRENGTH_LEVEL_GAP y el punto de desvanecimiento del prior de fuerza.

Todo dentro del pipeline del cron, sin intervención manual (Principio 2).
"""

import json
from datetime import datetime, timezone, timedelta

from . import espn, sim_table
from .config import DATA_DIR

# Ventana de emisión: se registra un partido cuando falta <= N días para el
# saque, así la predicción se emite con un adelanto consistente (≈ la jornada
# inminente) en vez de meses antes con datos que ya no valdrán.
PREDICTION_LEAD_DAYS = 8


def _season_dir(slug, season):
    d = DATA_DIR / slug / season
    d.mkdir(parents=True, exist_ok=True)
    return d


def _logged_ids(path):
    """event_id ya presentes en un .jsonl (para no duplicar)."""
    ids = set()
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                ids.add(json.loads(line)["event_id"])
            except Exception:
                continue
    return ids


def _append(path, obj):
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def _net_strengths(snap):
    """{team_id: att − def} para las filas v3 (el campo `strength` del registro es
    un único número por equipo; en v3 la fuerza es bidimensional, así que se guarda
    la desviación neta como proxy informativo — lo que calibra el Brier son las
    p_home/p_draw/p_away, no este campo)."""
    out = {}
    for t in snap.get("teams", []):
        if t.get("att") is not None:
            out[str(t["id"])] = float(t["att"]) - float(t.get("def") or 0.0)
    return out


def record_matchday(league, snap):
    """Emite predicciones 1X2 de los partidos próximos y rellena resultados de los
    ya jugados. La fuerza sale del snapshot (misma que usó la sim). Best-effort:
    si ESPN falla, no escribe nada y no rompe el cron."""
    slug, season, code = league["slug"], snap["season"], league["espn_code"]
    d = _season_dir(slug, season)
    pred_path = d / "predictions.jsonl"
    res_path = d / "results.jsonl"

    # Fuerza por equipo desde el snapshot (misma que usó la sim); default fondo.
    sc = sim_table.snapshot_context(snap, league["p_home"], league["p_draw"])
    model = snap.get("strength_model")
    # El snapshot trae fuerza pero declara un modelo que este código no tiene
    # compilado → no se EMITEN predicciones nuevas. Las filas son INMUTABLES: mejor
    # ninguna que congelar para siempre probabilidades de una fórmula distinta de la
    # que simuló. Los resultados (paso 2) no dependen del modelo y sí se rellenan.
    skip_emit = model not in (None, "v2", "v3")
    if skip_emit:
        print(f"[predictions] {slug}: strength_model="
              f"{model} desconocido, no se emiten predicciones")
    total_md = int(snap.get("total_md") or 0)
    w = sim_table.fade_weight(int(snap.get("jornada") or 0), total_md) if total_md else 0.0
    net = _net_strengths(snap)

    today = datetime.now(timezone.utc).date()
    issued = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    fmt = lambda dt: dt.strftime("%Y%m%d")

    # 1) Emitir predicciones de los fixtures próximos aún no registrados.
    logged = _logged_ids(pred_path)
    upcoming = [] if skip_emit else espn.fetch_scoreboard_range(
        code, fmt(today), fmt(today + timedelta(days=PREDICTION_LEAD_DAYS)))
    n_new = 0
    for ev in upcoming:
        if ev["state"] != "pre" or ev["event_id"] in logged:
            continue
        hid, aid = str(ev["home"]["id"]), str(ev["away"]["id"])
        # Dispatcher central del 1X2 (v3/v2/uniforme). None → el snapshot no
        # permite este partido (p. ej. un equipo sin att/def en v3): se salta el
        # partido, no la emisión entera.
        m1x2 = sim_table.match_1x2(snap, hid, aid, league["p_home"], league["p_draw"])
        if m1x2 is None:
            continue
        ph, pd, pa = m1x2
        sh = sc["strength"][hid] if sc else net.get(hid, 0.0)
        sa = sc["strength"][aid] if sc else net.get(aid, 0.0)
        _append(pred_path, {
            "event_id": ev["event_id"], "issued_at": issued, "season": season,
            "league": slug, "kickoff": ev["date"],
            "home": {"id": ev["home"]["id"], "name": ev["home"]["name"], "strength": round(sh, 4)},
            "away": {"id": ev["away"]["id"], "name": ev["away"]["name"], "strength": round(sa, 4)},
            "w": round(w, 4), "p_home": ph, "p_draw": pd, "p_away": pa,
            # Con QUÉ modelo se calculó esta fila. Sin esto, distinguir una fila
            # válida de una escrita con la fórmula equivocada exige arqueología de
            # fechas contra el git log (las del 2026-08-11 al 08-15 dicen v1 con el
            # cron ya en v2). La fila es inmutable: que se explique sola.
            "model": model or "uniform",
        })
        logged.add(ev["event_id"])
        n_new += 1

    # 2) Rellenar resultados de partidos ya jugados que tenían predicción.
    predicted = _logged_ids(pred_path)
    resolved = _logged_ids(res_path)
    recent = espn.fetch_scoreboard_range(
        code, fmt(today - timedelta(days=PREDICTION_LEAD_DAYS + 3)), fmt(today))
    n_res = 0
    for ev in recent:
        if (ev["state"] != "post" or ev["event_id"] not in predicted
                or ev["event_id"] in resolved):
            continue
        hs, as_ = ev["home_score"], ev["away_score"]
        if hs is None or as_ is None:
            continue
        result = "home" if hs > as_ else "away" if as_ > hs else "draw"
        _append(res_path, {
            "event_id": ev["event_id"], "resolved_at": issued,
            "result": result, "home_score": hs, "away_score": as_,
        })
        resolved.add(ev["event_id"])
        n_res += 1

    if n_new or n_res:
        print(f"  predicciones: +{n_new} emitidas, +{n_res} resueltas")
