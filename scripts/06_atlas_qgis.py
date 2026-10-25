"""Étape 6 - Projet QGIS et atlas A3 de l'état initial (à lancer avec le Python de QGIS).

    "C:\Program Files\QGIS 3.34.12\bin\python-qgis-ltr.bat" 06_atlas_qgis.py [numéros de cartes]

Produit livrables/02_Donnees_SIG/etat_initial.qgz (couches symbolisées, thèmes,
18 mises en page) et exporte chaque planche en PDF dans livrables/03_Atlas/planches.
Les planches sont définies dans etat_initial/atlas_planches.py (partagé avec l'extension QGIS) ;
l'assemblage de l'atlas et les aperçus PNG sont faits par 07_documents.py.
"""
import sqlite3
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))
sys.path.insert(0, str(RACINE / "scripts"))

from qgis.core import QgsApplication  # noqa: E402

app = QgsApplication([], True)  # interface activée : sans elle, aucune police dans les exports
app.initQgis()

import config  # noqa: E402
from etat_initial import atlas_planches  # noqa: E402

SIG = config.LIVRABLES / "02_Donnees_SIG"
GPKG = SIG / "etat_initial.gpkg"


def site():
    """Le site retenu par le criblage, pour les textes de présentation."""
    with sqlite3.connect(GPKG) as cx:
        n = cx.execute("SELECT count(*) FROM criblage_friches").fetchone()[0]
        nom, commune = cx.execute("SELECT site_nom, commune FROM criblage_friches ORDER BY rang LIMIT 1").fetchone()
    nom = nom.replace("(d'hydrocarbure)", "d'hydrocarbures")
    return {"nom": nom, "commune": commune,
            "presentation": f"Hypothèse d'une centrale photovoltaïque au sol sur la seule friche retenue par le "
                            f"criblage des {n} friches de Douaisis Agglo (carte de criblage dans la note)."}


atlas_planches.produire(
    GPKG, SIG / "rasters", config.LIVRABLES / "03_Atlas" / "planches", SIG / "etat_initial.qgz",
    cartouche=f"{config.CARTOUCHE} Réalisation : {config.AUTEUR}, octobre 2026. RGF93 / Lambert-93.",
    nomenclature=next((config.BRUT / "ocsge").rglob("NomenclatureOCSGE.csv"), None), site=site(),
    choix=set(sys.argv[1:]), titre="État initial de l'environnement - étude de cas, Douaisis")
app.exitQgis()
