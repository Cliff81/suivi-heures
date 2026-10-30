#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Suivi des heures - Logique metier partagee (version web).

Ce module reprend, sans dependance Tkinter, toute la logique de
"heures_app.py" : constantes, outils de temps, classe DB (SQLite) et
calculs (totaux mensuels, conformite legale). Il est importe par app.py
(serveur Flask) et reste 100 % compatible avec la base "heures.db"
existante.
"""

import os
import sqlite3
import calendar
import datetime

# --------------------------------------------------------------------------
# Constantes (identiques a l'application bureau)
# --------------------------------------------------------------------------
MOIS_NOMS = [
    "JANVIER", "FÉVRIER", "MARS", "AVRIL", "MAI", "JUIN",
    "JUILLET", "AOÛT", "SEPTEMBRE", "OCTOBRE", "NOVEMBRE", "DÉCEMBRE",
]
JOURS_NOMS = ["LUNDI", "MARDI", "MERCREDI", "JEUDI", "VENDREDI", "SAMEDI", "DIMANCHE"]

DUREE_LEGALE = 35 * 60          # 35 h : duree legale hebdomadaire
SEUIL_ACCORD = 39 * 60          # 39 h : duree contractuelle par defaut
DUREE_HEBDO_DEFAUT = 39 * 60    # duree hebdomadaire par defaut d'un salarie

MAX_JOUR = 10 * 60              # 10 h max de travail effectif par jour
MAX_SEMAINE = 48 * 60          # 48 h max sur une semaine
MAX_MOY_12 = 44 * 60          # 44 h en moyenne sur 12 semaines consecutives
MAX_AMPLITUDE = 12 * 60        # 12 h : amplitude journaliere max (taxis)

# --- Planification de tournee -------------------------------------------
# Temps d'installation par defaut selon le type de transport (minutes) :
# duree pour installer la personne dans le vehicule, appliquee aussi bien a
# la prise en charge qu'a la depose.
TYPES_TRANSPORT = [
    ("valide", "Valide"),
    ("fauteuil", "Fauteuil roulant"),
    ("brancard", "Brancard"),
]
INSTALLATION_DEFAUT = {"valide": 5, "fauteuil": 10, "brancard": 15}
STATIONNEMENT_DEFAUT = 3        # minutes pour se garer, a chaque arret

SALARIES_DEFAUT = [
    "PATRICK LLOPIS",
    "GEORGIA LAROCHE",
    "GREGOIRE GAMBIER",
    "ANGELINE AURIOL",
]

def _charger_env():
    """Lit un fichier .env place a cote de ce module et en tire des variables
    d'environnement. Evite de retaper la cle de cartographie ou la cle de
    session a chaque lancement sur un poste. Une variable deja presente dans
    l'environnement l'emporte : en ligne, c'est l'hebergeur qui decide.
    Le fichier n'est pas suivi par git (voir .gitignore)."""
    chemin = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    try:
        with open(chemin, encoding="utf-8") as f:
            lignes = f.readlines()
    except OSError:
        return
    for ligne in lignes:
        ligne = ligne.strip()
        if not ligne or ligne.startswith("#") or "=" not in ligne:
            continue
        nom, _, valeur = ligne.partition("=")
        os.environ.setdefault(nom.strip(), valeur.strip().strip('"').strip("'"))


_charger_env()

# Emplacement de la base : par defaut la "heures.db" du dossier parent
# (partagee avec l'application bureau). Surchargeable via SUIVI_DB.
_HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get(
    "SUIVI_DB", os.path.join(os.path.dirname(_HERE), "heures.db"))


# --------------------------------------------------------------------------
# Outils de temps
# --------------------------------------------------------------------------
def parse_heure(txt):
    """Convertit '06:15', '6h15', '6.25' ... en minutes depuis minuit.
    Renvoie None si vide, leve ValueError si invalide."""
    if txt is None:
        return None
    s = str(txt).strip().lower().replace(",", ".")
    if s == "":
        return None
    s = s.replace("h", ":")
    if ":" in s:
        parts = s.split(":")
        if len(parts) > 2:
            raise ValueError(txt)
        h = int(parts[0]) if parts[0] != "" else 0
        m = int(parts[1]) if parts[1] != "" else 0
        return h * 60 + m
    val = float(s)
    return int(round(val * 60))


def fmt_hm(minutes):
    """Minutes -> 'HH:MM'. Les negatifs/None deviennent '00:00'."""
    if minutes is None or minutes <= 0:
        return "00:00"
    h, m = divmod(int(round(minutes)), 60)
    return f"{h:02d}:{m:02d}"


