import os
import json
import streamlit as st
import pandas as pd
from pathlib import Path

# Imports directs depuis le package installer
from installer.models import BusinessConfig, Fact, Prov, StaffMember, Service
from installer.build import build_config, make_questions, compute_missing_info, apply_answer
from installer.validators import clean_extraction, norm_key, clean_first_name, clean_hours, clean_price, clean_duration, clean_text
from installer.agent_export import knowledge_base, DAYS_FR
from installer.export import finalize, canonical, save
from installer.pipeline import JsonCache, run_pipeline
from installer.cli import _env_clients

st.set_page_config(
    page_title="Décroche.ai — Installer Studio (Rôle 4)",
    page_icon="⚡",
    layout="wide"
)

# -----------------------------------------------------------------------------
# 1. ÉTAT DE SESSION
# -----------------------------------------------------------------------------
if "cfg" not in st.session_state:
    st.session_state.cfg = None

if "run_logs" not in st.session_state:
    st.session_state.run_logs = []

STATUS_BADGES = {
    "found": "🟢 Trouvé (≥ 2 sources)",
    "confirmed": "🔵 Confirmé (Commerçant)",
    "suggested": "🟡 À valider (1 source ou Défaut)",
    "conflict": "🔴 Conflit détecté",
    "missing": "⚪ Manquant"
}

# -----------------------------------------------------------------------------
# 2. BARRE LATÉRALE (SIDEBAR) : CHARGEMENT, ENQUÊTE & LOGS
# -----------------------------------------------------------------------------
st.sidebar.title("⚡ Installer Studio")
st.sidebar.caption("Hackathon Décroche — Équipe 06 · Rôle 4")

mode = st.sidebar.radio(
    "Source des données :",
    ["Cas Fictif (Import JSON)", "Commerce Réel (Enquête Live API)", "Ouvrir une config v1.x (.json)"]
)

if mode == "Cas Fictif (Import JSON)":
    st.sidebar.write("Test sans consommation d'API.")
    json_path = "maison_lemoine.json"
    if not os.path.exists(json_path) and os.path.exists("fixtures/maison_lemoine.json"):
        json_path = "fixtures/maison_lemoine.json"

    if st.sidebar.button("Charger le fichier local", type="primary"):
        if os.path.exists(json_path):
            raw = json.load(open(json_path, encoding="utf8"))
            data, w = clean_extraction(raw)
            prov = Prov(source="import", url=json_path, confidence=1.0)
            cfg = build_config(raw.get("name") or "Commerce Fictif", [{"prov": prov, "data": data}], None, w)
            st.session_state.cfg = cfg
            st.session_state.run_logs = [f"Importé depuis {json_path}"]
            st.sidebar.success("Fichier importé avec succès !")
        else:
            st.sidebar.error(f"Fichier `{json_path}` introuvable à la racine.")

elif mode == "Commerce Réel (Enquête Live API)":
    st.sidebar.write("Pipeline officiel (Google Places + Web + Registre + LLM).")
    target_name = st.sidebar.text_input("Nom du commerce", value="The barber by Lacrim")
    target_city = st.sidebar.text_input("Ville", value="Nanterre")
    custom_url = st.sidebar.text_input("URL spécifique (optionnelle)", value="https://thebarberbylacrim.com")

    if st.sidebar.button("Lancer l'enquête multi-sources", type="primary"):
        logs = []
        with st.spinner("Enquête en cours (Places, Planity/Site, Registre, Claude)..."):
            try:
                extractor, discover, lookup = _env_clients()
                urls = [custom_url.strip()] if custom_url.strip() else []
                cfg = run_pipeline(
                    target_name,
                    target_city,
                    urls=urls,
                    extractor=extractor,
                    discover=discover,
                    registry_fn=lookup,
                    cache=JsonCache(),
                    log=lambda m: logs.append(m)
                )
                st.session_state.cfg = cfg
                st.session_state.run_logs = logs
                st.sidebar.success("Enquête terminée avec succès !")
            except Exception as e:
                st.sidebar.error(f"Erreur durant l'enquête : {e}")

