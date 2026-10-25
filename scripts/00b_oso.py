"""Étape 0 bis (facultative) - Carte d'occupation des sols OSO du CESBIO, découpée au département.

OSO n'est diffusée qu'en une archive France entière (environ 5,6 Go, Recherche Data Gouv).
L'archive est lue en flux : seule la classification (fichier OCS) est écrite sur le disque,
puis découpée sur l'emprise du département et compressée. La chaîne fonctionne sans OSO :
la comparaison des sources se limite alors à OCS GE et Corine Land Cover.

    python 00b_oso.py
"""
import tarfile

import config  # en premier : prépare l'environnement (PROJ, chemins)
import rasterio
from rasterio.mask import mask

from etat_initial.reseau import SESSION, log, wfs

# Identifiants des fichiers dans le jeu « Carte d'occupation des sols du CES OSO »
# (doi:10.57745/UZ2NJ7), un par millésime
FICHIERS = {2020: 643418, 2021: 643420, 2022: 643419, 2023: 643417}
URL = "https://entrepot.recherche.data.gouv.fr/api/access/datafile/{}"


def extraire_classification(annee, cible):
    """Lit l'archive en flux et n'écrit que le raster de classification."""
    url = URL.format(FICHIERS[annee])
    log(f"OSO {annee} : lecture en flux de l'archive nationale")
    with SESSION.get(url, stream=True, timeout=600) as r:
        r.raise_for_status()
        r.raw.decode_content = False
        with tarfile.open(fileobj=r.raw, mode="r|gz") as archive:
            for membre in archive:
                nom = membre.name.rsplit("/", 1)[-1]
                log(f"  membre : {membre.name} ({membre.size / 1e6:.0f} Mo)")
                # la classification s'appelle OCS_<année>.tif ; les autres rasters
                # (confiance, validité) portent un suffixe
                if membre.isfile() and nom.upper().startswith("OCS_") and nom.lower().endswith(".tif") \
                        and "confid" not in nom.lower() and "valid" not in nom.lower():
                    with archive.extractfile(membre) as src, open(cible, "wb") as dst:
                        while bloc := src.read(1 << 22):
                            dst.write(bloc)
                    log(f"  classification écrite : {cible.name}")
                    return cible
    raise RuntimeError("raster de classification introuvable dans l'archive OSO")


def decouper(france, sortie):
    log("Découpe sur l'emprise du département")
    dep = wfs("geopf", "ADMINEXPRESS-COG.LATEST:departement", cql=f"code_insee='{config.DEPARTEMENT}'")
    zone = dep.buffer(config.MARGE_REFERENTIEL_M)
    with rasterio.open(france) as src:
        # le raster déclare un système local « RGF93 v1 / Lambert-93 » sans code EPSG :
        # les coordonnées sont bien en Lambert-93, on les découpe telles quelles
        data, transform = mask(src, list(zone.geometry), crop=True, nodata=0)
        profil = src.profile.copy()
        profil.update(height=data.shape[1], width=data.shape[2], transform=transform, nodata=0,
                      crs="EPSG:2154", compress="deflate", tiled=True, blockxsize=512,
                      blockysize=512, driver="GTiff")
        couleurs = None
        try:
            couleurs = src.colormap(1)
        except ValueError:
            pass
    with rasterio.open(sortie, "w", **profil) as dst:
        dst.write(data)
        if couleurs:
            dst.write_colormap(1, couleurs)
    log(f"  {sortie.name} : {data.shape[2]} x {data.shape[1]} pixels")


def main():
    sortie = config.OSO_RASTER
    if sortie.exists():
        log(f"OSO déjà présent : {sortie.name}")
        return
    sortie.parent.mkdir(parents=True, exist_ok=True)
    france = sortie.parent / f"OSO_{config.OSO_ANNEE}_France.tif"
    if not france.exists():
        partiel = france.with_suffix(".partiel")
        extraire_classification(config.OSO_ANNEE, partiel)
        partiel.replace(france)
    decouper(france, sortie)
    france.unlink()  # 1 à 2 Go : seule la découpe départementale est conservée


if __name__ == "__main__":
    main()