def fmt_hm_signe(minutes):
    """Minutes -> 'HH:MM' en conservant le signe (solde negatif)."""
    if minutes is None:
        minutes = 0
    minutes = int(round(minutes))
    signe = "-" if minutes < 0 else ""
    h, m = divmod(abs(minutes), 60)
    return f"{signe}{h:02d}:{m:02d}"


def fmt_centieme(minutes):
    """Minutes -> heures decimales (centiemes), ex 90 -> '1.50'."""
    if minutes is None:
        minutes = 0
    return f"{minutes / 60:.2f}"


def fmt_km(v):
    if v is None:
        return ""
    return f"{v:g}"


def cle_adresse(adresse):
    """Cle de cache d'une adresse : minuscules, espaces reduits.
    Deux saisies qui ne different que par la casse ou les espaces ne
    declenchent qu'un seul appel au service de cartographie."""
    return " ".join(str(adresse or "").lower().split())


def nom_client(c):
    """Affichage 'PRENOM NOM' a partir d'une ligne client."""
    prenom = (c["prenom"] or "").strip()
    nom = (c["nom"] or "").strip()
    return f"{prenom} {nom}".strip()


def nom_complet(s):
    """Affichage 'PRENOM NOM' a partir d'une ligne salarie."""
    try:
        prenom = (s["prenom"] or "").strip()
    except (KeyError, IndexError):
        prenom = ""
    nom = (s["nom"] or "").strip()
    return f"{prenom} {nom}".strip()


def heures_travaillees(amp_d, amp_f, pause_d, pause_f):
    """Minutes travaillees d'une journee a partir des 4 horaires."""
    if amp_d is None or amp_f is None:
        return 0
    amplitude = amp_f - amp_d
    pause = 0
    if pause_d is not None and pause_f is not None:
        pause = pause_f - pause_d
    net = amplitude - pause
    return net if net > 0 else 0


