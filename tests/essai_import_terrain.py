"""Essai de bout en bout du retour de terrain, sur la base du projet (à lancer après la chaîne).

    python tests/essai_import_terrain.py

Fabrique un GeoPackage de retour QField de test (trois observations, dont deux fautives, et
un habitat), le passe dans 10_import_terrain.py, vérifie ce qui entre en base et le rapport
d'anomalies, puis efface les relevés d'essai : la base livrée reste vide de relevés.
"""
import importlib.util
import sys
from datetime import date, timedelta
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "scripts"))

import config  # noqa: E402
import geopandas as gpd  # noqa: E402
import pandas as pd  # noqa: E402
from shapely.geometry import Point  # noqa: E402

from outils import pg_lire, psql  # noqa: E402


def main():
    spec = importlib.util.spec_from_file_location("imp", RACINE / "scripts" / "10_import_terrain.py")
    imp = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(imp)

    zip_geom = pg_lire("SELECT geom FROM etude.aire WHERE projet_id = 1 AND aire = 'zip'").geometry.iloc[0]
    centre = zip_geom.representative_point()
    loin = Point(centre.x + 5000, centre.y)  # hors de l'aire rapprochée
    gpkg = config.TRAVAIL / "essai_retour_qfield.gpkg"
    if gpkg.exists():
        gpkg.unlink()
    obs = gpd.GeoDataFrame({
        "uuid": ["00000000-0000-4000-8000-000000000001", "00000000-0000-4000-8000-000000000002",
                 "00000000-0000-4000-8000-000000000003"],
        "date_obs": [date.today(), date.today() + timedelta(days=2), date.today()],
        "observateur": ["Essai"] * 3, "groupe": ["Reptiles"] * 3,
        "taxon": ["Podarcis muralis", None, "Podarcis muralis"], "taxon_libre": [None, "Lézard indéterminé", None],
        "effectif": [2, 1, 1], "comportement": ["Repos"] * 3, "remarque": ["relevé d'essai"] * 3, "photo": [None] * 3},
        geometry=[centre, centre, loin], crs=2154)
    obs.to_file(gpkg, layer="observation", driver="GPKG")
    hab = gpd.GeoDataFrame({"uuid": ["00000000-0000-4000-8000-000000000011"], "date_obs": [date.today()],
                            "observateur": ["Essai"], "code_eunis": ["E5.1"], "etat_conservation": ["Moyen"],
                            "zone_humide": [False], "remarque": ["relevé d'essai"]},
                           geometry=[zip_geom.buffer(-10)], crs=2154)
    hab.to_file(gpkg, layer="habitat", driver="GPKG")

    imp.main(gpkg)
    n_obs = int(psql("SELECT count(*) FROM etude.observation WHERE observateur = 'Essai'"))
    n_hab = int(psql("SELECT count(*) FROM etude.habitat WHERE observateur = 'Essai'"))
    rapport = pd.read_csv(imp.RAPPORT, sep=";")
    print(f"en base : {n_obs} observation(s), {n_hab} habitat(s) ; anomalies : {sorted(set(rapport['motif']))}")
    assert n_obs == 1 and n_hab == 1
    assert {"date dans le futur", "hors de l'aire d'étude rapprochée"} <= set(rapport["motif"])
    # le déclencheur de la base refuse lui aussi une observation hors de l'aire rapprochée
    try:
        psql(f"INSERT INTO etude.observation (projet_id, uuid, date_obs, observateur, groupe, taxon, geom) "
             f"VALUES (1, gen_random_uuid(), current_date, 'Essai', 'Oiseaux', 'Alcedo atthis', "
             f"ST_SetSRID(ST_Point({loin.x}, {loin.y}), 2154))")
        raise AssertionError("le déclencheur aurait dû refuser l'observation")
    except RuntimeError as err:
        assert "hors de l'aire rapprochée" in str(err)
    psql("DELETE FROM etude.observation WHERE observateur = 'Essai'; DELETE FROM etude.habitat WHERE observateur = 'Essai';")
    imp.RAPPORT.unlink()
    gpkg.unlink()
    print("ESSAI RÉUSSI (relevés d'essai effacés)")


if __name__ == "__main__":
    main()
