"""Paramètres de la démonstration sur le Douaisis.

La bibliothèque etat_initial/ est générique (n'importe quel périmètre en France
métropolitaine) ; ce fichier fixe le territoire, le projet étudié et les chemins
de la chaîne de démonstration.
"""
import os
import sys
from pathlib import Path

# L'installateur de PostgreSQL déclare PROJ_LIB vers la base PROJ de PostGIS, plus ancienne
# que celle de pyproj et rasterio : toute reprojection échoue alors. La chaîne Python l'ignore
# (importer config avant geopandas) ; le serveur PostgreSQL la retrouve dans PROJ_LIB_POSTGIS.
PROJ_LIB_POSTGIS = None
for _var in ("PROJ_LIB", "PROJ_DATA"):
    if "PostgreSQL" in os.environ.get(_var, ""):
        PROJ_LIB_POSTGIS = os.environ.pop(_var)

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))  # rend la bibliothèque etat_initial importable

# --- Arborescence ---------------------------------------------------------------------------
BRUT = RACINE / "data" / "raw"
TRAVAIL = RACINE / "data" / "interim"
REFERENTIEL = TRAVAIL / "referentiel_douaisis.gpkg"   # référentiel territorial (criblage)
ETUDE = TRAVAIL / "etat_initial_site.gpkg"            # données de l'étude du site retenu
SQL = RACINE / "sql"
LIVRABLES = RACINE / "livrables"
DOCS = RACINE / "docs"            # carte web publiée avec GitHub Pages

# --- Territoire de démonstration ------------------------------------------------------------
EPCI_SIREN = "200044618"
EPCI_NOM = "Douaisis Agglo"
DEPARTEMENT = "59"
MARGE_REFERENTIEL_M = 5000   # les données du référentiel débordent de 5 km le territoire

# --- Projet étudié (étude de cas) ---------------------------------------------------------------
# Le site est choisi par le criblage des friches (02_criblage.py). L'étude est indépendante :
# réalisée à partir de données ouvertes réelles, sans lien avec un porteur de projet.
CARTOUCHE = "Étude indépendante réalisée à partir de données ouvertes, sans lien avec un porteur de projet."
TYPE_PROJET = "photovoltaique"
NOM_PROJET = "Étude de cas : centrale photovoltaïque au sol"
SURFACE_MIN_FRICHE_HA = 3.0       # en dessous, une centrale au sol est peu réaliste
FRICHE_RETENUE = None             # identifiant Cartofriches imposé (None : la mieux classée)

# --- Occupation du sol ------------------------------------------------------------------------
OCSGE = {
    2021: "OCS-GE_2-0__GPKG_LAMB93_D059_2021-01-01",
    2025: "OCS-GE_2-0__GPKG_LAMB93_D059_2025-01-01",
    "diff": "OCS-GE_2-0_DIFF-2021-2025_GPKG_LAMB93_D059_2026-10-12",
}
OCSGE_ANNEE = 2025
OSO_ANNEE = 2023
OSO_RASTER = BRUT / "oso" / f"OSO_{OSO_ANNEE}_D{DEPARTEMENT}.tif"   # découpe départementale

# --- Base PostgreSQL / PostGIS ---------------------------------------------------------------
# Instance propre au projet (port dédié, connexion locale sans mot de passe), dans data/pgdata
PG_BIN = Path(r"C:\Program Files\PostgreSQL\15\bin")
PG_DATA = RACINE / "data" / "pgdata"
PG_HOST = "localhost"
PG_PORT = 5435
PG_DB = "etat_initial"
PG_SUPERUSER = "postgres"

# --- QGIS et Inkscape -----------------------------------------------------------------------
QGIS_PYTHON = Path(r"C:\Program Files\QGIS 3.34.12\bin\python-qgis-ltr.bat")
INKSCAPE = Path(r"C:\Program Files\Inkscape\bin\inkscape.com")

# --- Auteur -----------------------------------------------------------------------------------
AUTEUR = "Jaurès DAA-HINGBANON"
CONTACT_URL = "https://jauresmas.github.io/portfolio/"
