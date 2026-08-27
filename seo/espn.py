"""Cliente de la API pública de ESPN — solo stdlib (urllib).

Mismos endpoints y mismo parseo que el JS del navegador, para que los datos de
partida sean idénticos a los que ve el usuario en el dashboard.
"""

import json
import re
import time
import urllib.error
import urllib.request

_BASE_V2   = "https://site.api.espn.com/apis/v2/sports/soccer"
_BASE_SITE = "https://site.api.espn.com/apis/site/v2/sports/soccer"
# NO poner un User-Agent tipo navegador ("Mozilla/..."): el bot-management de
# ESPN/Cloudflare lo devuelve 403 desde IPs de datacenter (rompió el cron SEO en
# silencio). El UA por defecto de urllib (Python-urllib/x.y) SÍ pasa; por eso
# _HEADERS va vacío (urllib añade su UA por defecto).
_HEADERS   = {}
_TIMEOUT   = 25
_RETRY_BACKOFF_S = 3.0


def _get_json(url):
    """GET + parseo JSON, con 1 reintento si el 403/429/5xx es un blip puntual del
    bot-management de ESPN/Cloudflare y no un bloqueo sostenido (visto 2026-08-27:
    solo 2 de ~15 llamadas a standings fallaron con 403 en la misma pasada del
    cron — las demás, mismo UA, pasaron)."""
    req = urllib.request.Request(url, headers=_HEADERS)
    for attempt in range(2):
        try:
            with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if attempt == 0 and (e.code in (403, 429) or e.code >= 500):
                time.sleep(_RETRY_BACKOFF_S)
                continue
            raise


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
    # Fase de liga UEFA (36 equipos): octavos directos / play-off de eliminatorias /
    # eliminado. Notas: "Qualifies for round of 16", "Knockout phase playoffs -
    # seeded|unseeded", "Eliminated". Estos strings NO aparecen en las ligas
    # domésticas, así que su mapeo aquí no cambia el de ninguna otra liga.
    # 'promo' = zona verde de cabeza (octavos, como Champions en 1ª); reusa
    # derive_bands_from_notes sin lógica nueva.
    if "round of 16" in d:            return "promo"
    if "knockout" in d:               return "playoff"   # play-off de eliminatorias
    if "eliminat" in d:               return "relega"    # eliminado (zona roja de cola)
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
    from .config import TEAM_LOGOS
    url = f"{_BASE_V2}/{espn_code}/standings"
    if season is not None:
        url += f"?season={season}"
    data = _get_json(url)
    entries = data["children"][0]["standings"]["entries"]
    rows = []
    for i, e in enumerate(entries):
        team = e["team"]
        tid = str(team["id"])
        logos = team.get("logos") or []
        rows.append({
            "rank":   i + 1,
            "id":     tid,
            "name":   team["displayName"],
            "abbr":   team.get("abbreviation", ""),
            "logo":   TEAM_LOGOS.get(tid) or (logos[0]["href"] if logos else None),
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


def fetch_roster(espn_code, team_id):
    """Plantilla de un equipo. Port de la lógica del JS (soporta el formato
    plano nuevo — atleta directo con displayName — y el agrupado antiguo).

    Devuelve una lista plana de atletas (cada uno con id/displayName/jersey/…).
    """
    url = f"{_BASE_SITE}/{espn_code}/teams/{team_id}/roster"
    data = _get_json(url)
    athletes = data.get("athletes") or []
    out = []
    for a in athletes:
        if not isinstance(a, dict):
            continue
        if a.get("displayName") is not None:
            out.append(a)
        else:
            for item in (a.get("items") or []):
                out.append(item)
    return out


def fetch_scoreboard_range(espn_code, start_yyyymmdd, end_yyyymmdd, strict=False):
    """Eventos del scoreboard en un rango de fechas (YYYYMMDD-YYYYMMDD),
    normalizados. Best-effort → [] si falla. Usado por el registro de predicciones.
    Cada evento: {event_id, date, kickoff, state, home{id,name}, away{id,name},
    home_score, away_score, venue} (scores None si aún no jugado; venue None si
    ESPN no lo trae). `date` es solo la fecha (YYYY-MM-DD); `kickoff` es el
    timestamp ISO completo (para umbrales de hora).

    `strict=True` PROPAGA el error en vez de devolver []. Para el llamante que
    necesita distinguir "no hay partidos" de "no pude preguntar": tragarse el fallo
    hace que un 403 parezca calma y se congele una fila de calibración a mitad de
    jornada."""
    try:
        data = _get_json(f"{_BASE_SITE}/{espn_code}/scoreboard"
                         f"?dates={start_yyyymmdd}-{end_yyyymmdd}&limit=500")
    except Exception:
        if strict:
            raise
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
            "venue":      (comp.get("venue") or {}).get("fullName"),
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
    from .config import (STRENGTH_LADDERS, STRENGTH_LEVEL_GAP,
                         USE_ABSOLUTE_RATING, STRENGTH_LEVEL_GAP_ABS,
                         PRIOR_SEASONS, PRIOR_DECAY)

    if not current_year:
        return {}
    prev = current_year - 1
    # Modelo v2 (flag): rating absoluto por diferencia de goles/partido (conserva la
    # dominancia). OFF: z-score de puntos de siempre (ruta INTACTA).
    gap = STRENGTH_LEVEL_GAP_ABS if USE_ABSOLUTE_RATING else STRENGTH_LEVEL_GAP
    # Prior multi-temporada (H1): solo el rating absoluto se mezcla (validado offline);
    # el z-score usa 1 temporada como siempre. PRIOR_SEASONS=1 ⇒ salida bit-idéntica.
    n_seasons = PRIOR_SEASONS if USE_ABSOLUTE_RATING else 1
    ratings = {}
    wsum = {}   # peso acumulado por equipo (solo blend absoluto)
    for ladder in STRENGTH_LADDERS:
        if active_codes is not None and not any(c in active_codes for c in ladder):
            continue  # ninguna liga activa usa esta escalera → sin peticiones
        for level, code in enumerate(ladder):
            offset = -level * gap
            if not USE_ABSOLUTE_RATING:
                try:
                    rows = fetch_table(code, season=prev)
                except Exception:
                    continue  # una división falla → se salta; las demás siguen
                if len(rows) < 2:
                    continue
                pts = [r["pts"] for r in rows]
                mean = sum(pts) / len(rows)
                std = (sum((p - mean) ** 2 for p in pts) / len(rows)) ** 0.5
                for r in rows:
                    z = (r["pts"] - mean) / std if std > 0 else 0.0
                    ratings[r["id"]] = z + offset
                continue
            # Rating absoluto, mezclado sobre las últimas n_seasons temporadas. El offset
            # de nivel se aplica por la división de CADA temporada (un equipo pudo alternar
            # 1ª/2ª); los ids de ESPN son globales, así que el blend acumula por equipo.
            for k in range(n_seasons):
                w = PRIOR_DECAY ** k
                try:
                    rows = fetch_table(code, season=prev - k)
                except Exception:
                    continue  # una temporada/división falla → se salta; el resto sigue
                if len(rows) < 2:
                    continue
                for r in rows:
                    gdpg = (r["gf"] - r["gc"]) / max(r["gp"], 1)
                    wsum[r["id"]] = wsum.get(r["id"], 0.0) + w
                    ratings[r["id"]] = ratings.get(r["id"], 0.0) + w * (gdpg + offset)
    if USE_ABSOLUTE_RATING:
        ratings = {tid: ratings[tid] / wsum[tid] for tid in ratings}  # media ponderada
    return ratings


def build_attack_defense(current_year, active_codes=None):
    """Fuerza de ataque/defensa por equipo (v3, Poisson).

    {team_id: {"att": gf/partido, "def": gc/partido}} — blend multi-temporada real
    con el MISMO bucle ladders/season que build_strength_ratings: por división,
    offset de nivel (POISSON_LEVEL_GAP_ATT/DEF) para que un ascendido entre débil
    en 1ª y un descendido fuerte en 2ª. `att`/`def` NO están centrados aquí: la
    media de la liga actual se resta en poisson.league_adjust (los ratings son
    absolutos, comparables solo tras el ajuste). PRIOR_SEASONS/PRIOR_DECAY igual
    que v2.

    Best-effort: una temporada/división que falle se salta; el resto sigue.
    """
    from .config import (STRENGTH_LADDERS, POISSON_LEVEL_GAP_ATT,
                         POISSON_LEVEL_GAP_DEF, PRIOR_SEASONS, PRIOR_DECAY)

    if not current_year:
        return {}
    prev = current_year - 1
    att = {}
    wsum = {}
    for ladder in STRENGTH_LADDERS:
        if active_codes is not None and not any(c in active_codes for c in ladder):
            continue  # ninguna liga activa usa esta escalera → sin peticiones
        for level, code in enumerate(ladder):
            off_att = -level * POISSON_LEVEL_GAP_ATT
            off_def = +level * POISSON_LEVEL_GAP_DEF
            for k in range(PRIOR_SEASONS):
                w = PRIOR_DECAY ** k
                try:
                    rows = fetch_table(code, season=prev - k)
                except Exception:
                    continue  # una temporada/división falla → se salta; el resto sigue
                if len(rows) < 2:
                    continue
                for r in rows:
                    gp = max(r["gp"], 1)
                    a = r["gf"] / gp + off_att
                    d = r["gc"] / gp + off_def
                    wsum[r["id"]] = wsum.get(r["id"], 0.0) + w
                    cur = att.get(r["id"])
                    att[r["id"]] = (cur[0] + w * a, cur[1] + w * d) if cur else (w * a, w * d)
    return {tid: {"att": att[tid][0] / wsum[tid], "def": att[tid][1] / wsum[tid]}
            for tid in att}


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
