r"""Étape 6 bis - Modèles QGIS des calculs clés et contrôle croisé avec la chaîne Python.

    "C:\Program Files\QGIS 3.34.12\bin\python-qgis-ltr.bat" 06b_modeles_qgis.py

Les traitements de l'étude se font avec les outils de la boîte à outils de QGIS, enchaînés dans
trois modèles du modeleur graphique (fichiers .model3, aussi intégrés au projet) :

  1. Aires d'étude d'un projet : tampons de la zone d'implantation potentielle ;
  2. Position des zonages : distance de chaque zonage à la ZIP et aire d'étude atteinte ;
  3. Occupation du sol par aire d'étude : surfaces OCS GE par aire et par poste de couverture.

La chaîne Python reproduit ces calculs pour relancer l'étude en une commande. Ce script fait
tourner les modèles sur les données livrées et compare leurs résultats à ceux de Python ; le
bilan (data/interim/controle_qgis_python.json) est repris dans la note méthodologique.
"""
import json
import os
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))
sys.path.insert(0, str(RACINE / "scripts"))

from qgis.core import QgsApplication  # noqa: E402

app = QgsApplication([], True)
app.initQgis()
sys.path.insert(0, str(Path(QgsApplication.prefixPath()) / "python" / "plugins"))
import processing  # noqa: E402
from processing.core.Processing import Processing  # noqa: E402

Processing.initialize()

from qgis.core import (QgsProcessing, QgsProcessingModelAlgorithm, QgsProcessingModelChildAlgorithm,  # noqa: E402
                       QgsProcessingModelChildParameterSource as Source, QgsProcessingModelOutput,
                       QgsProcessingModelParameter, QgsProcessingParameterNumber,
                       QgsProcessingParameterVectorLayer, QgsProject, QgsVectorLayer)
from qgis.PyQt.QtCore import QPointF  # noqa: E402

import config  # noqa: E402

SIG = config.LIVRABLES / "02_Donnees_SIG"
GPKG = SIG / "etat_initial.gpkg"
QGZ = SIG / "etat_initial.qgz"
DOSSIER = SIG / "modeles"
GROUPE = "État initial de l'environnement"
AUTEUR = config.AUTEUR


def couche(nom):
    return f"{GPKG}|layername={nom}"


def parametre(modele, definition, x, y):
    composant = QgsProcessingModelParameter(definition.name())
    composant.setPosition(QPointF(x, y))
    modele.addModelParameter(definition, composant)


def etape(modele, identifiant, algo, description, x, y, sources, sorties=None):
    """Ajoute un algorithme enfant ; sources : {paramètre: Source}, sorties : {nom: sortie de l'algorithme}."""
    enfant = QgsProcessingModelChildAlgorithm(algo)
    enfant.setChildId(identifiant)
    enfant.setDescription(description)
    enfant.setPosition(QPointF(x, y))
    for nom, source in sources.items():
        enfant.addParameterSources(nom, [source])
    if sorties:
        resultats = {}
        for nom, sortie in sorties.items():
            o = QgsProcessingModelOutput(nom)
            o.setDescription(nom)
            o.setChildOutputName(sortie)
            o.setChildId(identifiant)
            o.setPosition(QPointF(x + 260, y + 45))
            resultats[nom] = o
        enfant.setModelOutputs(resultats)
    modele.addChildAlgorithm(enfant)


def sortie_de(identifiant, nom="OUTPUT"):
    return Source.fromChildOutput(identifiant, nom)


def distances(modele, x):
    for nom, lib, val, y in (("immediate", "Aire immédiate (m)", 200, 50), ("rapprochee", "Aire rapprochée (m)", 1000, 110),
                             ("eloignee", "Aire éloignée (m)", 5000, 170)):
        parametre(modele, QgsProcessingParameterNumber(nom, lib, QgsProcessingParameterNumber.Double,
                                                       defaultValue=val, minValue=0), x, y)


