"""Étape 12 - Empaquette l'extension QGIS (bibliothèque etat_initial incluse) en archive installable.

    python 12_empaqueter_extension.py

Produit livrables/07_Extension_QGIS/etat_initial_qgis.zip, à installer dans QGIS par
Extensions > Installer/Gérer les extensions > Installer depuis un ZIP.
"""
import shutil
import zipfile

import config
from outils import log

SOURCE = config.RACINE / "extension" / "etat_initial_qgis"
ARCHIVE = config.LIVRABLES / "07_Extension_QGIS" / "etat_initial_qgis.zip"


def main():
    # la bibliothèque est copiée dans l'extension : une seule source de vérité, etat_initial/
    copie = SOURCE / "etat_initial"
    if copie.exists():
        shutil.rmtree(copie)
    shutil.copytree(config.RACINE / "etat_initial", copie, ignore=shutil.ignore_patterns("__pycache__"))
    ARCHIVE.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(ARCHIVE, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(SOURCE.rglob("*")):
            if f.is_file() and "__pycache__" not in f.parts:
                z.write(f, f.relative_to(SOURCE.parent))
    log(f"Extension : {ARCHIVE.relative_to(config.RACINE)} ({ARCHIVE.stat().st_size / 1e3:.0f} ko)")


if __name__ == "__main__":
    main()
