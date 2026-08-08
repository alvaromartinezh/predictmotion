#!/usr/bin/env python3
"""Backup de la base de datos de usuarios (CP3) — solo stdlib + openssl/git.

A diferencia de todo lo demás en data/, user_data/predictmotion.db contiene datos
de PERSONAS REALES (login, follows) que NO se pueden recalcular desde ESPN. Su
pérdida es irreversible → backup OFF-SITE desde el día uno (lección del incidente
del volumen de arranque, 2026-08-04).

Cada ejecución (cron diario):
  0. Limpia sesiones caducadas (mantenimiento de la DB).
  1. Copia CONSISTENTE en caliente con sqlite3 .backup() (no `cp` del fichero vivo).
  2. gzip + cifrado AES-256 (openssl, passphrase de .env) — el contenido es PII,
     aunque el repo sea privado y el email sea tu propia cuenta.
  3. PRIMARIO: git push a un repo PRIVADO de GitHub (deploy key dedicada), con
     rotación de snapshots.
  4. RESPALDO: email del dump cifrado (por defecto semanal, para no llenar el inbox).
  5. Copia local rotada en user_data/backups/ para restore rápido.
Alerta por email (reusa seo.notify, dedupe por transición) si algo falla; el fallo
de git o de email NO impide el resto de pasos.

Restore: ver docs/backups.md.

Cron (en el servidor):
  30 4 * * * cd /home/ubuntu/predictmotion && python3 scripts/backup_db.py >> /home/ubuntu/backup.log 2>&1
"""

from __future__ import annotations

import gzip
import os
import shutil
import smtplib
import ssl
import subprocess
import sys
import sqlite3
import tempfile
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from seo import notify  # noqa: E402  (reusa el envío de alertas + carga de .env)

# Cargar ROOT/.env ANTES de leer la config de módulo (si no, REPO_DIR/EMAIL_WEEKDAY/
# etc. definidos solo en .env se ignorarían por leerse en tiempo de import).
notify._load_env()


def log(msg):
    print(f"[backup] {datetime.now().isoformat(timespec='seconds')} {msg}", flush=True)


def _env(name, default=None):
    return os.environ.get(name, default)


# ── Configuración (de .env / entorno) ─────────────────────────────────────────
DB_PATH = Path(_env("ACCOUNTS_DB_PATH", ROOT / "user_data" / "predictmotion.db"))
LOCAL_DIR = Path(_env("BACKUP_LOCAL_DIR", ROOT / "user_data" / "backups"))
REPO_DIR = Path(_env("BACKUP_REPO_DIR", "/home/ubuntu/predictmotion-backups"))
KEEP = int(_env("BACKUP_KEEP", "14") or "14")
ENC_ITER = "200000"  # PBKDF2; DEBE coincidir en el descifrado (ver docs/backups.md)
# Email del dump: día de la semana (0=lunes … 6=domingo); -1 = cada ejecución;
# vacío/ausente = desactivado. Por defecto semanal (lunes).
EMAIL_WEEKDAY = _env("BACKUP_EMAIL_WEEKDAY", "0")


def cleanup_sessions():
    """Paso 0: borra sesiones caducadas (mantenimiento; no crítico)."""
    try:
        from accounts import sessions
        n = sessions.cleanup_expired()
        log(f"sesiones caducadas eliminadas: {n}")
    except Exception as e:  # noqa: BLE001
        log(f"aviso: limpieza de sesiones falló (no crítico): {e}")


def make_encrypted_dump(workdir: Path) -> Path:
    """Pasos 1-2: copia consistente → gzip → AES-256. Devuelve el fichero .enc."""
    passphrase = _env("BACKUP_PASSPHRASE")
    if not passphrase:
        raise RuntimeError("falta BACKUP_PASSPHRASE en .env (imprescindible para cifrar)")
    if not DB_PATH.exists():
        raise RuntimeError(f"no existe la DB {DB_PATH}")

    raw = workdir / "predictmotion.db"
    # 1) Copia consistente en caliente (WAL-safe) con la API .backup() de sqlite3.
    src = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    try:
        dst = sqlite3.connect(str(raw))
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()

    # 2a) gzip
    gz = workdir / "predictmotion.db.gz"
    with open(raw, "rb") as fi, gzip.open(gz, "wb") as fo:
        shutil.copyfileobj(fi, fo)

    # 2b) cifrado AES-256 con openssl (passphrase por env, nunca en la línea de comandos)
    enc = workdir / "predictmotion.db.gz.enc"
    env = {**os.environ, "PM_BK_PASS": passphrase}
    subprocess.run(
        ["openssl", "enc", "-aes-256-cbc", "-pbkdf2", "-iter", ENC_ITER, "-salt",
         "-in", str(gz), "-out", str(enc), "-pass", "env:PM_BK_PASS"],
        check=True, env=env, capture_output=True,
    )
    log(f"dump cifrado listo ({enc.stat().st_size} bytes)")
    return enc


def store_local(enc: Path, stamp: str) -> Path:
    """Paso 5: copia local rotada (restore rápido)."""
    LOCAL_DIR.mkdir(parents=True, exist_ok=True)
    dest = LOCAL_DIR / f"predictmotion-{stamp}.db.gz.enc"
    shutil.copy2(enc, dest)
    # rotación: conserva los KEEP más recientes
    files = sorted(LOCAL_DIR.glob("predictmotion-*.db.gz.enc"))
    for old in files[:-KEEP]:
        old.unlink(missing_ok=True)
    log(f"copia local: {dest.name} (conservando {min(len(files), KEEP)})")
    return dest


