"""Relance toute la chaîne de démonstration, de la base PostGIS aux livrables.

    python run_all.py              toute la chaîne (environ 25 minutes, dont 5 de téléchargements)
    python run_all.py 04 05 06     seulement certaines étapes

Les étapes PyQGIS (06, 08) sont lancées avec le Python de QGIS. La veille (09) et l'import
des relevés de terrain (10) se lancent à part, au besoin.
"""
import subprocess
import sys
import time

import config
from outils import log

ETAPES = [
    ("00", "00_base.py", "python", ["--neuve"]),
    ("00b", "00b_oso.py", "python", []),
    ("01", "01_referentiel.py", "python", []),
    ("02", "02_criblage.py", "python", []),
    ("03", "03_collecte_site.py", "python", ["--maj"]),
    ("04", "04_analyse_site.py", "python", []),
    ("05", "05_donnees_livrees.py", "python", []),
    ("06", "06_atlas_qgis.py", "qgis", []),
    ("06b", "06b_modeles_qgis.py", "qgis", []),
    ("07", "07_documents.py", "python", []),
    ("08", "08_qfield.py", "qgis", []),
    ("11", "11_planche_concertation.py", "python", []),
    ("12", "12_empaqueter_extension.py", "python", []),
    ("13", "13_carte_web.py", "python", []),
]


def main(choix):
    debut = time.time()
    for num, script, interprete, args in ETAPES:
        if choix and num not in choix:
            continue
        exe = str(config.QGIS_PYTHON) if interprete == "qgis" else sys.executable
        log(f"=== {num} {script}")
        r = subprocess.run([exe, str(config.RACINE / "scripts" / script), *args], cwd=config.RACINE / "scripts")
        if r.returncode != 0:
            log(f"Échec de l'étape {num} ({script}) : arrêt de la chaîne")
            sys.exit(r.returncode)
    log(f"Chaîne terminée en {(time.time() - debut) / 60:.0f} min")


if __name__ == "__main__":
    main(set(sys.argv[1:]))
