"""Autocomprobación de seo.espn._get_json: reintento de un 403/429/5xx puntual,
sin reintentar (ni retrasar) un error permanente. python3 -m seo.test_espn"""

import io
import urllib.error
import urllib.request

from seo import espn


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def demo():
    real_urlopen = urllib.request.urlopen
    real_sleep = espn.time.sleep
    calls = []
    slept = []
    espn.time.sleep = lambda s: slept.append(s)

    # 1) 403 en el primer intento, 200 en el segundo → reintenta y devuelve el JSON.
    def _flaky(req, timeout=None):
        calls.append(1)
        if len(calls) == 1:
            raise urllib.error.HTTPError(req.full_url, 403, "Forbidden", {}, None)
        return _Resp(b'{"ok": true}')

    urllib.request.urlopen = _flaky
    try:
        assert espn._get_json("https://x") == {"ok": True}
        assert len(calls) == 2, "debe reintentar una vez tras el 403"
        assert slept == [espn._RETRY_BACKOFF_S]
    finally:
        urllib.request.urlopen = real_urlopen

    # 2) 404 (permanente) → no reintenta, propaga en el primer intento.
    calls.clear(); slept.clear()

    def _perm(req, timeout=None):
        calls.append(1)
        raise urllib.error.HTTPError(req.full_url, 404, "Not Found", {}, None)

    urllib.request.urlopen = _perm
    try:
        try:
            espn._get_json("https://x")
            assert False, "un 404 debe propagar"
        except urllib.error.HTTPError as e:
            assert e.code == 404
        assert len(calls) == 1, "un fallo permanente no reintenta"
        assert not slept
    finally:
        urllib.request.urlopen = real_urlopen
        espn.time.sleep = real_sleep

    print("seo.test_espn: OK")


if __name__ == "__main__":
    demo()
