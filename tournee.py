#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Planification d'une tournee : a partir d'une heure de prise de service et
d'une liste de courses dans l'ordre de passage, on deroule les horaires.

Le salarie part de chez lui avec le vehicule, va chercher chaque patient
(a son domicile ou a une adresse donnee), le depose, puis enchaine. A chaque
arret on compte le temps de se garer, puis le temps d'installer la personne
dans le vehicule — le meme temps sert a la faire descendre.

Fonction pure : elle ne connait ni la base ni le reseau. Les durees de trajet
lui arrivent par le parametre `duree`, ce qui permet de la relire et de la
tester sans rien appeler dehors.
"""

from core import MAX_AMPLITUDE, fmt_hm


def _etape(genre, titre, debut, minutes, lieu="", detail="", **extra):
    e = {
        "genre": genre,
        "titre": titre,
        "debut": debut,
        "minutes": minutes,
        "fin": debut + (minutes or 0),
        "lieu": lieu,
        "detail": detail,
        "approx": False,
        "source": None,
        "km": None,
        "course": None,
        "origine": None,
        "destination": None,
        "inconnu": False,
    }
    e.update(extra)
    return e


def planifier(depart_adresse, heure_depart, courses, stationnement_defaut,
              pause_minutes, pause_apres, retour_depart, duree):
    """Deroule la tournee.

    depart_adresse        d'ou part le vehicule (domicile du salarie)
    heure_depart          minutes depuis minuit
    courses               liste ordonnee de dicts : libelle, prise, depose,
                          rdv, installation, stationnement
    stationnement_defaut  minutes pour se garer, quand la course n'impose rien
    pause_minutes         duree du repos dans la journee (0 = aucun)
    pause_apres           index de la course apres laquelle le repos tombe
    retour_depart         True si le salarie rentre chez lui a la fin
    duree(a, b)           -> {minutes, km, source, motif}

    Renvoie etapes / resume des courses / totaux / alertes / manques.
    """
    etapes, resume, manques, alertes = [], [], [], []
    conduite = installation = stationnement = attente = 0
    km_total = 0.0
    approx = False          # vrai des qu'une duree manque : la suite glisse

    t = heure_depart if heure_depart is not None else 0
    position = depart_adresse

    etapes.append(_etape("depart", "Prise de service", t, 0,
                         lieu=depart_adresse or "—"))

    def trajet(vers, titre, idx):
        """Ajoute l'etape de trajet et avance l'horloge."""
        nonlocal t, conduite, approx, km_total
        d = duree(position, vers)
        mn = d["minutes"]
        if mn is None:
            approx = True
            manques.append({"origine": position, "destination": vers,
                            "motif": d["motif"], "course": idx})
            mn = 0
        else:
            conduite += mn
            if d["km"]:
                km_total += d["km"]
        etapes.append(_etape(
            "trajet", titre, t, mn, lieu=vers or "—",
            detail=d["motif"] or "", approx=approx or mn is None,
            source=d["source"], km=d["km"], course=idx,
            origine=position, destination=vers,
            inconnu=d["minutes"] is None))
        t += mn

    def attendre(jusqua, pourquoi):
        """Patienter jusqu'a l'ouverture d'un creneau : arriver en avance ne
        sert a rien, ni pour le patient ni pour l'etablissement."""
        nonlocal t, attente
        if jusqua is None or t >= jusqua:
            return
        attente += jusqua - t
        etapes.append(_etape("attente", "Attente", t, jusqua - t,
                             detail=pourquoi, approx=approx))
        t = jusqua

    for i, c in enumerate(courses):
        sta = c["stationnement"] if c["stationnement"] is not None else stationnement_defaut
        ins = c["installation"] or 0
        libelle = c["libelle"] or "Course"

        # 1. rejoindre le point de prise en charge
        trajet(c["prise"], "Trajet", i)
        attendre(c.get("prise_au_plus_tot"),
                 "le patient ne peut pas être pris plus tôt")
        arrivee_prise = t

        # 2. se garer puis installer la personne
        etapes.append(_etape(
            "prise", f"Prise en charge — {libelle}", t, sta + ins,
            lieu=c["prise"] or "—",
            detail=f"{sta} min pour se garer + {ins} min d'installation",
            approx=approx, course=i))
        t += sta + ins
        stationnement += sta
        installation += ins
        position = c["prise"]

        # 3. conduire jusqu'au point de depose
        trajet(c["depose"], "Transport du patient", i)
        attendre(c.get("arrivee_debut"), "le créneau d'arrivée n'est pas ouvert")
        arrivee_depose = t

        # 4. se garer puis faire descendre la personne
        etapes.append(_etape(
            "depose", f"Dépose — {libelle}", t, sta + ins,
            lieu=c["depose"] or "—",
            detail=f"{sta} min pour se garer + {ins} min pour l'installer",
            approx=approx, course=i))
        t += sta + ins
        stationnement += sta
        installation += ins
        position = c["depose"]

        ecart = None
        if c["rdv"] is not None:
            ecart = c["rdv"] - arrivee_depose
            if ecart < 0:
                alertes.append({
                    "niveau": "ko",
                    "texte": f"{libelle} : arrivée prévue à "
                             f"{fmt_hm(arrivee_depose)}, soit "
                             f"{fmt_hm(-ecart)} après le rendez-vous de "
                             f"{fmt_hm(c['rdv'])}.",
                })
        resume.append({
            "libelle": libelle,
            "prise": c["prise"], "depose": c["depose"],
            "arrivee_prise": arrivee_prise,
            "arrivee_depose": arrivee_depose,
            "rdv": c["rdv"], "ecart": ecart,
            "approx": approx,
        })

        # 5. le repos de la journee, quand il tombe apres cette course
        if pause_minutes and pause_apres is not None and pause_apres == i:
            etapes.append(_etape("pause", "Repos", t, pause_minutes,
                                 lieu="", detail="temps de repos de la journée",
                                 approx=approx))
            t += pause_minutes

    if retour_depart and courses:
        trajet(depart_adresse, "Retour", None)
        etapes.append(_etape("retour", "Fin de service", t, 0,
                             lieu=depart_adresse or "—", approx=approx))
    elif courses:
        etapes.append(_etape("retour", "Fin de service", t, 0,
                             lieu=position or "—", approx=approx))

    fin = t
    amplitude = fin - (heure_depart or 0)
    if amplitude > MAX_AMPLITUDE:
        alertes.append({
            "niveau": "ko",
            "texte": f"Amplitude de {fmt_hm(amplitude)} : au-delà des "
                     f"{fmt_hm(MAX_AMPLITUDE)} autorisées sur une journée.",
        })
    if manques:
        alertes.append({
            "niveau": "warn",
            "texte": f"{len(manques)} trajet(s) sans durée connue : les heures "
                     f"affichées après le premier d'entre eux sont incomplètes.",
        })

    return {
        "etapes": etapes,
        "courses": resume,
        "manques": manques,
        "alertes": alertes,
        "totaux": {
            "debut": heure_depart,
            "fin": fin,
            "amplitude": amplitude,
            "conduite": conduite,
            "installation": installation,
            "stationnement": stationnement,
            "attente": attente,
            "pause": pause_minutes if (pause_minutes and pause_apres is not None
                                       and pause_apres < len(courses)) else 0,
            "km": round(km_total, 1) if km_total else 0.0,
            "approx": approx,
        },
    }


