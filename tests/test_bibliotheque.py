"""Tests de la bibliothèque etat_initial sur des données synthétiques (sans réseau).

    python -m pytest tests
"""
import importlib.util
import sys
from datetime import date, timedelta
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import LineString, Point, box

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))
sys.path.insert(0, str(RACINE / "scripts"))

from etat_initial import aires as A  # noqa: E402
from etat_initial import enjeux, ocsol, sources  # noqa: E402

CRS = "EPSG:2154"
ZIP = box(700_000, 7_020_000, 700_200, 7_020_200)  # 4 ha


@pytest.fixture
def aires():
    return A.aires_etude(ZIP, "photovoltaique")


# --- Aires d'étude --------------------------------------------------------------------------
def test_aires_emboitees(aires):
    assert list(aires["aire"]) == ["zip", "immediate", "rapprochee", "eloignee"]
    assert list(aires["distance_m"]) == [0, 200, 1000, 5000]
    geoms = list(aires.geometry)
    for petite, grande in zip(geoms, geoms[1:]):
        assert grande.buffer(1e-6).contains(petite)
    assert aires.loc[0, "surface_ha"] == pytest.approx(4.0)


def test_type_inconnu():
    with pytest.raises(ValueError):
        A.aires_etude(ZIP, "barrage")


def test_positionner(aires):
    objets = gpd.GeoDataFrame(geometry=[Point(700_100, 7_020_100), Point(700_350, 7_020_100),
                                        Point(700_900, 7_020_100), Point(704_000, 7_020_100),
                                        Point(710_000, 7_020_100)], crs=CRS)
    pos = A.positionner(objets, aires)
    assert list(pos["position"]) == ["zip", "immediate", "rapprochee", "eloignee", "hors"]
    assert pos["distance_zip_m"].iloc[0] == 0


# --- Découpage ----------------------------------------------------------------------------------
def test_meme_dimension_ecarte_les_fragments():
    # un polygone qui ne touche la zone que par un bord produit une ligne : elle est écartée
    zone = box(0, 0, 10, 10)
    voisin = gpd.GeoDataFrame(geometry=[box(10, 0, 20, 10), box(5, 5, 15, 15)], crs=CRS)
    dec = sources.decouper(voisin, zone)
    assert len(dec) == 1 and dec.geom_type.iloc[0] == "Polygon"
    assert dec["surface_totale_ha"].iloc[0] == pytest.approx(0.01)


# --- Occupation du sol ------------------------------------------------------------------------
@pytest.mark.parametrize("cs, us, attendu", [
    ("CS1.1.1.1", "US5", 1), ("CS2.2.1", "US1.1", 2), ("CS2.2.1", "US6.3", 3), ("CS2.1.1.1", "US1.2", 4),
    ("CS1.2.2", "US4.1.4", 5), ("CS1.2.1", "US6.2", 6), ("CS1.2.1", "US1.1", 2)])
def test_classe_ocsge(cs, us, attendu):
    assert ocsol.classe_ocsge(cs, us) == attendu


def test_classes_clc_et_oso():
    assert [ocsol.classe_clc(c) for c in ("112", "211", "231", "311", "321", "512", "332")] == [1, 2, 2, 4, 3, 5, 6]
    assert [ocsol.classe_oso(c) for c in (1, 6, 13, 16, 18, 23, 24)] == [1, 2, 2, 4, 3, 5, 1]


def test_accord_et_kappa():
    rng = np.random.default_rng(1)
    a = rng.integers(1, 7, size=(100, 100)).astype(np.uint8)
    masque = np.ones_like(a, dtype=bool)
    assert ocsol.accord(a, a, masque) == (1.0, 1.0)
    b = rng.integers(1, 7, size=(100, 100)).astype(np.uint8)
    po, kappa = ocsol.accord(a, b, masque)
    assert po == pytest.approx(1 / 6, abs=0.03) and abs(kappa) < 0.05  # accord dû au hasard


def test_carte_concordance():
    o = np.array([[1, 1, 2, 3]], dtype=np.uint8)
    c = np.array([[1, 2, 2, 4]], dtype=np.uint8)
    s = np.array([[1, 1, 3, 5]], dtype=np.uint8)
    assert ocsol.carte_concordance({"ocsge": o, "clc": c, "oso": s}).tolist() == [[3, 2, 1, 5]]


# --- Hiérarchisation des enjeux ----------------------------------------------------------------
def zonage(geom, nom):
    return gpd.GeoDataFrame({"code": ["X"], "nom": [nom], "couche": ["x"]}, geometry=[geom], crs=CRS)


def test_regles_de_distance(aires):
    d = {"znieff1": zonage(ZIP.buffer(50), "ZNIEFF qui recouvre la ZIP"),
         "zsc": zonage(box(703_000, 7_020_000, 703_500, 7_020_500), "Site Natura 2000 à 2,8 km")}
    enj = enjeux.hierarchiser(d, aires, {}).set_index("sujet")
    assert enj.loc["ZNIEFF de type I", "niveau"] == "Fort"
    assert enj.loc["Sites Natura 2000", "niveau"] == "Faible"
    assert enj.loc["ZNIEFF de type II", "niveau"] == "Nul"
    assert set(enj["niveau"]) <= set(enjeux.NIVEAUX)


def test_plu_qui_prevoit_le_projet(aires):
    zonage_plu = pd.DataFrame([{"aire": "Zone d'implantation potentielle", "zone": "UEpv",
                                "type": "Zone urbaine (U)", "intitule": "Secteur destiné à une centrale "
                                "photovoltaïque", "surface_ha": 4.0, "part": 1.0}])
    enj = enjeux.hierarchiser({}, aires, {"zonage": zonage_plu}).set_index("sujet")
    assert enj.loc["Document d'urbanisme", "niveau"] == "Faible"


# --- Contrôle des relevés de terrain ---------------------------------------------------------------
def charger_import():
    spec = importlib.util.spec_from_file_location("import_terrain", RACINE / "scripts" / "10_import_terrain.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_controle_des_releves(aires):
    imp = charger_import()
    aujourdhui = date.today()
    obs = gpd.GeoDataFrame({
        "uuid": ["a", "b", "c", "c", "e"],
        "date_obs": [aujourdhui, aujourdhui + timedelta(days=3), aujourdhui, aujourdhui, aujourdhui],
        "observateur": ["J. D.", "J. D.", "", "J. D.", "J. D."],
        "groupe": ["Oiseaux"] * 5, "taxon": ["Alcedo atthis"] * 5, "effectif": [1, 2, 1, 1, 0]},
        geometry=[Point(700_100, 7_020_100), Point(700_100, 7_020_100), Point(700_100, 7_020_100),
                  Point(700_100, 7_020_100), Point(720_000, 7_020_100)], crs=CRS)
    ok, ano = imp.controler(obs, ["uuid", "date_obs", "observateur", "groupe", "taxon"],
                            A.geom_aire(aires, "rapprochee"))
    assert list(ok["uuid"]) == ["a"]
    motifs = set(ano["motif"])
    assert {"date dans le futur", "champ obligatoire vide : observateur", "uuid en double dans le fichier",
            "hors de l'aire d'étude rapprochée", "effectif nul ou négatif"} <= motifs
