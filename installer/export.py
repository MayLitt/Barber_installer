"""Export de la config versionnée (v1.0...) et comparaison entre deux versions (pour le PLM manager)."""
from __future__ import annotations
import hashlib, json
from . import __version__
from .extract import MODEL, PROMPT_VERSION
from .models import BusinessConfig, now


def _strip(o):
    if isinstance(o, dict):
        return {k: _strip(v) for k, v in o.items() if k not in ("collected_at", "meta")}
    if isinstance(o, list):
        return [_strip(x) for x in o]
    return o


def canonical(cfg: BusinessConfig) -> str:
    return json.dumps(_strip(cfg.model_dump()), sort_keys=True, ensure_ascii=False)


def finalize(cfg: BusinessConfig, tag: str = "v1.0", parent: str | None = None) -> BusinessConfig:
    usage = cfg.meta.get("usage", [])
    cfg.meta.update({
        "tag": tag, "parent_sha256": parent, "pipeline_version": __version__, "prompt_version": PROMPT_VERSION,
        "model": MODEL, "generated_at": now(),
        "tokens": {"input": sum(u["input_tokens"] for u in usage), "output": sum(u["output_tokens"] for u in usage)},
        "content_sha256": hashlib.sha256(canonical(cfg).encode("utf8")).hexdigest(),
    })
    return cfg


def save(cfg: BusinessConfig, path: str) -> None:
    with open(path, "w", encoding="utf8") as f:
        json.dump(cfg.model_dump(), f, ensure_ascii=False, indent=2)


def _flat(o, prefix=""):
    out = {}
    if isinstance(o, dict):
        for k, v in o.items():
            out.update(_flat(v, f"{prefix}.{k}" if prefix else k))
    elif isinstance(o, list):
        for i, v in enumerate(o):
            key = v.get("name") or v.get("first_name") if isinstance(v, dict) else None
            out.update(_flat(v, f"{prefix}[{key or i}]"))
    else:
        out[prefix] = o
    return out


def diff(a: dict, b: dict) -> list[str]:
    fa, fb = _flat(_strip(a)), _flat(_strip(b))
    lines = []
    for k in sorted(set(fa) | set(fb)):
        if fa.get(k) != fb.get(k):
            lines.append(f"{k}: {fa.get(k)!r} -> {fb.get(k)!r}")
    return lines
