"""Cliente de la API pública de ESPN — solo stdlib (urllib).

Mismos endpoints y mismo parseo que el JS del navegador, para que los datos de
partida sean idénticos a los que ve el usuario en el dashboard.
"""

import json
import re
import urllib.request

_BASE_V2   = "https://site.api.espn.com/apis/v2/sports/soccer"
_BASE_SITE = "https://site.api.espn.com/apis/site/v2/sports/soccer"
# NO poner un User-Agent tipo navegador ("Mozilla/..."): el bot-management de
# ESPN/Cloudflare lo devuelve 403 desde IPs de datacenter (rompió el cron SEO en
# silencio). El UA por defecto de urllib (Python-urllib/x.y) SÍ pasa; por eso
# _HEADERS va vacío (urllib añade su UA por defecto).
_HEADERS   = {}
_TIMEOUT   = 25


def _get_json(url):
    req = urllib.request.Request(url, headers=_HEADERS)
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _stat(entry, name):
    for s in entry.get("stats", []):
        if s.get("name") == name:
            return s.get("value") or 0
    return 0


def _note_to_zone(desc):
    """Nota de ESPN (note.description) → zona interna. Port de noteToZone() del JS.

    Cubre 1ª división (Champions/Europa/Conference/Relegation) y 2ª división
    europea (Promotion / Promotion playoffs / Relegation). El 'promo' vale para la
    plaza top de cada nivel (Champions en 1ª, ascenso directo en 2ª): cada liga
    define su etiqueta; derive_bands_from_notes solo empareja el string de zona.
    """
    d = (desc or "").lower()
    # 2ª división: ascenso directo vs play-off de ascenso (comprobar antes que el
    # resto; ninguna nota de 1ª contiene "promotion").
    if "promotion" in d:  return "playoff" if "playoff" in d else "promo"
    # Descenso directo. El "relegation playoff" (playoff de permanencia) NO es zona
    # de descenso → no se marca (queda 'none'); comprobar el playoff primero.
    if "relegat" in d:    return "none" if "playoff" in d else "relega"
    if "champion" in d:   return "promo"
    if "europa" in d:     return "europa"
    if "conference" in d: return "conf"
    return "none"


def fetch_table(espn_code, season=None):
    """Clasificación de una liga regular. Port de fetchStandings().

    Con `season` (año de inicio, p. ej. 2025 → 2025-26) devuelve la tabla FINAL de
    esa temporada pasada (mismo endpoint + ?season=), usado por el prior de fuerza.
    """
    url = f"{_BASE_V2}/{espn_code}/standings"
    if season is not None:
        url += f"?season={season}"
    data = _get_json(url)
    entries = data["children"][0]["standings"]["entries"]
    rows = []
    for i, e in enumerate(entries):
        team = e["team"]
        logos = team.get("logos") or []
        rows.append({
            "rank":   i + 1,
            "id":     str(team["id"]),
            "name":   team["displayName"],
            "abbr":   team.get("abbreviation", ""),
            "logo":   logos[0]["href"] if logos else None,
            "zone":   _note_to_zone((e.get("note") or {}).get("description")),
            "gp":     int(_stat(e, "gamesPlayed")),
            "pts":    int(_stat(e, "points")),
            "gf":     int(_stat(e, "pointsFor")),
            "gc":     int(_stat(e, "pointsAgainst")),
            "wins":   int(_stat(e, "wins")),
            "draws":  int(_stat(e, "ties")),
            "losses": int(_stat(e, "losses")),
        })
    return rows


def fetch_league_meta(espn_code):
    """Metadatos vivos de la competición desde ESPN (nada hardcodeado).

    Devuelve {'logo':..., 'season':...} (best-effort, valores None si falla).
    - logo: de `leagues[0].logos`, preferida la variante 'dark' (logo claro para
      fondo oscuro); si no, la 'default'.
    - season: de `leagues[0].season.displayName`, extraído como 'YYYY-YY'.
    """
    out = {"logo": None, "season": None}
    try:
        data = _get_json(f"{_BASE_SITE}/{espn_code}/scoreboard")
    except Exception:
        return out
    lg = (data.get("leagues") or [{}])[0]
    logos = lg.get("logos") or []
    if logos:
        dark = next((l for l in logos if "dark" in (l.get("rel") or [])), None)
        href = (dark or logos[0]).get("href")
        if href and href.startswith("http://"):
            href = "https://" + href[len("http://"):]
        out["logo"] = href
    dn = (lg.get("season") or {}).get("displayName") or ""
    m = re.search(r"\d{4}-\d{2}", dn)
    if m:
        out["season"] = m.group(0)
    return out


