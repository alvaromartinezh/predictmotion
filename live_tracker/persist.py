"""Persistencia en disco de partidos finalizados.

Cuando un partido termina (state 'post') se guarda su detalle normalizado en
JSON, para poder mostrarlo después (todo lo del directo, ya finalizado) sin
depender de que ESPN siga sirviendo ese summary. Snapshots gitignored: viven solo
en el servidor, como los de seo/.
"""

from __future__ import annotations

import json
import logging
import os

from . import config

log = logging.getLogger("live_tracker.persist")


def _path(league: str, event_id: str) -> str:
    safe = "".join(c for c in str(event_id) if c.isalnum() or c in "-_")
    return os.path.join(config.DATA_DIR, league, safe + ".json")


def exists(league: str, event_id: str) -> bool:
    return os.path.isfile(_path(league, event_id))


def save(detail) -> None:
    """Guarda el dict normalizado del partido (idempotente)."""
    p = _path(detail.league, detail.id)
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(detail.to_dict(), f, ensure_ascii=False)
        os.replace(tmp, p)   # escritura atómica
    except Exception as e:
        log.warning("no se pudo persistir %s/%s: %s", detail.league, detail.id, e)


def load(league: str, event_id: str):
    """Devuelve el dict guardado o None."""
    p = _path(league, event_id)
    if not os.path.isfile(p):
        return None
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        log.warning("no se pudo leer %s/%s: %s", league, event_id, e)
        return None
