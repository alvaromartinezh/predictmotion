"""Fotos de jugador (recortes transparentes TheSportsDB) — caché incremental.

ESPN apenas publica headshots de futbolistas (~3% de los rosters). TheSportsDB
expone `strCutout` (PNG sin fondo) para muchos más. Como TheSportsDB ya no reparte
keys personales gratis (la free es la pública compartida '123', ~30 req/min global
y SIN endpoint de plantilla), la cobertura se construye de forma incremental y
reanudable dentro del cron/pipeline (Principio 2): se cachea por id ESPN de atleta
(estable entre temporadas) en `data/player_cuts.json` (gitignored).

Contrato del JSON (append-only, key = id ESPN del atleta):
  { "<athlete_id>": {"u": "https://…/cutout.png" | null, "t": <epoch última consulta>} }
  - `u: null` = no encontrado en TheSportsDB → se re-intenta pasados RE_PROBE_DAYS
    (la DB es colaborativa y va creciendo).
  - Con `u` presente no se vuelve a consultar (ids y URLs estables).

Concurrencia: el fichero de lock (flock) hace que el backfill manual y el cron no
pisen el presupuesto compartido de TheSportsDB a la vez. Si el backfill muere, el
lock se libera solo y el cron retoma.

Uso:
  python3 -m seo.player_cuts [--backfill] [--league <slug>] [--limit N] [--dry-run]
"""

import fcntl
import json
import os
import re
import sys
import time
import unicodedata
import urllib.parse
import urllib.request

from . import espn

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_PATH = os.path.join(ROOT, "data", "player_cuts.json")
LOCK_PATH = os.path.join(ROOT, "data", "player_cuts.lock")

_BASE = "https://www.thesportsdb.com/api/v1/json/123"
_TIMEOUT = 25
# La key libre es compartida globalmente (~30 req/min): 2,5 s entre peticiones
# ≈ 24 req/min propios, con backoff si TheSportsDB devuelve 429.
SLEEP = 2.5
BACKOFF_S = 8.0
RE_PROBE_DAYS = 30
# Límite por ejecución de mantenimiento dentro del cron (protege el presupuesto
# compartido y el tiempo de la ejecución). El backfill pasa limit=None (hasta
# terminar todo).
DEFAULT_LIMIT = 200
_SAVE_EVERY = 25

# Tokens de nombre de equipo que no desambigüan (no se usan para el match).
_IGNORE_TOKENS = {"fc", "cf", "cd", "sd", "sc", "ac", "de", "del", "club", "football", "team"}


