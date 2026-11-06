"""Registre officiel : API Recherche d'entreprises (gratuite, sans clé). Les noms de champs sont à vérifier au premier appel réel."""
from __future__ import annotations
import httpx
from .search import similar

NAF_TRADE = {"96.02A": "coiffeur", "96.02B": "coiffeur", "56.10A": "restaurant", "56.10B": "restaurant", "56.10C": "restaurant",
             "10.71C": "boulangerie", "10.71D": "boulangerie", "47.24Z": "boulangerie"}


def lookup(name: str, city: str):
    r = httpx.get("https://recherche-entreprises.api.gouv.fr/search", params={"q": f"{name} {city}".strip(), "per_page": 3}, timeout=10)
    r.raise_for_status()
    results = r.json().get("results", [])
    if not results:
        return None
    best = max(results, key=lambda x: similar(name, x.get("nom_complet", "")))
    legal = str(best.get("nature_juridique", ""))
    individual = legal.startswith("1")            # entrepreneur individuel : le nom est une personne -> non conservé
    siege = best.get("siege") or {}
    return {
        "siren": best.get("siren"),
        "naf": best.get("activite_principale"),
        "legal_form_code": legal or None,
        "individual": individual,
        "company_name": None if individual else best.get("nom_complet"),
        "address": siege.get("adresse") if not individual else None,
    }
