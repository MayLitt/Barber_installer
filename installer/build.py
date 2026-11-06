"""Fusion des sources, décision « trouvé / suggéré / conflit », génération des questions et de la liste « ce que l'agent ne saura pas »."""
from __future__ import annotations
import re
from .models import BusinessConfig, Fact, Prov, Question, Service, StaffMember
from .registry import NAF_TRADE
from .validators import norm_key, clean_hours, clean_price, clean_duration, clean_first_name, DAYS

TRUSTED = ("import", "commercant")
RULE_KEYS = {
    "walk_in": "Accepte-t-on les clients sans rendez-vous ?",
    "cancellation": "Quelle est la politique d'annulation ?",
    "late_policy": "Quelle est la politique en cas de retard du client ?",
    "technical_consultation": "Exigez-vous une consultation préalable pour les balayages/couleurs ?",
    "hair_specialties": "Pratiquez-vous les lissages, défrisages ou cheveux texturés ?",
    "payment_methods": "Quels sont les moyens de paiement acceptés au salon ?",
    "hair_prep": "Les clients doivent-ils venir avec les cheveux lavés ?"
}

RULE_LABELS = {
    "walk_in": "clients sans rendez-vous",
    "cancellation": "annulation",
    "late_policy": "retard du client",
    "technical_consultation": "consultation préalable",
    "hair_specialties": "spécialités lissages/bouclés",
    "payment_methods": "moyens de paiement",
    "hair_prep": "préparation des cheveux"
}
# Valeurs par défaut du métier : jamais présentées comme trouvées, toujours à valider.
DEFAULT_DURATIONS = [("balayage", 120), ("couleur", 60), ("coloration", 60), ("degrade", 40), ("rasage", 30), ("barbe", 20),
                     ("brushing", 30), ("enfant", 20), ("soin", 20), ("coupe", 30)]


def default_duration(name: str):
    k = norm_key(name)
    if "coupe" in k and "barbe" in k:
        return 50
    for kw, m in DEFAULT_DURATIONS:
        if kw in k:
            return m
    return None


def detect_trade(naf, *texts):
    if naf and naf in NAF_TRADE:
        return NAF_TRADE[naf]
    t = norm_key(" ".join(x for x in texts if x))
    if any(w in t for w in ("coiff", "barb", "salon de beaute")):
        return "coiffeur"
    if any(w in t for w in ("restaurant", "sushi", "pizz")):
        return "restaurant"
    return None


def _status(n_sources: int, provs) -> str:
    if any(p.source in TRUSTED for p in provs):
        return "confirmed"
    return "found" if n_sources >= 2 else "suggested"


def merge_scalar(items, key=None) -> Fact:
    groups: dict = {}
    for v, p in items:
        if v in (None, ""):
            continue
        k = key(v) if key else v
        g = groups.setdefault(k, {"value": v, "prov": []})
        g["prov"].append(p)
    if not groups:
        return Fact()
    if len(groups) == 1:
        g = next(iter(groups.values()))
        return Fact(value=g["value"], status=_status(len({p.source for p in g["prov"]}), g["prov"]), prov=g["prov"])
    return Fact(status="conflict", alternatives=[g["value"] for g in groups.values()],
                prov=[p for g in groups.values() for p in g["prov"]])


def _addr_key(a: str) -> str:
    m = re.search(r"\b\d{5}\b", a)
    return m.group(0) if m else norm_key(a)


def _consistent(a: dict, b: dict) -> bool:
    return all(a[d] == b[d] for d in DAYS if a.get(d) is not None and b.get(d) is not None)


def merge_hours(items) -> Fact:
    groups = []                      # [{"hours": dict, "prov": []}]
    for h, p in items:
        if not h:
            continue
        for g in groups:
            if _consistent(g["hours"], h):
                for d in DAYS:
                    if g["hours"].get(d) is None:
                        g["hours"][d] = h.get(d)
                g["prov"].append(p)
                break
        else:
            groups.append({"hours": dict(h), "prov": [p]})
    if not groups:
        return Fact()
    if len(groups) == 1:
        g = groups[0]
        return Fact(value=g["hours"], status=_status(len({p.source for p in g["prov"]}), g["prov"]), prov=g["prov"])
    return Fact(status="conflict", alternatives=[g["hours"] for g in groups], prov=[p for g in groups for p in g["prov"]])


