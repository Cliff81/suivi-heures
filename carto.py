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
import urllib.error
import urllib.parse
import urllib.request

from core import cle_adresse

# Geocodage : par defaut la Base Adresse Nationale, le service public
# francais. Gratuit, sans cle, et surtout les adresses des patients ne
# quittent pas la France — seules des coordonnees partent ensuite vers le
# service de trajet. Mettre SUIVI_GEO=carto pour repasser par la
# cartographie (adresses hors de France, par exemple).
GEOCODEUR = os.environ.get("SUIVI_GEO", "ban").strip().lower()
BAN_URL = os.environ.get("SUIVI_GEO_URL",
                         "https://api-adresse.data.gouv.fr/search/")
BAN_SCORE_MIN = 0.3     # en dessous, le rapprochement est trop douteux

CLE = os.environ.get("SUIVI_CARTO_CLE", "").strip()
BASE = os.environ.get("SUIVI_CARTO_URL",
                      "https://api.openrouteservice.org").rstrip("/")
PAYS = os.environ.get("SUIVI_CARTO_PAYS", "FRA").strip()
PROFIL = os.environ.get("SUIVI_CARTO_PROFIL", "driving-car").strip()

DELAI = 8               # secondes avant d'abandonner un appel
DELAI_OPTIM = 25        # l'optimisation est plus longue qu'un itineraire
BUDGET_APPELS = 40      # appels reseau max pour une planification


def actif():
    """Les trajets et l'optimisation sont-ils disponibles ?

    Le geocodage, lui, ne depend pas de cette cle quand il passe par la
    Base Adresse Nationale.
    """
    return bool(CLE)


def geocodeur_libelle():
    return ("Base Adresse Nationale" if GEOCODEUR == "ban"
            else "service de cartographie")


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


def _geocoder_ban(adresse):
    """Base Adresse Nationale -> ((lat, lon, libelle), motif)."""
    params = {"q": adresse, "limit": "1", "autocomplete": "0"}
    try:
        data = _get(BAN_URL + "?" + urllib.parse.urlencode(params))
    except Exception:
        return None, "la Base Adresse Nationale n'a pas répondu"
    try:
        feats = data.get("features") or []
        if not feats:
            return None, f"adresse introuvable : {adresse}"
        prop = feats[0].get("properties") or {}
        lon, lat = feats[0]["geometry"]["coordinates"][:2]
        if (prop.get("score") or 0) < BAN_SCORE_MIN:
            return None, f"adresse trop imprécise : {adresse}"
        return (lat, lon, prop.get("label") or adresse), None
    except (KeyError, IndexError, TypeError, ValueError):
        return None, "réponse inattendue de la Base Adresse Nationale"


def _geocoder_carto(adresse, budget):
    """Geocodage par le service de cartographie (hors de France, ou repli)."""
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
        return (lat, lon, libelle), None
    except (KeyError, IndexError, TypeError, ValueError):
        return None, "réponse inattendue du service de cartographie"


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

    if GEOCODEUR == "ban":
        point, motif = _geocoder_ban(adresse)
    elif GEOCODEUR == "auto":
        point, motif = _geocoder_ban(adresse)
        if point is None:
            point, motif = _geocoder_carto(adresse, budget)
    else:
        point, motif = _geocoder_carto(adresse, budget)

    if point is None:
        return None, motif
    db.geo_ecrire(adresse, point[0], point[1], point[2])
    return point, None


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


def optimiser(demande):
    """Soumet une demande d'optimisation (VROOM) au service.

    Renvoie (reponse, quota, motif) : la reponse decodee, le nombre
    d'optimisations restantes lu dans l'en-tete, et le motif d'echec le cas
    echeant. Ne leve jamais : un ecran de planification doit s'afficher meme
    quand le service est muet.

    Ce point d'entree a son propre quota, bien plus serre que les itineraires
    (50 par jour au moment de l'ecriture) : il ne doit etre appele que sur
    demande explicite, jamais au chargement d'une page.
    """
    if not actif():
        return None, None, "cartographie non configurée"

    corps = json.dumps(demande).encode("utf-8")
    req = urllib.request.Request(f"{BASE}/optimization", data=corps, headers={
        "Authorization": CLE,
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "suivi-heures/1.0",
    })
    try:
        with urllib.request.urlopen(req, timeout=DELAI_OPTIM) as rep:
            quota = rep.headers.get("x-ratelimit-remaining")
            data = json.loads(rep.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        quota = e.headers.get("x-ratelimit-remaining") if e.headers else None
        if e.code == 429:
            return None, _entier(quota), ("quota d'optimisations épuisé pour "
                                          "aujourd'hui")
        detail = ""
        try:
            detail = (json.loads(e.read().decode("utf-8"))
                      .get("error", {}).get("message", ""))
        except Exception:
            pass
        return None, _entier(quota), (f"le service a refusé la demande "
                                      f"({e.code}){' : ' + detail if detail else ''}")
    except Exception:
        return None, None, "le service d'optimisation n'a pas répondu"
    return data, _entier(quota), None


def _entier(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None
