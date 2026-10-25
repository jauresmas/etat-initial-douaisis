"""Enchaînement complet d'une étude : collecte, analyses, enjeux, écriture du GeoPackage.

Utilisé par l'extension QGIS (un périmètre quelconque) et, pour les analyses, par la chaîne
de démonstration (scripts/04_analyse_site.py).
"""
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pyogrio

from . import aires as A
from . import analyse, enjeux, ocsol, sources
from .parametres import CATALOGUE, CLASSES_HARMONISEES
from .reseau import log


def _palette(table):
    return {k: tuple(int(c[i:i + 2], 16) for i in (1, 3, 5)) + (255,) for k, (_, c) in table.items()}


def concordance(d, aires, oso_tif, dossier_rasters):
    """Trois sources d'occupation du sol sur la grille OSO ; écrit les rasters de comparaison."""
    try:
        import rasterio
        from rasterio import features
    except ImportError:
        log("  rasterio absent : comparaison des sources ignorée")
        return {}
    if not oso_tif or not Path(oso_tif).exists() or "ocsge" not in d or d["ocsge"].empty or "clc" not in d:
        log("  OSO ou OCS GE absent : comparaison des sources ignorée")
        return {}
    eloignee = A.geom_aire(aires, "eloignee")
    g, transform, profil = ocsol.grilles(d["ocsge"], d["clc"], oso_tif, eloignee)
    res = {"surfaces": [], "accords": []}
    for aire in ("zip", "immediate", "rapprochee", "eloignee"):
        masque = features.rasterize([(A.geom_aire(aires, aire), 1)], out_shape=g["oso"].shape,
                                    transform=transform, fill=0, dtype="uint8").astype(bool)
        res["surfaces"].append(ocsol.surfaces(g, masque).assign(aire=aire))
        for a, b in (("ocsge", "clc"), ("ocsge", "oso"), ("clc", "oso")):
            po, kappa = ocsol.accord(g[a], g[b], masque)
            res["accords"].append({"aire": aire, "comparaison": f"{ocsol.NOM_SOURCE[a]} / {ocsol.NOM_SOURCE[b]}",
                                   "accord": po, "kappa": kappa})
        if aire == "eloignee":
            res["matrice_ocsge_oso"] = ocsol.matrice(g["ocsge"], g["oso"], masque)
            res["matrice_ocsge_clc"] = ocsol.matrice(g["ocsge"], g["clc"], masque)
    dossier = Path(dossier_rasters)
    dossier.mkdir(parents=True, exist_ok=True)
    profil = profil | {"count": 1, "dtype": "uint8", "nodata": 0, "compress": "deflate"}
    with rasterio.open(dossier / "concordance_ocs.tif", "w", **profil) as dst:
        dst.write(ocsol.carte_concordance(g), 1)
        dst.write_colormap(1, _palette(ocsol.LEGENDE_CONCORDANCE))
    for s in ocsol.SOURCES:  # grilles harmonisées pour les cartes de comparaison
        with rasterio.open(dossier / f"ocs_harmonise_{s}.tif", "w", **profil) as dst:
            dst.write(g[s], 1)
            dst.write_colormap(1, _palette(CLASSES_HARMONISEES))
    res["surfaces"] = pd.concat(res["surfaces"], ignore_index=True)
    res["accords"] = pd.DataFrame(res["accords"])
    return res


def analyser(d, aires, oso_tif=None, dossier_rasters=None):
    """Tous les tableaux de l'état initial et la grille des enjeux.

    Renvoie (t, enj, couches) : t = tableaux, enj = enjeux (GeoDataFrame), couches = couches
    dérivées à écrire (évolution OCS GE, parcelles de la ZIP, observations patrimoniales).
    """
    t, couches = {}, {}
    zip_geom = A.geom_aire(aires, "zip")
    log("Inventaire des zonages")
    t["zonages"] = analyse.inventaire_zonages(d, aires)
    t["zones_humides"] = analyse.zones_humides(d, aires)
    if "ocsge" in d and not d["ocsge"].empty:
        log("Occupation du sol")
        t["occupation"] = analyse.occupation_ocsge(d["ocsge"], aires)
        t["annee_ocsge"] = " et ".join(str(a) for a in sorted(d["ocsge"]["millesime"].unique()))
        couches["ocsge_evolution"] = analyse.evolution_ocsge(d.get("ocsge_diff"), aires)
    if oso_tif:
        log("Comparaison OCS GE / Corine Land Cover / OSO")
        t["concordance"] = concordance(d, aires, oso_tif, dossier_rasters)
    log("Urbanisme, servitudes, foncier")
    t["zonage"] = analyse.zonage_site(d, aires)
    t["prescriptions"] = analyse.prescriptions_site(d, aires)
    t["servitudes"] = analyse.servitudes_site(d, aires)
    couches["parcelle_zip"], t["foncier"] = analyse.foncier_site(d, aires)
    info = d.get("info_surf")
    if info is not None and not info.empty:
        t["info_zip"] = sorted(set(info[info.intersects(zip_geom)]["libelle"].dropna()))
    log("Risques, réseaux, riverains")
    t["risques"] = analyse.risques_site(d, aires)
    t["reseaux"] = analyse.reseaux_site(d, aires)
    t["riverains"] = analyse.riverains(d, aires)
    if "espece_brute" in d and not d["espece_brute"].empty:
        log("Espèces (GBIF + TAXREF)")
        t["especes"] = analyse.especes(d["espece_brute"])
        t["especes_groupes"] = analyse.synthese_especes(t["especes"])
        pat = t["especes"][t["especes"]["patrimoniale"]]
        log(f"  {len(t['especes'])} espèces, {int(t['especes']['protegee'].sum())} protégées, "
            f"{len(pat)} patrimoniales")
        obs = sources.occurrences(A.geom_aire(aires, "rapprochee"), pat["species_key"].tolist())
        if not obs.empty:
            couches["observation_patrimoniale"] = obs.merge(
                pat[["species_key", "nom_francais", "nom_scientifique", "groupe", "protegee", "directives",
                     "liste_rouge_regionale"]], on="species_key")
    log("Hiérarchisation des enjeux")
    enj = enjeux.hierarchiser(d, aires, t)
    for th, grp in enj.groupby("theme", sort=False):
        log(f"  {th} : " + ", ".join(f"{r.sujet} ({r.niveau})" for r in grp.itertuples()))
    return t, enj, couches