# --- Modèle 1 : aires d'étude ----------------------------------------------------------------
def modele_aires():
    m = QgsProcessingModelAlgorithm("Aires d'étude d'un projet", GROUPE)
    parametre(m, QgsProcessingParameterVectorLayer("zip", "Zone d'implantation potentielle",
                                                   [QgsProcessing.TypeVectorPolygon], defaultValue=couche("projet")),
              120, 50)
    distances(m, 480)
    for i, (aire, lib) in enumerate((("immediate", "Aire d'étude immédiate"), ("rapprochee", "Aire d'étude rapprochée"),
                                     ("eloignee", "Aire d'étude éloignée"))):
        etape(m, f"tampon_{aire}", "native:buffer", f"Tampon : {lib.lower()}", 120 + i * 260, 260, {
            "INPUT": Source.fromModelParameter("zip"),
            "DISTANCE": Source.fromModelParameter(aire),
            "SEGMENTS": Source.fromStaticValue(16),
            "DISSOLVE": Source.fromStaticValue(True),
        }, {lib: "OUTPUT"})
    m.setHelpContent({"ALG_DESC": "Calcule les aires d'étude immédiate, rapprochée et éloignée autour de la zone "
                                  "d'implantation potentielle. Distances par défaut : centrale photovoltaïque au sol.",
                      "ALG_CREATOR": AUTEUR})
    return m


# --- Modèle 2 : position des zonages ------------------------------------------------------------
def modele_position():
    m = QgsProcessingModelAlgorithm("Position des zonages par rapport au projet", GROUPE)
    parametre(m, QgsProcessingParameterVectorLayer("zonages", "Zonages (ZNIEFF, Natura 2000, PPR...)",
                                                   [QgsProcessing.TypeVectorPolygon], defaultValue=couche("znieff1")),
              120, 50)
    parametre(m, QgsProcessingParameterVectorLayer("zip", "Zone d'implantation potentielle",
                                                   [QgsProcessing.TypeVectorPolygon], defaultValue=couche("projet")),
              300, 50)
    distances(m, 520)
    etape(m, "proche", "native:joinbynearest", "Distance de chaque zonage à la ZIP", 200, 200, {
        "INPUT": Source.fromModelParameter("zonages"),
        "INPUT_2": Source.fromModelParameter("zip"),
        "FIELDS_TO_COPY": Source.fromStaticValue(["fid"]),
        "DISCARD_NONMATCHING": Source.fromStaticValue(False),
        "PREFIX": Source.fromStaticValue("zip_"),
        "NEIGHBORS": Source.fromStaticValue(1),
    })
    etape(m, "position", "native:fieldcalculator", "Aire d'étude atteinte", 200, 320, {
        "INPUT": sortie_de("proche"),
        "FIELD_NAME": Source.fromStaticValue("position"),
        "FIELD_TYPE": Source.fromStaticValue(2),
        "FIELD_LENGTH": Source.fromStaticValue(12),
        "FORMULA": Source.fromExpression(
            "'CASE WHEN \"distance\" <= 0 THEN ''zip'' WHEN \"distance\" <= ' || to_string(@immediate) || "
            "' THEN ''immediate'' WHEN \"distance\" <= ' || to_string(@rapprochee) || "
            "' THEN ''rapprochee'' WHEN \"distance\" <= ' || to_string(@eloignee) || "
            "' THEN ''eloignee'' ELSE ''hors'' END'"),
    }, {"Zonages positionnés": "OUTPUT"})
    m.setHelpContent({"ALG_DESC": "Pour chaque zonage, distance à la zone d'implantation potentielle (0 si le zonage "
                                  "la recoupe) et aire d'étude atteinte : zip, immédiate, rapprochée, éloignée ou hors.",
                      "ALG_CREATOR": AUTEUR})
    return m


