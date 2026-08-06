#!/usr/bin/env python3
"""Chequeo simple de disponibilidad del sitio público — solo stdlib.

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

Sale con código 0 si el sitio está arriba, 1 si está caído (para el log).
"""

import json
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

    _write_status(status, detail)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
