"""Arranque del servicio: provider + caché + poller + servidor HTTP.

    python -m live_tracker            # producción (systemd)
    LIVE_TRACKING_ENABLED=false python -m live_tracker   # apagado
"""

import logging

from . import app, config
from .cache import LiveStore
from .providers.espn import EspnProvider


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    log = logging.getLogger("live_tracker")
    log.info("LIVE_TRACKING_ENABLED=%s", config.LIVE_TRACKING_ENABLED)

    store = LiveStore(EspnProvider())
    if config.LIVE_TRACKING_ENABLED:
        store.start_poller()

    httpd = app.serve(store)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        store.stop()
        httpd.shutdown()


if __name__ == "__main__":
    main()