def fetch_scoreboard_range(espn_code, start_yyyymmdd, end_yyyymmdd):
    """Eventos del scoreboard en un rango de fechas (YYYYMMDD-YYYYMMDD),
    normalizados. Best-effort → [] si falla. Usado por el registro de predicciones.
    Cada evento: {event_id, date, kickoff, state, home{id,name}, away{id,name},
    home_score, away_score} (scores None si aún no jugado). `date` es solo la fecha
    (YYYY-MM-DD); `kickoff` es el timestamp ISO completo (para umbrales de hora)."""
    try:
        data = _get_json(f"{_BASE_SITE}/{espn_code}/scoreboard"
                         f"?dates={start_yyyymmdd}-{end_yyyymmdd}&limit=500")
    except Exception:
        return []

    def _score(c):
        try:
            return int(c.get("score"))
        except (TypeError, ValueError):
            return None

    out = []
    for ev in data.get("events", []):
        comp = (ev.get("competitions") or [{}])[0]
        cs = comp.get("competitors", [])
        home = next((c for c in cs if c.get("homeAway") == "home"), None)
        away = next((c for c in cs if c.get("homeAway") == "away"), None)
        if not home or not away:
            continue
        state = (((ev.get("status") or {}).get("type")) or {}).get("state")
        out.append({
            "event_id":   str(ev.get("id")),
            "date":       (ev.get("date") or "")[:10],
            "kickoff":    ev.get("date") or "",
            "state":      state,
            "home":       {"id": str(home["team"]["id"]), "name": home["team"].get("displayName", "")},
            "away":       {"id": str(away["team"]["id"]), "name": away["team"].get("displayName", "")},
            "home_score": _score(home),
            "away_score": _score(away),
        })
    return out


def fetch_current_season_year(espn_code):
    """Año de inicio de la temporada actual (p. ej. 2026 para 2026-27), de ESPN.

    Best-effort: None si falla. Se usa para pedir la temporada previa (year-1).
    """
    try:
        data = _get_json(f"{_BASE_SITE}/{espn_code}/scoreboard")
    except Exception:
        return None
    year = ((data.get("leagues") or [{}])[0].get("season") or {}).get("year")
    try:
        return int(year)
    except (TypeError, ValueError):
        return None


def build_strength_ratings(current_year, active_codes=None):
    """Rating de fuerza por equipo desde la tabla FINAL de la temporada anterior.

    Recorre las escaleras de país (STRENGTH_LADDERS): dentro de cada escalera,
    z-score de puntos por división + un offset de nivel por división
    (STRENGTH_LEVEL_GAP), de modo que la cabeza de la 2ª cae en el tercio bajo de
    la 1ª. Fusiona todas las escaleras en un único {team_id: R} (los ids de ESPN
    son globales y estables entre temporadas/divisiones, así que un
    ascendido/descendido conserva su rating aunque cambie de división).

    `active_codes`: si se pasa, solo se procesan las escaleras que contienen alguna
    liga activa → no se descargan temporadas previas de países que no se generan.
    Con None se procesan todas (compatibilidad).

    Best-effort y robusto: si el fetch de una temporada previa falla (p. ej. 403),
    esa división se salta; el resto sigue.
    """
    from .config import STRENGTH_LADDERS, STRENGTH_LEVEL_GAP

    if not current_year:
        return {}
    prev = current_year - 1
    ratings = {}
    for ladder in STRENGTH_LADDERS:
        if active_codes is not None and not any(c in active_codes for c in ladder):
            continue  # ninguna liga activa usa esta escalera → sin peticiones
        for level, code in enumerate(ladder):
            try:
                rows = fetch_table(code, season=prev)
            except Exception:
                continue  # una división falla → se salta; las demás siguen
            pts = [r["pts"] for r in rows]
            n = len(pts)
            if n < 2:
                continue
            mean = sum(pts) / n
            var = sum((p - mean) ** 2 for p in pts) / n
            std = var ** 0.5
            offset = -level * STRENGTH_LEVEL_GAP
            for r in rows:
                z = (r["pts"] - mean) / std if std > 0 else 0.0
                ratings[r["id"]] = z + offset
    return ratings


def fetch_remaining_schedule(espn_code, team_id):
    """Próximos partidos de un equipo (estado 'pre').

    Best-effort: si falla o no hay datos, devuelve []. Nunca inventa partidos.
    """
    try:
        data = _get_json(f"{_BASE_SITE}/{espn_code}/teams/{team_id}/schedule")
    except Exception:
        return []
    out = []
    for ev in data.get("events", []):
        comp = (ev.get("competitions") or [{}])[0]
        status = (comp.get("status") or ev.get("status") or {}).get("type", {})
        if status.get("state") != "pre":
            continue
        competitors = comp.get("competitors", [])
        home = next((c for c in competitors if c.get("homeAway") == "home"), None)
        away = next((c for c in competitors if c.get("homeAway") == "away"), None)
        if not home or not away:
            continue
        is_home = str(home["team"]["id"]) == str(team_id)
        opp = away if is_home else home
        out.append({
            "date":     ev.get("date", "")[:10],
            "opponent": opp["team"].get("displayName", ""),
            "opp_id":   str(opp["team"].get("id", "")),
            "home":     is_home,
        })
    return out
