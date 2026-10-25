"""Collecte des données autour d'un périmètre : flux WFS, API du GPU, OCS GE, OSO, GBIF.

Chaque fonction renvoie des GeoDataFrame en Lambert-93, découpés sur l'aire d'étude
prévue au catalogue (parametres.CATALOGUE). Aucune donnée n'est saisie à la main.
"""
import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pyogrio
import shapely
from shapely.geometry import mapping
from shapely.geometry.polygon import orient

from .aires import geom_aire
from .parametres import CATALOGUE, CRS, GBIF_API, GPU_API, OCSGE_TELECHARGEMENT
from .reseau import SESSION, log, requete, telecharger, wfs


# --- Outils ----------------------------------------------------------------------------------
def reparer(texte):
    """Corrige les libellés encodés deux fois en UTF-8 (« ChÃ¢teau » -> « Château »)."""
    if not isinstance(texte, str) or not any(c in texte for c in "ÃÂâ€"):
        return texte
    try:
        return texte.encode("cp1252").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return texte


def nettoyer(gdf, garder, renommer):
    cols = [c for c in garder if c in gdf.columns]
    gdf = gdf[cols + ["geometry"]].rename(columns=renommer).copy()
    for c in gdf.columns:
        if gdf[c].dtype == object and c != "geometry":
            gdf[c] = gdf[c].map(reparer)
    gdf = gdf.set_geometry(gdf.geometry.force_2d())
    return gdf


def decouper(gdf, zone):
    """Garde les objets qui touchent la zone et les découpe ; conserve la surface d'origine."""
    if gdf.empty:
        return gdf
    idx = gdf.sindex.query(zone, predicate="intersects")
    gdf = gdf.iloc[sorted(set(idx))].copy()
    if gdf.empty:
        return gdf.reset_index(drop=True)
    surfaciques = gdf.geom_type.isin(["Polygon", "MultiPolygon"])
    if surfaciques.any():
        gdf["surface_totale_ha"] = (gdf.area / 10_000).round(2).where(surfaciques)
    dimension = {"Point": 0, "MultiPoint": 0, "LineString": 1, "MultiLineString": 1,
                 "Polygon": 2, "MultiPolygon": 2}
    dims = gdf.geom_type.map(dimension)
    gdf["geometry"] = [meme_dimension(g, d) for g, d in
                       zip(gdf.geometry.make_valid().intersection(zone), dims)]
    gdf = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty]
    return gdf.reset_index(drop=True)


def meme_dimension(geom, dim):
    """Ne garde d'une géométrie découpée que les parties de la dimension d'origine
    (un polygone découpé peut produire des fragments linéaires en limite de zone)."""
    if geom is None or geom.is_empty or dim is None:
        return geom
    parties = [p for p in shapely.get_parts(geom) if shapely.get_dimensions(p) == dim]
    if not parties:
        return None
    if len(parties) == 1:
        return parties[0]
    return [shapely.MultiPoint, shapely.MultiLineString, shapely.MultiPolygon][dim](
        [q for p in parties for q in shapely.get_parts(p)])


def _emprise(aires, aire, marge):
    return geom_aire(aires, aire).buffer(marge)


# --- Couches du catalogue ---------------------------------------------------------------------
def couche(code, aires, marge=0):
    """Télécharge une couche du catalogue sur son aire d'étude (plus une marge en m)."""
    return couche_zone(code, _emprise(aires, CATALOGUE[code]["aire"], marge))


def couche_zone(code, zone):
    """Télécharge une couche du catalogue sur une zone quelconque (ex. un territoire)."""
    fiche = CATALOGUE[code]
    gdf = wfs(fiche["service"], fiche["couche"], bbox=zone.bounds, tri=fiche.get("tri"),
              cql=fiche.get("filtre") if fiche["service"] != "brgm" else None)
    if gdf.empty:
        return gdf
    if fiche["service"] == "brgm" and fiche.get("filtre"):
        gdf = gdf.query(fiche["filtre"])
    gdf = nettoyer(gdf, fiche["garder"], fiche["renommer"])
    gdf = decouper(gdf, zone)
    gdf["source"] = fiche["libelle"]
    return gdf


