"""Découverte du commerce : Serper (API de recherche Google) si une clé existe, sinon URLs fournies à la main."""
from __future__ import annotations
import difflib
import httpx
from urllib.parse import urlparse
from .validators import norm_key

BLOCK = ("facebook.com", "instagram.com", "tiktok.com", "linkedin.com", "pagesjaunes.fr", "tripadvisor", "yelp.",
         "societe.com", "pappers.fr", "annuaire-entreprises", "google.", "youtube.com", "x.com", "twitter.com", "mapstr", "fresha.com", "treatwell")


def _post(path: str, key: str, q: str) -> dict:
    r = httpx.post(f"https://google.serper.dev/{path}", headers={"X-API-KEY": key, "Content-Type": "application/json"},
                   json={"q": q, "gl": "fr", "hl": "fr"}, timeout=15)
    r.raise_for_status()
    return r.json()


def similar(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, norm_key(a), norm_key(b)).ratio()


def find_candidates(name: str, city: str, key: str) -> dict:
    q = f"{name} {city}".strip()
    out = {"place": None, "site": None, "planity": None}
    places = _post("places", key, q).get("places", [])
    best = max(places, key=lambda p: similar(name, p.get("title", "")), default=None)
    if best and similar(name, best.get("title", "")) >= 0.55:
        out["place"] = {"name": best.get("title"), "address": best.get("address"), "phone": best.get("phoneNumber"),
                        "category": best.get("category"), "website": best.get("website"),
                        "rating": {"value": best.get("rating"), "count": best.get("ratingCount")}}
        out["site"] = best.get("website")
    for it in _post("search", key, q).get("organic", []):
        link = it.get("link", "")
        host = urlparse(link).hostname or ""
        if "planity.com" in host and not out["planity"]:
            out["planity"] = link
        elif not out["site"] and not any(b in host for b in BLOCK):
            out["site"] = link
    return out
