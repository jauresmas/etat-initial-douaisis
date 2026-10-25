"""Aires d'étude autour de la zone d'implantation potentielle (ZIP) et position des objets."""
import geopandas as gpd
import pandas as pd

from .parametres import AIRES, CRS, LIBELLE_AIRE, TYPES_PROJET


def aires_etude(zip_geom, type_projet):
    """Renvoie les quatre aires emboîtées (ZIP, immédiate, rapprochée, éloignée).

    Chaque aire contient les précédentes ; la colonne « couronne » donne la partie
    propre à l'aire (utile pour la cartographie).
    """
    if type_projet not in TYPES_PROJET:
        raise ValueError(f"type de projet inconnu : {type_projet} ({', '.join(TYPES_PROJET)})")
    dist = TYPES_PROJET[type_projet]
    zip_geom = gpd.GeoSeries([zip_geom], crs=CRS).make_valid().union_all()
    lignes, precedente = [], None
    for aire in AIRES:
        d = 0 if aire == "zip" else dist[aire]
        geom = zip_geom if d == 0 else zip_geom.buffer(d, quad_segs=16)
        couronne = geom if precedente is None else geom.difference(precedente)
        lignes.append({"aire": aire, "libelle": LIBELLE_AIRE[aire], "distance_m": d,
                       "surface_ha": round(geom.area / 10_000, 1), "geometry": geom,
                       "couronne": couronne})
        precedente = geom
    gdf = gpd.GeoDataFrame(lignes, geometry="geometry", crs=CRS)
    gdf["couronne"] = gpd.GeoSeries(gdf["couronne"], crs=CRS)
    return gdf


def geom_aire(aires, aire):
    return aires.loc[aires["aire"] == aire, "geometry"].iloc[0]


def positionner(gdf, aires, nom="position"):
    """Ajoute la distance à la ZIP (m) et l'aire d'étude la plus proche atteinte par chaque objet."""
    if gdf.empty:
        return gdf.assign(**{"distance_zip_m": pd.Series(dtype=float), nom: pd.Series(dtype=str)})
    zip_geom = geom_aire(aires, "zip")
    seuils = aires.set_index("aire")["distance_m"]
    gdf = gdf.copy()
    gdf["distance_zip_m"] = gdf.geometry.distance(zip_geom).round(0)

    def classe(d):
        if d <= 0:
            return "zip"
        for aire in AIRES[1:]:
            if d <= seuils[aire]:
                return aire
        return "hors"

    gdf[nom] = gdf["distance_zip_m"].map(classe)
    return gdf


def surfaces_par_aire(gdf, aires, colonne=None):
    """Surface (ha) de gdf dans chaque aire, éventuellement ventilée par une colonne."""
    lignes = []
    for _, a in aires.iterrows():
        decoupe = gdf.clip(a.geometry)
        if decoupe.empty:
            continue
        decoupe = decoupe.assign(surface_ha=decoupe.area / 10_000)
        if colonne:
            for valeur, s in decoupe.groupby(colonne)["surface_ha"].sum().items():
                lignes.append({"aire": a["aire"], colonne: valeur, "surface_ha": round(s, 2),
                               "part": round(s / (a.geometry.area / 10_000), 4)})
        else:
            s = decoupe["surface_ha"].sum()
            lignes.append({"aire": a["aire"], "surface_ha": round(s, 2),
                           "part": round(s / (a.geometry.area / 10_000), 4)})
    return pd.DataFrame(lignes)
