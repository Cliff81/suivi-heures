#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Acces au service de cartographie, pour les durees de trajet des tournees.

Eteint tant que SUIVI_CARTO_CLE n'est pas definie : sans cle, aucune requete
ne sort du serveur et les durees se saisissent a la main.

Les adresses des patients sont des donnees personnelles. Elles ne partent que
vers le service configure, et une seule fois : coordonnees et durees sont
ensuite relues dans la base (tables geo_cache et trajet_cache). Une duree
corrigee a la main est marquee source='manuel' et n'est jamais recouverte par
le service.

Par defaut OpenRouteService, dont les serveurs sont en Allemagne (UE).
"""

import json
import os
import urllib.parse
import urllib.request

from core import cle_adresse

CLE = os.environ.get("SUIVI_CARTO_CLE", "").strip()
BASE = os.environ.get("SUIVI_CARTO_URL",
                      "https://api.openrouteservice.org").rstrip("/")
PAYS = os.environ.get("SUIVI_CARTO_PAYS", "FRA").strip()
PROFIL = os.environ.get("SUIVI_CARTO_PROFIL", "driving-car").strip()

DELAI = 8               # secondes avant d'abandonner un appel
BUDGET_APPELS = 40      # appels reseau max pour une planification


def actif():
    """Le service est-il configure ?"""
    return bool(CLE)


class Budget:
    """Compteur d'appels reseau pour une planification.

    Une tournee de dix courses, toutes adresses inconnues, demanderait une
    cinquantaine d'appels : on s'arrete avant et les trajets restants sont
    signales comme a saisir.
    """

    def __init__(self, maxi=BUDGET_APPELS):
        self.reste = maxi

    def prendre(self):
        if self.reste <= 0:
            return False
        self.reste -= 1
        return True


def _get(url):
    req = urllib.request.Request(url, headers={
        "Accept": "application/json, application/geo+json",
        "User-Agent": "suivi-heures/1.0",
    })
    with urllib.request.urlopen(req, timeout=DELAI) as rep:
        return json.loads(rep.read().decode("utf-8"))


def geocoder(db, adresse, budget=None):
    """Adresse -> ((lat, lon, libelle), motif).

    Un seul des deux est renseigne. Le motif distingue les cas, parce qu'ils
    n'appellent pas la meme reaction : une adresse mal ecrite se corrige,
    un service injoignable se retente plus tard.
    Le resultat est memorise : une adresse n'est geocodee qu'une fois.
    """
    adresse = (adresse or "").strip()
    if not adresse:
        return None, "adresse manquante"
    deja = db.geo_lire(adresse)
    if deja is not None and deja["lat"] is not None:
        return (deja["lat"], deja["lon"], deja["libelle"]), None
    if not actif():
        return None, "cartographie non configurée"
    if budget is not None and not budget.prendre():
        return None, "trop d'adresses à localiser d'un coup"

    params = {"api_key": CLE, "text": adresse, "size": "1"}
    if PAYS:
        params["boundary.country"] = PAYS
    try:
        data = _get(f"{BASE}/geocode/search?" + urllib.parse.urlencode(params))
    except Exception:
        return None, "le service de cartographie n'a pas répondu"
    try:
        feats = data.get("features") or []
        if not feats:
            return None, f"adresse introuvable : {adresse}"
        lon, lat = feats[0]["geometry"]["coordinates"][:2]
        libelle = (feats[0].get("properties") or {}).get("label") or adresse
    except (KeyError, IndexError, TypeError, ValueError):
        return None, "réponse inattendue du service de cartographie"
    db.geo_ecrire(adresse, lat, lon, libelle)
    return (lat, lon, libelle), None


def duree_trajet(db, origine, destination, budget=None):
    """Duree entre deux adresses.

    Renvoie toujours un dictionnaire :
      minutes  int ou None quand elle reste inconnue
      km       float ou None
      source   'manuel', 'carto' ou None
      motif    pourquoi elle est inconnue, a afficher a l'administrateur
    """
    vide = {"minutes": None, "km": None, "source": None, "motif": None}
    o, d = (origine or "").strip(), (destination or "").strip()
    if not o or not d:
        return dict(vide, motif="adresse manquante")
    if cle_adresse(o) == cle_adresse(d):
        return {"minutes": 0, "km": 0.0, "source": "manuel", "motif": None}

    deja = db.trajet_lire(o, d)
    if deja is not None and deja["minutes"] is not None:
        return {"minutes": deja["minutes"], "km": deja["km"],
                "source": deja["source"], "motif": None}

    if not actif():
        return dict(vide, motif="cartographie non configurée")

    a, motif_a = geocoder(db, o, budget)
    if a is None:
        return dict(vide, motif=motif_a)
    b, motif_b = geocoder(db, d, budget)
    if b is None:
        return dict(vide, motif=motif_b)
    if budget is not None and not budget.prendre():
        return dict(vide, motif="trop de trajets à calculer d'un coup")

    params = {
        "api_key": CLE,
        "start": f"{a[1]},{a[0]}",
        "end": f"{b[1]},{b[0]}",
    }
    try:
        data = _get(f"{BASE}/v2/directions/{PROFIL}?"
                    + urllib.parse.urlencode(params))
        resume = data["features"][0]["properties"]["summary"]
        minutes = int(round(resume["duration"] / 60.0))
        km = round(resume["distance"] / 1000.0, 1)
    except Exception:
        return dict(vide, motif="le service de cartographie n'a pas répondu")

    db.trajet_ecrire(o, d, minutes, km, source="carto")
    return {"minutes": minutes, "km": km, "source": "carto", "motif": None}