# --------------------------------------------------------------------------
# Base de donnees
# --------------------------------------------------------------------------
class DB:
    def __init__(self, path):
        # timeout : evite les erreurs « database is locked » si plusieurs
        # requetes ecrivent en meme temps (utile en ligne / multi-workers).
        self.conn = sqlite3.connect(path, timeout=30)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA busy_timeout=30000")
        self._init_schema()
        self._init_salaries()

    def close(self):
        self.conn.close()

    def _init_schema(self):
        c = self.conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS salaries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nom TEXT NOT NULL,
                prenom TEXT DEFAULT '',
                duree_hebdo INTEGER DEFAULT %d,
                position INTEGER DEFAULT 0
            )""" % DUREE_HEBDO_DEFAUT)
        cols = {r["name"] for r in c.execute("PRAGMA table_info(salaries)")}
        if "prenom" not in cols:
            c.execute("ALTER TABLE salaries ADD COLUMN prenom TEXT DEFAULT ''")
        if "duree_hebdo" not in cols:
            c.execute("ALTER TABLE salaries ADD COLUMN duree_hebdo INTEGER "
                      "DEFAULT %d" % DUREE_HEBDO_DEFAUT)
        c.execute("""
            CREATE TABLE IF NOT EXISTS jours (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                salarie_id INTEGER NOT NULL,
                date TEXT NOT NULL,
                amp_d INTEGER, amp_f INTEGER,
                pause_d INTEGER, pause_f INTEGER,
                km_jour REAL, km_com REAL, km_vide REAL,
                UNIQUE(salarie_id, date)
            )""")
        c.execute("""
            CREATE TABLE IF NOT EXISTS payees (
                salarie_id INTEGER NOT NULL,
                annee INTEGER NOT NULL,
                mois INTEGER NOT NULL,
                minutes INTEGER DEFAULT 0,
                PRIMARY KEY (salarie_id, annee, mois)
            )""")
        c.execute("""
            CREATE TABLE IF NOT EXISTS conges_pris (
                salarie_id INTEGER NOT NULL,
                annee INTEGER NOT NULL,
                mois INTEGER NOT NULL,
                minutes INTEGER DEFAULT 0,
                PRIMARY KEY (salarie_id, annee, mois)
            )""")
        # comptes utilisateurs (specifique a la version web)
        c.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                login TEXT NOT NULL UNIQUE,
                pwd_hash TEXT NOT NULL,
                is_admin INTEGER DEFAULT 0,
                salarie_id INTEGER
            )""")
        ucols = {r["name"] for r in c.execute("PRAGMA table_info(users)")}
        if "salarie_id" not in ucols:
            c.execute("ALTER TABLE users ADD COLUMN salarie_id INTEGER")
        # detail des pauses saisies par un salarie pour une journee (sert a
        # re-afficher le formulaire « Ma journee » ; le total des pauses est,
        # lui, encode dans jours.pause_d/pause_f pour ne rien changer aux calculs)
        c.execute("""
            CREATE TABLE IF NOT EXISTS jour_pauses (
                salarie_id INTEGER NOT NULL,
                date TEXT NOT NULL,
                idx INTEGER NOT NULL,
                debut INTEGER, fin INTEGER,
                PRIMARY KEY (salarie_id, date, idx)
            )""")
        # --- Planification de tournee (tables propres a la version web :
        # l'application bureau les ignore, elle ne les lit jamais) ---
        c.execute("""
            CREATE TABLE IF NOT EXISTS clients (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nom TEXT NOT NULL,
                prenom TEXT DEFAULT '',
                adresse TEXT DEFAULT '',
                telephone TEXT DEFAULT '',
                type_transport TEXT DEFAULT 'valide',
                minutes_installation INTEGER,
                notes TEXT DEFAULT '',
                actif INTEGER DEFAULT 1
            )""")
        # Une journee se prepare ainsi : on declare qui est disponible, on
        # encaisse les courses sans savoir encore qui les prendra, puis on
        # attribue. Les anciennes tables tournees/tournee_courses portaient le
        # modele inverse (une tournee par salarie, ordonnee a la main).
        c.execute("DROP TABLE IF EXISTS tournee_courses")
        c.execute("DROP TABLE IF EXISTS tournees")

        # Le temps de se garer depend du lieu, pas du conducteur : il vaut
        # pour la journee entiere, et chaque course peut l'ajuster. Le porter
        # sur le salarie etait une erreur : au moment du calcul, une course
        # n'est attribuee a personne, sa valeur serait inconnaissable.
        c.execute("""
            CREATE TABLE IF NOT EXISTS journees (
                date TEXT PRIMARY KEY,
                minutes_stationnement INTEGER,
                notes TEXT DEFAULT ''
            )""")
        scols = {r["name"] for r in c.execute("PRAGMA table_info(journee_salaries)")}
        if "minutes_stationnement" in scols:
            c.execute("ALTER TABLE journee_salaries DROP COLUMN minutes_stationnement")
        c.execute("""
            CREATE TABLE IF NOT EXISTS journee_salaries (
                date TEXT NOT NULL,
                salarie_id INTEGER NOT NULL,
                heure_debut INTEGER,
                heure_fin INTEGER,
                places INTEGER DEFAULT 1,
                adresse_depart TEXT DEFAULT '',
                pause_minutes INTEGER DEFAULT 0,
                pause_apres INTEGER,
                pause_debut INTEGER,
                PRIMARY KEY (date, salarie_id)
            )""")
        c.execute("""
            CREATE TABLE IF NOT EXISTS courses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                client_id INTEGER,
                prise_adresse TEXT DEFAULT '',
                depose_adresse TEXT DEFAULT '',
                prise_au_plus_tot INTEGER,
                arrivee_debut INTEGER,
                arrivee_fin INTEGER,
                minutes_installation INTEGER,
                minutes_stationnement INTEGER,
                notes TEXT DEFAULT '',
                -- nuls tant que la course n'est pas attribuee
                salarie_id INTEGER,
                position INTEGER,
                prise_calc INTEGER,
                depose_calc INTEGER
            )""")
        c.execute("""
            CREATE TABLE IF NOT EXISTS optimisations (
                date TEXT PRIMARY KEY,
                maj TEXT,
                code INTEGER,
                nb_non_affectees INTEGER DEFAULT 0,
                message TEXT DEFAULT '',
                quota_restant INTEGER
            )""")
        # Coordonnees et durees deja connues : on n'interroge le service de
        # cartographie qu'une fois par adresse et par trajet.
        c.execute("""
            CREATE TABLE IF NOT EXISTS geo_cache (
                adresse TEXT PRIMARY KEY,
                lat REAL, lon REAL,
                libelle TEXT,
                maj TEXT
            )""")
        c.execute("""
            CREATE TABLE IF NOT EXISTS trajet_cache (
                origine TEXT NOT NULL,
                destination TEXT NOT NULL,
                minutes INTEGER,
                km REAL,
                source TEXT DEFAULT 'carto',
                maj TEXT,
                PRIMARY KEY (origine, destination)
            )""")
        # Adresse de depart du salarie (il part de chez lui avec le vehicule).
        scols = {r["name"] for r in c.execute("PRAGMA table_info(salaries)")}
        if "adresse" not in scols:
            c.execute("ALTER TABLE salaries ADD COLUMN adresse TEXT DEFAULT ''")
        self.conn.commit()

    def _init_salaries(self):
        c = self.conn.cursor()
        n = c.execute("SELECT COUNT(*) FROM salaries").fetchone()[0]
        if n == 0:
            for i, nom in enumerate(SALARIES_DEFAUT):
                c.execute("INSERT INTO salaries (nom, position) VALUES (?,?)",
                          (nom, i))
            self.conn.commit()

    # --- salaries ---
    def salaries(self):
        return self.conn.execute(
            "SELECT * FROM salaries ORDER BY position, id").fetchall()

    def salarie(self, sid):
        return self.conn.execute(
            "SELECT * FROM salaries WHERE id=?", (sid,)).fetchone()

    def duree_hebdo(self, sid):
        r = self.salarie(sid)
        if r is None:
            return DUREE_HEBDO_DEFAUT
        d = r["duree_hebdo"]
        return d if d else DUREE_HEBDO_DEFAUT

    def ajouter_salarie(self, nom, prenom="", duree=DUREE_HEBDO_DEFAUT):
        pos = self.conn.execute(
            "SELECT COALESCE(MAX(position),-1)+1 FROM salaries").fetchone()[0]
        self.conn.execute(
            "INSERT INTO salaries (nom, prenom, duree_hebdo, position) "
            "VALUES (?,?,?,?)", (nom, prenom, duree, pos))
        self.conn.commit()

    def modifier_salarie(self, sid, nom, prenom, duree):
        self.conn.execute(
            "UPDATE salaries SET nom=?, prenom=?, duree_hebdo=? WHERE id=?",
            (nom, prenom, duree, sid))
        self.conn.commit()

    def supprimer_salarie(self, sid):
        self.conn.execute("DELETE FROM jours WHERE salarie_id=?", (sid,))
        self.conn.execute("DELETE FROM payees WHERE salarie_id=?", (sid,))
        self.conn.execute("DELETE FROM conges_pris WHERE salarie_id=?", (sid,))
        self.conn.execute("DELETE FROM salaries WHERE id=?", (sid,))
        self.conn.commit()

    # --- jours ---
    def jour(self, sid, date_iso):
        return self.conn.execute(
            "SELECT * FROM jours WHERE salarie_id=? AND date=?",
            (sid, date_iso)).fetchone()

    def jours_intervalle(self, sid, debut_iso, fin_iso):
        rows = self.conn.execute(
            "SELECT * FROM jours WHERE salarie_id=? AND date BETWEEN ? AND ?",
            (sid, debut_iso, fin_iso)).fetchall()
        return {r["date"]: r for r in rows}

    def enregistrer_jour(self, sid, date_iso, vals):
        vide = all(vals[k] is None for k in vals)
        if vide:
            self.conn.execute(
                "DELETE FROM jours WHERE salarie_id=? AND date=?",
                (sid, date_iso))
        else:
            self.conn.execute("""
                INSERT INTO jours (salarie_id, date, amp_d, amp_f, pause_d,
                                   pause_f, km_jour, km_com, km_vide)
                VALUES (?,?,?,?,?,?,?,?,?)
                ON CONFLICT(salarie_id, date) DO UPDATE SET
                  amp_d=excluded.amp_d, amp_f=excluded.amp_f,
                  pause_d=excluded.pause_d, pause_f=excluded.pause_f,
                  km_jour=excluded.km_jour, km_com=excluded.km_com,
                  km_vide=excluded.km_vide
            """, (sid, date_iso, vals["amp_d"], vals["amp_f"], vals["pause_d"],
                  vals["pause_f"], vals["km_jour"], vals["km_com"],
                  vals["km_vide"]))

    # --- clients (planification de tournee) ---
    def clients(self, actifs_seuls=True):
        sql = "SELECT * FROM clients"
        if actifs_seuls:
            sql += " WHERE actif=1"
        sql += " ORDER BY nom, prenom"
        return self.conn.execute(sql).fetchall()

    def client(self, cid):
        return self.conn.execute(
            "SELECT * FROM clients WHERE id=?", (cid,)).fetchone()

    def ajouter_client(self, **v):
        cur = self.conn.execute(
            "INSERT INTO clients (nom, prenom, adresse, telephone, "
            "type_transport, minutes_installation, notes) VALUES (?,?,?,?,?,?,?)",
            (v["nom"], v.get("prenom", ""), v.get("adresse", ""),
             v.get("telephone", ""), v.get("type_transport", "valide"),
             v.get("minutes_installation"), v.get("notes", "")))
        self.conn.commit()
        return cur.lastrowid

    def modifier_client(self, cid, **v):
        self.conn.execute(
            "UPDATE clients SET nom=?, prenom=?, adresse=?, telephone=?, "
            "type_transport=?, minutes_installation=?, notes=?, actif=? WHERE id=?",
            (v["nom"], v.get("prenom", ""), v.get("adresse", ""),
             v.get("telephone", ""), v.get("type_transport", "valide"),
             v.get("minutes_installation"), v.get("notes", ""),
             1 if v.get("actif", 1) else 0, cid))
        self.conn.commit()

    def supprimer_client(self, cid):
        # Les courses deja planifiees gardent leur adresse : on detache
        # seulement la fiche, pour ne pas trouer une tournee passee.
        self.conn.execute(
            "UPDATE courses SET client_id=NULL WHERE client_id=?", (cid,))
        self.conn.execute("DELETE FROM clients WHERE id=?", (cid,))
        self.conn.commit()

    def set_salarie_adresse(self, sid, adresse):
        self.conn.execute("UPDATE salaries SET adresse=? WHERE id=?",
                          (adresse, sid))
        self.conn.commit()

    # --- reglages de la journee ---
    def journee(self, date_iso):
        return self.conn.execute(
            "SELECT * FROM journees WHERE date=?", (date_iso,)).fetchone()

    def stationnement(self, date_iso):
        """Minutes pour se garer a chaque arret, ce jour-la."""
        j = self.journee(date_iso)
        if j is not None and j["minutes_stationnement"] is not None:
            return j["minutes_stationnement"]
        return STATIONNEMENT_DEFAUT

    def poser_journee(self, date_iso, minutes_stationnement=None, notes=""):
        self.conn.execute(
            "INSERT INTO journees (date, minutes_stationnement, notes) "
            "VALUES (?,?,?) ON CONFLICT(date) DO UPDATE SET "
            "minutes_stationnement=excluded.minutes_stationnement, "
            "notes=excluded.notes",
            (date_iso, minutes_stationnement, notes))
        self.conn.commit()

    # --- disponibilites d'une journee ---
    def dispos(self, date_iso):
        return self.conn.execute(
            "SELECT * FROM journee_salaries WHERE date=? ORDER BY salarie_id",
            (date_iso,)).fetchall()

    def dispo(self, date_iso, sid):
        return self.conn.execute(
            "SELECT * FROM journee_salaries WHERE date=? AND salarie_id=?",
            (date_iso, sid)).fetchone()

    def poser_dispo(self, date_iso, sid, **v):
        self.conn.execute("""
            INSERT INTO journee_salaries (date, salarie_id, heure_debut,
                heure_fin, places, adresse_depart, pause_minutes)
            VALUES (?,?,?,?,?,?,?)
            ON CONFLICT(date, salarie_id) DO UPDATE SET
              heure_debut=excluded.heure_debut, heure_fin=excluded.heure_fin,
              places=excluded.places, adresse_depart=excluded.adresse_depart,
              pause_minutes=excluded.pause_minutes
        """, (date_iso, sid, v.get("heure_debut"), v.get("heure_fin"),
              max(1, v.get("places") or 1), v.get("adresse_depart", ""),
              v.get("pause_minutes") or 0))
        self.conn.commit()

    def set_pause(self, date_iso, sid, rang=None, debut=None):
        """Ou le solveur a place le repos : apres la course `rang`, et surtout
        a l'heure `debut` — c'est elle que lit l'affichage chronologique."""
        self.conn.execute(
            "UPDATE journee_salaries SET pause_apres=?, pause_debut=? "
            "WHERE date=? AND salarie_id=?", (rang, debut, date_iso, sid))
        self.conn.commit()

    def retirer_dispo(self, date_iso, sid):
        """Retire un salarie du vivier : ses courses retournent a attribuer."""
        self.conn.execute(
            "UPDATE courses SET salarie_id=NULL, position=NULL, prise_calc=NULL,"
            " depose_calc=NULL WHERE date=? AND salarie_id=?", (date_iso, sid))
        self.conn.execute(
            "DELETE FROM journee_salaries WHERE date=? AND salarie_id=?",
            (date_iso, sid))
        self.conn.commit()

    # --- courses de la journee ---
    def courses(self, date_iso, salarie_id=False):
        """Toutes les courses du jour, ou celles d'un salarie.
        salarie_id=None demande celles qui restent a attribuer."""
        sql = "SELECT * FROM courses WHERE date=?"
        args = [date_iso]
        if salarie_id is not False:
            if salarie_id is None:
                sql += " AND salarie_id IS NULL"
            else:
                sql += " AND salarie_id=?"
                args.append(salarie_id)
        sql += " ORDER BY position IS NULL, position, id"
        return self.conn.execute(sql, args).fetchall()

    def course(self, cid):
        return self.conn.execute(
            "SELECT * FROM courses WHERE id=?", (cid,)).fetchone()

    def ajouter_course(self, date_iso, client_id=None):
        cur = self.conn.execute(
            "INSERT INTO courses (date, client_id) VALUES (?,?)",
            (date_iso, client_id))
        self.conn.commit()
        return cur.lastrowid

    def modifier_course(self, cid, **v):
        self.conn.execute("""
            UPDATE courses SET client_id=?, prise_adresse=?, depose_adresse=?,
              prise_au_plus_tot=?, arrivee_debut=?, arrivee_fin=?,
              minutes_installation=?, minutes_stationnement=?, notes=?
            WHERE id=?""",
            (v.get("client_id"), v.get("prise_adresse", ""),
             v.get("depose_adresse", ""), v.get("prise_au_plus_tot"),
             v.get("arrivee_debut"), v.get("arrivee_fin"),
             v.get("minutes_installation"), v.get("minutes_stationnement"),
             v.get("notes", ""), cid))
        self.conn.commit()

    def supprimer_course(self, cid):
        self.conn.execute("DELETE FROM courses WHERE id=?", (cid,))
        self.conn.commit()

    # --- attribution ---
    def attribuer(self, cid, sid, position=None, prise=None, depose=None):
        """Place une course chez un salarie. sid=None la renvoie au vivier."""
        if sid is None:
            self.conn.execute(
                "UPDATE courses SET salarie_id=NULL, position=NULL,"
                " prise_calc=NULL, depose_calc=NULL WHERE id=?", (cid,))
        else:
            if position is None:
                r = self.conn.execute(
                    "SELECT COALESCE(MAX(position),-1)+1 FROM courses "
                    "WHERE salarie_id=? AND date=(SELECT date FROM courses "
                    "WHERE id=?)", (sid, cid)).fetchone()
                position = r[0]
            self.conn.execute(
                "UPDATE courses SET salarie_id=?, position=?, prise_calc=?,"
                " depose_calc=? WHERE id=?", (sid, position, prise, depose, cid))
        self.conn.commit()

    def vider_attributions(self, date_iso):
        self.conn.execute(
            "UPDATE courses SET salarie_id=NULL, position=NULL, prise_calc=NULL,"
            " depose_calc=NULL WHERE date=?", (date_iso,))
        self.conn.commit()

    def deplacer_course(self, cid, sens):
        """Monte (-1) ou descend (+1) une course dans l'ordre de son salarie."""
        r = self.course(cid)
        if r is None or r["salarie_id"] is None:
            return
        ordre = [x["id"] for x in self.courses(r["date"], r["salarie_id"])]
        i = ordre.index(cid)
        j = i + sens
        if not 0 <= j < len(ordre):
            return
        ordre[i], ordre[j] = ordre[j], ordre[i]
        for pos, oid in enumerate(ordre):
            self.conn.execute(
                "UPDATE courses SET position=? WHERE id=?", (pos, oid))
        self.conn.commit()

    # --- trace de la derniere optimisation ---
    def optimisation(self, date_iso):
        return self.conn.execute(
            "SELECT * FROM optimisations WHERE date=?", (date_iso,)).fetchone()

    def noter_optimisation(self, date_iso, code, nb_non_affectees, message,
                           quota_restant):
        self.conn.execute("""
            INSERT INTO optimisations (date, maj, code, nb_non_affectees,
                message, quota_restant)
            VALUES (?, datetime('now'), ?, ?, ?, ?)
            ON CONFLICT(date) DO UPDATE SET maj=excluded.maj, code=excluded.code,
              nb_non_affectees=excluded.nb_non_affectees,
              message=excluded.message, quota_restant=excluded.quota_restant
        """, (date_iso, code, nb_non_affectees, message, quota_restant))
        self.conn.commit()

    # --- cache cartographie ---
    def geo_lire(self, adresse):
        return self.conn.execute(
            "SELECT * FROM geo_cache WHERE adresse=?",
            (cle_adresse(adresse),)).fetchone()

    def geo_ecrire(self, adresse, lat, lon, libelle):
        self.conn.execute(
            "INSERT INTO geo_cache (adresse, lat, lon, libelle, maj) "
            "VALUES (?,?,?,?,datetime('now')) "
            "ON CONFLICT(adresse) DO UPDATE SET lat=excluded.lat, "
            "lon=excluded.lon, libelle=excluded.libelle, maj=excluded.maj",
            (cle_adresse(adresse), lat, lon, libelle))
        self.conn.commit()

    def trajet_lire(self, origine, destination):
        return self.conn.execute(
            "SELECT * FROM trajet_cache WHERE origine=? AND destination=?",
            (cle_adresse(origine), cle_adresse(destination))).fetchone()

    def trajet_ecrire(self, origine, destination, minutes, km=None, source="carto"):
        self.conn.execute(
            "INSERT INTO trajet_cache (origine, destination, minutes, km, "
            "source, maj) VALUES (?,?,?,?,?,datetime('now')) "
            "ON CONFLICT(origine, destination) DO UPDATE SET "
            "minutes=excluded.minutes, km=excluded.km, source=excluded.source, "
            "maj=excluded.maj",
            (cle_adresse(origine), cle_adresse(destination), minutes, km, source))
        self.conn.commit()

    def commit(self):
        self.conn.commit()

    # --- heures payees ---
    def payees(self, sid, annee, mois):
        r = self.conn.execute(
            "SELECT minutes FROM payees WHERE salarie_id=? AND annee=? AND mois=?",
            (sid, annee, mois)).fetchone()
        return r["minutes"] if r else 0

    def set_payees(self, sid, annee, mois, minutes):
        self.conn.execute("""
            INSERT INTO payees (salarie_id, annee, mois, minutes)
            VALUES (?,?,?,?)
            ON CONFLICT(salarie_id, annee, mois) DO UPDATE SET minutes=excluded.minutes
        """, (sid, annee, mois, minutes))
        self.conn.commit()

    # --- heures de conges (>39h) prises dans le mois ---
    def conges_pris(self, sid, annee, mois):
        r = self.conn.execute(
            "SELECT minutes FROM conges_pris WHERE salarie_id=? AND annee=? "
            "AND mois=?", (sid, annee, mois)).fetchone()
        return r["minutes"] if r else 0

    def set_conges_pris(self, sid, annee, mois, minutes):
        self.conn.execute("""
            INSERT INTO conges_pris (salarie_id, annee, mois, minutes)
            VALUES (?,?,?,?)
            ON CONFLICT(salarie_id, annee, mois) DO UPDATE SET minutes=excluded.minutes
        """, (sid, annee, mois, minutes))
        self.conn.commit()

    def solde_conges(self, sid, jusqu_annee, jusqu_mois):
        acquis = 0
        pris_total = 0
        for r in self.conn.execute(
                "SELECT annee, mois, minutes FROM conges_pris WHERE salarie_id=?",
                (sid,)):
            if (r["annee"], r["mois"]) <= (jusqu_annee, jusqu_mois):
                pris_total += r["minutes"]
        annees = set()
        for r in self.conn.execute(
                "SELECT DISTINCT substr(date,1,4) AS a FROM jours WHERE salarie_id=?",
                (sid,)):
            annees.add(int(r["a"]))
        for an in sorted(annees):
            for mo in range(1, 13):
                if (an, mo) > (jusqu_annee, jusqu_mois):
                    break
                acquis += totaux_mois(self, sid, an, mo)["sup39"]
        return acquis - pris_total

    # --- utilisateurs (web) ---
    def get_user(self, login):
        return self.conn.execute(
            "SELECT * FROM users WHERE login=?", (login,)).fetchone()

    def get_user_by_id(self, uid):
        return self.conn.execute(
            "SELECT * FROM users WHERE id=?", (uid,)).fetchone()

    def users(self):
        return self.conn.execute(
            "SELECT * FROM users ORDER BY login").fetchall()

    def ajouter_user(self, login, pwd_hash, is_admin=0, salarie_id=None):
        self.conn.execute(
            "INSERT INTO users (login, pwd_hash, is_admin, salarie_id) "
            "VALUES (?,?,?,?)",
            (login, pwd_hash, 1 if is_admin else 0, salarie_id))
        self.conn.commit()

    def modifier_user(self, uid, is_admin, salarie_id):
        self.conn.execute(
            "UPDATE users SET is_admin=?, salarie_id=? WHERE id=?",
            (1 if is_admin else 0, salarie_id, uid))
        self.conn.commit()

    def set_user_pwd(self, login, pwd_hash):
        self.conn.execute("UPDATE users SET pwd_hash=? WHERE login=?",
                          (pwd_hash, login))
        self.conn.commit()

    def supprimer_user(self, uid):
        self.conn.execute("DELETE FROM users WHERE id=?", (uid,))
        self.conn.commit()

    # --- pauses detaillees d'une journee (saisie self-service) ---
    def pauses_jour(self, sid, date_iso):
        return self.conn.execute(
            "SELECT debut, fin FROM jour_pauses WHERE salarie_id=? AND date=? "
            "ORDER BY idx", (sid, date_iso)).fetchall()

    def set_pauses_jour(self, sid, date_iso, paires):
        """paires = liste de (debut, fin) en minutes. Remplace les pauses
        existantes pour ce jour."""
        self.conn.execute(
            "DELETE FROM jour_pauses WHERE salarie_id=? AND date=?",
            (sid, date_iso))
        for i, (d, f) in enumerate(paires):
            self.conn.execute(
                "INSERT INTO jour_pauses (salarie_id, date, idx, debut, fin) "
                "VALUES (?,?,?,?,?)", (sid, date_iso, i, d, f))
        self.conn.commit()


