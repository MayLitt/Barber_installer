"""Récupération de pages : HTTP(S) uniquement, hôtes publics uniquement (anti-SSRF), taille et durée limitées, robots.txt respecté."""
from __future__ import annotations
import ipaddress, socket
from urllib.parse import urlparse, urljoin
from urllib.robotparser import RobotFileParser
import httpx

UA = "DecrocheInstallerBot/0.1 (hackathon ESILV; contact: equipe-06)"
MAX_BYTES = 1_500_000
MAX_REDIRECTS = 3


class FetchBlocked(Exception):
    pass


def is_public_host(host: str) -> bool:
    if not host or host.lower() in ("localhost",):
        return False
    try:
        infos = [ipaddress.ip_address(host)]          # adresse IP littérale
    except ValueError:
        try:
            infos = [ipaddress.ip_address(i[4][0]) for i in socket.getaddrinfo(host, None)]
        except socket.gaierror:
            return False
    return bool(infos) and all(ip.is_global for ip in infos)


def check_url(url: str) -> str:
    p = urlparse(url)
    if p.scheme not in ("http", "https") or not p.hostname:
        raise FetchBlocked(f"schéma ou hôte invalide : {url}")
    if not is_public_host(p.hostname):
        raise FetchBlocked(f"hôte non public bloqué : {p.hostname}")
    return url


def _robots_ok(client: httpx.Client, url: str) -> bool:
    p = urlparse(url)
    try:
        r = client.get(f"{p.scheme}://{p.netloc}/robots.txt", timeout=5)
        if r.status_code != 200:
            return True
        rp = RobotFileParser()
        rp.parse(r.text.splitlines())
        return rp.can_fetch(UA, url)
    except httpx.HTTPError:
        return True


def fetch_html(url: str) -> str:
    url = check_url(url)
    with httpx.Client(headers={"User-Agent": UA}, follow_redirects=False, timeout=10) as client:
        if not _robots_ok(client, url):
            raise FetchBlocked(f"interdit par robots.txt : {url}")
        for _ in range(MAX_REDIRECTS + 1):
            with client.stream("GET", url) as r:
                if r.is_redirect:
                    url = check_url(urljoin(url, r.headers.get("location", "")))
                    continue
                r.raise_for_status()
                if "html" not in r.headers.get("content-type", "") and "text" not in r.headers.get("content-type", ""):
                    raise FetchBlocked("type de contenu non texte")
                buf = b""
                for chunk in r.iter_bytes():
                    buf += chunk
                    if len(buf) > MAX_BYTES:
                        break
                return buf[:MAX_BYTES].decode(r.encoding or "utf-8", errors="replace")
    raise FetchBlocked("trop de redirections")
