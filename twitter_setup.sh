#!/bin/bash
# Instala dependencias y configura cron para el bot de notificaciones WhatsApp
# Ejecutar UNA vez en el VPS: bash twitter_setup.sh

set -e
cd /home/ubuntu/predictmotion

echo "=== Instalando dependencias ==="
pip3 install requests --break-system-packages 2>/dev/null || pip3 install requests

echo "=== Configurando cron jobs ==="
CRON_WEEKEND="0 12 * * 5,6,0 cd /home/ubuntu/predictmotion && python3 twitter_bot.py weekend >> /home/ubuntu/twitter_bot.log 2>&1"
CRON_MATCHES="*/5 * * * 5,6,0 cd /home/ubuntu/predictmotion && python3 twitter_bot.py matches >> /home/ubuntu/twitter_bot.log 2>&1"

(crontab -l 2>/dev/null | grep -v "twitter_bot"; \
 echo "$CRON_WEEKEND"; \
 echo "$CRON_MATCHES") | crontab -

echo "=== Cron jobs instalados ==="
crontab -l | grep twitter

echo ""
echo "=== Test de WhatsApp ==="
python3 -c "
import requests
from urllib.parse import quote
msg = 'PredictMotion Bot activo ✅'
r = requests.get(f'https://api.callmebot.com/whatsapp.php?phone=34666739947&text={quote(msg)}&apikey=7920575')
print(f'Status: {r.status_code}')
"

echo ""
echo "=== Setup completado ==="
echo "Logs en: /home/ubuntu/twitter_bot.log"
echo "Test manual: python3 twitter_bot.py weekend"
