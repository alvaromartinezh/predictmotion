#!/usr/bin/env python3
"""Auto-actualiza la allowlist de IPs de Cloudflare en la cadena iptables CF_WEB.

Contexto: el origen (:80/:443) está restringido a IPs de Cloudflare (ver
docs/origin-firewall.md). Como esa lista cambia de vez en cuando, este script la
refresca sin intervención manual (cron semanal). Solo stdlib salvo iptables.

Diseño A PRUEBA DE FALLOS (nunca deja el sitio fuera):
  - Descarga la lista OFICIAL de Cloudflare (API JSON) y la VALIDA (≥10 rangos,
    todos CIDR IPv4 válidos). Si falla o es sospechosa, NO toca las reglas y manda
    alerta por email (reusa seo.notify). Prefiere quedarse como está a romper.
  - Si la lista no cambió respecto a la cadena actual, no hace nada.
  - Solo si cambió: reconstruye CF_WEB (ACCEPT por rango + DROP) y persiste con
    netfilter-persistent. Requiere root (el cron usa sudo).

Uso:
  sudo python3 scripts/cf_firewall.py            # aplica si hay cambios
  sudo python3 scripts/cf_firewall.py --dry-run  # solo informa, no toca nada
"""
from __future__ import annotations

import ipaddress
import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from seo import notify  # noqa: E402  (alertas por email, best-effort)

CF_IPS_URL = "https://api.cloudflare.com/client/v4/ips"  # oficial; pasa con urllib
CHAIN = "CF_WEB"
MIN_RANGES = 10


def log(m):
    print(f"[cf_firewall] {m}", flush=True)


def fetch_ranges():
    """Descarga y valida los rangos IPv4 de Cloudflare. Lanza si algo no cuadra."""
    with urllib.request.urlopen(CF_IPS_URL, timeout=15) as r:
        data = json.loads(r.read().decode())
    cidrs = (data.get("result") or {}).get("ipv4_cidrs") or []
    valid = []
    for c in cidrs:
        ipaddress.ip_network(c)  # valida (lanza ValueError si no)
        valid.append(c)
    if len(valid) < MIN_RANGES:
        raise ValueError(f"lista CF sospechosa: {len(valid)} rangos (<{MIN_RANGES})")
    return sorted(valid)


def ipt(*args, check=True):
    return subprocess.run(["iptables", *args], capture_output=True, text=True, check=check)


def current_ranges():
    """Rangos ACCEPT actuales de CF_WEB, o None si la cadena no existe."""
    r = ipt("-S", CHAIN, check=False)
    if r.returncode != 0:
        return None
    out = []
    for line in r.stdout.splitlines():
        p = line.split()
        if len(p) >= 6 and p[0] == "-A" and p[2] == "-s" and p[-1] == "ACCEPT":
            out.append(p[3])
    return sorted(out)


def rebuild(ranges):
    ipt("-F", CHAIN)
    for c in ranges:
        ipt("-A", CHAIN, "-s", c, "-j", "ACCEPT")
    ipt("-A", CHAIN, "-j", "DROP")


def ensure_jump():
    """Asegura la regla INPUT que enruta :80/:443 nuevas a CF_WEB (por si faltara)."""
    spec = ["-p", "tcp", "-m", "conntrack", "--ctstate", "NEW",
            "-m", "multiport", "--dports", "80,443", "-j", CHAIN]
    if ipt("-C", "INPUT", *spec, check=False).returncode != 0:
        ipt("-I", "INPUT", "5", *spec)  # tras la regla de SSH en nuestra config


def save():
    subprocess.run(["netfilter-persistent", "save"], capture_output=True, text=True, check=True)


def main():
    if os.geteuid() != 0:
        log("ERROR: requiere root (usa sudo)")
        return 2
    dry = "--dry-run" in sys.argv

    try:
        new = fetch_ranges()
    except Exception as e:  # noqa: BLE001 — fetch/validación
        log(f"fetch/validación falló: {e}")
        notify.send_alert(
            "[PredictMotion] cf_firewall: no se pudo actualizar la allowlist",
            f"No se pudieron obtener/validar los rangos de Cloudflare:\n\n{e}\n\n"
            "Las reglas actuales se MANTIENEN (fail-safe). Revisa /home/ubuntu/cf_firewall.log.",
            dedup_key="cf-firewall-fetch", dedup_hours=20)
        return 1

    cur = current_ranges()
    if cur is None:
        log(f"la cadena {CHAIN} no existe — ¿enforce sin aplicar? no toco nada")
        notify.send_alert(
            "[PredictMotion] cf_firewall: cadena CF_WEB ausente",
            "La cadena iptables CF_WEB no existe; el filtrado del origen podría no estar\n"
            "activo. Revisa docs/origin-firewall.md.",
            dedup_key="cf-firewall-missing", dedup_hours=20)
        return 1

    if cur == new:
        log(f"sin cambios ({len(new)} rangos)")
        return 0

    added, removed = sorted(set(new) - set(cur)), sorted(set(cur) - set(new))
    log(f"cambios: {len(cur)} → {len(new)} rangos | +{added} -{removed}")
    if dry:
        log("[dry-run] no se aplica nada")
        return 0

    rebuild(new)
    ensure_jump()
    save()
    log(f"CF_WEB actualizada a {len(new)} rangos y persistida")
    return 0


if __name__ == "__main__":
    sys.exit(main())
