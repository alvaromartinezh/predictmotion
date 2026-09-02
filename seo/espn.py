"""Cliente de la API pública de ESPN — solo stdlib (urllib).

Mismos endpoints y mismo parseo que el JS del navegador, para que los datos de
partida sean idénticos a los que ve el usuario en el dashboard.
"""

import datetime
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
    # MLS (usa.1): "Qualifies for MLS Cup Playoffs - Round One Best-of-3 series"
    # (plazas directas) y "- Wild Card Matches" (repesca). Ninguno de los dos
    # strings aparece en las ligas europeas, así que no cambia su mapeo. Van antes
    # que el resto porque ambos contienen "playoffs".
    if "wild card" in d:              return "playoff"
    if "best-of-3" in d or "round one" in d:
        return "promo"
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


def fetch_table(espn_code, season=None, seasontype=None, child=0):
    """Clasificación de una liga regular. Port de fetchStandings().

    Con `season` (año de inicio, p. ej. 2025 → 2025-26) devuelve la tabla FINAL de
    esa temporada pasada (mismo endpoint + ?season=), usado por el prior de fuerza.

    `seasontype`: torneo dentro del año, para las ligas de temporada PARTIDA. Sin
    él, `mex.1?season=2024` y `?season=2025` devuelven LA MISMA tabla (el Clausura
    2025) y el Apertura es inalcanzable. Comprobado 2026-09-02: mex.1 → 1 Apertura /
    8 Clausura; arg.1 → 1 Apertura / 6 Clausura. Ver config.SPLIT_SEASON_TYPES.

    `child`: qué grupo de `children` leer. ESPN sirve **más de uno** en las ligas
    por conferencias o zonas (usa.1 Este/Oeste, arg.1 Group A/B); con el 0 de
    siempre se leería MEDIA LIGA en silencio. Cada zona es su propio slug
    (`mls-este`, `argentina-a`), así que la liga declara su índice con `child` en
    LEAGUES. `child=None` concatena TODOS los grupos: es lo que necesita el prior
    de fuerza, al que solo le importan los equipos y sus goles, no el orden.
    """
    from .config import TEAM_LOGOS
    url = f"{_BASE_V2}/{espn_code}/standings"
    query = [(k, v) for k, v in (("season", season), ("seasontype", seasontype))
             if v is not None]
    if query:
        url += "?" + "&".join(f"{k}={v}" for k, v in query)
    data = _get_json(url)
    children = data.get("children") or []
    if child is None:
        entries = [e for c in children for e in c["standings"]["entries"]]
    else:
        entries = children[child]["standings"]["entries"]
    rows = []
    for i, e in enumerate(entries):
        team = e["team"]
        tid = str(team["id"])
        logos = team.get("logos") or []
        rows.append({
            # El `rank` OFICIAL de ESPN, NO el orden de llegada. En las 15 ligas
            # actuales coinciden (comprobado: rank == i+1 en todas), así que esto
            # es bit-idéntico para ellas; pero hay ligas cuyas entradas NO vienen
            # ordenadas por puntos (usa.1 y arg.1 llegan casi alfabéticas: Chicago
            # 37 pts en el índice 0, Columbus 20 pts en el 1). Con `i + 1` esas
            # ligas salían con la clasificación entera mal, y el error se propagaba
            # al rows.html servido sin JS y a la rama de temporada terminada de
            # sim_table.simulate(), que confía en `rank`.
            "rank":   int(_stat(e, "rank")) or (i + 1),
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
    rows.sort(key=lambda r: r["rank"])
    return rows


def fetch_league_meta(espn_code):
    """Metadatos vivos de la competición desde ESPN (nada hardcodeado).

    Devuelve {'logo':..., 'season':...} (best-effort, valores None si falla).
    - logo: de `leagues[0].logos`, preferida la variante 'dark' (logo claro para
      fondo oscuro); si no, la 'default'.
    - season: de `leagues[0].season.displayName`, extraído como 'YYYY-YY'.
    """
    out = {"logo": None, "season": None, "tournament": None}
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
    # 'YYYY-YY' (ligas europeas: "2026-27 Spanish LALIGA") o 'YYYY' a secas (ligas
    # de año natural: "2026 MLS", "2026 Futebol Brasileiro", "2026 Argentine Liga
    # Profesional de Fútbol"). La alternativa 'YYYY-YY' va PRIMERA para que las 15
    # ligas europeas sigan devolviendo exactamente el mismo valor que antes. Sin
    # esto, _process_table lanza RuntimeError con las ligas de año natural y las
    # salta en TODAS las pasadas del cron, en silencio.
    season = lg.get("season") or {}
    dn = season.get("displayName") or ""
    m = re.search(r"\d{4}-\d{2}|\d{4}", dn)
    if m:
        out["season"] = m.group(0)
    # Torneo vivo de una liga de temporada partida: "Apertura 2026" / "Clausura
    # 2026". El nombre sale de `type.name` ("Torneo Apertura") y el año de
    # `type.abbreviation` ("2026 Liga MX Apertura"), que es el del TORNEO —en mex.1
    # el displayName es "2026-27" pero el Apertura es el de 2026. Sirve de clave de
    # partición: sin él, el Apertura y el Clausura escribirían en la misma carpeta y
    # per_period_series cruzaría sus jornadas, justo lo que la partición evita.
    tipo = season.get("type") or {}
    nombre = (tipo.get("name") or "").strip()
    # Solo las ligas de temporada partida traen "Torneo X"; el resto pone aquí el
    # nombre de la competición ("2026-27 LALIGA", "Regular Season") y no es un
    # torneo. Se exige el prefijo para no inventarse una partición.
    nombre = nombre[len("Torneo"):].strip() if nombre.startswith("Torneo") else ""
    if nombre:
        anio = re.search(r"\d{4}", tipo.get("abbreviation") or "")
        out["tournament"] = f"{nombre} {anio.group(0)}" if anio else nombre
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


def fetch_current_season(espn_code):
    """(año, seasontype) de la competición VIVA según ESPN, best-effort (None, None).

    El `type.id` dice qué torneo se juega ahora en las ligas de temporada partida
    (mex.1 → 1 'Torneo Apertura'; arg.1 → 6 'Torneo Clausura') y el endpoint de
    standings por defecto ya sirve ESE torneo: el ciclo Apertura/Clausura rueda
    solo, sin tocar nada a mano.
    """
    try:
        data = _get_json(f"{_BASE_SITE}/{espn_code}/scoreboard")
    except Exception:
        return None, None
    season = (data.get("leagues") or [{}])[0].get("season") or {}
    try:
        year = int(season.get("year"))
    except (TypeError, ValueError):
        year = None
    try:
        stype = int((season.get("type") or {}).get("id"))
    except (TypeError, ValueError):
        stype = None
    return year, stype


def fetch_current_season_year(espn_code):
    """Año de inicio de la temporada actual (p. ej. 2026 para 2026-27), de ESPN."""
    return fetch_current_season(espn_code)[0]


def prior_tournaments(espn_code, current_year, current_type, count):
    """Los `count` torneos ya TERMINADOS de una liga, del más reciente al más
    antiguo, como pares (season, seasontype) para `fetch_table`.

    Liga normal (no está en SPLIT_SEASON_TYPES) → [(Y-1, None), (Y-2, None), …],
    exactamente lo de siempre. Liga de temporada partida → recorre los torneos
    hacia atrás saltándose el que está en juego, así el blend multi-temporada son
    los 3 últimos TORNEOS y no tres veces la misma tabla.
    """
    from .config import SPLIT_SEASON_TYPES

    order = SPLIT_SEASON_TYPES.get(espn_code)   # tipos en orden cronológico del año
    if not order:
        return [(current_year - 1 - k, None) for k in range(count)]
    # Posición del torneo vivo dentro del año; si ESPN no lo dice, se empieza por
    # el último del año en curso.
    idx = order.index(current_type) if current_type in order else len(order)
    out, year = [], current_year
    while len(out) < count and year > current_year - count - 2:
        idx -= 1
        if idx < 0:
            year -= 1
            idx = len(order) - 1
        out.append((year, order[idx]))
    return out


def build_strength_ratings(current_year, active_codes=None, season_by_code=None):
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

    `season_by_code`: {code: (año, seasontype)} de la temporada VIVA de esa liga,
    para las que no siguen el calendario europeo. `current_year` sale de UNA sola
    llamada (la primera liga de la lista, europea) y se desfasa medio año con las de
    año natural: en marzo de 2027, esp.1 sigue en season.year=2026 (la 2026-27)
    mientras el Brasileirão ya va por el 2027, así que su prior pediría 2025 en vez
    de 2026. El `seasontype` además identifica el torneo vivo en las ligas de
    temporada partida, para que `prior_tournaments` empiece por el anterior. Ver
    config.CALENDAR_YEAR_CODES y SPLIT_SEASON_TYPES.

    Best-effort y robusto: si el fetch de una temporada previa falla (p. ej. 403),
    esa división se salta; el resto sigue.
    """
    from .config import (STRENGTH_LADDERS, STRENGTH_LEVEL_GAP,
                         USE_ABSOLUTE_RATING, STRENGTH_LEVEL_GAP_ABS,
                         PRIOR_SEASONS, PRIOR_DECAY)

    if not current_year:
        return {}
    season_by_code = season_by_code or {}
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
            year, stype = season_by_code.get(code, (current_year, None))
            # child=None: fusiona TODOS los grupos. En usa.1/arg.1 el prior con el
            # grupo 0 solo dejaría a media liga sin rating (y con el default de
            # fondo de tabla de resolve_strengths).
            temporadas = prior_tournaments(code, year, stype, n_seasons)
            if not USE_ABSOLUTE_RATING:
                try:
                    rows = fetch_table(code, season=temporadas[0][0],
                                       seasontype=temporadas[0][1], child=None)
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
            for k, (yr, st) in enumerate(temporadas):
                w = PRIOR_DECAY ** k
                try:
                    rows = fetch_table(code, season=yr, seasontype=st, child=None)
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


def build_attack_defense(current_year, active_codes=None, season_by_code=None):
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
    season_by_code = season_by_code or {}   # ver build_strength_ratings
    att = {}
    wsum = {}
    for ladder in STRENGTH_LADDERS:
        if active_codes is not None and not any(c in active_codes for c in ladder):
            continue  # ninguna liga activa usa esta escalera → sin peticiones
        for level, code in enumerate(ladder):
            off_att = -level * POISSON_LEVEL_GAP_ATT
            off_def = +level * POISSON_LEVEL_GAP_DEF
            year, stype = season_by_code.get(code, (current_year, None))
            for k, (yr, st) in enumerate(
                    prior_tournaments(code, year, stype, PRIOR_SEASONS)):
                w = PRIOR_DECAY ** k
                try:
                    rows = fetch_table(code, season=yr, seasontype=st, child=None)
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


# Topes de la API del scoreboard, ambos COMPROBADOS contra ESPN (2026-09-02):
# un rango de fechas de más de 365 días devuelve 400 Bad Request, y sin `limit`
# el corte está en 100 eventos (esp.1: 100 con el default, 350 con limit=1000).
_SCOREBOARD_MAX_DAYS = 364
_SCOREBOARD_LIMIT    = 1000


def fetch_remaining_schedules(espn_code, today=None):
    """Próximos partidos ('pre') de TODOS los equipos: {team_id: [partidos]}.

    UNA sola llamada al scoreboard con rango de fechas, en lugar de una llamada por
    equipo al endpoint /teams/<id>/schedule. Eran ~20-36 peticiones por liga, ~300
    por pasada del cron: con diferencia la mayor fuente de tráfico contra ESPN y de
    exposición a los 403 del bot-management (ver docs/incidentes). Ahora son 15, una
    por liga. El scoreboard devuelve la temporada restante ENTERA (comprobado:
    esp.1 → 350 eventos, todos 'pre', hasta 2027-05-30).

    Cada partido aparece en la lista de SUS DOS equipos, con `home` relativo a cada
    uno. Las listas van ordenadas por fecha (el endpoint por equipo ya venía en
    orden cronológico y la página de equipo las pinta tal cual).

    Best-effort: si falla devuelve {} y las páginas de equipo salen sin calendario,
    igual que antes cuando fallaba el fetch por equipo. Nunca inventa partidos.
    """
    today = today or datetime.date.today()
    end = today + datetime.timedelta(days=_SCOREBOARD_MAX_DAYS)
    url = (f"{_BASE_SITE}/{espn_code}/scoreboard"
           f"?limit={_SCOREBOARD_LIMIT}&dates={today:%Y%m%d}-{end:%Y%m%d}")
    try:
        data = _get_json(url)
    except Exception:
        return {}
    out = {}
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
        date = ev.get("date", "")[:10]
        for side, opp, is_home in ((home, away, True), (away, home, False)):
            tid = str(side["team"].get("id", ""))
            if not tid:
                continue
            out.setdefault(tid, []).append({
                "date":     date,
                "opponent": opp["team"].get("displayName", ""),
                "opp_id":   str(opp["team"].get("id", "")),
                "home":     is_home,
            })
    for sched in out.values():
        sched.sort(key=lambda m: m["date"])
    return out
