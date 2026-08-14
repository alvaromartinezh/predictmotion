"""Rate limiter en memoria (ventana deslizante) — solo stdlib.

Defensa en profundidad para /api/auth (anti-abuso del login). El servicio es un
único proceso (ThreadingHTTPServer, varios hilos) → un dict con lock basta; no hay
estado que compartir entre procesos. Se auto-limpia de claves vacías.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque


class RateLimiter:
    def __init__(self, max_events: int, window_seconds: int):
        self.max = max_events
        self.window = window_seconds
        self._events: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()
        self._last_gc = 0.0

    def allow(self, key: str) -> bool:
        """True si `key` puede hacer otra petición; False si excede el límite."""
        now = time.time()
        cutoff = now - self.window
        with self._lock:
            dq = self._events[key]
            while dq and dq[0] < cutoff:
                dq.popleft()
            if len(dq) >= self.max:
                return False
            dq.append(now)
            # GC ocasional. Se borra por ANTIGÜEDAD, no solo las deques vacías: una
            # deque solo se poda dentro de allow() de esa misma clave, así que una IP
            # que entra una vez y no vuelve dejaba su entrada para siempre y el dict
            # crecía una por cliente durante toda la vida del servicio.
            if now - self._last_gc > 60:
                self._last_gc = now
                for k in [k for k, d in self._events.items() if not d or d[-1] < cutoff]:
                    del self._events[k]
            return True