elif mode == "Ouvrir une config v1.x (.json)":
    uploaded = st.sidebar.file_uploader("Charger une configuration JSON", type=["json"])
    if uploaded and st.sidebar.button("Ouvrir la configuration"):
        raw = json.load(uploaded)
        st.session_state.cfg = BusinessConfig.model_validate(raw)
        st.session_state.run_logs = [f"Configuration {uploaded.name} chargée."]
        st.sidebar.success("Configuration chargée !")

# Monitoring Budget & Jetons
if st.session_state.cfg and st.session_state.cfg.meta.get("tokens"):
    tokens = st.session_state.cfg.meta["tokens"]
    st.sidebar.markdown("---")
    st.sidebar.subheader("💰 Consommation LLM")
    st.sidebar.write(f"- Jetons entrée : `{tokens.get('input', 0)}`")
    st.sidebar.write(f"- Jetons sortie : `{tokens.get('output', 0)}`")
    st.sidebar.caption("Modèle : Claude 3.5 Haiku (budget d'équipe préservé)")

# -----------------------------------------------------------------------------
# 3. VÉRIFICATION D'INITIALISATION
# -----------------------------------------------------------------------------
if st.session_state.cfg is None:
    st.info("👈 Veuillez sélectionner une source dans le menu latéral et charger un commerce pour démarrer.")
    st.stop()

cfg: BusinessConfig = st.session_state.cfg

# -----------------------------------------------------------------------------
# 4. EN-TÊTE D'ANALYSE
# -----------------------------------------------------------------------------
col_title, col_m1, col_m2, col_m3 = st.columns([3, 1, 1, 1])
with col_title:
    st.title(f"🏢 {cfg.name.value}")
    st.caption(f"Secteur détecté : **{cfg.trade or 'Non sectorisé'}** | Catégorie brute : `{cfg.category.value or 'N/A'}`")
with col_m1:
    st.metric("Questions restantes", len(cfg.pending_questions))
with col_m2:
    st.metric("Infos non fournies", len(cfg.missing_info))
with col_m3:
    st.metric("Prestations / Produits", len(cfg.services))

if cfg.warnings:
    with st.expander(f"⚠️ Avertissements et filtres appliqués ({len(cfg.warnings)})", expanded=False):
        for w in cfg.warnings:
            st.warning(w)

if st.session_state.run_logs:
    with st.expander("📜 Journal d'exécution du pipeline", expanded=False):
        for log in st.session_state.run_logs:
            st.code(log, language="bash")

# -----------------------------------------------------------------------------
# 5. ONGLETS FONCTIONNELS
# -----------------------------------------------------------------------------
tab_inspect, tab_calibrate, tab_export = st.tabs([
    "🔍 1. Données Scrapées & Traçabilité",
    "⚙️ 2. Questions & Calibration Métier",
    "📦 3. Validation & Export v1.0"
])