# --------------------------------------------------------------------------
# Calcul des totaux
# --------------------------------------------------------------------------
def semaines_du_mois(annee, mois):
    first = datetime.date(annee, mois, 1)
    last = datetime.date(annee, mois, calendar.monthrange(annee, mois)[1])
    start = first - datetime.timedelta(days=first.weekday())  # lundi
    semaines = []
    d = start
    while d <= last:
        semaines.append([d + datetime.timedelta(days=i) for i in range(7)])
        d += datetime.timedelta(days=7)
    return semaines


def totaux_semaine(minutes_travaillees, seuil_accord=SEUIL_ACCORD):
    total = minutes_travaillees
    sup35 = max(0, total - DUREE_LEGALE)
    sup_accord = max(0, total - seuil_accord)
    dans_accord = sup35 - sup_accord
    return total, sup35, dans_accord, sup_accord


def totaux_mois(db, sid, annee, mois):
    seuil = db.duree_hebdo(sid)
    res = {"total": 0, "sup35": 0, "accord39": 0, "sup39": 0}
    semaines = semaines_du_mois(annee, mois)
    debut = semaines[0][0].isoformat()
    fin = semaines[-1][6].isoformat()
    data = db.jours_intervalle(sid, debut, fin)
    for sem in semaines:
        mins = 0
        for d in sem:
            if d.month != mois or d.year != annee:
                continue
            j = data.get(d.isoformat())
            if j:
                mins += heures_travaillees(j["amp_d"], j["amp_f"],
                                           j["pause_d"], j["pause_f"])
        _, sup35, accord, sup39 = totaux_semaine(mins, seuil)
        res["total"] += mins
        res["sup35"] += sup35
        res["accord39"] += accord
        res["sup39"] += sup39
    return res