def collecter(aires, codes=None, marge=0):
    """Toutes les couches du catalogue (ou celles demandées). Renvoie {code: GeoDataFrame}."""
    resultat = {}
    for code in codes or CATALOGUE:
        try:
            gdf = couche(code, aires, marge)
        except Exception as err:  # un service indisponible ne bloque pas l'étude
            log(f"  {code} : ÉCHEC ({err.__class__.__name__} : {str(err)[:120]})")
            continue
        log(f"  {code} : {len(gdf)} objet(s)")
        resultat[code] = gdf
    return resultat


# --- Limites administratives --------------------------------------------------------------
def communes(zone):
    gdf = wfs("geopf", "ADMINEXPRESS-COG.LATEST:commune", bbox=zone.bounds)
    gdf = nettoyer(gdf, ["code_insee", "nom_officiel", "population", "codes_siren_des_epci",
                         "code_insee_du_departement"],
                   {"nom_officiel": "nom", "codes_siren_des_epci": "epci",
                    "code_insee_du_departement": "departement"})
    idx = gdf.sindex.query(zone, predicate="intersects")
    return gdf.iloc[sorted(set(idx))].sort_values("code_insee").reset_index(drop=True)


# --- Urbanisme (Géoportail de l'Urbanisme, API Carto) -------------------------------------------
def _gpu(ressource, geom_l93=None, **params):
    """Interroge l'API Carto du GPU, page par page ; renvoie un GeoDataFrame en Lambert-93."""
    if geom_l93 is not None:
        geom = gpd.GeoSeries([geom_l93.simplify(10)], crs=CRS).to_crs(4326).iloc[0]
        params["geom"] = json.dumps(mapping(geom))
    params["_limit"] = 500
    morceaux, debut = [], 0
    while True:
        params["_start"] = debut
        feats = requete(f"{GPU_API}/{ressource}", params=params, timeout=120).json().get("features", [])
        if not feats:
            break
        morceaux.append(gpd.GeoDataFrame.from_features(feats, crs=4326))
        debut += len(feats)
        if len(feats) < params["_limit"]:
            break
    if not morceaux:
        return gpd.GeoDataFrame(geometry=[], crs=CRS)
    gdf = pd.concat(morceaux, ignore_index=True)
    return gpd.GeoDataFrame(gdf, crs=4326).to_crs(CRS)


def documents_urbanisme(com):
    """Document d'urbanisme applicable par commune (PLU, PLUi, carte communale ou RNU)."""
    lignes = []
    for _, c in com.iterrows():
        muni = requete(f"{GPU_API}/municipality", params={"insee": c["code_insee"]}).json()["features"]
        rnu = bool(muni and muni[0]["properties"].get("is_rnu"))
        docs = _gpu("document", c.geometry.representative_point())
        if not docs.empty:
            docs = docs[docs["du_type"].notna()].copy()
            # un PLUi couvre la commune entière : on le préfère au document communal s'il existe
            docs["ordre"] = docs["du_type"].map({"PLUi": 0, "PSMV": 2}).fillna(1)
            d = docs.sort_values("ordre").iloc[0]
            lignes.append({"code_insee": c["code_insee"], "commune": c["nom"],
                           "type_document": d["du_type"], "partition": d.get("partition"),
                           "nom_document": reparer(d.get("name")), "rnu": rnu})
        else:
            lignes.append({"code_insee": c["code_insee"], "commune": c["nom"],
                           "type_document": "RNU" if rnu else "Aucun document publié",
                           "partition": None, "nom_document": None, "rnu": rnu})
    tab = pd.DataFrame(lignes)
    return com[["code_insee", "geometry"]].merge(tab, on="code_insee")


