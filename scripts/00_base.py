"""Étape 0 - Instance PostgreSQL/PostGIS du projet, base et schémas.

L'instance est locale (port 5435, connexion sans mot de passe depuis la machine) ;
ses fichiers sont dans data/pgdata et ne sont pas versionnés.

    python 00_base.py            démarre l'instance (la crée si besoin)
    python 00_base.py --neuve    recrée la base vide (schémas, rôles, catalogue)
"""
import argparse
import subprocess
import time

import config
from outils import log, pg_env, psql

PG_CTL = str(config.PG_BIN / "pg_ctl.exe")


def instance():
    if not (config.PG_DATA / "PG_VERSION").exists():
        log(f"Création de l'instance PostgreSQL ({config.PG_DATA})")
        subprocess.run([str(config.PG_BIN / "initdb.exe"), "-D", str(config.PG_DATA),
                        "-U", config.PG_SUPERUSER, "-A", "trust", "-E", "UTF8",
                        "--locale=C", "--lc-messages=C"], check=True, capture_output=True)
        conf = config.PG_DATA / "postgresql.conf"
        conf.write_text(conf.read_text() + f"\nport = {config.PG_PORT}\n"
                        "listen_addresses = 'localhost'\nshared_buffers = 512MB\n"
                        "work_mem = 64MB\nmaintenance_work_mem = 512MB\n"
                        "timezone = 'Europe/Paris'\n")
    etat = subprocess.run([PG_CTL, "status", "-D", str(config.PG_DATA)], capture_output=True)
    if etat.returncode != 0:
        log(f"Démarrage de PostgreSQL sur le port {config.PG_PORT}")
        # sorties vers NUL : le serveur hérite des descripteurs, les capturer
        # bloquerait le script jusqu'à l'arrêt de PostgreSQL
        subprocess.run([PG_CTL, "start", "-D", str(config.PG_DATA), "-w",
                        "-l", str(config.PG_DATA.parent / "postgresql.log")],
                       check=True, env=pg_env(), stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
        time.sleep(1)


def base_neuve():
    log(f"Base {config.PG_DB} : création")
    psql(f"DROP DATABASE IF EXISTS {config.PG_DB} WITH (FORCE)", base="postgres")
    psql(f"CREATE DATABASE {config.PG_DB} ENCODING 'UTF8' TEMPLATE template0", base="postgres")
    psql(fichier=config.SQL / "01_structure.sql")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--neuve", action="store_true", help="recrée la base vide")
    args = p.parse_args()
    instance()
    existe = psql(f"SELECT 1 FROM pg_database WHERE datname = '{config.PG_DB}'", base="postgres")
    if args.neuve or not existe:
        base_neuve()
    log(psql("SELECT 'PostgreSQL ' || current_setting('server_version') || ', PostGIS ' || postgis_lib_version()"))
