r"""Essai de l'extension QGIS hors interface, sur une autre friche du territoire (Python de QGIS).

    "C:\Program Files\QGIS 3.34.12\bin\python-qgis-ltr.bat" tests/essai_extension_qgis.py

Lance l'algorithme « Produire l'état initial d'un périmètre » sans l'OCS GE (pour aller vite)
et vérifie que le GeoPackage, le projet et les 18 planches sont produits.
"""
import os
import sqlite3
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "extension"))

from qgis.core import QgsApplication, QgsVectorLayer  # noqa: E402

app = QgsApplication([], True)
app.initQgis()
sys.path.insert(0, str(Path(QgsApplication.prefixPath()) / "python" / "plugins"))
import processing  # noqa: E402
from processing.core.Processing import Processing  # noqa: E402

Processing.initialize()
from etat_initial_qgis.fournisseur import Fournisseur  # noqa: E402

fournisseur = Fournisseur()  # garder une référence : sinon Python le détruit
QgsApplication.processingRegistry().addProvider(fournisseur)

SORTIE = RACINE / "data" / "interim" / "essai_extension"
friches = QgsVectorLayer(f"{RACINE / 'data' / 'interim' / 'referentiel_douaisis.gpkg'}|layername=friche", "f", "ogr")
friches.setSubsetString("\"site_nom\" = 'Cimenterie'")  # autre site du territoire (copie de travail)
res = processing.run("etatinitial:etat_initial", {
    "PERIMETRE": friches, "NOM": "Essai - ancienne cimenterie de Cantin", "TYPE": 2, "OCSGE": False,
    "ESPECES": True, "FONCIER": False, "OSO": None, "ATLAS": True, "DOSSIER": str(SORTIE)})
gpkg = Path(res["GPKG"])
with sqlite3.connect(gpkg) as cx:
    couches = [r[0] for r in cx.execute("SELECT table_name FROM gpkg_contents")]
    enjeux = cx.execute("SELECT niveau, count(*) FROM t_enjeux GROUP BY 1").fetchall()
planches = sorted(Path(res["ATLAS"]).glob("Carte_*.pdf"))
print(f"{len(couches)} couches et tables ; enjeux : {enjeux} ; {len(planches)} planches ; projet : "
      f"{Path(res['QGZ']).exists()}")
assert len(planches) == 18 and Path(res["QGZ"]).exists() and enjeux
print("ESSAI RÉUSSI")
os._exit(0)  # QGIS plante parfois à la fermeture après Processing : sortie directe
