"""Étape 13 - Données de la carte web (docs/, publiée avec GitHub Pages).

Exporte en GeoJSON (WGS84, géométries simplifiées) les couches utiles à la consultation et
les chiffres clés de l'étude ; la page docs/index.html les affiche avec MapLibre GL JS.
Le parcellaire et les propriétaires ne sont pas publiés.

    python 13_carte_web.py
"""
import json

import config
import geopandas as gpd
import pyogrio

from outils import log, psql

GPKG = config.LIVRABLES / "02_Donnees_SIG" / "etat_initial.gpkg"
DONNEES = config.DOCS / "donnees"

COUCHES = {  # nom livré -> (fichier, colonnes publiées, tolérance de simplification en m)
    "projet": ("zip", ["nom"], 0.5),
    "aire_etude": ("aires", ["aire", "libelle", "distance_m"], 2),
    "enjeu": ("enjeux", ["theme", "sujet", "niveau"], 1),
    "znieff1": ("znieff1", ["code", "nom", "url"], 5),
    "znieff2": ("znieff2", ["code", "nom", "url"], 10),
    "zsc": ("natura2000", ["code", "nom", "url"], 5),
    "zps": ("natura2000_zps", ["code", "nom", "url"], 5),
    "rnr": ("reserves", ["code", "nom", "url"], 5),
    "pnr": ("pnr", ["code", "nom"], 20),
    "zdh": ("zones_humides", ["milieu"], 3),
    "unesco_bien": ("unesco_bien", ["nom"], 3),
    "unesco_tampon": ("unesco_tampon", [], 5),
    "zone_urba": ("plu", ["libelle", "libelong", "typezone"], 1),
    "observation_patrimoniale": ("especes", ["nom_francais", "nom_scientifique", "groupe", "annee"], 0),
    "criblage_friches": ("criblage", ["rang", "site_nom", "commune", "surface_ha", "classe", "contraintes",
                                      "atouts"], 2),
    "contexte_epci": ("epci", ["nom"], 20),
}


def exporter(nom, fichier, colonnes, tol):
    sortie = DONNEES / f"{fichier}.geojson"
    try:
        gdf = gpd.read_file(GPKG, layer=nom)
    except Exception:  # couche absente de l'étude : collection vide, la page l'ignore
        gdf = gpd.GeoDataFrame(geometry=[], crs=2154)
    if gdf.empty:
        sortie.write_text('{"type": "FeatureCollection", "features": []}', encoding="utf-8")
        return 0
    gdf = gdf[[c for c in colonnes if c in gdf.columns] + ["geometry"]].copy()
    if tol:
        gdf["geometry"] = gdf.geometry.simplify(tol, preserve_topology=True)
    gdf = gdf.to_crs(4326)
    for c in gdf.columns:
        if c != "geometry" and gdf[c].dtype == object:
            gdf[c] = gdf[c].fillna("")
    gdf.to_file(sortie, driver="GeoJSON", engine="pyogrio", layer_options={"COORDINATE_PRECISION": 6,
                                                                            "RFC7946": "YES"})
    return len(gdf)


def chiffres():
    enj = pyogrio.read_dataframe(GPKG, layer="t_enjeux", read_geometry=False)
    crib = pyogrio.read_dataframe(GPKG, layer="criblage_friches", read_geometry=False).sort_values("rang")
    esp = pyogrio.read_dataframe(GPKG, layer="t_especes", read_geometry=False)
    zon = pyogrio.read_dataframe(GPKG, layer="t_zonage", read_geometry=False)
    zz = zon[zon["aire"] == "Zone d'implantation potentielle"].sort_values("part", ascending=False)
    site = crib.iloc[0]
    reconvertis = int(psql("SELECT count(*) FROM criblage.critere WHERE part_en_activite > 0.30 "
                           "AND NOT surface_insuffisante"))
    return {
        "site": site["site_nom"].replace("(d'hydrocarbure)", "d'hydrocarbures"), "commune": site["commune"],
        "surface_ha": float(site["surface_ha"]), "nb_friches": len(crib),
        "classes": crib["classe"].value_counts().to_dict(), "reconvertis": reconvertis,
        "plu": [{"zone": r.zone, "part": round(r.part, 3), "intitule": r.intitule} for r in zz.itertuples()],
        "especes": {"total": len(esp), "protegees": int(esp["protegee"].sum()),
                    "patrimoniales": int(esp["patrimoniale"].sum())},
        "enjeux": enj[["theme", "sujet", "niveau", "justification"]].to_dict("records"),
        "cartouche": config.CARTOUCHE, "auteur": config.AUTEUR,
    }


def main():
    DONNEES.mkdir(parents=True, exist_ok=True)
    for nom, (fichier, cols, tol) in COUCHES.items():
        n = exporter(nom, fichier, cols, tol)
        log(f"  {fichier}.geojson : {n} objet(s)")
    (DONNEES / "etude.json").write_text(json.dumps(chiffres(), ensure_ascii=False, indent=1, default=str),
                                        encoding="utf-8")
    taille = sum(f.stat().st_size for f in DONNEES.glob("*")) / 1e6
    log(f"Carte web : {len(list(DONNEES.glob('*')))} fichiers, {taille:.1f} Mo dans docs/donnees")


if __name__ == "__main__":
    main()