TABLEAUX = ("zonages", "zones_humides", "occupation", "zonage", "prescriptions", "servitudes", "foncier",
            "risques", "reseaux", "especes", "especes_groupes")


def ecrire_resultats(t, enj, couches, gpkg, ecrire):
    """Écrit les tableaux (t_*), les couches dérivées et la couche des enjeux spatialisés."""
    for nom in TABLEAUX:
        if isinstance(t.get(nom), pd.DataFrame) and not t[nom].empty:
            ecrire(t[nom], f"t_{nom}", gpkg)
    conc = t.get("concordance") or {}
    if conc:
        ecrire(conc["surfaces"], "t_ocs_sources", gpkg)
        ecrire(conc["accords"], "t_ocs_accords", gpkg)
        for m in ("matrice_ocsge_oso", "matrice_ocsge_clc"):
            ecrire(conc[m].reset_index(names="ocsge"), f"t_{m}", gpkg)
    for nom, gdf in couches.items():
        if gdf is not None and not gdf.empty:
            ecrire(gdf, nom, gpkg)
    spatial = enj[enj.geometry.notna()].copy()
    spatial["geometry"] = [sources.meme_dimension(g, 2) for g in spatial.geometry.make_valid()]
    spatial = spatial[spatial.geometry.notna()]
    if not spatial.empty:
        ecrire(spatial, "enjeu", gpkg)
    ecrire(pd.DataFrame(enj.drop(columns="geometry")), "t_enjeux", gpkg)


def collecter(aires, cache, ocsge=True, foncier_pm=False, especes=True, journal_etape=None):
    """Collecte complète pour un périmètre quelconque (extension QGIS). Renvoie {nom: couche}."""
    etape = journal_etape or (lambda texte, part: log(texte))
    eloignee = A.geom_aire(aires, "eloignee")
    cache = Path(cache)
    d = {}
    etape("Communes et couches du catalogue", 5)
    d["commune"] = sources.communes(eloignee)
    for i, code in enumerate(CATALOGUE):
        d.update(sources.collecter(aires, [code]))
        etape(None, 5 + 35 * (i + 1) / len(CATALOGUE))
    etape("Urbanisme (Géoportail de l'Urbanisme)", 42)
    d["doc_urba"] = sources.documents_urbanisme(d["commune"])
    d.update({k: v for k, v in sources.urbanisme(aires, "rapprochee").items() if not v.empty})
    etape("Parcellaire", 55)
    d["parcelle"] = sources.parcelles(aires, "immediate")
    if foncier_pm:
        etape("Personnes morales (DGFiP)", 58)
        morceaux = [sources.personnes_morales(dep, cache / "dgfip") for dep in sources.departements(
            A.geom_aire(aires, "immediate"))]
        pm = pd.concat(morceaux, ignore_index=True)
        d["proprietaire_pm"] = _pm_parcelles(pm, d["parcelle"])
    if ocsge:
        etape("OCS GE (téléchargement par département)", 62)
        d["ocsge"] = sources.ocsge_zone(eloignee, cache / "ocsge")
        d["ocsge_diff"] = sources.ocsge_diff_zone(A.geom_aire(aires, "rapprochee"), cache / "ocsge")
    if especes:
        etape("Espèces connues (GBIF, statuts TAXREF)", 75)
        esp = sources.especes_gbif(A.geom_aire(aires, "rapprochee"))
        if not esp.empty:
            fiches = sources.fiches_especes(esp["species_key"].tolist(), cache / "especes")
            tab = esp.merge(pd.DataFrame(fiches).drop(columns=["statuts"]), on="species_key")
            tab["statuts"] = [repr(f["statuts"]) for f in fiches]
            d["espece_brute"] = tab
    return d


def _pm_parcelles(pm, parc):
    """Rapproche le fichier DGFiP des personnes morales et les parcelles (identifiant à 14 caractères)."""
    cols = {c.lower(): c for c in pm.columns}

    def col(*noms):
        for n in noms:
            for k, v in cols.items():
                if n in k:
                    return pm[v].fillna("")
        raise KeyError(noms)

    idu = (col("département", "departement").str.zfill(2) + col("code commune").str.zfill(3)
           + col("préfixe", "prefixe").str.zfill(3) + col("section").str.strip().str.rjust(2, "0")
           + col("n° plan", "plan").str.zfill(4))
    out = pd.DataFrame({"idu": idu, "groupe": col("groupe personne"),
                        "denomination": col("dénomination", "denomination")})
    return out[out["idu"].isin(parc["idu"])].drop_duplicates("idu")


def ecrire_gpkg(gdf, nom, gpkg):
    """Écriture d'une couche ou d'une table dans un GeoPackage (sans dépendance à la chaîne)."""
    Path(gpkg).parent.mkdir(parents=True, exist_ok=True)
    if isinstance(gdf, gpd.GeoDataFrame):
        gdf.to_file(gpkg, layer=nom, driver="GPKG", engine="pyogrio")
    else:
        pyogrio.write_dataframe(pd.DataFrame(gdf), gpkg, layer=nom, driver="GPKG")