def build_config(name_hint: str, docs: list[dict], registry: dict | None = None, warnings=None) -> BusinessConfig:
    """docs : [{"prov": Prov, "data": sortie de clean_extraction}]"""
    cfg = BusinessConfig(warnings=list(warnings or []))
    cfg.name = Fact(value=name_hint, status="confirmed", prov=[Prov(source="commercant", confidence=1.0)])

    addr_items = [(d["data"]["address"], d["prov"]) for d in docs if d["data"].get("address")]
    if registry and registry.get("address"):
        addr_items.append((registry["address"], Prov(source="registre", confidence=0.95)))
    cfg.address = merge_scalar(addr_items, key=_addr_key)

    cfg.phone = merge_scalar([(d["data"]["phone"], d["prov"]) for d in docs if d["data"].get("phone")])
    if cfg.phone.value:
        kinds = {d["data"].get("phone_kind") for d in docs if d["data"].get("phone") == cfg.phone.value}
        if "mobile" in kinds:
            cfg.phone.note = "mobile"
            if cfg.phone.status in ("found", "suggested"):
                cfg.phone.status = "suggested"
        elif "special" in kinds:
            cfg.phone.note = "numéro non géographique : à vérifier"

    cfg.category = merge_scalar([(d["data"]["category"], d["prov"]) for d in docs if d["data"].get("category")], key=norm_key)
    cfg.hours = merge_hours([(d["data"].get("hours"), d["prov"]) for d in docs])
    cfg.trade = detect_trade((registry or {}).get("naf"), cfg.category.value, name_hint)
    if registry:
        cfg.legal = Fact(value={k: registry.get(k) for k in ("siren", "naf", "legal_form_code", "individual", "company_name")},
                         status="found", prov=[Prov(source="registre", url="https://annuaire-entreprises.data.gouv.fr/", confidence=0.95)])

    # Services
    acc: dict = {}
    for d in docs:
        for s in d["data"]["services"]:
            a = acc.setdefault(norm_key(s["name"]), {"name": s["name"], "prices": [], "durs": [], "staff": [], "book": None, "prov": []})
            a["prov"].append(d["prov"])
            if s["price_eur"] is not None:
                a["prices"].append((s["price_eur"], d["prov"]))
            if s["duration_min"] is not None:
                a["durs"].append((s["duration_min"], d["prov"]))
            for n in s["staff"]:
                if n not in a["staff"]:
                    a["staff"].append(n)
            if s["bookable_online"] is not None:
                a["book"] = s["bookable_online"]
    for a in acc.values():
        pf = merge_scalar(a["prices"])
        df = merge_scalar(a["durs"])
        svc = Service(name=a["name"], staff=a["staff"], bookable_online=a["book"], prov=a["prov"])
        svc.price_eur, svc.status = pf.value, (pf.status if pf.status != "missing" else "missing")
        if pf.status == "conflict":
            svc.alt_prices = sorted(float(x) for x in pf.alternatives)
        if df.status == "conflict":
            svc.duration_status = "conflict"
        elif df.value is not None:
            svc.duration_min, svc.duration_status = int(df.value), df.status
            svc.duration_source = "page" if df.status != "confirmed" else "commercant"
        elif cfg.trade == "coiffeur" and default_duration(a["name"]):
            svc.duration_min, svc.duration_status = default_duration(a["name"]), "suggested"
            svc.duration_source = "defaut_metier"
            svc.prov.append(Prov(source="defaut_metier", confidence=0.3))
        cfg.services.append(svc)

    # Équipe (prénoms seulement)
    team: dict = {}
    for d in docs:
        for m in d["data"]["staff"]:
            t = team.setdefault(m["first_name"], StaffMember(first_name=m["first_name"]))
            t.prov.append(d["prov"])
            for sp in m["specialties"]:
                if sp not in t.specialties:
                    t.specialties.append(sp)
    cfg.staff = list(team.values())

    # Règles d'accueil et note
    for k in RULE_KEYS:
        f = merge_scalar([(d["data"]["rules"].get(k), d["prov"]) for d in docs if d["data"]["rules"].get(k)], key=norm_key)
        cfg.rules[k] = f
    ratings = [(d["data"]["rating"], d["prov"]) for d in docs if d["data"].get("rating")]
    if ratings:
        r, p = max(ratings, key=lambda x: x[0]["count"])
        cfg.rating = Fact(value=r, status="suggested", prov=[p])
    for d in docs:
        if d["data"].get("suspected_instructions"):
            cfg.warnings.append(f"Instructions suspectes dans {d['prov'].url or d['prov'].source} : ignorées")

    cfg.pending_questions = make_questions(cfg)
    cfg.missing_info = compute_missing_info(cfg)
    return cfg


def make_questions(cfg: BusinessConfig) -> list[Question]:
    qs: list[Question] = []

    def add(kind, field, text, options=None):
        qs.append(Question(id=f"q{len(qs) + 1}", kind=kind, field=field, text=text, options=[str(o) for o in (options or [])]))

    for fname, label in (("phone", "le numéro du salon"), ("address", "l'adresse"), ("hours", "les horaires")):
        f = getattr(cfg, fname)
        if f.status == "conflict":
            add("conflict", fname, f"Sources contradictoires pour {label}. Laquelle est correcte ?", f.alternatives)
        elif f.status == "missing":
            add("missing", fname, f"Je n'ai pas trouvé {label}. Pouvez-vous le renseigner ?")
    if cfg.phone.value and cfg.phone.note == "mobile":
        add("confirm_mobile", "phone", f"Le numéro {cfg.phone.value} est un portable. Est-ce bien celui du salon (et non un portable personnel) ?", ["oui", "non"])
    for s in cfg.services:
        if s.status == "conflict":
            add("conflict", f"service:{norm_key(s.name)}", f"Plusieurs prix trouvés pour « {s.name} ». Lequel est correct ?", s.alt_prices)
    nop = [s.name for s in cfg.services if s.price_eur is None and s.status != "conflict"]
    if nop:
        add("missing_prices", "services", "Prix manquants : " + ", ".join(nop))
    # Les trois questions de calibration
    if any(not s.staff for s in cfg.services) and (cfg.trade == "coiffeur" or cfg.staff):
        add("staff_assignment", "services", "Qui réalise quelle prestation ?", [m.first_name for m in cfg.staff])
    if any(s.duration_min is None or s.duration_source == "defaut_metier" or s.duration_status == "conflict" for s in cfg.services):
        add("durations", "services", "Durée des prestations (valeurs par défaut du métier à valider en un clic)")
    if cfg.rush_delay_min.status == "missing":
        add(
            "rush", 
            "rush_delay_min", 
            "Temps d'attente indicatif à annoncer aux appelants lors d'un pic d'affluence (Mode Rush) :", 
            ["20 minutes", "30 minutes", "45 minutes"]
        )
    for k, text in RULE_KEYS.items():
        if cfg.rules[k].status == "missing":
            add("rule", f"rules.{k}", text)
    return qs


