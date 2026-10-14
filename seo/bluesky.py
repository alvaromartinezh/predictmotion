"""Publicador de Bluesky (AT Protocol) — difusión automática de los tuits.

Por qué existe: `seo/tweets.py` genera el texto y la tarjeta PNG de cada
jornada, pero el canal final era MANUAL (el bot manda el tuit al Telegram del
dueño, que lo sube a X a mano). Eso incumple el principio 2 de CLAUDE.md
("el sitio debe sobrevivir meses sin mantenimiento manual"). La API de X cuesta
dinero; la de Bluesky es gratis, sin revisión de app y sin portal: basta el
handle + un app password. Así que el mismo texto y la misma imagen que ya se
generan salen publicados sin que nadie toque nada.

Credenciales en `.env` (mismo mecanismo que TELEGRAM_BOT_TOKEN, ver
`seo/notify._load_env`):

    BLUESKY_HANDLE=predictmotion.bsky.social
    BLUESKY_APP_PASSWORD=xxxx-xxxx-xxxx-xxxx

El app password se saca en Configuración → Privacidad y seguridad → App
passwords. NO es la contraseña de la cuenta: se revoca sin perder la cuenta.

Sin dependencias (urllib). Best-effort: si algo falla devuelve False y lo dice
por stderr; nunca lanza, para no tumbar el cron que lo llama.

Límites de la API (si se superan, el post se rechaza):
  - texto: 300 graphemes  → se recorta a 300 caracteres.
  - blob de imagen: 1 MB  → las tarjetas de tweets.py pesan ~140 KB.
  - escritura: 5 000 puntos/hora, un post cuesta 3.

Ver [[docs/tweets]].
"""

import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

from . import notify

PDS = "https://bsky.social/xrpc"
MAX_TEXT = 300
MAX_BLOB = 1_000_000

_URL_RE = re.compile(r"https?://[^\s\]）)]+")


def _req(method, body, token=None, content_type="application/json"):
    """POST a un endpoint XRPC. Devuelve el JSON de respuesta o None."""
    data = json.dumps(body).encode("utf-8") if content_type == "application/json" else body
    req = urllib.request.Request(f"{PDS}/{method}", data=data, method="POST")
    req.add_header("Content-Type", content_type)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:300]
        print(f"[bluesky] {method} HTTP {e.code}: {detail}", file=sys.stderr)
    except (urllib.error.URLError, OSError, ValueError) as e:
        print(f"[bluesky] {method} falló: {e}", file=sys.stderr)
    return None


def _session():
    """(accessJwt, did) o (None, None) si no hay credenciales o el login falla."""
    notify._load_env()
    handle = os.environ.get("BLUESKY_HANDLE")
    password = os.environ.get("BLUESKY_APP_PASSWORD")
    if not (handle and password):
        print("[bluesky] sin BLUESKY_HANDLE/BLUESKY_APP_PASSWORD en .env, no se publica")
        return None, None
    # Sin caché de sesión a propósito: cada run del cron es un proceso nuevo y
    # corto, y el login cuesta una petición. Si algún día se publica en bucle,
    # cachear accessJwt (vive ~2 h) o usar refreshJwt.
    s = _req("com.atproto.server.createSession",
             {"identifier": handle, "password": password})
    if not s or not s.get("accessJwt"):
        return None, None
    return s["accessJwt"], s["did"]


def _facets(text):
    """Enlaces clicables. Bluesky NO autodetecta URLs: sin facet el enlace sale
    como texto plano y nadie entra, que es justo el objetivo del post. Los
    offsets son en BYTES del texto codificado en UTF-8, no en caracteres — con
    acentos o emoji (los tuits llevan ambos) contar caracteres los desplaza."""
    raw = text.encode("utf-8")
    out = []
    for m in _URL_RE.finditer(text):
        url = m.group(0).rstrip(".,;:")
        start = len(text[: m.start()].encode("utf-8"))
        out.append({
            "index": {"byteStart": start, "byteEnd": start + len(url.encode("utf-8"))},
            "features": [{"$type": "app.bsky.richtext.facet#link", "uri": url}],
        })
    assert all(f["index"]["byteEnd"] <= len(raw) for f in out)
    return out


def post(text, png=None, alt=""):
    """Publica un post (texto + imagen opcional). True si Bluesky lo aceptó."""
    if not text:
        return False
    text = text[:MAX_TEXT]
    token, did = _session()
    if not token:
        return False

    embed = None
    if png and len(png) <= MAX_BLOB:
        up = _req("com.atproto.repo.uploadBlob", png, token=token,
                  content_type="image/png")
        if up and up.get("blob"):
            embed = {"$type": "app.bsky.embed.images",
                     "images": [{"alt": alt or text.split("\n")[0], "image": up["blob"]}]}
    elif png:
        print(f"[bluesky] imagen de {len(png)} B pasa de {MAX_BLOB}, se publica sin ella",
              file=sys.stderr)

    record = {"$type": "app.bsky.feed.post", "text": text,
              "createdAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
              "langs": ["es"], "facets": _facets(text)}
    if embed:
        record["embed"] = embed

    res = _req("com.atproto.repo.createRecord", token=token,
               body={"repo": did, "collection": "app.bsky.feed.post", "record": record})
    if res and res.get("uri"):
        print(f"[bluesky] publicado {res['uri']}")
        return True
    return False


def _self_check():
    """Lo único no trivial aquí son los offsets en bytes de los facets."""
    t = "📊 LaLiga · Jornada 9\nMás en https://predictmotion.com/laliga ✅"
    (f,) = _facets(t)
    raw = t.encode("utf-8")
    i = f["index"]
    assert raw[i["byteStart"]:i["byteEnd"]].decode("utf-8") == \
        "https://predictmotion.com/laliga", raw[i["byteStart"]:i["byteEnd"]]
    assert f["features"][0]["uri"] == "https://predictmotion.com/laliga"
    assert _facets("sin enlaces aquí") == []
    # Punto final pegado al enlace: no forma parte de la URL.
    (g,) = _facets("entra en https://predictmotion.com.")
    assert g["features"][0]["uri"] == "https://predictmotion.com"
    print("ok: facets")


if __name__ == "__main__":
    if "--self-check" in sys.argv:
        _self_check()
    elif "--post" in sys.argv:
        print(post("Prueba de publicación automática. https://predictmotion.com"))
    else:
        print(__doc__)
