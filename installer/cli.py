"""Ligne de commande : run | import | ask | show | kb | diff"""
from __future__ import annotations
import argparse, json, os, sys
from .build import apply_answer, build_config
from .export import diff, finalize, save
from .models import BusinessConfig, Prov
from .validators import clean_extraction, norm_key

ICON = {"found": "✓ trouvé    ", "confirmed": "✓ confirmé  ", "suggested": "~ à valider ", "conflict": "! conflit    ", "missing": "✗ manquant  "}


def render(cfg: BusinessConfig, p=print):
    def line(label, f):
        v = f.value if f.status != "conflict" else " | ".join(map(str, f.alternatives))
        srcs = ",".join(sorted({x.source for x in f.prov}))
        p(f"  {ICON[f.status]} {label:<14} {v if v is not None else ''}  [{srcs}]{'  ' + f.note if f.note else ''}")
    p(f"\n=== {cfg.name.value} (métier : {cfg.trade or '?'}) ===")
    for label, f in (("Adresse", cfg.address), ("Téléphone", cfg.phone), ("Horaires", cfg.hours), ("Registre", cfg.legal), ("Note", cfg.rating)):
        line(label, f)
    for s in cfg.services:
        d = f"{s.duration_min} min ({s.duration_source})" if s.duration_min else "durée ?"
        pr = s.price_eur if s.price_eur is not None else ("/".join(map(str, s.alt_prices)) or "?")
        p(f"  {ICON[s.status]} {s.name[:34]:<34} {pr} €  {d}  {', '.join(s.staff)}")
    p(f"  Équipe : {', '.join(m.first_name for m in cfg.staff) or '—'}")
    for w in cfg.warnings:
        p(f"  ⚠ {w}")
    p(f"  Questions restantes : {len(cfg.pending_questions)}")


def ask(cfg: BusinessConfig, input_fn=input, p=print):
    for q in list(cfg.pending_questions):
        p(f"\n? {q.text}")
        if q.kind in ("conflict", "confirm_mobile", "rush"):
            for i, o in enumerate(q.options):
                p(f"   {i}. {o}")
            a = input_fn("   > ").strip()
            if q.kind == "confirm_mobile":
                apply_answer(cfg, q, a or "oui")
            elif a.isdigit():
                n = int(a)
                if q.kind == "rush":                      # 0-2 = choix de la liste, sinon nombre de minutes
                    apply_answer(cfg, q, q.options[n] if n < len(q.options) else n)
                elif n < len(q.options):
                    apply_answer(cfg, q, n)
        elif q.kind == "durations":
            ans = {}
            for s in cfg.services:
                if s.duration_min is None or s.duration_source == "defaut_metier" or s.duration_status == "conflict":
                    a = input_fn(f"   {s.name} [{s.duration_min or '?'} min] (Entrée = valider) > ").strip()
                    v = a or s.duration_min
                    if v:
                        ans[s.name] = v
            apply_answer(cfg, q, ans)
        elif q.kind == "staff_assignment":
            p(f"   Équipe : {', '.join(q.options) or '(aucun prénom trouvé)'} — prénoms séparés par des virgules, Entrée pour passer")
            ans = {}
            for s in cfg.services:
                if not s.staff:
                    a = input_fn(f"   {s.name} > ").strip()
                    if a:
                        ans[s.name] = [x.strip() for x in a.split(",")]
            apply_answer(cfg, q, ans)
        elif q.kind == "missing_prices":
            ans = {}
            for s in cfg.services:
                if s.price_eur is None and s.status != "conflict":
                    a = input_fn(f"   Prix de {s.name} (€) > ").strip().replace(",", ".")
                    if a:
                        ans[s.name] = a
            apply_answer(cfg, q, ans)
        elif q.field == "hours":
            h = {}
            for d, lab in zip(("mon", "tue", "wed", "thu", "fri", "sat", "sun"), ("Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche")):
                a = input_fn(f"   {lab} (ex. 09:30-19:30, ou f = fermé) > ").strip()
                h[d] = "closed" if a.lower() in ("f", "fermé", "ferme") else (a or None)
            apply_answer(cfg, q, h)
        else:
            a = input_fn("   > ").strip()
            if a:
                apply_answer(cfg, q, a)
    return cfg


