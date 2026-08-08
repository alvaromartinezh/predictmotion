# Backups de la base de datos de usuarios (CP3)

`user_data/predictmotion.db` (login con Google + follows) es el **único dato del
sitio que NO se puede recalcular** desde ESPN. Su pérdida es irreversible, así que
tiene backup **off-site** desde el primer día (lección del incidente del volumen de
arranque, 2026-08-04).

## Qué hace el backup (`scripts/backup_db.py`, cron diario)

0. Limpia sesiones caducadas (mantenimiento de la DB).
1. Copia **consistente en caliente** con `sqlite3 .backup()` (no `cp` del fichero vivo).
2. **gzip + cifrado AES-256** (`openssl`, passphrase de `.env`).
3. **PRIMARIO:** `git push` a un repo **privado** de GitHub (`predictmotion-backups`)
   con una **deploy key** dedicada. Guarda `latest.db.gz.enc` + `snapshots/…` rotados.
4. **RESPALDO:** email del dump cifrado (por defecto **semanal**, lunes) a `ALERT_TO`.
5. Copia **local rotada** en `user_data/backups/` (restore rápido).

Si falla un paso off-site, manda **alerta por email** (reusa `seo/notify.py`, dedupe)
pero no aborta los demás. El fichero es de pocos KB.

## ⚠️ La passphrase (imprescindible para restaurar)

`BACKUP_PASSPHRASE` (en el `.env` del servidor) cifra el dump. **Guárdala también
FUERA del servidor** (tu gestor de contraseñas). Si el servidor se pierde y la
passphrase solo vivía ahí, **los backups off-site son indescifrables**. El repo y el
email guardan el dump cifrado; la passphrase nunca se sube a ninguno de los dos.

## Restaurar (probado)

Necesitas: un `*.db.gz.enc` (del repo privado, del email, o de `user_data/backups/`)
y la `BACKUP_PASSPHRASE`.

```bash
# 1) descifrar (mismo -iter que al cifrar: 200000)
openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 \
  -in predictmotion-YYYYMMDD-HHMMSS.db.gz.enc -out restored.db.gz -pass pass:'LA_PASSPHRASE'
# 2) descomprimir
gunzip restored.db.gz          # -> restored.db
# 3) verificar
sqlite3 restored.db "PRAGMA integrity_check;"   # debe decir: ok
# 4) poner en su sitio (con el servicio parado para no pisar el WAL)
sudo systemctl stop accounts
cp restored.db /home/ubuntu/predictmotion/user_data/predictmotion.db
rm -f /home/ubuntu/predictmotion/user_data/predictmotion.db-wal \
      /home/ubuntu/predictmotion/user_data/predictmotion.db-shm
sudo systemctl start accounts
curl -fsS http://127.0.0.1:8771/api/health
```

## Alta del repo privado + deploy key (one-shot, ya hecho)

1. En GitHub: **New repository** → nombre `predictmotion-backups` → **Private** →
   sin README → Create.
2. **Deploy key** (Settings → Deploy keys → Add deploy key): pegar la clave pública
   de `~/.ssh/predictmotion_backups_key.pub` (generada en el servidor) y **marcar
   "Allow write access"**.
3. En el servidor, `~/.ssh/config`:
   ```
   Host github-backups
     HostName github.com
     User git
     IdentityFile ~/.ssh/predictmotion_backups_key
     IdentitiesOnly yes
   ```
4. Clonar con el alias (así `git push` usa la deploy key):
   ```
   git clone github-backups:USUARIO/predictmotion-backups.git /home/ubuntu/predictmotion-backups
   ```

## Cron (servidor)

```
30 4 * * * cd /home/ubuntu/predictmotion && python3 scripts/backup_db.py >> /home/ubuntu/backup.log 2>&1
```

## Variables (`.env` del servidor)

- `BACKUP_PASSPHRASE` — passphrase AES (imprescindible; guárdala también off-server).
- `BACKUP_REPO_DIR` — clon del repo de backups (def. `/home/ubuntu/predictmotion-backups`).
- `BACKUP_KEEP` — nº de snapshots a conservar local y en el repo (def. 14).
- `BACKUP_EMAIL_WEEKDAY` — día del email de respaldo (0=lunes … 6=domingo; `-1` cada
  ejecución; vacío = desactivado). Def. 0.
- Reusa `SMTP_*` / `ALERT_TO` de las alertas.
