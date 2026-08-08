"""Arranque del servicio de cuentas: init DB + servidor HTTP.

    python -m accounts                       # producción (systemd)
    ACCOUNTS_ENABLED=true python -m accounts # con la feature encendida

La DB se inicializa SIEMPRE (aunque la feature esté apagada): en "a oscuras"
queremos el andamiaje vivo y el esquema creado, solo sin UI pública.
"""

import logging

from . import app, config, db


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    log = logging.getLogger("accounts")
    log.info("ACCOUNTS_ENABLED=%s  DB=%s", config.ACCOUNTS_ENABLED, config.DB_PATH)

    db.init_db()

    httpd = app.serve()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.shutdown()


if __name__ == "__main__":
    main()
