"""Publicación directa en X (Twitter) con imagen, vía tweepy (OAuth 1.0a).

Se usa cuando el usuario pulsa el botón "Publicar" en Telegram. Sube la imagen
(endpoint v1.1 media/upload) y crea el tweet (endpoint v2 create_tweet) con el
texto + la foto adjunta. Si las claves no están en `.env`, queda deshabilitado.
"""

from __future__ import annotations
from pathlib import Path

import config


def is_enabled() -> bool:
    return config.X_ENABLED


def publish(text: str, image_path: str | Path | None = None) -> tuple[bool, str]:
    """Publica un tweet con `text` y, si se da, la imagen `image_path`.
    Devuelve (ok, url_del_tweet) o (False, mensaje_de_error)."""
    if not config.X_ENABLED:
        return False, "X API no configurada (faltan claves en .env)"
    try:
        import tweepy

        client = tweepy.Client(
            consumer_key=config.X_API_KEY,
            consumer_secret=config.X_API_SECRET,
            access_token=config.X_ACCESS_TOKEN,
            access_token_secret=config.X_ACCESS_SECRET,
        )

        media_ids = None
        if image_path:
            auth = tweepy.OAuth1UserHandler(
                config.X_API_KEY, config.X_API_SECRET,
                config.X_ACCESS_TOKEN, config.X_ACCESS_SECRET,
            )
            api = tweepy.API(auth)
            media = api.media_upload(filename=str(image_path))
            media_ids = [media.media_id]

        resp = client.create_tweet(text=text, media_ids=media_ids)
        tweet_id = resp.data.get("id") if resp and resp.data else None
        if not tweet_id:
            return False, "X no devolvió id de tweet"
        return True, f"https://x.com/i/web/status/{tweet_id}"
    except Exception as e:
        return False, str(e)
