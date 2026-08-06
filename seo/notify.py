"""Envío de alertas por email (Zoho SMTP) — solo stdlib.

Punto único de envío para las dos alertas de robustez del sitio:
  1. El cron de generate_site falla (0 ligas o excepción) → generate_site.py.
  2. El sitio público no responde → scripts/healthcheck.py.

Principios (ver CLAUDE.md, Principio 2 y sección de incidentes):
  - Cero dependencias: ``smtplib`` + ``email`` son stdlib.
  - Best-effort: si el propio envío falla, se loguea y NO se propaga. Una alerta
    rota no debe tumbar el cron ni el healthcheck.
  - Anti-ruido: dedupe por clave — no reenvía la MISMA alerta si se mandó hace
    menos de ``dedup_hours`` (evita ~8 emails/día si algo está caído todo el día).

Credenciales: variables de entorno, cargadas de un ``.env`` en la raíz del repo
(gitignored). Nunca en git. Ver ``.env.example``.
"""

import json
import os
import smtplib
import ssl
import sys
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_ENV_FILE = ROOT / ".env"
_STATE_FILE = ROOT / "data" / "alerts_state.json"

# Ventana por defecto de dedupe (horas). El cron corre cada 3h; con 6h se manda
# como mucho una alerta cada dos ejecuciones fallidas mientras dure el fallo.
DEDUP_HOURS = 6

_env_loaded = False


def _load_env():
    """Carga ROOT/.env en os.environ (sin pisar variables ya definidas).

    Mini-parser: líneas ``CLAVE=valor``; ignora vacías y ``#``. Sin dependencias.
    """
    global _env_loaded
    if _env_loaded:
        return
    _env_loaded = True
    try:
        text = _ENV_FILE.read_text(encoding="utf-8")
    except OSError:
        return
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = val


def _read_state():
    try:
        return json.loads(_STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write_state(state):
    try:
        _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _STATE_FILE.write_text(json.dumps(state), encoding="utf-8")
    except OSError as e:
        print(f"[notify] no se pudo guardar el estado de alertas: {e}", file=sys.stderr)


def _recently_sent(key, dedup_hours):
    if dedup_hours <= 0:
        return False
    last = _read_state().get(key)
    if not last:
        return False
    try:
        prev = datetime.fromisoformat(last)
    except ValueError:
        return False
    age_h = (datetime.now(timezone.utc) - prev).total_seconds() / 3600.0
    return age_h < dedup_hours


def _mark_sent(key):
    state = _read_state()
    state[key] = datetime.now(timezone.utc).isoformat()
    _write_state(state)


def _send_smtp(subject, body):
    host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    port = int(os.environ.get("SMTP_PORT", "465"))
    # AUTENTICACIÓN: la cuenta SMTP + su app password. Con Gmail, el usuario es la
    # dirección @gmail.com y la password es una "Contraseña de aplicación" (requiere
    # verificación en dos pasos), no la del login normal.
    user = os.environ.get("SMTP_USER")
    pw = os.environ.get("SMTP_PASS")
    # REMITENTE VISIBLE (header From). Con Gmail debe COINCIDIR con el usuario
    # autenticado (o un alias verificado como "Enviar como"); si no, Gmail lo
    # reescribe. Si no se define, se envía desde la propia cuenta.
    sender = os.environ.get("ALERT_FROM") or user
    to = os.environ.get("ALERT_TO")
    if not (user and pw and to):
        print("[notify] faltan credenciales SMTP (SMTP_USER/SMTP_PASS/ALERT_TO);"
              " no se envía el email", file=sys.stderr)
        return False

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = to
    # Date y Message-ID: sin ellas Gmail marca el mensaje como sospechoso (o lo
    # descarta). El Message-ID se ancla al dominio del remitente para no desalinear.
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=sender.split("@")[-1] if "@" in sender else None)
    msg.set_content(body)

    ctx = ssl.create_default_context()
    # Puerto 465 → SSL implícito (SMTP_SSL). Puerto 587 → STARTTLS. Cambiar de uno
    # a otro es solo SMTP_PORT en el .env; si 465 diera 535/handshake, probar
    # 587. El sobre (MAIL FROM) va con `sender`, no con `user`.
    if port == 587:
        with smtplib.SMTP(host, port, timeout=30) as srv:
            srv.ehlo()
            srv.starttls(context=ctx)
            srv.ehlo()
            srv.login(user, pw)
            srv.send_message(msg, from_addr=sender, to_addrs=[to])
    else:
        with smtplib.SMTP_SSL(host, port, timeout=30, context=ctx) as srv:
            srv.login(user, pw)
            srv.send_message(msg, from_addr=sender, to_addrs=[to])
    return True


def send_alert(subject, body, dedup_key=None, dedup_hours=DEDUP_HOURS):
    """Manda una alerta por email. Devuelve True si se envió.

    - ``dedup_key``: clave estable para el anti-ruido (por defecto, el asunto).
      Útil cuando el asunto varía (traceback) pero la alerta es "la misma".
    - ``dedup_hours``: no reenvía la misma clave dentro de esta ventana. 0 lo
      desactiva (p. ej. el healthcheck, que ya dedupea por transición up/down).

    Nunca lanza: cualquier fallo (SMTP, red, credenciales) se loguea a stderr.
    """
    _load_env()
    key = dedup_key or subject
    if _recently_sent(key, dedup_hours):
        print(f"[notify] alerta '{key}' silenciada (enviada hace <{dedup_hours}h)")
        return False
    try:
        sent = _send_smtp(subject, body)
    except Exception as e:  # noqa: BLE001 — best-effort, no debe propagar
        print(f"[notify] fallo al enviar la alerta: {e}", file=sys.stderr)
        return False
    if sent:
        _mark_sent(key)
        print(f"[notify] alerta enviada: {subject}")
    return sent