GPU_COLONNES = {
    "zone-urba": ["partition", "libelle", "libelong", "typezone", "destdomi", "datvalid", "urlfic"],
    "prescription-surf": ["partition", "libelle", "txt", "typepsc", "stypepsc", "urlfic"],
    "prescription-lin": ["partition", "libelle", "txt", "typepsc", "stypepsc", "urlfic"],
    "prescription-pct": ["partition", "libelle", "txt", "typepsc", "stypepsc", "urlfic"],
    "info-surf": ["partition", "libelle", "txt", "typeinf", "stypeinf", "urlfic"],
    "assiette-sup-s": ["suptype", "partition", "nomass", "typeass", "idgen", "fichier"],
    "assiette-sup-l": ["suptype", "partition", "nomass", "typeass", "idgen", "fichier"],
    "assiette-sup-p": ["suptype", "partition", "nomass", "typeass", "idgen", "fichier"],
    "generateur-sup-s": ["suptype", "partition", "nomgen", "typegen", "idgen", "fichier"],
    "generateur-sup-l": ["suptype", "partition", "nomgen", "typegen", "idgen", "fichier"],
    "generateur-sup-p": ["suptype", "partition", "nomgen", "typegen", "idgen", "fichier"],
}


def urbanisme(aires, aire="rapprochee"):
    """Zonage, prescriptions, informations et servitudes du GPU sur l'aire demandée."""
    zone = geom_aire(aires, aire)
    resultat = {}
    for ressource, cols in GPU_COLONNES.items():
        gdf = _gpu(ressource, zone)
        if not gdf.empty:
            gdf = nettoyer(gdf, cols, {})
            if "suptype" in gdf.columns:
                gdf["suptype"] = gdf["suptype"].str.upper()
            gdf = decouper(gdf, zone)
        log(f"  {ressource} : {len(gdf)} objet(s)")
        resultat[ressource.replace("-", "_")] = gdf
    return resultat


# --- Foncier -------------------------------------------------------------------------------------
def parcelles(aires, aire="immediate"):
    zone = geom_aire(aires, aire)
    gdf = wfs("geopf", "CADASTRALPARCELS.PARCELLAIRE_EXPRESS:parcelle", bbox=zone.bounds, tri="gid")
    gdf = nettoyer(gdf, ["idu", "code_insee", "nom_com", "section", "numero", "contenance"],
                   {"nom_com": "commune"})
    gdf = gdf.drop_duplicates("idu")
    idx = gdf.sindex.query(zone, predicate="intersects")
    gdf = gdf.iloc[sorted(set(idx))].reset_index(drop=True)
    gdf["part_dans_zip"] = (gdf.intersection(geom_aire(aires, "zip")).area / gdf.area).round(3)
    return gdf


DGFIP_PM = ("https://data.economie.gouv.fr/api/v2/catalog/datasets/"
            "fichiers-des-locaux-et-des-parcelles-des-personnes-morales/attachments/"
            "fichier_des_parcelles_situation_2025_dpts_{}_zip")


def personnes_morales(departement, dossier):
    """Parcelles détenues par des personnes morales (fichier ouvert de la DGFiP, 2025).

    Les propriétaires personnes physiques ne sont pas diffusés : ils relèvent des fichiers
    fonciers, accessibles sous convention, et n'apparaissent jamais dans les livrables.
    """
    import zipfile
    lot = "01_a_56" if departement < "57" else "57_a_976"
    archive = telecharger(DGFIP_PM.format(lot), Path(dossier) / f"parcelles_pm_2025_{lot}.zip")
    morceaux = []
    with zipfile.ZipFile(archive) as z:
        for nom in z.namelist():
            # un fichier par département, nommé ...PM_25_NB_<dép>0.txt (ou .csv)
            if not re.search(rf"_{departement}0?\.(txt|csv)$", nom, re.I):
                continue
            with z.open(nom) as f:
                morceaux.append(pd.read_csv(f, sep=";", dtype=str, encoding="latin-1"))
    if not morceaux:
        raise FileNotFoundError(f"département {departement} absent de {archive.name}")
    pm = pd.concat(morceaux, ignore_index=True)
    pm.columns = [reparer(c).strip() for c in pm.columns]
    return pm


