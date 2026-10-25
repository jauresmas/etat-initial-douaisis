"""Étape 9 - Veille sur le référentiel : détecte les couches modifiées chez leur producteur.

Pour chaque couche du catalogue (meta.catalogue), la couche est de nouveau interrogée sur
l'emprise du référentiel ; son volume et son empreinte (somme de contrôle des géométries)
sont comparés à ceux de la base. Le résultat est consigné dans meta.journal_maj ; avec
--appliquer, les couches modifiées sont rechargées dans le schéma ref.

    python 09_veille.py               contrôle seul
    python 09_veille.py --appliquer   contrôle et mise à jour des couches modifiées
"""
import argparse
import importlib

import config
import pandas as pd

from etat_initial import sources
from outils import log, pg_ecrire, pg_lire, psql

referentiel = importlib.import_module("01_referentiel")


def main(appliquer=False):
    cat = pg_lire("SELECT code, libelle, nb_objets, empreinte FROM meta.catalogue "
                  "WHERE service IS NOT NULL ORDER BY code", geom=None)
    zone = pg_lire("SELECT ST_Buffer(geom, %s) AS geom FROM ref.epci" % config.MARGE_REFERENTIEL_M)
    zone = zone.geometry.iloc[0]
    lignes, modifiees = [], []
    for r in cat.itertuples():
        try:
            gdf = sources.couche_zone(r.code, zone)
        except Exception as err:
            lignes.append({"code": r.code, "nb_avant": r.nb_objets, "nb_apres": None, "changement": None,
                           "commentaire": f"service indisponible ({err.__class__.__name__})"})
            log(f"  {r.code} : service indisponible")
            continue
        emp = referentiel.empreinte(gdf)
        change = emp != r.empreinte
        lignes.append({"code": r.code, "nb_avant": r.nb_objets, "nb_apres": len(gdf), "changement": change,
                       "commentaire": (f"{len(gdf) - r.nb_objets:+d} objet(s)" if len(gdf) != r.nb_objets
                                       else "géométries modifiées") if change else "inchangée"})
        log(f"  {r.code} : {'MODIFIÉE' if change else 'inchangée'} ({r.nb_objets} -> {len(gdf)})")
        if change:
            modifiees.append((r.code, gdf, emp))
    journal = pd.DataFrame(lignes)
    pg_ecrire(journal, "journal_import", "meta")
    psql("INSERT INTO meta.journal_maj (code, nb_avant, nb_apres, changement, commentaire) "
         "SELECT code, nb_avant, nb_apres, changement, commentaire FROM meta.journal_import;"
         "DROP TABLE meta.journal_import;")
    log(f"{len(modifiees)} couche(s) modifiée(s) sur {len(cat)}")
    if appliquer and modifiees:
        for code, gdf, emp in modifiees:
            pg_ecrire(gdf, code, "ref")
            psql(f"ALTER TABLE ref.{code} ADD COLUMN gid serial PRIMARY KEY;"
                 f"CREATE INDEX ON ref.{code} USING gist (geom);"
                 f"GRANT SELECT ON ref.{code} TO lecteur;"
                 f"UPDATE meta.catalogue SET nb_objets = {len(gdf)}, empreinte = '{emp}', date_maj = now() "
                 f"WHERE code = '{code}';")
        psql("REFRESH MATERIALIZED VIEW criblage.resultat;")
        log("Couches rechargées et criblage recalculé")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--appliquer", action="store_true", help="recharge les couches modifiées")
    main(ap.parse_args().appliquer)
