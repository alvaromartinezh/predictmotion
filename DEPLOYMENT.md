# Deployment Info

## Hosting
- **VPS**: Oracle Cloud Always Free (Madrid)
- **OS**: Ubuntu 24.04 ARM (aarch64)
- **IP pública**: 51.170.44.34
- **Dominio**: predictmotion.com (Namecheap)
- **Servidor web**: Caddy con HTTPS automático (Let's Encrypt)
- **Acceso SSH**: `ssh predictmotion` (alias configurado)

## Estructura en el servidor
- Repo clonado en: `/home/ubuntu/predictmotion/`
- Caddyfile: `/etc/caddy/Caddyfile`

## Auto-deploy
- Cron job cada 2 minutos hace `git pull` desde main
- Script: `/home/ubuntu/update_web.sh`
- Log: `/home/ubuntu/update_web.log`

## Comandos útiles
- Reiniciar Caddy: `sudo systemctl restart caddy`
- Ver logs Caddy: `sudo journalctl -u caddy -f`
- Forzar pull manual: `~/update_web.sh`
