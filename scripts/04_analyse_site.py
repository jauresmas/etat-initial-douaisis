"""Étape 4 - Analyses de l'état initial, comparaison des sources d'occupation du sol et
hiérarchisation des enjeux du site retenu.

Les analyses sont celles de la bibliothèque (etat_initial/etude.py), communes avec
l'extension QGIS. Les tableaux sont écrits dans le GeoPackage de l'étude (tables t_*), la
couche « enjeu » alimente la carte de synthèse, et les enjeux sont enregistrés dans PostGIS.

    python 04_analyse_site.py
"""
import json

import config
import geopandas as gpd
import numpy as np
import pandas as pd
import pyogrio
from shapely import MultiPolygon, get_parts

from etat_initial import aires as A
from etat_initial import etude
from outils import ecrire, log, pg_ecrire, psql


def charger():
    d = {}
    for nom, _ in pyogrio.list_layers(config.ETUDE):
        if nom.startswith("t_") or nom in ("enjeu", "concordance"):
            continue
        d[nom] = gpd.read_file(config.ETUDE, layer=nom, engine="pyogrio") if nom != "espece_brute" \
            else pyogrio.read_dataframe(config.ETUDE, layer=nom, read_geometry=False)
    return d


def multipolygone(g):
    polys = [p for p in get_parts(g) if p.geom_type in ("Polygon", "MultiPolygon")] if g is not None else []
    return MultiPolygon([q for p in polys for q in get_parts(p)]) if polys else None


def main():
    d = charger()
    p = d["projet"]
    aires = A.aires_etude(p.geometry.iloc[0], p["type_projet"].iloc[0])
    t, enj, couches = etude.analyser(d, aires, oso_tif=config.TRAVAIL / "oso_site.tif",
                                     dossier_rasters=config.TRAVAIL)
    log("Écriture des résultats")
    etude.ecrire_resultats(t, enj, couches, config.ETUDE, ecrire)

    conc = t.get("concordance") or {}
    esp = t.get("especes", pd.DataFrame(columns=["protegee", "patrimoniale"]))
    chiffres = {"surface_zip_ha": round(A.geom_aire(aires, "zip").area / 10_000, 1),
                "nb_zonages_eloignee": int(len(t["zonages"])), "nb_especes": int(len(esp)),
                "nb_protegees": int(esp["protegee"].sum()), "nb_patrimoniales": int(esp["patrimoniale"].sum()),
                "riverains": t["riverains"], "accords": conc["accords"].to_dict("records") if conc else [],
                "enjeux": enj["niveau"].value_counts().to_dict()}
    (config.TRAVAIL / "chiffres_site.json").write_text(json.dumps(chiffres, ensure_ascii=False, indent=1,
                                                                   default=int), encoding="utf-8")

    log("Enjeux dans PostGIS (etude.enjeu)")
    psql("DELETE FROM etude.enjeu WHERE projet_id = 1")
    e = enj.assign(projet_id=1)[["projet_id", "theme", "sujet", "niveau", "justification", "geometry"]]
    e["geometry"] = [multipolygone(g) for g in e.geometry]
    pg_ecrire(gpd.GeoDataFrame(e, geometry="geometry", crs=enj.crs), "enjeu_import", "etude")
    psql("INSERT INTO etude.enjeu (projet_id, theme, sujet, niveau, justification, geom) "
         "SELECT projet_id, theme, sujet, niveau, justification, geom FROM etude.enjeu_import;"
         "DROP TABLE etude.enjeu_import;")
    log(psql("SELECT niveau || ' : ' || count(*) FROM etude.enjeu GROUP BY niveau ORDER BY 1"))


if __name__ == "__main__":
    np.seterr(all="ignore")
    main()
