"""Guardas de entrada de la API de cuentas (revisión 2026-08-15).

Todo lo que hay aquí falló de verdad antes del endurecimiento, y son fallos que no
se ven mirando la web: hay que provocarlos.

    python3 -m accounts.test_hardening
"""

from __future__ import annotations

import sys
import time

from . import config
from .app import Handler
from .ratelimit import RateLimiter


class _Rutas:
    """Los validadores son métodos que solo usan `self._valid_slug`; instanciar el
    Handler de verdad abriría sockets, así que se toman prestados sobre un doble."""
    def _valid_slug(self, slug):
        return slug == "laliga"
    _valid_team = Handler._valid_team
    _valid_match = Handler._valid_match


def _next(valor):
    return Handler._login_next(None, {"next": valor})


def main():
    origen = "https://predictmotion.com"

    # ── Destino post-login: va a una cabecera Location, es entrada hostil ──
    # CRLF: send_header de CPython NO lo sanea, así que esto inyectaba un
    # Set-Cookie entero en la respuesta (fijación de sesión), sin necesidad de
    # credencial válida.
    assert _next("/cuenta\r\nSet-Cookie: pm_session=X") == "/cuenta"
    assert _next("/cuenta\nX-Falsa: 1") == "/cuenta"
    # Open redirect: el navegador normaliza "\" a "/".
    assert _next("/\\evil.com") == "/cuenta"
    assert _next("//evil.com") == "/cuenta"
    assert _next("https://evil.com") == "/cuenta"
    # De un origen propio se conserva SOLO la ruta; así el localhost que la
    # allowlist trae para el dev cross-port no sirve de destino externo en prod.
    assert _next(origen + "/cuenta") == "/cuenta"
    assert _next("http://localhost:8765/cuenta") == "/cuenta"
    assert _next(origen) == "/"
    # Y el camino normal sigue funcionando.
    assert _next("/siguiendo?x=1") == "/siguiendo?x=1"
    assert _next(None) == "/cuenta"
    # Lo que se devuelve NUNCA puede partir la respuesta en dos.
    for hostil in ("/a\r\nb", "/a\nb", "/a\x7fb", "/\\x", "//x"):
        assert "\r" not in _next(hostil) and "\n" not in _next(hostil)

    # ── Cuerpos JSON que no son objetos ──
    # json.loads("[1]") es truthy, así que el `or {}` de los llamadores no saltaba
    # y el .get() siguiente reventaba con AttributeError → error interno.
    class _Cuerpo:
        _read_json = Handler._read_json
    for crudo, esperado in ((b"[1]", None), (b'"x"', None), (b"5", None),
                            (b'{"a":1}', {"a": 1}), (b"", None), (b"{", None)):
        c = _Cuerpo(); c._raw_body = crudo
        assert c._read_json() == esperado, crudo

    # ── Ids: numéricos ASCII, no "lo que sea" ──
    r = _Rutas()
    assert r._valid_team("83", "laliga")
    assert not r._valid_team("٣٤", "laliga")        # dígitos árabes: isdigit() los daba por buenos
    assert not r._valid_team("²", "laliga")
    assert not r._valid_team("83", "no-existe")
    assert not r._valid_team("8" * 13, "laliga")
    assert r._valid_match("laliga", "401883226")
    assert not r._valid_match("laliga", "../../health")   # inyectaba ruta en la URL interna
    assert not r._valid_match("laliga", "x" * 21)
    assert not r._valid_match("laliga", "")

    # ── Rate limiter: el GC dejaba viva una entrada por IP para siempre ──
    rl = RateLimiter(max_events=5, window_seconds=1)
    assert rl.allow("ip-que-no-vuelve")
    rl._last_gc = 0.0                    # fuerza la pasada de GC en el siguiente allow
    time.sleep(1.05)                     # su único evento queda fuera de la ventana
    assert rl.allow("otra-ip")
    assert "ip-que-no-vuelve" not in rl._events, "el GC debe soltar las IPs que no vuelven"

    # ── Tope de votos: era la única tabla del usuario sin límite ──
    assert isinstance(config.MAX_VOTES, int) and config.MAX_VOTES > 0

    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
