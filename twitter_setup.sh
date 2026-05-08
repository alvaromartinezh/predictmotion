#!/bin/bash
# Instala dependencias y configura cron para el bot de Bluesky
# Ejecutar UNA vez en el VPS: bash twitter_setup.sh

set -e
cd /home/ubuntu/predictmotion

echo "=== Instalando dependencias ==="
pip3 install atproto playwright requests --break-system-packages 2>/dev/null \
  || pip3 install atproto playwright requests

python3 -m playwright install chromium
python3 -m playwright install-deps chromium

echo "=== Configurando cron jobs ==="
CRON_WEEKEND="0 12 * * 5,6,0 cd /home/ubuntu/predictmotion && python3 twitter_bot.py weekend >> /home/ubuntu/twitter_bot.log 2>&1"
CRON_MATCHES="*/5 * * * 5,6,0 cd /home/ubuntu/predictmotion && python3 twitter_bot.py matches >> /home/ubuntu/twitter_bot.log 2>&1"

(crontab -l 2>/dev/null | grep -v "twitter_bot"; \
 echo "$CRON_WEEKEND"; \
 echo "$CRON_MATCHES") | crontab -

echo "=== Cron jobs instalados ==="
crontab -l | grep twitter

echo ""
echo "=== Test de credenciales ==="
python3 -c "
from atproto import Client
from pathlib import Path
handle   = (Path('BLUESKY') / 'HANDLE.txt').read_text().strip()
app_pass = (Path('BLUESKY') / 'APP.txt').read_text().strip()
client = Client()
client.login(handle, app_pass)
print(f'Cuenta conectada: @{handle}')
"

echo ""
echo "=== Setup completado ==="
echo "Logs en: /home/ubuntu/twitter_bot.log"
echo "Test manual: python3 twitter_bot.py weekend"
