"""Autocomprobación de seo.espn: reintento de un 403/429/5xx puntual sin reintentar
un error permanente, parseo de la temporada, orden de la clasificación y calendario
restante en bloque. python3 -m seo.test_espn"""

import datetime
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

    _check_season_label()
    _check_table_rank()
    _check_remaining_schedules()

    print("seo.test_espn: OK")


def _fake_json(payload, seen=None):
    """Sustituye _get_json por uno que devuelve `payload` y anota la URL pedida."""
    def _f(url):
        if seen is not None:
            seen.append(url)
        return payload
    return _f


def _check_season_label():
    """fetch_league_meta debe sacar la temporada tanto de 'YYYY-YY' (ligas europeas)
    como de 'YYYY' a secas (ligas de año natural). Sin lo segundo, _process_table
    lanza RuntimeError y salta esas ligas en TODAS las pasadas del cron."""
    real = espn._get_json
    casos = [
        ("2026-27 Spanish LALIGA",                     "2026-27"),  # las 15 de hoy
        ("2026-27 Liga BBVA MX",                       "2026-27"),
        ("2026 MLS",                                   "2026"),
        ("2026 Futebol Brasileiro",                    "2026"),
        ("2026 Argentine Liga Profesional de Fútbol",  "2026"),
        ("sin año",                                    None),
    ]
    try:
        for dn, esperado in casos:
            espn._get_json = _fake_json({"leagues": [{"season": {"displayName": dn}}]})
            got = espn.fetch_league_meta("x")["season"]
            assert got == esperado, f"{dn!r} → {got!r}, esperaba {esperado!r}"
    finally:
        espn._get_json = real


def _entry(tid, name, rank, pts):
    return {"team": {"id": tid, "displayName": name, "abbreviation": name[:3]},
            "stats": [{"name": "rank", "value": float(rank)},
                      {"name": "points", "value": float(pts)},
                      {"name": "gamesPlayed", "value": 1.0}]}


def _check_table_rank():
    """fetch_table debe usar el `rank` OFICIAL y ORDENAR por él: usa.1 y arg.1
    sirven las entradas casi alfabéticas, no por puntos."""
    real = espn._get_json
    try:
        # Entradas desordenadas (como MLS) → se reordenan por rank real.
        payload = {"children": [{"standings": {"entries": [
            _entry("1", "Chicago", 3, 37), _entry("2", "Columbus", 15, 20),
            _entry("3", "Cincinnati", 1, 45),
        ]}}]}
        espn._get_json = _fake_json(payload)
        rows = espn.fetch_table("usa.1")
        assert [r["name"] for r in rows] == ["Cincinnati", "Chicago", "Columbus"]
        assert [r["rank"] for r in rows] == [1, 3, 15]

        # Sin stat `rank` (tabla degradada) → se cae al orden de llegada, como antes.
        sin_rank = {"children": [{"standings": {"entries": [
            {"team": {"id": "9", "displayName": "A"}, "stats": []},
            {"team": {"id": "8", "displayName": "B"}, "stats": []},
        ]}}]}
        espn._get_json = _fake_json(sin_rank)
        rows = espn.fetch_table("x")
        assert [r["name"] for r in rows] == ["A", "B"]
        assert [r["rank"] for r in rows] == [1, 2]
    finally:
        espn._get_json = real


def _check_remaining_schedules():
    """Una llamada por liga: el partido debe aparecer en los DOS equipos con su
    `home` relativo, ordenado por fecha, y solo los 'pre'."""
    real = espn._get_json
    seen = []

    def ev(date, hid, hname, aid, aname, state="pre"):
        return {"date": date + "T19:00Z", "competitions": [{
            "status": {"type": {"state": state}},
            "competitors": [
                {"homeAway": "home", "team": {"id": hid, "displayName": hname}},
                {"homeAway": "away", "team": {"id": aid, "displayName": aname}},
            ]}]}

    payload = {"events": [
        ev("2026-10-01", "10", "Local", "20", "Visita"),
        ev("2026-09-01", "20", "Visita", "10", "Local"),
        ev("2026-08-01", "10", "Local", "30", "Otro", state="post"),  # jugado → fuera
    ]}
    try:
        espn._get_json = _fake_json(payload, seen)
        out = espn.fetch_remaining_schedules("esp.1", today=datetime.date(2026, 9, 2))

        assert set(out) == {"10", "20"}, "el partido va en los dos equipos"
        assert "30" not in out, "los 'post' no cuentan"
        # Ordenado por fecha, no por orden de llegada.
        assert [m["date"] for m in out["10"]] == ["2026-09-01", "2026-10-01"]
        # `home` relativo a cada equipo.
        assert [m["home"] for m in out["10"]] == [False, True]
        assert [m["home"] for m in out["20"]] == [True, False]
        assert out["10"][1]["opponent"] == "Visita"

        # La URL debe llevar `limit` (sin él ESPN corta en 100) y un rango de como
        # mucho 365 días (más devuelve 400 Bad Request).
        url = seen[0]
        assert f"limit={espn._SCOREBOARD_LIMIT}" in url, url
        assert "dates=20260902-" in url, url
        ini, fin = url.split("dates=")[1].split("-")
        span = (datetime.datetime.strptime(fin, "%Y%m%d").date()
                - datetime.datetime.strptime(ini, "%Y%m%d").date()).days
        assert span <= 365, f"rango de {span} días: ESPN devuelve 400"

        # Fallo de red → {} (best-effort), las páginas de equipo salen sin calendario.
        def _boom(url):
            raise RuntimeError("caído")
        espn._get_json = _boom
        assert espn.fetch_remaining_schedules("esp.1") == {}
    finally:
        espn._get_json = real


if __name__ == "__main__":
    demo()