# --- OCS GE (IGN) -----------------------------------------------------------------------------------
def ocsge_archives(departement):
    """Liste des archives OCS GE 2.0 publiées pour un département (millésimes et différentiels)."""
    dep = f"D{int(departement):03d}" if departement.isdigit() else f"D0{departement}"
    r = requete(f"{OCSGE_TELECHARGEMENT}/resource/OCSGE", params={"zone": dep})
    noms = sorted(set(re.findall(rf"OCS-GE_2-0_[A-Z0-9_-]*?_GPKG_LAMB93_{dep}_[0-9-]+", r.text)))
    return {"millesimes": {int(n[-10:-6]): n for n in noms if "DIFF" not in n and "PATCH" not in n},
            "differentiels": [n for n in noms if "DIFF" in n]}


def ocsge_gpkg(nom, dossier):
    """Télécharge et extrait une archive OCS GE ; renvoie le chemin du GeoPackage utile."""
    dossier = Path(dossier)
    archive = telecharger(f"{OCSGE_TELECHARGEMENT}/download/OCSGE/{nom}/{nom}.7z", dossier / f"{nom}.7z")
    cibles = sorted((dossier / nom).rglob("OCCUPATION_SOL.gpkg")) or sorted((dossier / nom).rglob("DIFF_*.gpkg"))
    if not cibles:
        extraire_7z(archive, dossier)
        cibles = sorted((dossier / nom).rglob("OCCUPATION_SOL.gpkg")) or sorted((dossier / nom).rglob("DIFF_*.gpkg"))
    return cibles[0]


def extraire_7z(archive, dossier):
    """Extrait les GeoPackage d'une archive 7z : py7zr s'il est installé (Python du poste),
    sinon 7-Zip en ligne de commande (Python de QGIS, qui n'a pas py7zr)."""
    motif = re.compile(r"(OCCUPATION_SOL\.gpkg|DIFF_.*\.gpkg|NomenclatureOCSGE\.csv)$")
    try:
        import py7zr
        with py7zr.SevenZipFile(archive) as z:
            z.extract(path=dossier, targets=[n for n in z.getnames() if motif.search(n)])
        return
    except ImportError:
        pass
    import shutil
    import subprocess
    exe = shutil.which("7z") or next((p for p in (r"C:\Program Files\7-Zip\7z.exe",
                                                  r"C:\Program Files (x86)\7-Zip\7z.exe") if Path(p).exists()), None)
    if not exe:
        raise RuntimeError("ni py7zr ni 7-Zip : impossible d'extraire l'OCS GE (installer 7-Zip)")
    subprocess.run([exe, "x", "-y", f"-o{dossier}", str(archive), "*.gpkg", "*.csv", "-r"], check=True,
                   capture_output=True)


def lire_ocsge(gpkg, zone):
    gdf = pyogrio.read_dataframe(gpkg, bbox=tuple(zone.bounds))
    gdf = gdf.set_crs(CRS, allow_override=True)
    return decouper(gdf, zone)


def departements(zone):
    com = wfs("geopf", "ADMINEXPRESS-COG.LATEST:departement", bbox=zone.bounds)
    return sorted(com[com.intersects(zone)]["code_insee"])


def ocsge_zone(zone, dossier, annee=None):
    """OCS GE sur une zone qui peut chevaucher plusieurs départements : pour chacun, le millésime
    demandé ou le plus récent publié. Colonnes : code_cs, code_us, millesime, departement."""
    morceaux = []
    for dep in departements(zone):
        mill = ocsge_archives(dep)["millesimes"]
        if not mill:
            log(f"  OCS GE : aucun millésime publié pour le département {dep}")
            continue
        a = annee if annee in mill else max(mill)
        log(f"  OCS GE {a} du département {dep}")
        gdf = lire_ocsge(ocsge_gpkg(mill[a], dossier), zone).rename(columns=str.lower)
        morceaux.append(gdf[["code_cs", "code_us", "geometry"]].assign(millesime=a, departement=dep))
    if not morceaux:
        return gpd.GeoDataFrame(columns=["code_cs", "code_us", "millesime", "departement"], geometry=[], crs=CRS)
    return gpd.GeoDataFrame(pd.concat(morceaux, ignore_index=True), crs=CRS)


