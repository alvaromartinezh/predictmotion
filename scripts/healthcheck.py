#!/usr/bin/env python3
"""Chequeo de disponibilidad Y DE FRESCURA del sitio público — solo stdlib.

Hace un GET a https://predictmotion.com y, si no responde 200, manda un email
(Zoho SMTP, vía seo.notify). Pensado para correr en su propio cron cada 15 min:

    */15 * * * * cd /home/ubuntu/predictmotion && python3 scripts/healthcheck.py >> /home/ubuntu/healthcheck.log 2>&1

Anti-falsas-alarmas:
  - Reintento: si el primer intento falla (≠200, timeout o error de red), espera
    RETRY_DELAY y reintenta UNA vez. Solo si el segundo también falla se
    considera caída. Un timeout aislado no dispara email.
  - Anti-ruido por transición: guarda el último estado (up/down) en disco y solo
    manda email en el CAMBIO up→down (caída) y down→up (recuperación). Mientras
    siga caído no repite.

**Frescura (añadido 2026-10-13).** Un 200 NO significa que el sitio esté vivo:
los dashboards se sirven desde `data/<slug>/latest.json` y el kiosco desde
`data/articles/index.json`, así que si el cron del generador o el de artículos
mueren, la web sigue devolviendo 200 con datos congelados y nadie se entera.
Pasó: el 2026-10-13 el "dato curioso" llevaba 24 h sin publicar (se atascaba en
un kind sin datos) y el único aviso fue una línea en un log que nadie mira. Así
que, cuando el sitio responde, se comprueba la EDAD de los ficheros que alimentan
cada parte y se avisa de los que se han quedado atrás. Umbrales holgados a
propósito (varias pasadas falladas del cron correspondiente, no una), y el
anti-ruido de `notify.send_alert` evita repetir.

Sale con código 0 si el sitio está arriba, 1 si está caído (para el log).
"""

import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from seo import notify  # noqa: E402

URL = "https://predictmotion.com"
TIMEOUT = 10          # segundos por intento
RETRY_DELAY = 30      # segundos de espera antes del reintento
STATE_FILE = ROOT / "data" / "healthcheck_state.json"
DATA_DIR = ROOT / "data"

# Edad máxima tolerada de cada fuente, en horas. Cada umbral son VARIAS pasadas
# falladas del cron que escribe ese fichero, no una: una pasada suelta puede
# fallar por un 403 de ESPN y se recupera sola a la siguiente (ver
# docs/incidentes). No hay umbral para los 4 slugs de selecciones: sus tablas se
# calculan en el cliente y no dejan `latest.json`.
MAX_AGE_H = {
    "ligas":    8,    # seo.generate_site, cron cada 3h  → 8h = 2 pasadas perdidas
    "noticias": 3,    # news.aggregate, cron cada 30 min → 3h = 6 pasadas perdidas
    "articulos": 30,  # articles.generate: el dato curioso publica 7 al día TODOS
                      # los días (no necesita partidos), así que 30h sin tocar el
                      # índice es que algo está roto, parón FIFA incluido.
}


