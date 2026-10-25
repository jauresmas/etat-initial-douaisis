"""Étape 3 - Collecte des données de l'état initial sur le site retenu.

Toutes les couches sont interrogées par flux sur leur aire d'étude (catalogue de
etat_initial/parametres.py), puis écrites dans data/interim/etat_initial_site.gpkg.
Une couche déjà collectée n'est pas retéléchargée (option --maj pour tout reprendre).

    python 03_collecte_site.py [--maj]
"""
import argparse

import config
import geopandas as gpd
import pandas as pd
import rasterio
from rasterio.mask import mask

from etat_initial import aires as A
from etat_initial import sources
from etat_initial.parametres import CATALOGUE, TYPES_PROJET
from outils import couches, ecrire, log, pg_lire


def projet():
    p = pg_lire("SELECT id, nom, type_projet, commentaire, geom FROM etude.projet WHERE id = 1")
    if p.empty:
        raise SystemExit("Aucun projet en base : lancer d'abord 02_criblage.py")
    return p


def main(maj=False):
    p = projet()
    zip_geom = p.geometry.iloc[0]
    aires = A.aires_etude(zip_geom, p["type_projet"].iloc[0])
    gpkg = config.ETUDE
    if maj and gpkg.exists():
        gpkg.unlink()  # repart d'un GeoPackage vide : aucune couche d'une étude précédente ne subsiste
    deja = couches(gpkg)
    log(f"{p['nom'].iloc[0]}")
    log("  aires : " + ", ".join(f"{r.aire} {r.surface_ha:.0f} ha" for r in aires.itertuples()))

    ecrire(p.rename_geometry("geometry"), "projet", gpkg)
    ecrire(aires.drop(columns="couronne"), "aire_etude", gpkg)
    couronnes = aires.drop(columns="geometry").set_geometry("couronne").rename_geometry("geometry")
    ecrire(couronnes, "aire_couronne", gpkg)
    eloignee = A.geom_aire(aires, "eloignee")
    rapprochee = A.geom_aire(aires, "rapprochee")

    log("Communes")
    if "commune" not in deja:
        com = sources.communes(eloignee)
        ecrire(com, "commune", gpkg)

    log("Couches du catalogue")
    for code in CATALOGUE:
        if code in deja:
            continue
        gdf = sources.collecter(aires, [code]).get(code)
        if gdf is not None:
            ecrire(gdf, code, gpkg)

    log("Urbanisme (Géoportail de l'Urbanisme)")
    if "doc_urba" not in deja:
        com = gpd.read_file(gpkg, layer="commune")
        ecrire(sources.documents_urbanisme(com), "doc_urba", gpkg)
    if "zone_urba" not in deja:
        for nom, gdf in sources.urbanisme(aires, "rapprochee").items():
            if not gdf.empty:
                ecrire(gdf, nom, gpkg)

    log("Foncier")
    if "parcelle" not in deja:
        parc = sources.parcelles(aires, "immediate")
        pm = sources.personnes_morales(config.DEPARTEMENT, config.BRUT / "dgfip")
        ecrire(parc, "parcelle", gpkg)
        ecrire(pm_du_site(pm, parc), "proprietaire_pm", gpkg)

    log("OCS GE")
    # tous les départements touchés par les aires d'étude, chacun avec son dernier millésime
    if "ocsge" not in deja:
        ecrire(sources.ocsge_zone(eloignee, config.BRUT / "ocsge"), "ocsge", gpkg)
    if "ocsge_diff" not in deja:
        ecrire(sources.ocsge_diff_zone(rapprochee, config.BRUT / "ocsge"), "ocsge_diff", gpkg)

    log("OSO (CESBIO)")
    oso = config.TRAVAIL / "oso_site.tif"
    if config.OSO_RASTER.exists() and (maj or not oso.exists()):
        with rasterio.open(config.OSO_RASTER) as src:
            data, transform = mask(src, [eloignee], crop=True, nodata=0)
            profil = src.profile | {"height": data.shape[1], "width": data.shape[2],
                                    "transform": transform}
            palette = src.colormap(1)
        with rasterio.open(oso, "w", **profil) as dst:
            dst.write(data)
            dst.write_colormap(1, palette)
        log(f"  -> oso_site.tif : {data.shape[2]} x {data.shape[1]} pixels")

    log("Données naturalistes (GBIF, statuts TAXREF)")
    if "espece" not in deja:
        esp = sources.especes_gbif(rapprochee)
        fiches = sources.fiches_especes(esp["species_key"].tolist(), config.BRUT / "cache_especes")
        tab = esp.merge(pd.DataFrame(fiches).drop(columns=["statuts"]), on="species_key")
        tab["statuts"] = [f["statuts"] for f in fiches]
        ecrire(tab.assign(statuts=tab["statuts"].map(lambda s: repr(s))), "espece_brute", gpkg)


def pm_du_site(pm, parc):
    """Associe le fichier DGFiP des personnes morales aux parcelles du site (identifiant à 14 car.)."""
    cols = {c.lower(): c for c in pm.columns}

    def col(*noms):
        for n in noms:
            for k, v in cols.items():
                if n in k:
                    return pm[v].fillna("")
        raise KeyError(noms)

    dep = col("département", "departement").str.zfill(2)
    com = col("code commune").str.zfill(3)
    prefixe = col("préfixe", "prefixe").str.zfill(3)
    section = col("section").str.strip().str.rjust(2, "0")
    numero = col("n° plan", "plan").str.zfill(4)
    pm = pm.assign(idu=dep + com + prefixe + section + numero)
    garde = pm[pm["idu"].isin(parc["idu"])].copy()
    renomme = {}
    for cible, motifs in {"siren": ("siren",), "groupe": ("groupe personne",),
                          "forme_juridique": ("forme juridique abrégée", "forme juridique"),
                          "denomination": ("dénomination", "denomination")}.items():
        for k, v in cols.items():
            if any(m in k for m in motifs) and cible not in renomme.values():
                renomme[v] = cible
                break
    garde = garde.rename(columns=renomme)
    garder = ["idu"] + [c for c in ("siren", "groupe", "forme_juridique", "denomination") if c in garde]
    return garde[garder].drop_duplicates()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--maj", action="store_true", help="retélécharge toutes les couches")
    main(ap.parse_args().maj)
