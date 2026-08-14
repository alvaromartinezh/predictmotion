"""Verificación del ID token de Google — pure-stdlib, sin dependencias.

Flujo de identidad pura (Sign in with Google): el navegador obtiene un ID token
(JWT RS256 firmado por Google) y lo manda al backend. Aquí verificamos la firma
LOCALMENTE contra las claves públicas de Google (JWKS), sin llamar al endpoint
`tokeninfo` (que Google desaconseja para producción) y sin librerías externas.

Verificar RS256 = RSA PKCS#1 v1.5 sobre SHA-256. La stdlib no lo expone en una
llamada, pero es aritmética modular: m = sig^e mod n, y se compara con el
EMSA-PKCS1-v1.5 esperado. ~60 líneas, patrón conocido.

Comprobaciones (todas obligatorias): alg=RS256; firma válida con la clave del
`kid`; iss ∈ issuers de Google; aud == nuestro Client ID; exp no vencido; iat no
futura; email_verified == true.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import logging
import threading
import time
import urllib.request

from . import config

log = logging.getLogger("accounts.auth")

# DigestInfo DER de SHA-256 (prefijo ASN.1 de EMSA-PKCS1-v1.5).
_SHA256_DER_PREFIX = bytes.fromhex("3031300d060960864801650304020105000420")


class TokenError(Exception):
    """El ID token no es válido (firma, claims o configuración)."""


# ── Caché de JWKS (claves públicas de Google) ─────────────────────────────────
_jwks_lock = threading.Lock()
_jwks_by_kid: dict[str, dict] = {}
_jwks_expiry: float = 0.0
_jwks_last_try: float = 0.0
# Espera mínima entre descargas de JWKS. Sin esto, un `kid` desconocido (o el ""
# por defecto de un token basura) forzaba una descarga a Google POR PETICIÓN, y
# encima dentro del lock global: unas pocas IPs mandando tokens con kid aleatorio
# serializaban todos los logins y martilleaban googleapis.com desde el origen.
_JWKS_MIN_REFETCH = 60.0


def _b64url_decode(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _b64url_to_int(s: str) -> int:
    return int.from_bytes(_b64url_decode(s), "big")


def _fetch_jwks() -> tuple[dict[str, dict], float]:
    """Descarga las claves públicas de Google y calcula su caducidad de caché."""
    req = urllib.request.Request(config.GOOGLE_CERTS_URL)  # UA por defecto de urllib
    with urllib.request.urlopen(req, timeout=10) as resp:
        raw = resp.read()
        cache_control = resp.headers.get("Cache-Control", "")
    keys = {k["kid"]: k for k in json.loads(raw).get("keys", []) if "kid" in k}
    # Respeta el max-age del Cache-Control (default prudente si no viene).
    max_age = 3600
    for part in cache_control.split(","):
        part = part.strip()
        if part.startswith("max-age="):
            try:
                max_age = int(part.split("=", 1)[1])
            except ValueError:
                pass
    return keys, time.time() + max_age


def _get_jwk(kid: str) -> dict | None:
    """Devuelve la JWK del `kid`, refrescando la caché si hace falta."""
    global _jwks_by_kid, _jwks_expiry, _jwks_last_try
    now = time.time()
    with _jwks_lock:
        fresh = now < _jwks_expiry and kid in _jwks_by_kid
        # Un kid que no conocemos solo justifica UNA descarga por ventana: si Google
        # rotó claves, en 60 s las tenemos; si el kid es inventado, no hay descarga.
        if not fresh and now - _jwks_last_try >= _JWKS_MIN_REFETCH:
            _jwks_last_try = now
            try:
                _jwks_by_kid, _jwks_expiry = _fetch_jwks()
            except Exception as e:  # noqa: BLE001
                log.warning("no se pudieron descargar las claves de Google: %s", e)
                # Si la descarga falla pero teníamos la clave cacheada, la usamos.
        return _jwks_by_kid.get(kid)


def _rsa_pkcs1v15_verify_sha256(jwk: dict, msg: bytes, sig: bytes) -> bool:
    """Verifica una firma RSA PKCS#1 v1.5 sobre SHA-256 (RS256) con aritmética modular."""
    try:
        n = _b64url_to_int(jwk["n"])
        e = _b64url_to_int(jwk["e"])
    except (KeyError, ValueError):
        return False
    k = (n.bit_length() + 7) // 8
    sig_int = int.from_bytes(sig, "big")
    if sig_int >= n:
        return False
    em = pow(sig_int, e, n).to_bytes(k, "big")
    t = _SHA256_DER_PREFIX + hashlib.sha256(msg).digest()
    if k < len(t) + 11:
        return False
    expected = b"\x00\x01" + b"\xff" * (k - len(t) - 3) + b"\x00" + t
    return hmac.compare_digest(em, expected)


def verify_google_id_token(credential: str) -> dict:
    """Verifica el ID token y devuelve sus claims. Lanza TokenError si no es válido."""
    if not config.GOOGLE_CLIENT_ID:
        raise TokenError("GOOGLE_CLIENT_ID no configurado")
    if not credential or credential.count(".") != 2:
        raise TokenError("formato de token inválido")

    header_b64, payload_b64, sig_b64 = credential.split(".")
    try:
        header = json.loads(_b64url_decode(header_b64))
    except (ValueError, json.JSONDecodeError):
        raise TokenError("cabecera ilegible")
    if header.get("alg") != "RS256":
        raise TokenError(f"alg no soportado: {header.get('alg')}")

    jwk = _get_jwk(header.get("kid", ""))
    if not jwk:
        raise TokenError("kid desconocido")

    signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
    try:
        # Único base64 sin guarda: una firma malformada lanzaba binascii.Error, que
        # no es TokenError, así que se escapaba del handler y el usuario recibía un
        # error interno (con traceback en el log) en vez del redirect ?login=error.
        sig = _b64url_decode(sig_b64)
    except (ValueError, binascii.Error):
        raise TokenError("firma ilegible")
    if not _rsa_pkcs1v15_verify_sha256(jwk, signing_input, sig):
        raise TokenError("firma inválida")

    try:
        claims = json.loads(_b64url_decode(payload_b64))
    except (ValueError, json.JSONDecodeError):
        raise TokenError("payload ilegible")

    if claims.get("iss") not in config.GOOGLE_ISSUERS:
        raise TokenError(f"emisor inválido: {claims.get('iss')}")
    if claims.get("aud") != config.GOOGLE_CLIENT_ID:
        raise TokenError("aud no coincide con el Client ID")

    now = time.time()
    leeway = config.TOKEN_LEEWAY_SECONDS
    if float(claims.get("exp", 0)) < now - leeway:
        raise TokenError("token caducado")
    if float(claims.get("iat", now)) > now + leeway:
        raise TokenError("iat en el futuro")
    if not claims.get("email_verified"):
        raise TokenError("email no verificado")

    return claims
