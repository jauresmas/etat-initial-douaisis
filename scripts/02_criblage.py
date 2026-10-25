"""Étape 2 - Criblage des friches du territoire et choix du site étudié.

Le calcul est fait dans PostGIS (sql/03_criblage.sql) selon la grille de criblage.regle.
Le site retenu est la friche la mieux classée (ou celle imposée dans config.FRICHE_RETENUE) ;
il devient le projet n° 1 du schéma etude, ce qui calcule ses aires d'étude dans la base.

    python 02_criblage.py
"""
import config
from outils import ecrire, log, pg_lire, psql


def main():
    log("Criblage des friches (PostGIS)")
    psql(fichier=config.SQL / "03_criblage.sql")
    res = pg_lire("SELECT * FROM criblage.classement ORDER BY rang")
    for classe, n in res["classe"].value_counts().items():
        log(f"  {classe} : {n} friche(s)")
    ecrire(res, "criblage_friches", config.REFERENTIEL)
    regles = pg_lire("SELECT * FROM criblage.regle ORDER BY effet, critere", geom=None)
    ecrire(regles, "criblage_regles", config.REFERENTIEL)

    if config.FRICHE_RETENUE:
        site = res[res["site_id"] == config.FRICHE_RETENUE].iloc[0]
    else:
        site = res.iloc[0]
    log(f"Site retenu : {site['site_nom']} ({site['commune']}, {site['surface_ha']:.1f} ha, "
        f"classe « {site['classe']} », {site['points']} points)")
    log(f"  atouts : {site['atouts']}")
    log(f"  contraintes : {site['contraintes']}")
    print(res[["rang", "site_nom", "commune", "surface_ha", "classe", "points", "contraintes",
               "atouts"]].head(12).to_string(index=False))

    nom = f"{config.NOM_PROJET} - {site['site_nom']} ({site['commune']})"
    psql("TRUNCATE etude.projet RESTART IDENTITY CASCADE;"
         "INSERT INTO etude.projet (nom, type_projet, commentaire, geom) "
         f"SELECT {sql_texte(nom)}, '{config.TYPE_PROJET}', "
         f"{sql_texte('Étude indépendante sur données ouvertes. Friche Cartofriches' + site['site_id'])}, "
         f"ST_Multi(geom) FROM ref.friche WHERE site_id = '{site['site_id']}';")
    log(psql("SELECT string_agg(aire || ' ' || round(ST_Area(geom) / 10000) || ' ha', ', ' "
             "ORDER BY distance_m) FROM etude.aire WHERE projet_id = 1"))


def sql_texte(texte):
    return "'" + str(texte).replace("'", "''") + "'"


if __name__ == "__main__":
    main()