def compute_missing_info(cfg: BusinessConfig) -> list[str]:
    """Ce que l'agent ne saura pas : à transmettre à l'Agent trainer (réponse « je ne sais pas » + rappel)."""
    out = []
    for fname, label in (("phone", "Téléphone du salon"), ("address", "Adresse"), ("hours", "Horaires")):
        if getattr(cfg, fname).status in ("missing", "conflict"):
            out.append(f"{label} non fiable ou absent")
    for k in RULE_KEYS:
        if cfg.rules[k].status == "missing":
            out.append(f"Règle « {RULE_LABELS[k]} » non renseignée")
    if cfg.trade == "coiffeur":
        keys = " ".join(norm_key(s.name) for s in cfg.services)
        if not any(w in keys for w in ("lissage", "defrisage", "boucl")):
            out.append("Lissage, défrisage, cheveux bouclés : non listés")
        out.append("Disponibilités individuelles des professionnels : non fournies (l'agent s'appuie sur les créneaux libres)")
    return out


def _svc(cfg, key):
    return next((s for s in cfg.services if norm_key(s.name) == key), None)


def apply_answer(cfg: BusinessConfig, q: Question, ans) -> None:
    prov = [Prov(source="commercant", confidence=1.0)]
    if q.kind == "conflict":
        val = q.options[int(ans)] if str(ans).isdigit() else ans
        if q.field.startswith("service:"):
            s = _svc(cfg, q.field.split(":", 1)[1])
            s.price_eur, s.status, s.alt_prices = float(val), "confirmed", []
        elif q.field == "hours":
            f = cfg.hours
            idx = int(ans)
            cfg.hours = Fact(value=f.alternatives[idx], status="confirmed", prov=prov)
        else:
            setattr(cfg, q.field, Fact(value=val, status="confirmed", prov=prov))
    elif q.kind == "confirm_mobile":
        if str(ans).lower() in ("oui", "o", "y", "yes"):
            cfg.phone.status, cfg.phone.note = "confirmed", "mobile confirmé par le commerçant"
        else:
            cfg.phone = Fact(note="mobile refusé : numéro à renseigner")
            cfg.pending_questions.append(Question(id=f"q{len(cfg.pending_questions) + 50}", kind="missing", field="phone", text="Quel est le numéro du salon ?"))
    elif q.kind == "missing":
        if q.field == "hours":
            h = clean_hours(ans)
            if h:
                cfg.hours = Fact(value=h, status="confirmed", prov=prov)
        elif q.field == "phone":
            from .validators import norm_phone
            ph, _ = norm_phone(str(ans))
            if ph:
                cfg.phone = Fact(value=ph, status="confirmed", prov=prov)
        elif ans:
            setattr(cfg, q.field, Fact(value=str(ans), status="confirmed", prov=prov))
    elif q.kind == "missing_prices":
        for name, v in ans.items():
            s = _svc(cfg, norm_key(name))
            if s and clean_price(v):
                s.price_eur, s.status = float(v), "confirmed"
    elif q.kind == "staff_assignment":
        for name, names in ans.items():
            s = _svc(cfg, norm_key(name))
            if s:
                s.staff = [n for n in (clean_first_name(x) for x in names) if n]
    elif q.kind == "durations":
        for name, v in ans.items():
            s = _svc(cfg, norm_key(name))
            if s and clean_duration(v):
                s.duration_min, s.duration_status, s.duration_source = int(v), "confirmed", "commercant"
    elif q.kind == "rush":
        cfg.rush_delay_min = Fact(value=int(ans), status="confirmed", prov=prov)
    elif q.kind == "rule":
        k = q.field.split(".", 1)[1]
        from .validators import clean_text
        t = clean_text(str(ans), 300)
        if t:
            cfg.rules[k] = Fact(value=t, status="confirmed", prov=prov)
    cfg.pending_questions = [x for x in cfg.pending_questions if x.id != q.id]
    cfg.missing_info = compute_missing_info(cfg)