# =============================================================================
# ONGLET 1 : INSPECTION DES DONNÉES & TRAÇABILITÉ (MODIFIABLE & GÉNÉRIQUE)
# =============================================================================
with tab_inspect:
    st.subheader("1. Établissement, Coordonnées & Horaires")
    col_id, col_h = st.columns(2)

    with col_id:
        st.markdown("##### Coordonnées de base (modifiables)")
        c_name = st.text_input("Nom commercial :", value=cfg.name.value or "", key="edit_name")
        c_addr = st.text_input("Adresse postale :", value=cfg.address.value or "", key="edit_addr")
        c_phone = st.text_input("Téléphone pro :", value=cfg.phone.value or "", key="edit_phone")

        if st.button("💾 Mettre à jour les coordonnées", key="btn_save_coords"):
            cfg.name = Fact(value=clean_text(c_name, 120), status="confirmed", prov=[Prov(source="commercant", confidence=1.0)])
            cfg.address = Fact(value=clean_text(c_addr, 200), status="confirmed", prov=[Prov(source="commercant", confidence=1.0)])
            from installer.validators import norm_phone
            ph, ph_k = norm_phone(c_phone)
            cfg.phone = Fact(value=ph or c_phone, status="confirmed", note=ph_k, prov=[Prov(source="commercant", confidence=1.0)])
            st.success("Coordonnées mises à jour !")
            st.rerun()

        if cfg.legal.value:
            leg = cfg.legal.value
            st.caption(f"SIREN : `{leg.get('siren')}` | Code NAF : `{leg.get('naf')}` | Forme : `{leg.get('legal_form_code')}`")

        if cfg.rating.value:
            r = cfg.rating.value
            st.caption(f"Note moyenne : ⭐ {r.get('value')} ({r.get('count')} avis au total)")

    with col_h:
        st.markdown("##### Horaires d'ouverture consolidés (modifiables)")
        h_rows = []
        for d_key, d_fr in DAYS_FR:
            val = (cfg.hours.value or {}).get(d_key, "closed") if cfg.hours.value else "closed"
            h_rows.append({
                "code": d_key,
                "Jour": d_fr,
                "Plage horaire": "fermé" if val == "closed" else val
            })
        df_h = pd.DataFrame(h_rows)

        edited_h = st.data_editor(
            df_h[["Jour", "Plage horaire"]],
            disabled=["Jour"],
            use_container_width=True,
            key="editor_hours_tab1"
        )

        if st.button("💾 Mettre à jour les horaires", key="btn_save_hours"):
            new_h_dict = {}
            for idx, row in edited_h.iterrows():
                d_k = h_rows[idx]["code"]
                val_str = str(row["Plage horaire"]).strip().lower()
                new_h_dict[d_k] = "closed" if val_str in ("fermé", "ferme", "closed") else val_str

            cleaned = clean_hours(new_h_dict)
            if cleaned:
                cfg.hours = Fact(
                    value=cleaned,
                    status="confirmed",
                    prov=[Prov(source="commercant", confidence=1.0)]
                )
                cfg.pending_questions = [q for q in cfg.pending_questions if q.field != "hours"]
                st.success("Horaires mis à jour et confirmés !")
                st.rerun()
            else:
                st.error("Format invalide. Exemple attendu : 09:30-19:30 ou fermé.")
        st.caption(f"Statut des horaires : {STATUS_BADGES.get(cfg.hours.status)}")

    st.markdown("---")
    st.subheader("2. Équipe (Prénoms seuls — Minimisation RGPD)")
    st.caption("Ajoutez ou gérez les membres d'équipe si le site public n'affichait pas de liste.")

    col_staff_l, col_staff_r = st.columns([3, 2])
    with col_staff_l:
        if cfg.staff:
            staff_data = [
                {"Prénom": m.first_name, "Spécialités": ", ".join(m.specialties) or "Polyvalent", "Sources": ", ".join(sorted({p.source for p in m.prov}))}
                for m in cfg.staff
            ]
            st.table(pd.DataFrame(staff_data))
        else:
            st.info("Aucun membre d'équipe extrait publiquement (équipe polyvalente ou non renseignée).")

    with col_staff_r:
        with st.expander("➕ Ajouter un membre d'équipe", expanded=not bool(cfg.staff)):
            add_fname = st.text_input("Prénom seul (RGPD strict) :", key="input_add_staff_fn")
            add_specs = st.text_input("Spécialités (séparées par virgules) :", key="input_add_staff_sp")
            if st.button("Ajouter à l'équipe", key="btn_add_staff"):
                fn_clean = clean_first_name(add_fname.strip().capitalize())
                if fn_clean:
                    sp_list = [clean_text(x, 40) for x in add_specs.split(",") if clean_text(x, 40)]
                    cfg.staff.append(StaffMember(first_name=fn_clean, specialties=sp_list, prov=[Prov(source="commercant", confidence=1.0)]))
                    cfg.pending_questions = make_questions(cfg)
                    st.success(f"{fn_clean} ajouté à l'équipe !")
                    st.rerun()
                else:
                    st.error("Veuillez renseigner un prénom valide unique sans nom de famille.")

    st.markdown("---")
    st.subheader("3. Catalogue (Prestations ou Produits)")
    st.caption("Visualisez les prestations scrapées, modifiez-les directement ou ajoutez celles absentes du web.")

    if cfg.services:
        svc_data = []
        for s in cfg.services:
            sources_str = ", ".join(sorted({p.source for p in s.prov}))
            svc_data.append({
                "Nom": s.name,
                "Prix (€)": s.price_eur if s.price_eur is not None else 0.0,
                "Statut": STATUS_BADGES.get(s.status),
                "Durée (min)": s.duration_min if s.duration_min else 0,
                "Source Durée": s.duration_source or "—",
                "Affectation": ", ".join(s.staff) if s.staff else "Tous / Polyvalent",
                "En ligne": bool(s.bookable_online),
                "Sources": sources_str
            })
        st.dataframe(pd.DataFrame(svc_data), use_container_width=True)
    else:
        st.warning("Aucune prestation scrapée en ligne.")

    with st.expander("➕ Ajouter une prestation manquante non scrapable", expanded=not bool(cfg.services)):
        c_s1, c_s2, c_s3, c_s4 = st.columns([3, 2, 2, 3])
        with c_s1:
            new_s_name = st.text_input("Nom de la prestation :", key="add_s_name")
        with c_s2:
            new_s_price = st.number_input("Prix (€) :", min_value=0.0, max_value=2000.0, value=30.0, step=1.0, key="add_s_price")
        with c_s3:
            new_s_dur = st.number_input("Durée (min) :", min_value=5, max_value=360, value=30, step=5, key="add_s_dur")
        with c_s4:
            staff_options = [m.first_name for m in cfg.staff]
            new_s_staff = st.multiselect("Affectation staff :", options=staff_options, key="add_s_staff")

        if st.button("Ajouter au catalogue", key="btn_add_service"):
            clean_nm = clean_text(new_s_name, 100)
            if clean_nm:
                new_svc = Service(
                    name=clean_nm,
                    price_eur=clean_price(new_s_price),
                    duration_min=clean_duration(new_s_dur),
                    duration_status="confirmed",
                    duration_source="commercant",
                    staff=new_s_staff,
                    status="confirmed",
                    prov=[Prov(source="commercant", confidence=1.0)]
                )
                cfg.services.append(new_svc)
                cfg.pending_questions = make_questions(cfg)
                cfg.missing_info = compute_missing_info(cfg)
                st.success(f"Prestation « {clean_nm} » ajoutée !")
                st.rerun()
            else:
                st.error("Le nom de la prestation est requis.")


