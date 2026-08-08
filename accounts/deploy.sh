#!/usr/bin/env bash
# Despliegue del servicio de cuentas EN EL SERVIDOR (Oracle VM). Idempotente:
# instala el servicio systemd y añade al Caddyfile los reverse_proxy de las rutas
# de cuentas (:8771), con validación + rollback. Ejecutar en el VM:
#   bash /home/ubuntu/predictmotion/accounts/deploy.sh
#
# Nota: en CP0 el servicio se despliega A OSCURAS (ACCOUNTS_ENABLED=false por
# defecto). /api/health responde igual; el resto devuelve "disabled".
set -euo pipefail

REPO=/home/ubuntu/predictmotion
UNIT=accounts.service
CADDY=${CADDYFILE:-/etc/caddy/Caddyfile}

echo "==> 1/3 systemd: instalar y arrancar $UNIT"
sudo cp "$REPO/accounts/$UNIT" "/etc/systemd/system/$UNIT"
sudo systemctl daemon-reload
sudo systemctl enable "$UNIT"
sudo systemctl restart "$UNIT"

echo "==> 2/3 Caddy: asegurar reverse_proxy de las rutas de cuentas -> :8771"
# Las rutas específicas de cuentas deben ir ANTES de try_files. /api/live/* (:8770)
# lo gestiona el deploy del live_tracker; aquí solo añadimos las de cuentas.
ROUTES=(
  "reverse_proxy /api/auth/* localhost:8771"
  "reverse_proxy /api/me localhost:8771"
  "reverse_proxy /api/follows/* localhost:8771"
  "reverse_proxy /api/account localhost:8771"
)

NEED_RELOAD=0
BAK="$CADDY.bak.$(date +%s)"
for ROUTE in "${ROUTES[@]}"; do
  # Marca única e inequívoca por ruta (la parte del path).
  MATCH=$(printf '%s' "$ROUTE" | awk '{print $2}')
  if sudo grep -qF "$MATCH localhost:8771" "$CADDY"; then
    echo "    ya presente: $MATCH"
    continue
  fi
  if [ "$NEED_RELOAD" -eq 0 ]; then
    sudo cp "$CADDY" "$BAK"
    echo "    backup en $BAK"
  fi
  NEED_RELOAD=1
  # Inserta la línea justo antes de 'try_files {path}', conservando la sangría.
  sudo sed -i "s#^\([[:space:]]*\)try_files {path}#\1${ROUTE}\n\1try_files {path}#" "$CADDY"
  echo "    añadida: $ROUTE"
done

if [ "$NEED_RELOAD" -eq 1 ]; then
  if sudo caddy validate --config "$CADDY" --adapter caddyfile; then
    sudo systemctl reload caddy
    echo "    Caddyfile válido y recargado"
  else
    echo "    !! Caddyfile inválido: restaurando backup"
    sudo cp "$BAK" "$CADDY"
    exit 1
  fi
else
  echo "    todas las rutas ya presentes, no se toca el Caddyfile"
fi

echo "==> 3/3 smoke test"
sleep 2
sudo systemctl --no-pager --lines=0 status "$UNIT" || true
curl -fsS http://127.0.0.1:8771/api/health && echo "  <- accounts OK"
echo "==> Listo. Prueba: https://predictmotion.com/api/health"