def _norm(s):
    s = unicodedata.normalize("NFD", (s or "").lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", "", s)


def _team_tokens(name):
    toks = set()
    for w in re.split(r"[^a-z0-9]+", (name or "").lower()):
        if len(w) > 2 and w not in _IGNORE_TOKENS:
            toks.add(w)
    return toks


def _team_matches(tsdb_team, espn_team):
    """¿El nombre de equipo de TheSportsDB y el de ESPN comparten algún token
    significativo? (p. ej. "Albacete Balompié" ↔ "Albacete")."""
    a = _team_tokens(tsdb_team)
    b = _team_tokens(espn_team)
    return bool(a & b)


def load_cache():
    try:
        with open(CACHE_PATH) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_cache(cache):
    os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
    tmp = CACHE_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(cache, f, separators=(",", ":"))
    os.replace(tmp, CACHE_PATH)


def _get_json(url):
    req = urllib.request.Request(url)  # UA por defecto de urllib (mismo gotcha que ESPN)
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


def lookup_cutout(name, espn_team):
    """Busca en TheSportsDB el cutout (PNG transparente) de un jugador.

    Devuelve la URL o None. El emparejamiento es CONSERVADOR (mejor sin foto que
    foto del jugador equivocado): se exige nombre normalizado exacto y, si hay
    varias coincidencias o la única no casa con el equipo, se descarta.
    """
    q = urllib.parse.quote(name)
    try:
        data = _get_json(f"{_BASE}/searchplayers.php?p={q}")
    except Exception:
        raise
    players = data.get("player") or []
    exact = [p for p in players if _norm(p.get("strPlayer")) == _norm(name)]
    if not exact:
        return None
    hits = [p for p in exact if _team_matches(p.get("strTeam"), espn_team)]
    if len(hits) == 1:
        return hits[0].get("strCutout")
    if len(exact) == 1 and not exact[0].get("strTeam"):
        # Sin dato de equipo: aceptamos el único resultado exacto.
        return exact[0].get("strCutout")
    return None


def _collect(leagues):
    """Recorre las plantillas de todas las ligas y devuelve la lista de atletas
    pendientes de consultar: [(athlete_id, name, team_name)]."""
    todo = []
    for league in leagues:
        slug = league["slug"]
        code = league["espn_code"]
        try:
            table = espn.fetch_table(code)
        except Exception as exc:
            print(f"  [{slug}] tabla no disponible: {exc}")
            continue
        for team in table:
            try:
                athletes = espn.fetch_roster(code, team["id"])
            except Exception as exc:
                print(f"  [{slug}] roster {team['name']}: {exc}")
                continue
            for a in athletes:
                aid = str(a.get("id") or "")
                if not aid:
                    continue
                name = a.get("displayName") or ""
                if not name:
                    continue
                todo.append((aid, name, team["name"]))
    return todo


def run(leagues, limit=DEFAULT_LIMIT, dry_run=False):
    """Una pasada del mantenimiento de fotos. Lanza las consultas que falten hasta
    `limit` (None = backfill, hasta terminar todo el trabajo pendiente)."""
    cache = load_cache()

    # Lock: si el backfill (o este mismo cron) ya está corriendo, se omite. flock
    # se libera solo si el proceso muere → el cron retoma automáticamente.
    lock = open(LOCK_PATH, "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("player_cuts: otro proceso en curso (backfill activo), se omite.")
        return 0

    todo = []
    for aid, name, team in _collect(leagues):
        entry = cache.get(aid)
        if entry is None:
            todo.append((aid, name, team))
        elif entry.get("u") is None and entry.get("t", 0) < time.time() - RE_PROBE_DAYS * 86400:
            todo.append((aid, name, team))  # re-probar los "no encontrado" viejos

    print(f"player_cuts: {len(cache)} en caché, {len(todo)} pendientes de consultar "
          f"(límite={limit if limit else '∞'})")
    done = 0
    found = 0
    for aid, name, team in todo:
        if limit is not None and done >= limit:
            break
        done += 1
        if dry_run:
            continue
        for attempt in range(3):
            try:
                u = lookup_cutout(name, team)
                break
            except Exception:
                if attempt == 2:
                    u = None  # fallo de red → no cachear, reintentará otro día
                    break
                time.sleep(BACKOFF_S)
        if u:
            found += 1
        cache[aid] = {"u": u, "t": int(time.time())}
        if not dry_run and done % _SAVE_EVERY == 0:
            save_cache(cache)
        if not dry_run:
            print(f"  [{done}/{len(todo)}] {name} → {'FOTO' if u else '—'}")
            sys.stdout.flush()
        time.sleep(SLEEP)

    if not dry_run:
        save_cache(cache)
    print(f"player_cuts: fin — {done} consultadas ({found} con foto). "
          f"Total en caché: {len(cache)}.")
    return done


def main(argv=None):
    import argparse

    from .config import LEAGUES, league_by_slug

    ap = argparse.ArgumentParser()
    ap.add_argument("--backfill", action="store_true",
                    help="Limpia todo el trabajo pendiente (sin límite por pasada)")
    ap.add_argument("--league", help="Solo esta liga (slug)")
    ap.add_argument("--limit", type=int, default=None,
                    help="Máx. consultas en esta pasada (def: None → todas)")
    ap.add_argument("--dry-run", action="store_true", help="No consulta ni escribe")
    args = ap.parse_args(argv)

    leagues = [league_by_slug(args.league)] if args.league else LEAGUES
    if args.league and not leagues[0]:
        print(f"Liga desconocida: {args.league}", file=sys.stderr)
        return 1
    leagues = [lg for lg in leagues if lg]

    limit = None if args.backfill else (args.limit if args.limit is not None else DEFAULT_LIMIT)
    return run(leagues, limit=limit, dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