def _probe():
    """Un intento. Devuelve (ok, detalle)."""
    req = urllib.request.Request(URL, method="GET",
                                 headers={"User-Agent": "PredictMotion-healthcheck"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            code = resp.getcode()
            return (code == 200, f"HTTP {code}")
    except Exception as e:  # noqa: BLE001 — timeout, DNS, 5xx… todo cuenta como caída
        return (False, f"{type(e).__name__}: {e}")


def _check():
    """Sonda con un reintento. Devuelve (ok, detalle)."""
    ok, detail = _probe()
    if ok:
        return True, detail
    print(f"[healthcheck] 1er intento falló ({detail}); reintento en {RETRY_DELAY}s")
    time.sleep(RETRY_DELAY)
    ok2, detail2 = _probe()
    return ok2, detail2


def _read_prev_status():
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8")).get("status")
    except (OSError, ValueError):
        return None


def _write_status(status, detail):
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps({
            "status": status,
            "detail": detail,
            "at": datetime.now(timezone.utc).isoformat(),
        }), encoding="utf-8")
    except OSError as e:
        print(f"[healthcheck] no se pudo guardar el estado: {e}", file=sys.stderr)


def _age_h(path):
    """Horas desde la última escritura de `path`; None si no existe."""
    try:
        return (time.time() - path.stat().st_mtime) / 3600.0
    except OSError:
        return None


def _stale():
    """Fuentes de datos que se han quedado atrás. Devuelve [(qué, edad_en_horas)].

    Un fichero que NO EXISTE no se reporta: puede ser una competición que se
    acaba de retirar (política de CLAUDE.md: competición terminada se ELIMINA) o
    una liga que aún no ha generado su primer snapshot. Lo que se vigila es que
    lo que existe siga MOVIÉNDOSE.
    """
    out = []
    for d in sorted(DATA_DIR.glob("*")):
        if not d.is_dir() or d.name in ("articles", "news"):
            continue
        age = _age_h(d / "latest.json")
        if age is not None and age > MAX_AGE_H["ligas"]:
            out.append((d.name, age))
    for nombre, fichero, clave in (("noticias", DATA_DIR / "news" / "latest.json", "noticias"),
                                   ("artículos", DATA_DIR / "articles" / "index.json", "articulos")):
        age = _age_h(fichero)
        if age is not None and age > MAX_AGE_H[clave]:
            out.append((nombre, age))
    return out


def main():
    ok, detail = _check()
    status = "up" if ok else "down"
    prev = _read_prev_status()
    print(f"[healthcheck] {status} ({detail}) — estado previo: {prev}")

    # Email solo en las transiciones (dedupe por estado, sin repetir).
    if not ok and prev != "down":
        notify.send_alert(
            "[PredictMotion] el sitio NO responde",
            f"{URL} no devolvió 200 en dos intentos seguidos.\n\n"
            f"Último detalle: {detail}\n\n"
            "Posibles causas (ver CLAUDE.md, incidentes): Caddy caído (¿nginx "
            "ocupando el :80?) o el servidor. Comprobar:\n"
            "  systemctl status caddy\n"
            "  ss -tlnp | grep :80",
            dedup_hours=0,  # la transición up/down ya evita repetir
        )
    elif ok and prev == "down":
        notify.send_alert(
            "[PredictMotion] el sitio se recuperó",
            f"{URL} vuelve a responder 200 ({detail}).",
            dedup_hours=0,
        )

    # Frescura: solo tiene sentido si el sitio responde (si está caído, el aviso
    # de la caída ya lo cuenta todo y este sería ruido encima).
    if ok:
        viejos = _stale()
        if viejos:
            lineas = "\n".join(f"  - {qué}: {edad:.1f} h sin actualizarse" for qué, edad in viejos)
            print(f"[healthcheck] datos viejos: {', '.join(q for q, _ in viejos)}")
            notify.send_alert(
                "[PredictMotion] el sitio responde pero hay datos CONGELADOS",
                f"{URL} devuelve 200, pero estas fuentes no se actualizan:\n\n{lineas}\n\n"
                f"Umbrales: ligas {MAX_AGE_H['ligas']}h · noticias {MAX_AGE_H['noticias']}h · "
                f"artículos {MAX_AGE_H['articulos']}h.\n\n"
                "Qué mirar (en el servidor):\n"
                "  tail -30 /home/ubuntu/seo_generate.log     # ligas\n"
                "  tail -30 /home/ubuntu/news.log             # noticias\n"
                "  tail -30 /home/ubuntu/articles_stat.log    # artículos\n"
                "  crontab -l; cat /etc/cron.d/predictmotion-articles",
                dedup_key="healthcheck_datos_congelados",
                dedup_hours=12,
            )

    _write_status(status, detail)
    return 0 if ok else 1


def _self_check():
    """`python3 scripts/healthcheck.py --self-check` — comprueba la detección de
    datos congelados sin tocar la red ni mandar correos. Existe porque este
    código solo corre desatendido: si un umbral se rompe, el fallo es SILENCIO
    justo cuando hace falta la alarma, y eso no lo nota nadie."""
    global DATA_DIR
    import tempfile
    real = DATA_DIR
    try:
        with tempfile.TemporaryDirectory() as tmp:
            DATA_DIR = Path(tmp)
            viejo = DATA_DIR / "laliga"; viejo.mkdir()
            nuevo = DATA_DIR / "premier"; nuevo.mkdir()
            (viejo / "latest.json").write_text("{}")
            (nuevo / "latest.json").write_text("{}")
            antiguo = time.time() - (MAX_AGE_H["ligas"] + 2) * 3600
            os.utime(viejo / "latest.json", (antiguo, antiguo))

            nombres = [q for q, _ in _stale()]
            assert nombres == ["laliga"], f"solo la liga vieja debe salir: {nombres}"

            # Una liga SIN latest.json no se reporta (competición retirada).
            (viejo / "latest.json").unlink()
            assert _stale() == [], f"un fichero que no existe no es un dato viejo: {_stale()}"

            # Noticias y artículos, con su propio umbral.
            (DATA_DIR / "news").mkdir(); (DATA_DIR / "articles").mkdir()
            (DATA_DIR / "news" / "latest.json").write_text("{}")
            (DATA_DIR / "articles" / "index.json").write_text("[]")
            viejo_news = time.time() - (MAX_AGE_H["noticias"] + 1) * 3600
            os.utime(DATA_DIR / "news" / "latest.json", (viejo_news, viejo_news))
            nombres = [q for q, _ in _stale()]
            assert nombres == ["noticias"], f"las noticias caducan antes que los artículos: {nombres}"
    finally:
        DATA_DIR = real
    print("[healthcheck] self-check OK")
    return 0


if __name__ == "__main__":
    if "--self-check" in sys.argv:
        sys.exit(_self_check())
    sys.exit(main())
