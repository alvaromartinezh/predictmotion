"""Caché en memoria + poller en hilo de fondo.

El servidor sirve SIEMPRE desde caché (nunca bloquea esperando a ESPN). El poller
descubre qué partidos están en vivo (scoreboard) y refresca su detalle (summary)
cada LIVE_POLL_SECONDS. Si una llamada a la fuente falla, se conserva la última
copia buena marcada `stale` y se loguea, sin tirar nada.
"""

from __future__ import annotations

import logging
import threading
import time

from . import config, persist
from .providers.base import MatchDataProvider

log = logging.getLogger("live_tracker.cache")


class LiveStore:
    def __init__(self, provider: MatchDataProvider):
        self.provider = provider
        self._matches: dict[str, tuple[float, list]] = {}      # league -> (ts, [Match])
        self._details: dict[tuple, tuple[float, object]] = {}  # (league,id) -> (ts, MatchDetail)
        self._post_seen: dict[tuple, float] = {}   # (league,id) -> ts en que se vio 'post'
        self._post_refreshed: set = set()          # claves ya re-guardadas tras el final
        self._lock = threading.RLock()
        self._stop = threading.Event()

    # ── lectura (la usa el servidor) ──────────────────────────────────────────

    def get_matches(self, league: str):
        with self._lock:
            entry = self._matches.get(league)
        now = time.time()
        if entry and now - entry[0] < config.SCOREBOARD_POLL_SECONDS * 2:
            return entry[1]
        return self._refresh_matches(league)

    def get_detail(self, league: str, event_id: str):
        """Devuelve el dict normalizado del partido (listo para servir) o None.
        Orden: caché en memoria (fresca) → disco (partido finalizado guardado) →
        fetch a la fuente."""
        key = (league, event_id)
        with self._lock:
            entry = self._details.get(key)
        if entry and time.time() - entry[0] < config.DETAIL_TTL_SECONDS:
            return entry[1].to_dict()
        # Partidos finalizados ya persistidos: se sirven de disco (no cambian).
        disk = persist.load(league, event_id)
        if disk is not None:
            return disk
        md = self._refresh_detail(league, event_id)
        return md.to_dict() if md else None

    # ── refresco (defensivo) ──────────────────────────────────────────────────

    def _refresh_matches(self, league: str):
        try:
            matches = self.provider.list_matches(league)
            with self._lock:
                self._matches[league] = (time.time(), matches)
            return matches
        except Exception as e:
            log.warning("scoreboard %s falló: %s", league, e)
            with self._lock:
                entry = self._matches.get(league)
            return entry[1] if entry else []

    def _refresh_detail(self, league: str, event_id: str):
        key = (league, event_id)
        try:
            detail = self.provider.get_match(league, event_id)
            with self._lock:
                self._details[key] = (time.time(), detail)
            # Partido finalizado → se guarda para poder mostrarlo después. Se
            # persiste siempre que lo traemos en 'post' (sobrescribe): así el
            # refresco tardío captura las stats que ESPN consolida tras el final.
            if detail.status.state == "post":
                persist.save(detail)
            return detail
        except Exception as e:
            log.warning("summary %s/%s falló: %s", league, event_id, e)
            with self._lock:
                entry = self._details.get(key)
            if entry:
                entry[1].stale = True
                return entry[1]
            return None

    def _handle_finished(self, league: str, event_id: str, now: float):
        """Persistencia de un partido finalizado: una vez al verlo terminar y una
        segunda vez pasados FINAL_REFRESH_SECONDS (para capturar las stats que ESPN
        consolida tras el pitido final)."""
        key = (league, event_id)
        if not persist.exists(league, event_id):
            self._refresh_detail(league, event_id)     # primera vez → guarda
            self._post_seen[key] = now
        elif key not in self._post_refreshed:
            seen = self._post_seen.setdefault(key, now)  # si reinició, cuenta desde ahora
            if now - seen >= config.FINAL_REFRESH_SECONDS:
                self._refresh_detail(league, event_id)   # re-guarda (consolidado)
                self._post_refreshed.add(key)

    # ── poller en hilo de fondo ───────────────────────────────────────────────

    def start_poller(self):
        t = threading.Thread(target=self._poll_loop, name="live-poller", daemon=True)
        t.start()
        return t

    def stop(self):
        self._stop.set()

    def _poll_loop(self):
        log.info("poller arrancado (scoreboard cada %ss, detalle en vivo cada %ss)",
                 config.SCOREBOARD_POLL_SECONDS, config.LIVE_POLL_SECONDS)
        last_scoreboard = 0.0
        while not self._stop.is_set():
            now = time.time()
            live_ids = []
            # Scoreboard de cada liga (descubrir partidos en vivo y recién finalizados).
            if now - last_scoreboard >= config.SCOREBOARD_POLL_SECONDS:
                for league in config.LEAGUES:
                    matches = self._refresh_matches(league)
                    for m in matches:
                        if m.status.state == "in":
                            live_ids.append((league, m.id))
                        elif m.status.state == "post":
                            self._handle_finished(league, m.id, now)
                last_scoreboard = now
            else:
                # Reusar la lista en vivo conocida de la caché.
                with self._lock:
                    for league, (_, matches) in self._matches.items():
                        for m in matches:
                            if m.status.state == "in":
                                live_ids.append((league, m.id))
            # Refrescar el detalle de los partidos en vivo.
            for league, eid in live_ids:
                if self._stop.is_set():
                    break
                self._refresh_detail(league, eid)
            self._stop.wait(config.LIVE_POLL_SECONDS)
