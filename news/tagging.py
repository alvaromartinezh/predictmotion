"""Etiquetado automático de noticias por liga/equipo — sin NLP.

Estrategia de dos niveles, de más fiable a menos:
  1. <category> del feed: los tres medios traen el nombre del equipo como
     categoría ("Getafe CF", "FC Barcelona", "F.C. Barcelona"). Match directo.
  2. Match de alias sobre título + resumen: alias derivados EN VIVO de ESPN
     (nombre oficial + "core" sin CF/FC/CD… + motes coloquiales de config).

La tabla de alias se construye desde ESPN (sin hardcode: se actualiza con
ascensos/descensos). Cualquier alias que apunte a >1 equipo se DESCARTA
(auto-pruning de colisiones → sin falsos positivos por ambigüedad).

Es HEURÍSTICO y está pendiente de ajuste fino (mismo espíritu que los params de
fuerza del Monte Carlo): se prioriza no etiquetar antes que etiquetar mal.
"""

import re
import unicodedata

from .config import COLLOQUIAL_ALIASES, LEAGUES
from seo import espn

# Tokens de tipo de club que se quitan para obtener el "core" del nombre.
# NO se quita "real"/"de"/"atletico" (romperían "Real Madrid", "Atlético de
# Madrid"…). "de" sí se colapsa dentro del core multi-palabra.
_CLUB_TOKENS = {"cf", "fc", "cd", "ud", "rc", "rcd", "sd", "ca", "club", "sad", "afc"}
_MIN_ALIAS_LEN = 4       # descarta alias demasiado cortos (ruido)


def _norm(s):
    """minúsculas, sin acentos, sin puntuación, espacios colapsados.

    Los PUNTOS se eliminan sin dejar espacio (no se espacian) para que las siglas
    con puntos de los medios ("F.C. Barcelona", "R.C.D. Mallorca", "C.A. Osasuna")
    colapsen a "fc barcelona"/"rcd mallorca"/… y el stripping de tokens de club
    las reduzca al mismo core que el nombre de ESPN."""
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower().replace(".", "")
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _core(norm_name):
    """Nombre normalizado sin los tokens de tipo de club."""
    toks = [t for t in norm_name.split() if t not in _CLUB_TOKENS]
    return " ".join(toks).strip()


def build_alias_index():
    """{alias_normalizado: {'id','name','slug'}} para todos los equipos de las
    ligas de interés. Best-effort: si una liga falla en ESPN, se salta.

    Devuelve también la lista de equipos por si el caller la quiere.
    """
    teams = []          # {id, name, slug, norm, core}
    for slug, code in LEAGUES.items():
        try:
            # child=None: fusiona todos los grupos. usa.1 y arg.1 sirven la tabla
            # por conferencia/zona y con el grupo 0 se indexaría media liga.
            rows = espn.fetch_table(code, child=None)
        except Exception:
            continue    # una liga sin datos (p. ej. pretemporada) → se salta
        for r in rows:
            norm = _norm(r["name"])
            teams.append({
                "id": r["id"], "name": r["name"], "slug": slug,
                "norm": norm, "core": _core(norm),
            })

    # alias → set de ids (para detectar colisiones)
    alias_to_ids = {}
    team_by_id = {t["id"]: t for t in teams}

    def add(alias, tid):
        a = _norm(alias)
        if len(a) < _MIN_ALIAS_LEN:
            return
        alias_to_ids.setdefault(a, set()).add(tid)

    for t in teams:
        add(t["norm"], t["id"])       # nombre oficial completo
        add(t["core"], t["id"])       # core sin CF/FC/…
        # motes coloquiales: si la clave aparece en el nombre normalizado
        for key, motes in COLLOQUIAL_ALIASES.items():
            if _norm(key) in t["norm"]:
                for m in motes:
                    add(m, t["id"])

    # Descarta colisiones: un alias que apunta a >1 equipo es ambiguo.
    index = {}
    for alias, ids in alias_to_ids.items():
        if len(ids) == 1:
            tid = next(iter(ids))
            index[alias] = team_by_id[tid]
    return index


def _match_categories(cats, index):
    """Equipos detectados por las <category> del feed (exacto o por core)."""
    found = {}
    for c in cats:
        n = _norm(c)
        t = index.get(n) or index.get(_core(n))
        if t:
            found[t["id"]] = t
    return found


def _match_text(text, index):
    """Equipos detectados en texto libre (título+resumen) por límite de palabra."""
    n = _norm(text)
    found = {}
    for alias, t in index.items():
        # \b sobre alias ya normalizado (solo [a-z0-9 ]); word-boundary evita
        # substrings (p. ej. 'betis' dentro de otra palabra).
        if re.search(r"\b" + re.escape(alias) + r"\b", n):
            found[t["id"]] = t
    return found


def tag_item(item, index):
    """Añade item['teams'] y item['leagues'] (in-place) y devuelve el item.

    Prioridad: categorías del feed > match en texto. La liga sale de los equipos
    detectados; si no hay ninguno, se usa league_hint del feed (Marca por liga)."""
    teams = _match_categories(item.get("categories", []), index)
    if not teams:
        teams = _match_text(item["title"] + " " + item.get("summary", ""), index)

    item["teams"] = [
        {"id": t["id"], "name": t["name"], "slug": t["slug"]}
        for t in teams.values()
    ]
    leagues = sorted({t["slug"] for t in teams.values()})
    if not leagues and item.get("league_hint"):
        leagues = [item["league_hint"]]
    item["leagues"] = leagues
    return item