# --- Modèle 3 : occupation du sol par aire --------------------------------------------------------
def modele_occupation():
    m = QgsProcessingModelAlgorithm("Occupation du sol par aire d'étude", GROUPE)
    parametre(m, QgsProcessingParameterVectorLayer("ocsge", "Occupation du sol (OCS GE)",
                                                   [QgsProcessing.TypeVectorPolygon], defaultValue=couche("ocsge")),
              120, 50)
    parametre(m, QgsProcessingParameterVectorLayer("aires", "Aires d'étude (champ « aire »)",
                                                   [QgsProcessing.TypeVectorPolygon], defaultValue=couche("aire_etude")),
              400, 50)
    etape(m, "decoupe", "native:intersection", "Découper l'occupation du sol par les aires", 260, 170, {
        "INPUT": Source.fromModelParameter("ocsge"),
        "OVERLAY": Source.fromModelParameter("aires"),
        "INPUT_FIELDS": Source.fromStaticValue(["code_cs", "code_us"]),
        "OVERLAY_FIELDS": Source.fromStaticValue(["aire"]),
    })
    etape(m, "surface", "native:fieldcalculator", "Surface de chaque morceau (ha)", 260, 280, {
        "INPUT": sortie_de("decoupe"),
        "FIELD_NAME": Source.fromStaticValue("surface_ha"),
        "FIELD_TYPE": Source.fromStaticValue(0),
        "FIELD_LENGTH": Source.fromStaticValue(12),
        "FIELD_PRECISION": Source.fromStaticValue(4),
        "FORMULA": Source.fromStaticValue("$area / 10000"),
    })
    etape(m, "bilan", "qgis:statisticsbycategories", "Total par aire et par couverture", 260, 390, {
        "INPUT": sortie_de("surface"),
        "VALUES_FIELD_NAME": Source.fromStaticValue("surface_ha"),
        "CATEGORIES_FIELD_NAME": Source.fromStaticValue(["aire", "code_cs"]),
    }, {"Occupation du sol par aire (ha)": "OUTPUT"})
    m.setHelpContent({"ALG_DESC": "Surface de chaque poste de couverture de l'OCS GE dans chaque aire d'étude "
                                  "(champ sum du tableau de sortie, en hectares).", "ALG_CREATOR": AUTEUR})
    return m


# --- Contrôle croisé QGIS / Python -----------------------------------------------------------------
def lire_table(nom):
    lyr = QgsVectorLayer(couche(nom), nom, "ogr")
    return [f.attributes() for f in lyr.getFeatures()], [x.name() for x in lyr.fields()]


def comme_dicts(lyr):
    noms = [x.name() for x in lyr.fields()]
    return [dict(zip(noms, f.attributes())) for f in lyr.getFeatures()]


def lancer(modele, parametres):
    """Exécute un modèle ; sorties en couches temporaires, renvoyées par leur libellé."""
    sorties = {d.description(): d.name() for d in modele.destinationParameterDefinitions()}
    res = processing.run(modele, {**parametres, **{nom: "TEMPORARY_OUTPUT" for nom in sorties.values()}})
    couches = {}
    for lib, nom in sorties.items():
        lyr = res[nom]
        couches[lib] = lyr if not isinstance(lyr, str) else QgsVectorLayer(lyr, lib, "ogr")
    return couches


