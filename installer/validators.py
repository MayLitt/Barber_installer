"""Validation et nettoyage : ce qui n'est pas dans le schéma ou invalide est écarté."""
from __future__ import annotations
import re, unicodedata
from .sanitize import injection_signals

DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def norm_key(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def clean_text(s, limit=300):
    if not isinstance(s, str):
        return None
    s = re.sub(r"[\x00-\x1f\x7f]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()[:limit]
    if not s or injection_signals(s):
        return None
    return s


def norm_phone(raw):
    """Retourne (numéro normalisé, type) ; type = fixe | mobile | special | surtaxe."""
    if not raw or not isinstance(raw, str):
        return None, None
    d = re.sub(r"[^\d+]", "", raw)
    if d.startswith("+33"):
        d = "0" + d[3:]
    elif d.startswith("0033"):
        d = "0" + d[4:]
    d = re.sub(r"\D", "", d)
    if len(d) != 10 or not d.startswith("0"):
        return None, None
    if d.startswith("089"):
        return None, "surtaxe"
    kind = "mobile" if d[:2] in ("06", "07") else "special" if d.startswith("08") else "fixe"
    return " ".join(d[i:i + 2] for i in range(0, 10, 2)), kind


_H = re.compile(r"(\d{1,2})[h:](\d{2})?-(\d{1,2})[h:](\d{2})?")


def _hm(h, m):
    return int(h) * 60 + int(m or 0)


def clean_hours(h):
    if not isinstance(h, dict):
        return None
    out = {}
    for d in DAYS:
        v = h.get(d)
        if v is None:
            out[d] = None
            continue
        v = str(v).strip().lower().replace(" ", "").replace("–", "-").replace("—", "-")
        if v in ("closed", "fermé", "ferme"):
            out[d] = "closed"
            continue
        m = _H.fullmatch(v)
        if not m:
            out[d] = None
            continue
        a, b = _hm(m[1], m[2]), _hm(m[3], m[4])
        if not (0 <= a < b <= 24 * 60):
            out[d] = None
            continue
        out[d] = f"{a // 60:02d}:{a % 60:02d}-{b // 60:02d}:{b % 60:02d}"
    return out if any(v is not None for v in out.values()) else None


def clean_price(p):
    try:
        p = float(p)
    except (TypeError, ValueError):
        return None
    return p if 0 < p <= 1500 else None


def clean_duration(d):
    try:
        d = int(d)
    except (TypeError, ValueError):
        return None
    return d if 5 <= d <= 480 else None


_NAME = re.compile(r"[A-ZÀ-ÖØ-Þ][a-zà-öø-ÿ'’-]{1,19}")


def clean_first_name(n):
    """Un seul prénom ; un nom complet ou un pseudo est rejeté (minimisation)."""
    if isinstance(n, str) and _NAME.fullmatch(n.strip()):
        return n.strip()
    return None


def clean_extraction(raw: dict):
    """Passe la sortie brute du modèle dans le filtre. Retourne (données propres, avertissements)."""
    raw = raw or {}
    w, d = [], {}
    d["name"] = clean_text(raw.get("name"), 120)
    d["address"] = clean_text(raw.get("address"), 200)
    d["category"] = clean_text(raw.get("category"), 80)
    ph, kind = norm_phone(raw.get("phone"))
    d["phone"], d["phone_kind"] = ph, kind
    if raw.get("phone") and not ph:
        w.append(f"téléphone rejeté ({kind or 'format invalide'})")
    d["hours"] = clean_hours(raw.get("hours"))
    services = []
    for s in (raw.get("services") or [])[:60]:
        nm = clean_text(s.get("name"), 100)
        if not nm:
            continue
        staff = [x for x in (clean_first_name(n) for n in (s.get("staff") or [])) if x]
        b = s.get("bookable_online")
        services.append({"name": nm, "price_eur": clean_price(s.get("price_eur")),
                         "duration_min": clean_duration(s.get("duration_min")), "staff": staff,
                         "bookable_online": b if isinstance(b, bool) else None})
    d["services"] = services
    staff = []
    for m in (raw.get("staff") or [])[:15]:
        fn = clean_first_name(m.get("first_name"))
        if not fn:
            w.append("prénom rejeté (nom complet, pseudo ou format invalide)")
            continue
        sp = [x for x in (clean_text(t, 40) for t in (m.get("specialties") or [])[:5]) if x]
        staff.append({"first_name": fn, "specialties": sp})
    d["staff"] = staff
    rules = {}
    for k in ("walk_in", "cancellation", "late_policy"):
        t = clean_text((raw.get("rules") or {}).get(k), 300)
        if t:
            rules[k] = t
    d["rules"] = rules
    r = raw.get("rating") or {}
    try:
        val, cnt = float(r.get("value")), int(r.get("count"))
        d["rating"] = {"value": val, "count": cnt} if 0 <= val <= 5 and cnt >= 0 else None
    except (TypeError, ValueError):
        d["rating"] = None
    d["suspected_instructions"] = bool(raw.get("suspected_instructions"))
    if d["suspected_instructions"]:
        w.append("la page semble contenir des instructions adressées à une IA (ignorées)")
    return d, w
