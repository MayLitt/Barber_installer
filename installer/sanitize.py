"""HTML -> texte visible uniquement, retrait des e-mails nominatifs, détection (indicative) d'injection."""
from __future__ import annotations
import re
from bs4 import BeautifulSoup, Comment

HIDDEN_STYLE = re.compile(r"display\s*:\s*none|visibility\s*:\s*hidden|font-size\s*:\s*0|opacity\s*:\s*0|left\s*:\s*-\d{3,}|text-indent\s*:\s*-\d{3,}", re.I)
GENERIC_MAIL = {"contact", "info", "infos", "reservation", "reservations", "rdv", "bonjour", "hello", "salon", "accueil"}
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")

# Signaux seulement : la vraie défense est le schéma typé + la validation + les règles dans le code.
INJECTION = [re.compile(p, re.I) for p in (
    r"ignor(e|ez|er)\s+(all|any|previous|toutes?|les|tes|vos|ces)\b",
    r"(system|developer)\s+prompt",
    r"tu es maintenant|you are now",
    r"note\s+(pour|to)\s+(l['’]\s*)?(the\s+)?(ia|ai|assistant|llm)\b",
    r"nouvelles?\s+(consignes?|instructions?)",
    r"r[ée]ponds\s+uniquement|respond\s+only|disregard",
    r"instructions?\s+(pr[ée]c[ée]dentes?|pour\s+l['’]ia)",
)]


def injection_signals(text: str) -> list[str]:
    return [p.pattern for p in INJECTION if p.search(text or "")]


def redact_emails(text: str) -> str:
    def sub(m):
        local = m.group(0).split("@")[0].lower()
        return m.group(0) if local in GENERIC_MAIL else "[e-mail]"
    return EMAIL.sub(sub, text)


def html_to_text(html: str, limit: int = 12000) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for el in soup(["script", "style", "noscript", "template", "iframe", "svg", "head"]):
        el.decompose()
    for c in soup.find_all(string=lambda s: isinstance(s, Comment)):
        c.extract()
    for el in soup.find_all(True):
        if el.decomposed:
            continue
        a = el.attrs or {}
        if "hidden" in a or a.get("aria-hidden") == "true" or HIDDEN_STYLE.search(a.get("style", "") or ""):
            el.decompose()
    text = soup.get_text("\n")
    text = "\n".join(l.strip() for l in text.splitlines() if l.strip())
    return redact_emails(text)[:limit]
