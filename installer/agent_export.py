"""Export « fiche commerce » : données validées, en français, à coller dans la base de connaissances de l'agent.
Ce n'est PAS le prompt de l'agent (comportement, ton, « je ne sais pas ») : c'est le travail de l'Agent trainer."""
from __future__ import annotations
from .models import BusinessConfig

DAYS_FR = [("mon", "Lundi"), ("tue", "Mardi"), ("wed", "Mercredi"), ("thu", "Jeudi"), ("fri", "Vendredi"), ("sat", "Samedi"), ("sun", "Dimanche")]
RULES_FR = {"walk_in": "Clients sans rendez-vous", "cancellation": "Annulation", "late_policy": "Retard du client"}


def _eur(x: float) -> str:
    return f"{x:g}".replace(".", ",") + " €"


def knowledge_base(cfg: BusinessConfig, include_suggested: bool = False) -> str:
    ok = ("found", "confirmed") + (("suggested",) if include_suggested else ())
    skipped = 0
    out = [f"# {cfg.name.value}", ""]
    for label, f in (("Adresse", cfg.address), ("Téléphone", cfg.phone)):
        if f.status in ok and f.value:
            out.append(f"{label} : {f.value}")
        elif f.value:
            skipped += 1
    out.append("")
    if cfg.hours.status in ok and cfg.hours.value:
        out.append("## Horaires d'ouverture")
        for k, lab in DAYS_FR:
            v = cfg.hours.value.get(k)
            if v:
                out.append(f"- {lab} : {'fermé' if v == 'closed' else v.replace('-', ' à ')}")
        out.append("")
    elif cfg.hours.value or cfg.hours.alternatives:
        skipped += 1
    lines = []
    for s in cfg.services:
        if s.price_eur is None or s.status not in ok:
            skipped += 1
            continue
        part = [f"{s.name} : {_eur(s.price_eur)}"]
        if s.duration_min and s.duration_status in ok and s.duration_source != "defaut_metier":
            part.append(f"{s.duration_min} min")
        if s.staff:
            part.append("avec " + " ou ".join(s.staff))
        lines.append("- " + " · ".join(part))
    if lines:
        out += ["## Prestations et tarifs", *lines, ""]
    if cfg.staff:
        out.append("## Équipe")
        out += [f"- {m.first_name}" + (f" : {', '.join(m.specialties)}" if m.specialties else "") for m in cfg.staff]
        out.append("")
    if cfg.rush_delay_min.status in ok and cfg.rush_delay_min.value:
        out += ["## Délai en heure de rush", f"{cfg.rush_delay_min.value} minutes", ""]
    rules = [f"- {RULES_FR[k]} : {f.value}" for k, f in cfg.rules.items() if f.status in ok and f.value]
    if rules:
        out += ["## Règles d'accueil", *rules, ""]
    if cfg.missing_info:
        out += ["## Informations que l'établissement n'a pas fournies", *[f"- {m}" for m in cfg.missing_info], ""]
    out.append(f"<!-- config {cfg.meta.get('tag', '?')} · sha256 {str(cfg.meta.get('content_sha256', ''))[:12]} · "
               f"{skipped} information(s) non validée(s) exclue(s) -->")
    return "\n".join(out)
