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
    conduite = installation = stationnement = 0
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

    for i, c in enumerate(courses):
        sta = c["stationnement"] if c["stationnement"] is not None else stationnement_defaut
        ins = c["installation"] or 0
        libelle = c["libelle"] or "Course"

        # 1. rejoindre le point de prise en charge
        trajet(c["prise"], "Trajet", i)
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
            "pause": pause_minutes if (pause_minutes and pause_apres is not None
                                       and pause_apres < len(courses)) else 0,
            "km": round(km_total, 1) if km_total else 0.0,
            "approx": approx,
        },
    }
