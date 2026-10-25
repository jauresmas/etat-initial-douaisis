"""Étape 10 - Retour du terrain : contrôle et import des relevés QField dans PostGIS.

Chaque relevé est contrôlé (champs obligatoires, date, position dans l'aire rapprochée,
doublons). Les relevés valides sont versés dans etude.observation et etude.habitat (une
nouvelle synchronisation met à jour un relevé déjà importé, reconnu par son uuid) ; les
autres sont listés dans un rapport d'anomalies à renvoyer à l'observateur.

    python 10_import_terrain.py [chemin du GeoPackage rapporté de QField]
"""
import sys
from datetime import date
from pathlib import Path

import config
import geopandas as gpd
import pandas as pd
import pyogrio

from outils import log, pg_ecrire, pg_lire, psql

DEFAUT = config.LIVRABLES / "06_Terrain" / "qfield" / "inventaire_terrain.gpkg"
RAPPORT = config.LIVRABLES / "06_Terrain" / "anomalies_import.csv"


def controler(gdf, obligatoires, aire):
    """Renvoie (valides, anomalies) ; une ligne d'anomalie par relevé et par motif."""
    motifs = []
    for i, r in gdf.iterrows():
        for champ in obligatoires:
            if pd.isna(r.get(champ)) or str(r.get(champ)).strip() == "":
                motifs.append((i, f"champ obligatoire vide : {champ}"))
        if pd.notna(r.get("date_obs")) and pd.to_datetime(r["date_obs"]).date() > date.today():
            motifs.append((i, "date dans le futur"))
        if r.geometry is None or r.geometry.is_empty:
            motifs.append((i, "géométrie absente"))
        elif not r.geometry.intersects(aire):
            motifs.append((i, "hors de l'aire d'étude rapprochée"))
        if "effectif" in gdf.columns and pd.notna(r.get("effectif")) and r["effectif"] <= 0:
            motifs.append((i, "effectif nul ou négatif"))
    doublons = gdf[gdf["uuid"].duplicated(keep="first")].index
    motifs += [(i, "uuid en double dans le fichier") for i in doublons]
    rejet = sorted({i for i, _ in motifs})
    anomalies = pd.DataFrame(motifs, columns=["ligne", "motif"])
    return gdf.drop(index=rejet), anomalies


def main(gpkg):
    gpkg = Path(gpkg)
    log(f"Relevés : {gpkg}")
    aire = pg_lire("SELECT geom FROM etude.aire WHERE projet_id = 1 AND aire = 'rapprochee'").geometry.iloc[0]
    couches = {n for n, _ in pyogrio.list_layers(gpkg)}
    bilan = []

    if "observation" in couches:
        obs = gpd.read_file(gpkg, layer="observation").to_crs(2154)
        obs["taxon"] = obs["taxon"].where(obs["taxon"].notna() & (obs["taxon"] != ""), obs.get("taxon_libre"))
        ok, ano = controler(obs, ["uuid", "date_obs", "observateur", "groupe", "taxon"], aire)
        bilan.append(ano.assign(couche="observation", uuid=obs.loc[ano["ligne"], "uuid"].values
                                if not ano.empty else None))
        if not ok.empty:
            ok = ok.assign(projet_id=1, statut_repro=None)[
                ["projet_id", "uuid", "date_obs", "observateur", "groupe", "taxon", "effectif", "comportement",
                 "statut_repro", "remarque", "photo", "geometry"]]
            pg_ecrire(ok, "observation_import", "etude")
            psql("""INSERT INTO etude.observation (projet_id, uuid, date_obs, observateur, groupe, taxon, effectif,
                        comportement, statut_repro, remarque, photo, geom)
                    SELECT projet_id, uuid::uuid, date_obs::date, observateur, groupe, taxon, effectif::int,
                           comportement, statut_repro, remarque, photo, ST_Force2D(geom)
                    FROM etude.observation_import
                    ON CONFLICT (uuid) DO UPDATE SET date_obs = EXCLUDED.date_obs, observateur = EXCLUDED.observateur,
                        groupe = EXCLUDED.groupe, taxon = EXCLUDED.taxon, effectif = EXCLUDED.effectif,
                        comportement = EXCLUDED.comportement, remarque = EXCLUDED.remarque,
                        photo = EXCLUDED.photo, geom = EXCLUDED.geom;
                    DROP TABLE etude.observation_import;""")
        log(f"  observations : {len(ok)} importée(s), {len(obs) - len(ok)} rejetée(s)")

    if "habitat" in couches:
        hab = gpd.read_file(gpkg, layer="habitat").to_crs(2154)
        ok, ano = controler(hab, ["uuid", "date_obs", "observateur", "code_eunis"], aire)
        bilan.append(ano.assign(couche="habitat", uuid=hab.loc[ano["ligne"], "uuid"].values
                                if not ano.empty else None))
        if not ok.empty:
            ok = ok.assign(projet_id=1)[["projet_id", "uuid", "date_obs", "observateur", "code_eunis",
                                         "etat_conservation", "zone_humide", "remarque", "geometry"]]
            pg_ecrire(ok, "habitat_import", "etude")
            psql("""INSERT INTO etude.habitat (projet_id, uuid, date_obs, observateur, code_eunis,
                        etat_conservation, zone_humide, remarque, geom)
                    SELECT projet_id, uuid::uuid, date_obs::date, observateur, code_eunis, etat_conservation,
                           zone_humide::boolean, remarque, ST_Multi(ST_Force2D(geom))
                    FROM etude.habitat_import
                    ON CONFLICT (uuid) DO UPDATE SET code_eunis = EXCLUDED.code_eunis,
                        etat_conservation = EXCLUDED.etat_conservation, zone_humide = EXCLUDED.zone_humide,
                        remarque = EXCLUDED.remarque, geom = EXCLUDED.geom;
                    DROP TABLE etude.habitat_import;""")
        log(f"  habitats : {len(ok)} importé(s), {len(hab) - len(ok)} rejeté(s)")

    bilan = pd.concat(bilan, ignore_index=True) if bilan else pd.DataFrame()
    if not bilan.empty:
        RAPPORT.parent.mkdir(parents=True, exist_ok=True)
        bilan.to_csv(RAPPORT, sep=";", index=False, encoding="utf-8-sig")
        log(f"  {len(bilan)} anomalie(s) : {RAPPORT.relative_to(config.RACINE)}")
    log(psql("SELECT (SELECT count(*) FROM etude.observation) || ' observations, ' || "
             "(SELECT count(*) FROM etude.habitat) || ' habitats en base'"))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else DEFAUT)