def push_repo(enc: Path, stamp: str) -> None:
    """Paso 3 (PRIMARIO): git push al repo privado. Best-effort con alerta si falla."""
    if not (REPO_DIR / ".git").exists():
        log(f"aviso: {REPO_DIR} no es un repo git; se omite el push (configúralo, ver docs/backups.md)")
        return
    snaps = REPO_DIR / "snapshots"
    snaps.mkdir(exist_ok=True)
    shutil.copy2(enc, REPO_DIR / "latest.db.gz.enc")
    shutil.copy2(enc, snaps / f"predictmotion-{stamp}.db.gz.enc")
    # rotación de snapshots en el repo
    files = sorted(snaps.glob("predictmotion-*.db.gz.enc"))
    for old in files[:-KEEP]:
        old.unlink(missing_ok=True)

    def git(*args):
        return subprocess.run(["git", *args], cwd=str(REPO_DIR), check=True,
                              capture_output=True, text=True)

    git("add", "-A")
    # commit puede "fallar" si no hay cambios; lo tratamos aparte
    r = subprocess.run(["git", "commit", "-m", f"backup {stamp}"], cwd=str(REPO_DIR),
                       capture_output=True, text=True)
    if r.returncode != 0 and "nothing to commit" not in (r.stdout + r.stderr):
        raise RuntimeError(f"git commit falló: {r.stderr.strip()}")
    git("push", "origin", "HEAD")
    log("push al repo privado OK")


def email_backup(enc: Path, stamp: str) -> None:
    """Paso 4 (RESPALDO): adjunta el dump cifrado por email. Best-effort."""
    if EMAIL_WEEKDAY == "" or EMAIL_WEEKDAY is None:
        return
    try:
        wd = int(EMAIL_WEEKDAY)
    except ValueError:
        return
    if wd != -1 and datetime.now().weekday() != wd:
        return

    host = _env("SMTP_HOST", "smtp.gmail.com")
    port = int(_env("SMTP_PORT", "465"))
    user = _env("SMTP_USER"); pw = _env("SMTP_PASS")
    sender = _env("ALERT_FROM") or user
    to = _env("ALERT_TO")
    if not (user and pw and to):
        log("aviso: sin credenciales SMTP; no se envía el email de respaldo")
        return

    msg = EmailMessage()
    msg["Subject"] = f"[PredictMotion] backup DB {stamp}"
    msg["From"] = sender
    msg["To"] = to
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=sender.split("@")[-1] if "@" in sender else None)
    msg.set_content(
        "Copia de seguridad cifrada de la base de datos de usuarios de PredictMotion.\n"
        f"Fecha: {stamp}\n\n"
        "Para restaurar necesitas la BACKUP_PASSPHRASE (guárdala en tu gestor de\n"
        "contraseñas, NO solo en el servidor). Instrucciones: docs/backups.md.\n"
    )
    with open(enc, "rb") as f:
        msg.add_attachment(f.read(), maintype="application", subtype="octet-stream",
                           filename=f"predictmotion-{stamp}.db.gz.enc")
    ctx = ssl.create_default_context()
    if port == 587:
        with smtplib.SMTP(host, port, timeout=30) as s:
            s.ehlo(); s.starttls(context=ctx); s.ehlo(); s.login(user, pw)
            s.send_message(msg, from_addr=sender, to_addrs=[to])
    else:
        with smtplib.SMTP_SSL(host, port, timeout=30, context=ctx) as s:
            s.login(user, pw); s.send_message(msg, from_addr=sender, to_addrs=[to])
    log("email de respaldo enviado")


def main():
    notify._load_env()  # carga ROOT/.env en os.environ (passphrase, SMTP, repo dir)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    log(f"inicio (stamp={stamp})")
    cleanup_sessions()
    try:
        with tempfile.TemporaryDirectory() as tmp:
            enc = make_encrypted_dump(Path(tmp))
            store_local(enc, stamp)          # local primero (más fiable)
            # git y email son best-effort: si uno falla, se avisa pero no aborta el otro
            errs = []
            for step in (lambda: push_repo(enc, stamp), lambda: email_backup(enc, stamp)):
                try:
                    step()
                except Exception as e:  # noqa: BLE001
                    log(f"ERROR en paso best-effort: {e}")
                    errs.append(str(e))
            if errs:
                notify.send_alert(
                    "[PredictMotion] backup: fallo parcial",
                    "El backup local se hizo, pero fallaron pasos off-site:\n\n- "
                    + "\n- ".join(errs)
                    + "\n\nRevisa /home/ubuntu/backup.log y docs/backups.md.",
                    dedup_key="backup-partial", dedup_hours=20,
                )
        log("fin OK")
    except Exception as e:  # noqa: BLE001 — fallo total (ni siquiera el dump local)
        log(f"FALLO TOTAL: {e}")
        notify.send_alert(
            "[PredictMotion] backup: FALLO TOTAL",
            f"No se pudo generar la copia de seguridad de la DB de usuarios:\n\n{e}\n\n"
            "Los datos de usuarios NO se están respaldando. Revisa /home/ubuntu/backup.log.",
            dedup_key="backup-total", dedup_hours=20,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
