"""Orchestration : découverte -> récupération -> sanitisation -> extraction -> validation -> fusion."""
from __future__ import annotations
import hashlib, json, os
from pathlib import Path
from urllib.parse import urlparse
from .build import build_config
from .extract import MODEL, PROMPT_VERSION
from .fetch import fetch_html, FetchBlocked
from .models import Prov
from .sanitize import html_to_text
from .validators import clean_extraction


class JsonCache:
    def __init__(self, path=".cache"):
        self.dir = Path(path)
        self.dir.mkdir(exist_ok=True)

    def get(self, key):
        f = self.dir / f"{key}.json"
        return json.loads(f.read_text(encoding="utf8")) if f.exists() else None

    def set(self, key, val):
        (self.dir / f"{key}.json").write_text(json.dumps(val, ensure_ascii=False), encoding="utf8")


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf8")).hexdigest()


def source_label(url: str) -> str:
    return "planity" if "planity.com" in (urlparse(url).hostname or "") else "site"


def run_pipeline(name, city, urls=(), *, extractor, discover=None, registry_fn=None, fetch_fn=fetch_html,
                 cache=None, max_docs=4, log=print):
    docs, warnings, sources, usage = [], [], [], []
    cands = {}
    if discover:
        try:
            cands = discover(name, city) or {}
        except Exception as e:                              # une source en panne ne bloque pas le flux
            warnings.append(f"découverte indisponible : {e}")
    place = cands.get("place")
    if place:
        raw = {k: place.get(k) for k in ("name", "address", "phone", "category", "rating", "hours")}
        data, w = clean_extraction(raw)
        docs.append({"prov": Prov(source="google_places", confidence=0.95), "data": data})
        warnings += w
        log(f"  Fiche Google : {place.get('name')} ({place.get('address')})")
    targets = []
    for u in [cands.get("site"), cands.get("planity"), *urls]:
        if u and u not in targets:
            targets.append(u)
    for url in targets[:max_docs]:
        src = source_label(url)
        try:
            text = html_to_text(fetch_fn(url))
        except (FetchBlocked, Exception) as e:
            warnings.append(f"{url} : non lu ({e})")
            log(f"  ✗ {url} : {e}")
            continue
        key = _sha(text + MODEL + PROMPT_VERSION)
        hit = cache.get(key) if cache else None
        if hit:
            raw, u = hit["raw"], None
        else:
            try:
                raw, u = extractor(text, url, src)
            except Exception as e:
                warnings.append(f"{url} : extraction indisponible ({e})")
                log(f"  ✗ {url} : extraction indisponible ({e})")
                continue
            if cache:
                cache.set(key, {"raw": raw})
        if u:
            usage.append(u)
        data, w = clean_extraction(raw)
        warnings += [f"{url} : {x}" for x in w]
        docs.append({"prov": Prov(source=src, url=url, confidence=0.8), "data": data})
        sources.append({"source": src, "url": url, "text_sha256": _sha(text), "cached": bool(hit)})
        log(f"  ✓ {src} lu : {url}{' (cache)' if hit else ''}")
    registry = None
    if registry_fn:
        try:
            registry = registry_fn(name, city)
        except Exception as e:
            warnings.append(f"registre indisponible : {e}")
    cfg = build_config(name, docs, registry, warnings)
    cfg.meta["sources"] = sources
    cfg.meta["usage"] = usage
    return cfg
