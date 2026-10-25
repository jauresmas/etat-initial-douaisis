"""Fonctions communes de la chaîne : GeoPackage de travail, base PostGIS, journal."""
import os
import subprocess
from functools import lru_cache

import config  # noqa: F401  (environnement PROJ et chemins)
import geopandas as gpd
import pandas as pd
import pyogrio

from etat_initial.reseau import log  # noqa: F401  (réexporté pour les scripts)


# --- GeoPackage ---------------------------------------------------------------------------------
def ecrire(gdf, couche, gpkg):
    gpkg.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(gdf, gpd.GeoDataFrame):
        gdf.to_file(gpkg, layer=couche, driver="GPKG", engine="pyogrio")
    else:  # table attributaire
        pyogrio.write_dataframe(gdf, gpkg, layer=couche, driver="GPKG")
    log(f"  -> {couche} : {len(gdf)} entités")


def lire(couche, gpkg, **kw):
    return gpd.read_file(gpkg, layer=couche, engine="pyogrio", **kw)


def couches(gpkg):
    return {nom for nom, _ in pyogrio.list_layers(gpkg)} if gpkg.exists() else set()


# --- PostGIS ----------------------------------------------------------------------------------------
def pg_env():
    env = os.environ.copy()
    env.update(PGHOST=config.PG_HOST, PGPORT=str(config.PG_PORT), PGCLIENTENCODING="UTF8",
               LC_ALL="C", LANG="C")  # messages de psql en ASCII, quelle que soit la langue du poste
    if config.PROJ_LIB_POSTGIS:  # le serveur PostGIS a besoin de sa propre base PROJ
        env["PROJ_LIB"] = config.PROJ_LIB_POSTGIS
    return env


def psql(sql=None, fichier=None, base=None, variables=None):
    """Exécute du SQL avec psql (arrêt à la première erreur) ; renvoie la sortie texte."""
    cmd = [str(config.PG_BIN / "psql.exe"), "-X", "-q", "-v", "ON_ERROR_STOP=1",
           "-d", base or config.PG_DB, "-U", config.PG_SUPERUSER]
    for cle, val in (variables or {}).items():
        cmd += ["-v", f"{cle}={val}"]
    if fichier:
        cmd += ["-f", str(fichier)]
    else:
        # le SQL passe par l'entrée standard en UTF-8 : en argument de ligne de
        # commande, Windows le convertirait dans la page de code locale
        cmd += ["-At"]
    res = subprocess.run(cmd, env=pg_env(), capture_output=True, text=True, encoding="utf-8",
                         errors="replace", input=None if fichier else sql)
    if res.returncode != 0:
        raise RuntimeError(f"psql a échoué ({fichier or sql[:80]}) :\n{res.stderr}")
    for ligne in res.stderr.strip().splitlines():
        if not any(m in ligne for m in ("NOTICE", "DETAIL", "drop cascades", "HINT")):
            log(f"  psql : {ligne}")
    return res.stdout.strip()


@lru_cache(maxsize=1)
def moteur():
    from sqlalchemy import create_engine
    return create_engine(f"postgresql+psycopg2://{config.PG_SUPERUSER}@{config.PG_HOST}:"
                         f"{config.PG_PORT}/{config.PG_DB}")


def pg_lire(sql, geom="geom"):
    if geom:
        return gpd.read_postgis(sql, moteur(), geom_col=geom)
    return pd.read_sql(sql, moteur())


def pg_ecrire(gdf, table, schema, mode="replace"):
    if isinstance(gdf, gpd.GeoDataFrame):
        gdf = gdf.rename_geometry("geom") if gdf.geometry.name != "geom" else gdf
        gdf.to_postgis(table, moteur(), schema=schema, if_exists=mode, index=False, chunksize=5000)
    else:
        gdf.to_sql(table, moteur(), schema=schema, if_exists=mode, index=False, chunksize=5000)
    log(f"  -> {schema}.{table} : {len(gdf)} lignes")