def _env_clients():
    from .extract import claude_extractor
    from .registry import lookup
    from .places import search_place
    
    key = os.getenv("GOOGLE_MAPS_API_KEY") or os.getenv("SERPER_API_KEY")
    
    def discover_fn(name: str, city: str):
        place_data = search_place(name, city, key)
        if not place_data:
            return {}
        return {
            "place": place_data,
            "site": place_data.get("website"),
            "planity": None  # Sera enrichi si le site pointe vers Planity ou via --url
        }
        
    discover = discover_fn if key else None
    return claude_extractor(), discover, lookup


def _load(path) -> BusinessConfig:
    return BusinessConfig.model_validate(json.load(open(path, encoding="utf8")))


def main(argv=None):
    ap = argparse.ArgumentParser(prog="installer")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run"); r.add_argument("--name", required=True); r.add_argument("--city", default="")
    r.add_argument("--url", action="append", default=[]); r.add_argument("--tag", default="v1.0")
    r.add_argument("--out", default="out"); r.add_argument("--no-ask", action="store_true")
    i = sub.add_parser("import"); i.add_argument("file"); i.add_argument("--tag", default="v1.0")
    i.add_argument("--out", default="out"); i.add_argument("--no-ask", action="store_true")
    a = sub.add_parser("ask"); a.add_argument("config"); a.add_argument("--tag", default="v1.1"); a.add_argument("--out", default="out")
    s = sub.add_parser("show"); s.add_argument("config")
    k = sub.add_parser("kb"); k.add_argument("config"); k.add_argument("--include-suggested", action="store_true"); k.add_argument("--out")
    d = sub.add_parser("diff"); d.add_argument("a"); d.add_argument("b")
    args = ap.parse_args(argv)

    if args.cmd == "show":
        render(_load(args.config)); return
    if args.cmd == "kb":
        from .agent_export import knowledge_base
        text = knowledge_base(_load(args.config), args.include_suggested)
        if args.out:
            open(args.out, "w", encoding="utf8").write(text)
            print(f"Fiche écrite : {args.out}")
        else:
            print(text)
        return
    if args.cmd == "diff":
        for l in diff(json.load(open(args.a, encoding="utf8")), json.load(open(args.b, encoding="utf8"))):
            print(l)
        return
    os.makedirs(getattr(args, "out", "out"), exist_ok=True)
    parent = None
    if args.cmd == "run":
        from .pipeline import JsonCache, run_pipeline
        extractor, discover, lookup = _env_clients()
        print(f"Enquête sur « {args.name} » {args.city}")
        cfg = run_pipeline(args.name, args.city, args.url, extractor=extractor, discover=discover, registry_fn=lookup, cache=JsonCache())
        name = args.name
    elif args.cmd == "import":
        raw = json.load(open(args.file, encoding="utf8"))
        data, w = clean_extraction(raw)
        cfg = build_config(raw.get("name") or "commerce", [{"prov": Prov(source="import", url=args.file, confidence=1.0), "data": data}], None, w)
        name = cfg.name.value
    else:
        cfg = _load(args.config); parent = cfg.meta.get("content_sha256"); name = cfg.name.value
    render(cfg)
    if not getattr(args, "no_ask", False) and cfg.pending_questions:
        ask(cfg)
        render(cfg)
    finalize(cfg, args.tag, parent)
    path = os.path.join(args.out, f"{norm_key(name).replace(' ', '_')}.{args.tag}.json")
    save(cfg, path)
    print(f"\nConfig écrite : {path}  (sha256 {cfg.meta['content_sha256'][:12]}…)")
    if cfg.missing_info:
        print("Ce que l'agent ne saura pas :")
        for m in cfg.missing_info:
            print(f"  - {m}")


if __name__ == "__main__":
    main()