def ocsge_diff_zone(zone, dossier):
    """Dernier différentiel OCS GE de chaque département, colonnes harmonisées :
    cs_avant, us_avant, cs_apres, us_apres, periode."""
    morceaux = []
    for dep in departements(zone):
        diffs = ocsge_archives(dep)["differentiels"]
        if not diffs:
            continue
        nom = max(diffs, key=lambda n: re.search(r"DIFF-(\d{4})-(\d{4})", n).group(2))
        gdf = lire_ocsge(ocsge_gpkg(nom, dossier), zone)
        annees = sorted({int(c[3:7]) for c in gdf.columns if re.fullmatch(r"CS_\d{4}", c)})
        if len(annees) < 2:
            continue
        av, ap = annees[0], annees[-1]
        gdf = gdf.rename(columns={f"CS_{av}": "cs_avant", f"US_{av}": "us_avant",
                                  f"CS_{ap}": "cs_apres", f"US_{ap}": "us_apres"})
        morceaux.append(gdf[["cs_avant", "us_avant", "cs_apres", "us_apres", "geometry"]]
                        .assign(periode=f"{av}-{ap}", departement=dep))
        log(f"  OCS GE différentielle {av}-{ap} du département {dep}")
    if not morceaux:
        return gpd.GeoDataFrame(geometry=[], crs=CRS)
    return gpd.GeoDataFrame(pd.concat(morceaux, ignore_index=True), crs=CRS)


# --- OSO (CESBIO) -----------------------------------------------------------------------------------
OSO_CLASSES = {
    1: "Bâti dense", 2: "Bâti diffus", 3: "Zones industrielles et commerciales", 4: "Surfaces routes",
    5: "Colza", 6: "Céréales à paille", 7: "Protéagineux", 8: "Soja", 9: "Tournesol", 10: "Maïs",
    11: "Riz", 12: "Tubercules et racines", 13: "Prairies", 14: "Vergers", 15: "Vignes",
    16: "Forêts de feuillus", 17: "Forêts de conifères", 18: "Pelouses", 19: "Landes ligneuses",
    20: "Surfaces minérales", 21: "Plages et dunes", 22: "Glaciers ou neiges", 23: "Eau", 24: "Serres",
}


# --- Données naturalistes (GBIF, statuts TAXREF) ---------------------------------------------------------
TAXREF_GBIF = "0e61f8fe-7d25-4f81-ada7-d970bbb2c6d6"   # référentiel TAXREF publié sur GBIF
TAXREF_STATUTS = "https://taxref.mnhn.fr/api/status/search/lines"
VERSION_FICHE = 2  # à incrémenter quand le contenu des fiches en cache change


def _wkt_gbif(geom_l93):
    """Polygone simplifié, en WGS84 et orienté dans le sens trigonométrique (exigé par GBIF)."""
    g = gpd.GeoSeries([geom_l93.convex_hull.simplify(50)], crs=CRS).to_crs(4326).iloc[0]
    return orient(g, 1.0).wkt


def especes_gbif(geom_l93, annees=(2010, 2026)):
    """Espèces observées (occurrences GBIF), avec leur nombre de données, par regroupement facetté."""
    params = {"geometry": _wkt_gbif(geom_l93), "year": f"{annees[0]},{annees[1]}",
              "occurrenceStatus": "PRESENT", "hasGeospatialIssue": "false", "limit": 0,
              "facet": "speciesKey", "facetLimit": 3000}
    r = requete(f"{GBIF_API}/occurrence/search", params=params).json()
    log(f"  GBIF : {r['count']} occurrences depuis {annees[0]}")
    return pd.DataFrame([{"species_key": int(c["name"]), "nb_donnees": c["count"]}
                         for c in r["facets"][0]["counts"]]) if r["facets"] else pd.DataFrame()


