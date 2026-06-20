#!/usr/bin/env bash
# Despliegue del live tracker EN EL SERVIDOR (Oracle VM). Idempotente y seguro:
# instala el servicio systemd y añade el reverse_proxy /api/* al Caddyfile con
# validación + rollback. Ejecutar en el VM:
#   bash /home/ubuntu/predictmotion/live_tracker/deploy.sh
set -euo pipefail

REPO=/home/ubuntu/predictmotion
UNIT=live-tracker.service
CADDY=${CADDYFILE:-/etc/caddy/Caddyfile}

echo "==> 1/3 systemd: instalar y arrancar $UNIT"
sudo cp "$REPO/live_tracker/$UNIT" "/etc/systemd/system/$UNIT"
sudo systemctl daemon-reload
sudo systemctl enable "$UNIT"
sudo systemctl restart "$UNIT"

echo "==> 2/3 Caddy: asegurar 'reverse_proxy /api/* localhost:8770'"
if sudo grep -q "reverse_proxy /api/\*" "$CADDY"; then
  echo "    ya presente, no se toca el Caddyfile"
else
  BAK="$CADDY.bak.$(date +%s)"
  sudo cp "$CADDY" "$BAK"
  echo "    backup en $BAK"
  # Inserta la línea justo antes de 'try_files {path}', conservando la sangría.
  sudo sed -i 's#^\([[:space:]]*\)try_files {path}#\1reverse_proxy /api/* localhost:8770\n\1try_files {path}#' "$CADDY"
  if sudo caddy validate --config "$CADDY" --adapter caddyfile; then
    sudo systemctl reload caddy
    echo "    Caddyfile válido y recargado"
  else
    echo "    !! Caddyfile inválido: restaurando backup"
    sudo cp "$BAK" "$CADDY"
    exit 1
  fi
fi

echo "==> 3/3 smoke test"
sleep 2
sudo systemctl --no-pager --lines=0 status "$UNIT" || true
curl -fsS http://127.0.0.1:8770/api/live/health && echo "  <- live-tracker OK"
echo "==> Listo. Prueba: https://predictmotion.com/api/live/health"
