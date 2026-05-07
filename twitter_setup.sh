#!/bin/bash
# Instala dependencias y configura cron para el bot de Twitter
# Ejecutar UNA vez en el VPS: bash twitter_setup.sh

set -e
cd /home/ubuntu/predictmotion

echo "=== Instalando dependencias ==="
pip3 install tweepy playwright requests --break-system-packages 2>/dev/null \
  || pip3 install tweepy playwright requests

python3 -m playwright install chromium
python3 -m playwright install-deps chromium

echo "=== Configurando cron jobs ==="
# Añadir cron jobs (no duplicar si ya existen)
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
import tweepy
from pathlib import Path
def r(f): return (Path('TWITTER') / f).read_text().strip()
client = tweepy.Client(
    consumer_key=r('Consumer_key.txt'),
    consumer_secret=r('Consumer_key_secret.txt'),
    access_token=r('access_token.txt'),
    access_token_secret=r('access_token_secret.txt'),
)
me = client.get_me()
print(f'Cuenta conectada: @{me.data.username}')
"

echo ""
echo "=== Setup completado ==="
echo "Logs en: /home/ubuntu/twitter_bot.log"
echo "Test manual: python3 twitter_bot.py weekend"