def controler(modeles):
    bilan = {}
    # 1. aires d'étude : surfaces des tampons QGIS / aires calculées par Python
    res = lancer(modeles["aires"], {"zip": couche("projet"), "immediate": 200, "rapprochee": 1000, "eloignee": 5000})
    py = {d["aire"]: d["surface_ha"] for d in comme_dicts(QgsVectorLayer(couche("aire_etude"), "a", "ogr"))}
    ecarts = []
    for aire, sortie in (("immediate", "Aire d'étude immédiate"), ("rapprochee", "Aire d'étude rapprochée"),
                         ("eloignee", "Aire d'étude éloignée")):
        lyr = res[sortie]
        s = sum(f.geometry().area() for f in lyr.getFeatures()) / 10_000
        ecarts.append(abs(s - py[aire]))
    bilan["aires"] = {"nb": 3, "ecart_max_ha": round(max(ecarts), 3)}

    # 2. position des zonages : distances QGIS / inventaire Python (ZNIEFF et zonages patrimoniaux)
    zon_py = comme_dicts(QgsVectorLayer(couche("t_zonages"), "z", "ogr"))
    ecarts, accords, n = [], 0, 0
    for nom in ("znieff1", "unesco_bien", "unesco_tampon", "pprt"):
        if not QgsVectorLayer(couche(nom), nom, "ogr").isValid():
            continue
        lyr = lancer(modeles["position"], {"zonages": couche(nom), "zip": couche("projet"), "immediate": 200,
                                           "rapprochee": 1000, "eloignee": 5000})["Zonages positionnés"]
        for f in lyr.getFeatures():
            ident = f["code"] if "code" in f.fields().names() else None
            nomf = f["nom"] if "nom" in f.fields().names() else None
            cand = [z for z in zon_py if z["code_couche"] == nom and
                    ((ident and z["identifiant"] == ident) or (nomf and z["nom"] == nomf))]
            if not cand:
                continue
            z = min(cand, key=lambda c: abs(c["distance_zip_m"] - f["distance"]))
            ecarts.append(abs(z["distance_zip_m"] - f["distance"]))
            accords += z["position"] == f["position"]
            n += 1
    bilan["zonages"] = {"nb": n, "ecart_max_m": round(max(ecarts), 1) if ecarts else None,
                        "positions_identiques": accords}

    # 3. occupation du sol : surfaces par aire et par couverture QGIS / tableau Python
    lyr = lancer(modeles["occupation"], {"ocsge": couche("ocsge"), "aires": couche("aire_etude")})[
        "Occupation du sol par aire (ha)"]
    qg = {(d["aire"], d["code_cs"]): d["sum"] for d in comme_dicts(lyr)}
    libelles = {"Zone d'implantation potentielle": "zip", "Aire d'étude immédiate": "immediate",
                "Aire d'étude rapprochée": "rapprochee"}
    py = {}
    for d in comme_dicts(QgsVectorLayer(couche("t_occupation"), "o", "ogr")):
        cle = (libelles[d["aire"]], d["code_cs"])
        py[cle] = py.get(cle, 0) + d["surface_ha"]
    communs = [k for k in py if k in qg]
    ecarts = [abs(py[k] - qg[k]) for k in communs]
    total = sum(py[k] for k in communs)
    bilan["occupation"] = {"nb": len(communs), "ecart_max_ha": round(max(ecarts), 3),
                           "ecart_total_pct": round(100 * sum(ecarts) / total, 3) if total else None}
    return bilan


def main():
    DOSSIER.mkdir(parents=True, exist_ok=True)
    fabriques = {"aires": (modele_aires, "aires_etude.model3"), "position": (modele_position, "position_zonages.model3"),
                 "occupation": (modele_occupation, "occupation_sol_par_aire.model3")}
    modeles = {}
    for cle, (fabrique, fichier) in fabriques.items():
        m = fabrique()
        m.updateDestinationParameters()
        m.toFile(str(DOSSIER / fichier))
        modeles[cle] = m
        print(f"Modèle : modeles/{fichier}")
    bilan = controler(modeles)
    print(json.dumps(bilan, ensure_ascii=False))
    (config.TRAVAIL / "controle_qgis_python.json").write_text(json.dumps(bilan, ensure_ascii=False, indent=1),
                                                              encoding="utf-8")
    # intégration au projet QGIS livré (boîte à outils > Modèles du projet)
    projet = QgsProject.instance()
    projet.read(str(QGZ))
    fournisseur = QgsApplication.processingRegistry().providerById("project")
    if fournisseur is not None:
        for m in modeles.values():
            fournisseur.add_model(m)
    projet.write(str(QGZ))
    print(f"Modèles intégrés au projet : {QGZ.name}")


main()
os._exit(0)  # QGIS plante parfois à la fermeture après Processing : sortie directe