# =============================================================================
# ONGLET 2 : QUESTIONS EN SUSPENS & CALIBRATION DYNAMIQUE (100% GÉNÉRIQUE)
# =============================================================================
with tab_calibrate:
    st.subheader("Questions nécessaires au bon fonctionnement de l'agent vocal")
    st.info("Principe Rôle 4 : Zéro question sur ce qui a déjà été trouvé. Seuls les manques, conflits ou règles internes apparaissent ici.")

    if not cfg.pending_questions:
        st.success("🎉 Aucune question en suspens ! Toutes les données sont consolidées.")
    else:
        st.write(f"Il reste **{len(cfg.pending_questions)} question(s)** à trancher :")

        with st.form("form_questions_dynamique"):
            answers = {}

            for q in cfg.pending_questions:
                st.markdown(f"### ❓ {q.text}")

                # 1. Conflit de sources, choix multiples ou rush
                if q.kind in ("conflict", "confirm_mobile", "rush"):
                    if q.kind == "confirm_mobile":
                        options = ["oui", "non"]
                        choice = st.radio("Sélectionnez l'option applicable :", options=options, key=f"q_{q.id}")
                        answers[q.id] = choice
                    elif q.kind == "rush":
                        st.caption("ℹ️ Lorsque vous activerez le mode « Rush » dans votre application, l'agent vocal annoncera ce délai d'attente aux appelants.")
                        rush_map = {
                            "20 minutes d'attente": 20,
                            "30 minutes d'attente (recommandé)": 30,
                            "45 minutes d'attente": 45
                        }
                        choice_label = st.radio(
                            "Sélectionnez le délai d'attente par défaut :",
                            options=list(rush_map.keys()),
                            index=1,
                            key=f"q_{q.id}"
                        )
                        answers[q.id] = rush_map[choice_label]
                    else:
                        options = q.options
                        choice = st.radio("Sélectionnez l'option applicable :", options=options, key=f"q_{q.id}")
                        answers[q.id] = choice

                # 2. Organisation de l'équipe (Qui fait quoi ?) - Traitement agnostique
                elif q.kind == "staff_assignment":
                    staff_names = [m.first_name for m in cfg.staff]
                    staff_answers = {}

                    if not staff_names:
                        st.caption("Aucun membre d'équipe public n'a été trouvé. Précisez le fonctionnement :")
                        col_st1, col_st2 = st.columns([2, 1])
                        with col_st1:
                            all_poly = st.checkbox("Commerce individuel ou équipe polyvalente (tout le monde assure tout)", value=True, key=f"poly_{q.id}")
                        with col_st2:
                            quick_staff = st.text_input("Ou renseignez les prénoms de l'équipe (séparés par virgule) :", key=f"quick_st_{q.id}")
                            if quick_staff:
                                staff_names = [clean_first_name(n.strip()) for n in quick_staff.split(",") if clean_first_name(n.strip())]

                        if not all_poly and staff_names:
                            for s in cfg.services:
                                sel = st.multiselect(f"Responsable(s) pour « {s.name} » :", options=staff_names, key=f"staff_{q.id}_{norm_key(s.name)}")
                                if sel:
                                    staff_answers[s.name] = sel
                            answers[q.id] = staff_answers
                        else:
                            answers[q.id] = {}
                    else:
                        st.caption(f"Équipe identifiée ({', '.join(staff_names)}). Indiquez qui assure chaque prestation :")
                        col_s1, col_s2 = st.columns(2)
                        for idx, s in enumerate(cfg.services):
                            if not s.staff:
                                with col_s1 if idx % 2 == 0 else col_s2:
                                    sel = st.multiselect(
                                        f"Prestation « {s.name} » :",
                                        options=staff_names,
                                        default=[],
                                        key=f"staff_{q.id}_{norm_key(s.name)}"
                                    )
                                    if sel:
                                        staff_answers[s.name] = sel
                        answers[q.id] = staff_answers

                # 3. Calibration des durées (Pré-remplies ou défaut métier)
                elif q.kind == "durations":
                    st.caption("Ajustez ou validez les durées estimées (en minutes) :")
                    dur_answers = {}
                    cols_d = st.columns(3)
                    for idx, s in enumerate(cfg.services):
                        if s.duration_min is None or s.duration_source == "defaut_metier" or s.duration_status == "conflict":
                            with cols_d[idx % 3]:
                                default_val = int(s.duration_min) if s.duration_min else 30
                                val = st.number_input(
                                    f"{s.name}",
                                    min_value=5,
                                    max_value=360,
                                    value=default_val,
                                    step=5,
                                    key=f"dur_{q.id}_{norm_key(s.name)}"
                                )
                                dur_answers[s.name] = val
                    answers[q.id] = dur_answers

                # 4. Horaires à renseigner ou corriger
                elif q.field == "hours":
                    st.caption("Renseignez ou ajustez les plages horaires (ex: 09:30-19:30 ou fermé) :")
                    hours_answers = {}
                    cols_h = st.columns(2)
                    for i, (d_k, d_label) in enumerate(DAYS_FR):
                        with cols_h[i % 2]:
                            cur_val = (cfg.hours.value or {}).get(d_k, "closed") if cfg.hours.value else "closed"
                            display_cur = "fermé" if cur_val == "closed" else (cur_val or "")
                            ans_h = st.text_input(
                                f"{d_label} :",
                                value=display_cur,
                                key=f"q_hour_{q.id}_{d_k}"
                            )
                            hours_answers[d_k] = "closed" if ans_h.strip().lower() in ("fermé", "ferme", "closed", "f") else ans_h.strip()
                    answers[q.id] = hours_answers

                # 4 bis. Question Sans Rendez-vous (Guidée Oui / Non)
                elif q.field == "rules.walk_in":
                    st.caption("ℹ️ Indiquez si l'agent vocal peut accepter des passages spontanés au salon.")
                    walk_in_mode = st.radio(
                        "Acceptez-vous les clients sans rendez-vous ?",
                        options=[
                            "Non (Sur rendez-vous uniquement)",
                            "Oui (Selon les disponibilités)"
                        ],
                        key=f"radio_{q.id}"
                    )
                    if "Non" in walk_in_mode:
                        st.caption("Consigne pré-remplie pour l'agent (modifiable si besoin) :")
                        ans_walk = st.text_input(
                            "Consigne pour l'agent :",
                            value="Le salon fonctionne exclusivement sur rendez-vous.",
                            key=f"text_non_{q.id}"
                        )
                    else:
                        st.caption("Consigne pré-remplie pour l'agent (modifiable si besoin) :")
                        ans_walk = st.text_input(
                            "Consigne pour l'agent :",
                            value="Les passages sans rendez-vous sont acceptés selon les disponibilités et créneaux libres du jour.",
                            key=f"text_oui_{q.id}"
                        )
                    answers[q.id] = ans_walk

                # 4 ter. Consultation technique (Guidée Oui / Non)
                elif q.field == "rules.technical_consultation":
                    st.caption("ℹ️ Pour les prestations longues (balayage, couleur, décoloration).")
                    tech_mode = st.radio(
                        "Exigez-vous une consultation préalable avant un balayage ou une décoloration ?",
                        options=[
                            "Non (Réservation directe sans prérequis)",
                            "Oui (Diagnostic ou consultation préalable obligatoire)"
                        ],
                        key=f"radio_{q.id}"
                    )
                    if "Oui" in tech_mode:
                        st.caption("Consigne pré-remplie pour l'agent (modifiable si besoin) :")
                        ans_tech = st.text_input(
                            "Consigne pour l'agent :",
                            value="Une consultation préalable obligatoire de 30 minutes au salon est requise avant de planifier un balayage ou une décoloration.",
                            key=f"text_tech_oui_{q.id}"
                        )
                    else:
                        ans_tech = "Réservation directe autorisée sans consultation préalable obligatoire."
                    answers[q.id] = ans_tech

                # 4 quater. Spécialités capillaires (Lissages, défrisages, texturés)
                elif q.field == "rules.hair_specialties":
                    st.caption("ℹ️ Précisez la position du salon sur les lissages et défrisages pour éviter les hallucinations.")
                    spec_mode = st.radio(
                        "Pratiquez-vous les lissages, défrisages ou cheveux texturés/bouclés ?",
                        options=[
                            "Non (Prestations non pratiquées au salon)",
                            "Oui (Prestations assurées par l'équipe)"
                        ],
                        key=f"radio_{q.id}"
                    )
                    if "Non" in spec_mode:
                        st.caption("Consigne pré-remplie pour l'agent (modifiable si besoin) :")
                        ans_spec = st.text_input(
                            "Consigne pour l'agent :",
                            value="Le salon ne pratique ni les lissages, ni les défrisages, et n'a pas d'expertise spécifique sur cheveux très bouclés.",
                            key=f"text_spec_non_{q.id}"
                        )
                    else:
                        st.caption("Précisez qui s'en occupe et les modalités :")
                        ans_spec = st.text_input(
                            "Consigne pour l'agent :",
                            value="Prestation assurée sur rendez-vous après diagnostic au salon.",
                            key=f"text_spec_oui_{q.id}"
                        )
                    answers[q.id] = ans_spec

                # 4 quinquies. Moyens de paiement
                elif q.field == "rules.payment_methods":
                    st.caption("ℹ️ Renseignez les moyens de paiement acceptés pour répondre aux questions fréquentes.")
                    pay_mode = st.radio(
                        "Quels moyens de paiement acceptez-vous ?",
                        options=[
                            "Carte Bancaire (CB) et Espèces uniquement (pas de chèques)",
                            "Carte Bancaire, Espèces et Chèques",
                            "Paiement sans contact et Apple Pay acceptés dès 1 €"
                        ],
                        key=f"radio_{q.id}"
                    )
                    st.caption("Consigne pré-remplie pour l'agent (modifiable si besoin) :")
                    ans_pay = st.text_input(
                        "Consigne pour l'agent :",
                        value=f"Règlement par {pay_mode.lower()}.",
                        key=f"text_pay_{q.id}"
                    )
                    answers[q.id] = ans_pay

                # 5. Prix manquants
                elif q.kind == "missing_prices":
                    st.caption("Renseignez les montants non affichés publiquement :")
                    price_answers = {}
                    for s in cfg.services:
                        if s.price_eur is None and s.status != "conflict":
                            p_val = st.number_input(
                                f"Prix de « {s.name} » (€) :",
                                min_value=1.0,
                                max_value=2000.0,
                                value=20.0,
                                step=1.0,
                                key=f"price_{q.id}_{norm_key(s.name)}"
                            )
                            price_answers[s.name] = p_val
                    answers[q.id] = price_answers