def derouler_calcule(depart_adresse, heure_depart, courses, pause, duree):
    """Deroule une tournee deja calculee par le solveur.

    Pourquoi un second moteur : des qu'un vehicule a plusieurs places, le
    solveur groupe les patients — il enchaine deux ou trois prises en charge
    avant la premiere depose. Le deroule en cascade de `planifier()` suppose
    au contraire prise puis depose, une course a la fois : il donnerait des
    horaires faux. Ici on ne recalcule rien, on remet simplement dans l'ordre
    du temps les heures que le solveur a arretees.

    courses : [{libelle, prise, depose, prise_calc, depose_calc, rdv,
                installation, stationnement}]
    pause   : {"debut": minutes, "minutes": n} ou None
    """
    evenements = []
    for i, c in enumerate(courses):
        if c["prise_calc"] is not None:
            evenements.append((c["prise_calc"], 0, i, "prise"))
        if c["depose_calc"] is not None:
            evenements.append((c["depose_calc"], 1, i, "depose"))
    if pause and pause.get("debut") is not None and pause.get("minutes"):
        evenements.append((pause["debut"], 2, None, "pause"))
    evenements.sort()

    etapes, resume, manques, alertes = [], [], [], []
    conduite = installation = stationnement = attente = 0
    km_total = 0.0
    t = heure_depart if heure_depart is not None else (
        evenements[0][0] if evenements else 0)
    position = depart_adresse

    etapes.append(_etape("depart", "Prise de service", t, 0,
                         lieu=depart_adresse or "—"))

    for heure, _rang, i, genre in evenements:
        if genre == "pause":
            etapes.append(_etape("pause", "Repos", heure, pause["minutes"],
                                 detail="temps de repos de la journée"))
            t = heure + pause["minutes"]
            continue

        c = courses[i]
        sta = c["stationnement"] or 0
        ins = c["installation"] or 0
        lieu = c["prise"] if genre == "prise" else c["depose"]

        if lieu and position and lieu != position:
            d = duree(position, lieu)
            mn = d["minutes"]
            if mn is None:
                manques.append({"origine": position, "destination": lieu,
                                "motif": d["motif"], "course": i})
            else:
                conduite += mn
                if d["km"]:
                    km_total += d["km"]
            etapes.append(_etape(
                "trajet", "Trajet" if genre == "prise" else "Transport du patient",
                t, mn or 0, lieu=lieu or "—", detail=d["motif"] or "",
                source=d["source"], km=d["km"], course=i,
                origine=position, destination=lieu,
                inconnu=mn is None))
            t += mn or 0

        # Filet : une heure enregistree plus ancienne que l'horloge courante
        # ferait reculer le deroule. Cela ne doit plus arriver (les heures
        # sont effacees des qu'un parametre change), mais un deroule qui
        # recule serait pire que tout.
        heure = max(heure, t)
        if heure > t:
            attente += heure - t
            etapes.append(_etape(
                "attente", "Attente", t, heure - t,
                detail="en avance : rien à faire avant cette heure"))
        t = heure

        titre = ("Prise en charge — " if genre == "prise" else "Dépose — ") + \
                (c["libelle"] or "Course")
        etapes.append(_etape(
            genre, titre, t, sta + ins, lieu=lieu or "—",
            detail=f"{sta} min pour se garer + {ins} min d'installation",
            course=i))
        t += sta + ins
        stationnement += sta
        installation += ins
        position = lieu

    if depart_adresse and position and position != depart_adresse:
        d = duree(position, depart_adresse)
        mn = d["minutes"]
        if mn is None:
            manques.append({"origine": position, "destination": depart_adresse,
                            "motif": d["motif"], "course": None})
        else:
            conduite += mn
            if d["km"]:
                km_total += d["km"]
        etapes.append(_etape("trajet", "Retour", t, mn or 0,
                             lieu=depart_adresse, source=d["source"],
                             km=d["km"], origine=position,
                             destination=depart_adresse, inconnu=mn is None,
                             detail=d["motif"] or ""))
        t += mn or 0
    etapes.append(_etape("retour", "Fin de service", t, 0,
                         lieu=depart_adresse or position or "—"))

    for c in courses:
        ecart = None
        if c["rdv"] is not None and c["depose_calc"] is not None:
            ecart = c["rdv"] - c["depose_calc"]
            if ecart < 0:
                alertes.append({"niveau": "ko", "texte":
                    f"{c['libelle']} : arrivée prévue à "
                    f"{fmt_hm(c['depose_calc'])}, après le créneau de "
                    f"{fmt_hm(c['rdv'])}."})
        resume.append({
            "libelle": c["libelle"], "prise": c["prise"], "depose": c["depose"],
            "arrivee_prise": c["prise_calc"], "arrivee_depose": c["depose_calc"],
            "rdv": c["rdv"], "ecart": ecart, "approx": False})

    fin = t
    amplitude = fin - (heure_depart if heure_depart is not None else fin)
    if amplitude > MAX_AMPLITUDE:
        alertes.append({"niveau": "ko", "texte":
            f"Amplitude de {fmt_hm(amplitude)} : au-delà des "
            f"{fmt_hm(MAX_AMPLITUDE)} autorisées sur une journée."})
    if manques:
        alertes.append({"niveau": "warn", "texte":
            f"{len(manques)} trajet(s) sans durée connue : les heures restent "
            f"justes (elles viennent du calcul), seules les durées manquent."})

    return {
        "etapes": etapes, "courses": resume, "manques": manques,
        "alertes": alertes,
        "totaux": {
            "debut": heure_depart, "fin": fin, "amplitude": amplitude,
            "conduite": conduite, "installation": installation,
            "stationnement": stationnement,
            "pause": pause["minutes"] if (pause and pause.get("debut") is not None) else 0,
            "attente": attente,
            "km": round(km_total, 1) if km_total else 0.0,
            "approx": False,
        },
    }
