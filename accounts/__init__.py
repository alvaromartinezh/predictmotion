"""Cuentas de usuario — backend API con estado (SQLite), separado del sitio.

A diferencia del resto del sitio (estático, sin estado, regenerado desde ESPN),
este servicio guarda datos de PERSONAS REALES (login con Google, equipos y
competiciones seguidas). Por eso vive aparte, en su propio proceso y puerto, con
su base de datos en `user_data/` (gitignored) y su propia estrategia de backup.

Diseñado COMO API (endpoints /api/auth, /api/me, /api/follows, …) para que una
app móvil futura hable con los mismos endpoints sin reescribir lógica. Mismo
patrón que `live_tracker`: servicio Python stdlib + systemd + Caddy reverse_proxy.

Ver docs/fase0-cuentas.md para el diseño completo y el plan por checkpoints.
"""