# Question Préparation des cheveux (Coupes à sec, shampoing, techniques)
                elif q.field == "rules.hair_prep":
                    st.caption("ℹ️ Consigne pour les appelants demandant s'il faut se laver les cheveux avant de venir.")
                    prep_mode = st.radio(
                        "Faut-il venir avec les cheveux propres ou lavés ?",
                        options=[
                            "Shampoing systématiquement inclus et réalisé sur place",
                            "Cheveux propres et secs recommandés (notamment pour coupes femme/homme à sec et diagnostics)",
                            "Cheveux lavés de la veille pour les techniques (balayage, couleur)"
                        ],
                        key=f"radio_{q.id}"
                    )
                    ans_prep = st.text_input(
                        "Consigne pour l'agent :",
                        value=f"Consigne cheveux : {prep_mode.lower()}.",
                        key=f"text_prep_{q.id}"
                    )
                    answers[q.id] = ans_prep

                # 6. Saisie libre générique (annulation, retard, etc.)
                else:
                    st.caption("Renseignez votre politique ou laissez vide si non applicable :")
                    text_ans = st.text_input(
                        "Votre réponse :",
                        key=f"text_{q.id}"
                    )
                    answers[q.id] = text_ans

                st.markdown("---")

            submitted = st.form_submit_button("💾 Enregistrer et appliquer les réponses", type="primary", use_container_width=True)

            if submitted:
                for q in list(cfg.pending_questions):
                    if q.id in answers and answers[q.id] is not None:
                        apply_answer(cfg, q, answers[q.id])

                st.success("Toutes les réponses ont été appliquées ! La configuration est à jour.")
                st.rerun()