def totaux_hebdo_annee(db, sid, annee):
    premier = datetime.date(annee, 1, 1)
    lundi = premier - datetime.timedelta(days=premier.weekday())
    fin_annee = datetime.date(annee, 12, 31)
    debut = lundi.isoformat()
    fin = (fin_annee + datetime.timedelta(days=7)).isoformat()
    data = db.jours_intervalle(sid, debut, fin)
    res = []
    d = lundi
    while d <= fin_annee:
        mins = 0
        for i in range(7):
            j = data.get((d + datetime.timedelta(days=i)).isoformat())
            if j:
                mins += heures_travaillees(j["amp_d"], j["amp_f"],
                                           j["pause_d"], j["pause_f"])
        res.append((d, mins))
        d += datetime.timedelta(days=7)
    return res


def verifier_conformite(db, sid, annee):
    debut = datetime.date(annee, 1, 1).isoformat()
    fin = datetime.date(annee, 12, 31).isoformat()
    data = db.jours_intervalle(sid, debut, fin)
    jours_10h = []
    jours_ampl = []
    for iso, j in sorted(data.items()):
        m = heures_travaillees(j["amp_d"], j["amp_f"], j["pause_d"], j["pause_f"])
        if m > MAX_JOUR:
            jours_10h.append((iso, m))
        if j["amp_d"] is not None and j["amp_f"] is not None:
            ampl = j["amp_f"] - j["amp_d"]
            if ampl > MAX_AMPLITUDE:
                jours_ampl.append((iso, ampl))
    hebdo = totaux_hebdo_annee(db, sid, annee)
    semaines_48h = [(d, m) for d, m in hebdo if m > MAX_SEMAINE]
    pire_moy = 0
    pire_fenetre = None
    for i in range(len(hebdo) - 11):
        fenetre = hebdo[i:i + 12]
        moy = sum(m for _, m in fenetre) / 12
        if moy > pire_moy:
            pire_moy = moy
            pire_fenetre = (fenetre[0][0], fenetre[-1][0])
    return {
        "jours_10h": jours_10h,
        "jours_ampl": jours_ampl,
        "semaines_48h": semaines_48h,
        "moy12_max": pire_moy,
        "moy12_fenetre": pire_fenetre,
        "moy12_depassee": pire_moy > MAX_MOY_12,
    }
