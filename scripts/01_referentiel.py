"""Étape 1 - Référentiel territorial du Douaisis, chargé dans PostGIS avec son catalogue.

Le référentiel couvre Douaisis Agglo et une marge de 5 km. Il sert au criblage des
friches (étape 2) et constitue la base de veille de l'agence : chaque couche est
inscrite au catalogue (meta.catalogue) avec son volume et une empreinte de contrôle,
que 09_veille.py compare aux flux pour signaler les mises à jour.

    python 01_referentiel.py
"""
import hashlib

import config
import geopandas as gpd
import pandas as pd

from etat_initial import sources
from etat_initial.parametres import CATALOGUE, SERVICES
from outils import ecrire, log, pg_ecrire, psql

# Couches utiles au criblage et aux cartes de contexte (les couches de détail
# - parcelles, bâti, RPG, haies - sont chargées pour le seul site étudié)
CODES = ["znieff1", "znieff2", "zsc", "zps", "apb", "rnn", "rnr", "rb", "cen", "ramsar", "pnr",
         "zdh", "cours_eau", "plan_eau", "clc", "unesco_bien", "unesco_tampon", "terril_unesco",
         "ppr_inond", "ppr_mvt", "ppr_minier", "pprt", "sis", "ssp", "ligne_elec", "poste_elec",
         "parc_pv", "eolienne", "route", "voie_ferree"]


def empreinte(gdf):
    """Somme de contrôle des géométries : change dès qu'un objet est ajouté, retiré ou modifié."""
    h = hashlib.md5()
    for wkb in sorted(gdf.geometry.normalize().to_wkb()):
        h.update(wkb)
    return h.hexdigest()


def territoire():
    log(f"Territoire : {config.EPCI_NOM}")
    com = sources.wfs("geopf", "ADMINEXPRESS-COG.LATEST:commune",
                      cql=f"codes_siren_des_epci LIKE '%{config.EPCI_SIREN}%'")
    com = sources.nettoyer(com, ["code_insee", "nom_officiel", "population"], {"nom_officiel": "nom"})
    com = com.sort_values("code_insee").reset_index(drop=True)
    epci = gpd.GeoDataFrame({"siren": [config.EPCI_SIREN], "nom": [config.EPCI_NOM],
                             "nb_communes": [len(com)], "population": [int(com.population.sum())]},
                            geometry=[com.union_all()], crs=com.crs)
    return com, epci


def friches(zone_epci):
    log("Friches (Cartofriches, Cerema)")
    f = sources.wfs("geo2france", "cerema:cartofriche", bbox=zone_epci.bounds)
    f = sources.nettoyer(f, ["site_id", "site_nom", "site_type", "site_statut", "comm_nom", "comm_insee",
                             "activite_libelle", "urba_zone_type", "urba_zone_lib", "urba_doc_type",
                             "site_numero_basias", "site_numero_basol", "sol_pollution_existe",
                             "proprio_type", "source_nom", "site_url"],
                         {"comm_nom": "commune", "comm_insee": "code_insee"})
    f["geometry"] = f.geometry.make_valid()
    f = f[f.geom_type.isin(["Polygon", "MultiPolygon"])].copy()
    # friches dont le centre est dans l'EPCI (l'OCS GE départementale ne couvre pas les voisines)
    f = f[f.geometry.representative_point().within(zone_epci)].copy()
    # Cartofriches agrège plusieurs inventaires (BASIAS, observatoires locaux) : un même site peut y
    # figurer deux fois, sous deux noms, avec des contours presque identiques. Deux fiches dont les
    # contours se recouvrent à plus de 90 % sont un doublon ; on garde la plus renseignée, de
    # préférence celle qui décrit l'ancienne activité.
    f = f.drop_duplicates("site_id").reset_index(drop=True)
    f["priorite"] = f["activite_libelle"].notna().astype(int) * 100 + f.notna().sum(axis=1)
    paires = gpd.sjoin(f[["geometry"]], f[["geometry"]], predicate="intersects")
    paires = paires[paires.index < paires["index_right"]]
    retirer = set()
    for i, j in zip(paires.index, paires["index_right"]):
        a, b = f.geometry[i], f.geometry[j]
        if a.intersection(b).area / a.union(b).area > 0.90:
            retirer.add(j if f.at[i, "priorite"] >= f.at[j, "priorite"] else i)
    avant = len(f)
    f = f.drop(index=sorted(retirer)).drop(columns="priorite")
    log(f"  {avant} friches dans l'EPCI, {len(retirer)} doublon(s) retiré(s)")
    f["surface_ha"] = (f.area / 10_000).round(2)
    # commune de situation recalculée (le champ source donne parfois la commune voisine)
    com = sources.wfs("geopf", "ADMINEXPRESS-COG.LATEST:commune", bbox=zone_epci.bounds)[["nom_officiel",
                                                                                          "geometry"]]
    pts = f.geometry.representative_point().to_frame("geometry").set_crs(f.crs)
    f["commune"] = gpd.sjoin(pts, com, predicate="within")["nom_officiel"].reindex(f.index).fillna(
        f["commune"].str.title())
    return f.sort_values("site_id").reset_index(drop=True)


