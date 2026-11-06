"""Connecteur officiel Google Places API (Places API v1 - Search Text).
Extrait l'identité, l'adresse, le téléphone, les horaires et la catégorie.
"""
from __future__ import annotations
import os
import httpx
from .models import Prov
from .validators import clean_extraction

PLACES_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"

FIELD_MASK = [
    "places.id",
    "places.displayName",
    "places.formattedAddress",
    "places.nationalPhoneNumber",
    "places.websiteUri",
    "places.regularOpeningHours",
    "places.primaryType",
    "places.rating",
    "places.userRatingCount"
]

DAYS_MAPPING = {
    1: "mon", 2: "tue", 3: "wed", 4: "thu", 5: "fri", 6: "sat", 0: "sun"
}


def search_place(name: str, city: str = "", api_key: str | None = None) -> dict | None:
    key = api_key or os.getenv("GOOGLE_MAPS_API_KEY")
    if not key:
        return None

    query = f"{name} {city}".strip()
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": key,
        "X-Goog-FieldMask": ",".join(FIELD_MASK)
    }
    payload = {
        "textQuery": query,
        "languageCode": "fr",
        "regionCode": "fr",
        "maxResultCount": 3
    }

    resp = httpx.post(PLACES_SEARCH_URL, json=payload, headers=headers, timeout=10.0)
    if resp.status_code != 200:
        return None

    results = resp.json().get("places", [])
    if not results:
        return None

    raw_place = results[0]

    # Parsing des horaires structurés
    hours_dict = {}
    periods = (raw_place.get("regularOpeningHours") or {}).get("periods", [])
    for p in periods:
        op = p.get("open", {})
        cl = p.get("close", {})
        d = DAYS_MAPPING.get(op.get("day"))
        if d:
            open_h = f"{op.get('hour', 0):02d}:{op.get('minute', 0):02d}"
            close_h = f"{cl.get('hour', 0):02d}:{cl.get('minute', 0):02d}"
            hours_dict[d] = f"{open_h}-{close_h}"

    for d in ("mon", "tue", "wed", "thu", "fri", "sat", "sun"):
        if d not in hours_dict and periods:
            hours_dict[d] = "closed"

    # Construction du format standardisé
    name_extracted = (raw_place.get("displayName") or {}).get("text", name)
    rating_val = raw_place.get("rating")
    rating_cnt = raw_place.get("userRatingCount")
    rating_obj = {"value": float(rating_val), "count": int(rating_cnt)} if rating_val and rating_cnt else None

    return {
        "name": name_extracted,
        "address": raw_place.get("formattedAddress"),
        "phone": raw_place.get("nationalPhoneNumber"),
        "category": raw_place.get("primaryType"),
        "website": raw_place.get("websiteUri"),
        "hours": hours_dict if periods else None,
        "rating": rating_obj,
        "services": [],
        "staff": [],
        "rules": {},
        "suspected_instructions": False
    }