# =============================================================================
# ONGLET 3 : VALIDATION & EXPORT V1.0 (PLM & AGENT VOCAL)
# =============================================================================
with tab_export:
    st.subheader("Finalisation et Exportation de la Configuration")

    col_tag, col_btn = st.columns([2, 2])
    with col_tag:
        tag_val = st.text_input("Tag de version (PLM Manager) :", value="v1.1")

    # Scellement avec calcul d'empreinte SHA-256 déterministe
    cfg_final = finalize(cfg, tag=tag_val)
    sha_hash = cfg_final.meta.get("content_sha256", "")

    st.info(f"**Empreinte cryptographique d'intégrité (SHA-256) :** `{sha_hash}`")

    # Section ce que l'agent ne saura pas
    if cfg_final.missing_info:
        with st.expander("🛡️ Ce que l'agent vocal ne saura pas (Supervision / Anti-hallucination)", expanded=True):
            st.caption("Ces manques sont injectés dans la fiche pour contraindre l'agent à dire « Je ne peux pas le confirmer » et proposer un rappel.")
            for m in cfg_final.missing_info:
                st.markdown(f"- **{m}**")

    col_out_json, col_out_kb = st.columns(2)

    with col_out_json:
        st.markdown("#### 1. Configuration JSON Versionnée")
        st.caption("Contient la traçabilité complète de chaque fait (pour le PLM Manager).")
        json_str = json.dumps(cfg_final.model_dump(), ensure_ascii=False, indent=2)

        file_slug = norm_key(cfg_final.name.value).replace(" ", "_")
        json_filename = f"{file_slug}.{tag_val}.json"

        st.download_button(
            label="⬇️ Télécharger la configuration (JSON)",
            data=json_str,
            file_name=json_filename,
            mime="application/json",
            use_container_width=True
        )
        st.json(cfg_final.model_dump())

    with col_out_kb:
        st.markdown("#### 2. Base de Connaissances Markdown")
        st.caption("Fiche épurée prête à être injectée dans ElevenLabs / Décroche.ai.")

        kb_text = knowledge_base(cfg_final, include_suggested=False)
        st.download_button(
            label="⬇️ Télécharger la fiche agent (Markdown)",
            data=kb_text,
            file_name="fiche_agent.md",
            mime="text/markdown",
            use_container_width=True
        )
        st.text_area("Contenu de la Knowledge Base :", kb_text, height=450)