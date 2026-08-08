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
# IMPORTANTE (orden en un bloque route{}): el bloque route ejecuta las directivas
# EN EL ORDEN ESCRITO y reverse_proxy es terminal. El live_tracker instala un
# catch-all 'reverse_proxy /api/* localhost:8770' que, si queda por ENCIMA,
# captura /api/me, /api/auth/*, etc. y las rutas de cuentas nunca se alcanzan.
# Por eso las rutas de cuentas (más específicas) deben insertarse ANTES de ese
# catch-all. Si el catch-all no existe (live_tracker sin desplegar), se usa como
# ancla 'try_files {path}'.
ROUTES=(
  "reverse_proxy /api/health localhost:8771"
  "reverse_proxy /api/auth/* localhost:8771"
  "reverse_proxy /api/me localhost:8771"
  "reverse_proxy /api/follows/* localhost:8771"
  "reverse_proxy /api/account localhost:8771"
)

# Ancla de inserción: preferimos justo antes del catch-all de live_tracker.
if sudo grep -qF "reverse_proxy /api/* localhost:8770" "$CADDY"; then
  ANCHOR_RE='reverse_proxy /api/\* localhost:8770'
  echo "    ancla: antes del catch-all /api/* -> :8770 (live_tracker)"
else
  ANCHOR_RE='try_files {path}'
  echo "    ancla: antes de try_files (no hay catch-all de live_tracker)"
fi

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
  # Inserta la línea justo antes del ancla, conservando la sangría. `&` reproduce
  # el texto emparejado (sangría + ancla), así la línea ancla queda intacta.
  sudo sed -i "s#^\([[:space:]]*\)${ANCHOR_RE}#\1${ROUTE}\n&#" "$CADDY"
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