def ocsge(zone):
    """Millésime de référence et différentiel de l'OCS GE, découpés sur le référentiel."""
    gpkg = sources.ocsge_gpkg(config.OCSGE[config.OCSGE_ANNEE], config.BRUT / "ocsge")
    occ = sources.lire_ocsge(gpkg, zone)[["code_cs", "code_us", "geometry"]]
    diff = sources.lire_ocsge(sources.ocsge_gpkg(config.OCSGE["diff"], config.BRUT / "ocsge"), zone)
    diff = diff.rename(columns=str.lower)[["cs_2021", "us_2021", "cs_2025", "us_2025", "geometry"]]
    return occ, diff


def main():
    com, epci = territoire()
    zone = epci.geometry.iloc[0].buffer(config.MARGE_REFERENTIEL_M)
    ecrire(com, "commune", config.REFERENTIEL)
    ecrire(epci, "epci", config.REFERENTIEL)
    contexte = sources.communes(zone)
    ecrire(contexte, "commune_contexte", config.REFERENTIEL)

    fr = friches(epci.geometry.iloc[0])
    ecrire(fr, "friche", config.REFERENTIEL)

    log("Couches du catalogue sur le référentiel")
    couches = {}
    for code in CODES:
        try:
            gdf = sources.couche_zone(code, zone)
        except Exception as err:
            log(f"  {code} : ÉCHEC ({err.__class__.__name__}) - couche ignorée")
            continue
        log(f"  {code} : {len(gdf)} objet(s)")
        couches[code] = gdf
        ecrire(gdf, code, config.REFERENTIEL)

    log("OCS GE (millésime de référence et différentiel)")
    occ, diff = ocsge(zone)
    ecrire(occ, f"ocsge_{config.OCSGE_ANNEE}", config.REFERENTIEL)
    ecrire(diff, "ocsge_diff_2021_2025", config.REFERENTIEL)

    log("Chargement dans PostGIS (schéma ref)")
    psql("DROP SCHEMA IF EXISTS ref CASCADE; CREATE SCHEMA ref;"
         "COMMENT ON SCHEMA ref IS 'Référentiel territorial : couches ouvertes découpées sur le "
         "territoire et sa marge de 5 km';")
    tables = {"commune": com, "epci": epci, "commune_contexte": contexte, "friche": fr,
              f"ocsge_{config.OCSGE_ANNEE}": occ, "ocsge_diff_2021_2025": diff, **couches}
    for table, gdf in tables.items():
        pg_ecrire(gdf, table, "ref")

    lignes = []
    for table, gdf in tables.items():
        fiche = CATALOGUE.get(table, {})
        lignes.append({"code": table, "libelle": fiche.get("libelle", {
                           "commune": "Communes de Douaisis Agglo (ADMIN EXPRESS COG)",
                           "epci": "Périmètre de Douaisis Agglo", "commune_contexte": "Communes du référentiel",
                           "friche": "Friches recensées (Cartofriches)",
                           f"ocsge_{config.OCSGE_ANNEE}": f"OCS GE {config.OCSGE_ANNEE}",
                           "ocsge_diff_2021_2025": "OCS GE, différentiel 2021-2025"}.get(table, table)),
                       "theme": fiche.get("theme", "contexte" if "commun" in table or table == "epci"
                                          else "sol" if "ocsge" in table else "foncier"),
                       "famille": fiche.get("famille"),
                       "producteur": SERVICES[fiche["service"]]["producteur"] if fiche else
                       ("Cerema" if table == "friche" else "IGN"),
                       "service": fiche.get("service"), "couche_source": fiche.get("couche"),
                       "table_ref": f"ref.{table}", "nb_objets": len(gdf), "empreinte": empreinte(gdf),
                       "date_maj": pd.Timestamp.now(tz="Europe/Paris")})
    # table d'import fusionnée dans meta.catalogue par 02_referentiel.sql (le journal de veille
    # des couches déjà connues est conservé)
    pg_ecrire(pd.DataFrame(lignes), "catalogue_import", "meta")
    psql(fichier=config.SQL / "02_referentiel.sql")
    log(psql("SELECT count(*) || ' couches, ' || sum(nb_objets) || ' objets' FROM meta.catalogue"))


if __name__ == "__main__":
    main()
