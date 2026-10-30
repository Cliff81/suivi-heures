#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Attribution des courses d'une journee aux salaries disponibles.

Le probleme est un VRP avec fenetres horaires : plusieurs vehicules partant
de chez eux, des courses qui lient une prise en charge a une depose, des
creneaux a tenir. Il est resolu par le service d'optimisation (VROOM) de
l'API de cartographie.

Ce module ne connait ni la base ni le reseau : il construit la demande et
relit la reponse. On peut donc le verifier sans rien appeler dehors.

Deux pieges du format VROOM, verifies contre l'API :
  - la fenetre d'un vehicule est `time_window` (singulier), celle d'une etape
    est `time_windows` (pluriel). Le singulier sur une etape est accepte et
    ignore en silence : la contrainte disparait sans erreur.
  - les identifiants sont des entiers. On encode la depose en decalant l'id
    de la course, pour retrouver la course a la relecture.
"""

DECALAGE_DEPOSE = 1_000_000     # id de depose = id de course + ce decalage

# Codes rendus par VROOM dans le champ "code".
MOTIFS = {
    0: None,
    1: "le solveur a rencontré une erreur interne",
    2: "la demande envoyée au solveur est invalide",
    3: "le service n'a pas pu calculer les trajets",
}


def construire(salaries, courses, coords, profil="driving-car"):
    """Construit la demande d'optimisation.

    salaries : [{id, adresse, debut, fin, places, pause}] en minutes
    courses  : [{id, prise, depose, service_prise, service_depose,
                 prise_au_plus_tot, arrivee_debut, arrivee_fin}] en minutes
    coords   : {adresse -> (lat, lon)} deja geocodees

    Renvoie (demande, ecartes). `ecartes` liste ce qui n'a pas pu entrer dans
    le calcul, avec le motif : une adresse sans coordonnees ne peut pas etre
    confiee au solveur, mais elle ne doit pas disparaitre silencieusement.
    """
    ecartes = []

    def point(adresse):
        c = coords.get(adresse)
        return [c[1], c[0]] if c else None      # VROOM attend [lon, lat]

    vehicules = []
    for s in salaries:
        p = point(s["adresse"])
        if p is None:
            ecartes.append({"genre": "salarie", "id": s["id"],
                            "motif": f"adresse de départ inutilisable : {s['adresse'] or '—'}"})
            continue
        v = {
            "id": s["id"],
            "profile": profil,
            "start": p,
            "end": p,
            "capacity": [max(1, s.get("places") or 1)],
            "time_window": [int(s["debut"]) * 60, int(s["fin"]) * 60],
        }
        if s.get("pause"):
            # Le repos de la journee : le solveur le place ou il gene le moins.
            v["breaks"] = [{"id": s["id"], "service": int(s["pause"]) * 60}]
        vehicules.append(v)

    envois = []
    for c in courses:
        a, b = point(c["prise"]), point(c["depose"])
        if a is None or b is None:
            manquante = c["prise"] if a is None else c["depose"]
            ecartes.append({"genre": "course", "id": c["id"],
                            "motif": f"adresse inutilisable : {manquante or '—'}"})
            continue
        prise = {"id": c["id"], "location": a,
                 "service": int(c["service_prise"]) * 60}
        if c.get("prise_au_plus_tot") is not None:
            prise["time_windows"] = [[int(c["prise_au_plus_tot"]) * 60, 24 * 3600]]
        depose = {"id": c["id"] + DECALAGE_DEPOSE, "location": b,
                  "service": int(c["service_depose"]) * 60}
        if c.get("arrivee_debut") is not None or c.get("arrivee_fin") is not None:
            debut = int(c.get("arrivee_debut") or 0) * 60
            fin = int(c["arrivee_fin"]) * 60 if c.get("arrivee_fin") is not None \
                else 24 * 3600
            depose["time_windows"] = [[debut, fin]]
        envois.append({"amount": [1], "pickup": prise, "delivery": depose})

    return {"vehicles": vehicules, "shipments": envois}, ecartes


def relire(reponse):
    """Relit la reponse du solveur.

    Renvoie :
      affectations  {course_id: {"salarie": id, "position": n,
                                 "prise": minutes, "depose": minutes}}
      non_affectees [course_id]
      motif         None si tout va bien, sinon le texte a afficher
      resume        {"duree": minutes, "vehicules": n}
    """
    code = reponse.get("code")
    if code is None or code != 0:
        return {"affectations": {}, "non_affectees": [],
                "motif": MOTIFS.get(code, "réponse inattendue du solveur"),
                "resume": {}}

    affectations = {}
    for route in reponse.get("routes") or []:
        sid = route.get("vehicle")
        rang = 0
        for etape in route.get("steps") or []:
            genre = etape.get("type")
            ident = etape.get("id")
            if ident is None or genre not in ("pickup", "delivery"):
                continue
            cid = ident - DECALAGE_DEPOSE if ident >= DECALAGE_DEPOSE else ident
            fiche = affectations.setdefault(
                cid, {"salarie": sid, "position": None,
                      "prise": None, "depose": None})
            # Arriver tot ne sert a rien : quand le creneau n'est pas encore
            # ouvert, VROOM fait patienter et le service commence plus tard.
            # C'est cette heure-la qui compte pour le patient.
            debut = etape.get("arrival", 0) + etape.get("waiting_time", 0)
            minutes = int(round(debut / 60.0))
            if genre == "pickup":
                fiche["position"] = rang
                fiche["prise"] = minutes
                rang += 1
            else:
                fiche["depose"] = minutes

    non_affectees = []
    for item in reponse.get("unassigned") or []:
        ident = item.get("id")
        if ident is None:
            continue
        cid = ident - DECALAGE_DEPOSE if ident >= DECALAGE_DEPOSE else ident
        if cid not in non_affectees:
            non_affectees.append(cid)

    resume = reponse.get("summary") or {}
    return {
        "affectations": affectations,
        "non_affectees": non_affectees,
        "motif": None,
        "resume": {
            "duree": int(round(resume.get("duration", 0) / 60.0)),
            "vehicules": resume.get("routes", 0),
        },
    }