def _fiche_espece(cle, cache):
    """Nom, groupe et statuts réglementaires d'une espèce (mis en cache sur le disque)."""
    fichier = Path(cache) / f"{cle}.json"
    if fichier.exists():
        fiche = json.loads(fichier.read_text(encoding="utf-8"))
        if "erreur" not in fiche and fiche.get("version") == VERSION_FICHE:  # sinon redemandée
            return fiche
    sp = requete(f"{GBIF_API}/species/{cle}").json()
    fiche = {"species_key": cle, "nom_scientifique": sp.get("canonicalName") or sp.get("scientificName"),
             "regne": sp.get("kingdom"), "classe": sp.get("class"), "ordre": sp.get("order"),
             "famille": sp.get("family"), "nom_francais": None, "cd_nom": None, "statuts": [],
             "version": VERSION_FICHE}
    try:
        noms = requete(f"{GBIF_API}/species/{cle}/vernacularNames", params={"limit": 500}).json()["results"]
        fr = [n for n in noms if n.get("language") == "fra"]
        # le nom de TAXREF (référentiel national) d'abord, sinon le premier nom français
        fr.sort(key=lambda n: (n.get("source") or "") != "TAXREF")
        fiche["nom_francais"] = fr[0]["vernacularName"][:1].upper() + fr[0]["vernacularName"][1:] if fr else None
        tx = requete(f"{GBIF_API}/species", params={"datasetKey": TAXREF_GBIF,
                                                    "name": fiche["nom_scientifique"]}).json()["results"]
        tx = [t for t in tx if t.get("taxonID", "").isdigit() and t.get("rank") == "SPECIES"]
        if tx:
            fiche["cd_nom"] = tx[0]["taxonID"]
            st = requete(TAXREF_STATUTS, params={"taxrefId": fiche["cd_nom"], "size": 200},
                         timeout=60, entetes={"Accept": "application/hal+json;version=1"}).json()
            for s in st.get("_embedded", {}).get("status", []):
                fiche["statuts"].append({"type": s.get("statusTypeName"), "groupe": s.get("statusTypeGroup"),
                                         "code": s.get("statusCode"), "libelle": s.get("statusName"),
                                         "lieu": s.get("locationName")})
    except Exception as err:  # statut indisponible : l'espèce reste listée, sans statut
        fiche["erreur"] = f"{err.__class__.__name__}"
    Path(cache).mkdir(parents=True, exist_ok=True)
    fichier.write_text(json.dumps(fiche, ensure_ascii=False), encoding="utf-8")
    return fiche


def fiches_especes(cles, cache, paralleles=8):
    with ThreadPoolExecutor(max_workers=paralleles) as pool:
        return list(pool.map(lambda c: _fiche_espece(c, cache), cles))


def occurrences(geom_l93, species_keys, annees=(2010, 2026), maxi=300):
    """Localisation des observations d'une liste d'espèces (points, en Lambert-93)."""
    lignes = []
    wkt = _wkt_gbif(geom_l93)
    for cle in species_keys:
        params = {"geometry": wkt, "year": f"{annees[0]},{annees[1]}", "speciesKey": cle,
                  "occurrenceStatus": "PRESENT", "hasCoordinate": "true", "limit": maxi}
        for o in requete(f"{GBIF_API}/occurrence/search", params=params).json()["results"]:
            lignes.append({"species_key": cle, "annee": o.get("year"),
                           "precision_m": o.get("coordinateUncertaintyInMeters"),
                           "jeu_donnees": o.get("datasetName"), "x": o["decimalLongitude"],
                           "y": o["decimalLatitude"]})
    if not lignes:
        return gpd.GeoDataFrame(geometry=[], crs=CRS)
    df = pd.DataFrame(lignes)
    gdf = gpd.GeoDataFrame(df.drop(columns=["x", "y"]), geometry=gpd.points_from_xy(df.x, df.y), crs=4326)
    gdf = gdf.to_crs(CRS)
    return gdf[gdf.within(geom_l93)].reset_index(drop=True)
