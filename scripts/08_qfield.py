"""Étape 8 - Projet QField des inventaires de terrain (à lancer avec le Python de QGIS).

    "C:\\Program Files\\QGIS 3.34.12\\bin\\python-qgis-ltr.bat" 08_qfield.py

Produit livrables/06_Terrain/qfield/ : un GeoPackage de saisie (observations, habitats),
la liste des espèces déjà connues autour du site (saisie semi-automatique), le périmètre et
les enjeux en consultation, et un projet QGIS dont les formulaires sont prêts pour QField
(listes de valeurs, valeurs par défaut, contraintes, photo). Le dossier se copie tel quel sur
la tablette, ou s'empaquette avec l'extension QFieldSync. Les relevés reviennent en base par
10_import_terrain.py.
"""
import sqlite3
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))
sys.path.insert(0, str(RACINE / "scripts"))

from qgis.core import QgsApplication  # noqa: E402

app = QgsApplication([], True)
app.initQgis()

from qgis.core import (QgsCoordinateReferenceSystem, QgsDefaultValue, QgsEditFormConfig,  # noqa: E402
                       QgsEditorWidgetSetup, QgsField, QgsFieldConstraints, QgsFields, QgsProject,
                       QgsVectorFileWriter, QgsVectorLayer, QgsWkbTypes, QgsCoordinateTransformContext,
                       QgsAttributeEditorContainer, QgsAttributeEditorField)
from qgis.PyQt.QtCore import QVariant  # noqa: E402

import config  # noqa: E402
from etat_initial import atlas_qgis as AQ  # noqa: E402

SOURCE = config.LIVRABLES / "02_Donnees_SIG" / "etat_initial.gpkg"
DOSSIER = config.LIVRABLES / "06_Terrain" / "qfield"
GPKG = DOSSIER / "inventaire_terrain.gpkg"
QGZ = DOSSIER / "inventaire_terrain.qgz"

GROUPES = ["Oiseaux", "Chiroptères", "Mammifères terrestres", "Amphibiens", "Reptiles", "Odonates",
           "Lépidoptères", "Orthoptères", "Autres insectes", "Flore", "Autre"]
COMPORTEMENTS = ["Nicheur certain", "Nicheur probable", "Nicheur possible", "Chant ou cri",
                 "Alimentation", "Repos", "Passage ou transit", "Individu mort", "Indice de présence",
                 "Plante en fleur", "Plante végétative"]
# Habitats EUNIS courants sur les friches industrielles et leurs abords (Nord)
EUNIS = {"C1.3": "Lacs, étangs et mares eutrophes permanents", "C3.21": "Phragmitaies",
         "D5.1": "Roselières normalement sans eau libre", "E2.1": "Pâturages permanents mésotrophes",
         "E2.2": "Prairies de fauche de basse et moyenne altitudes",
         "E2.6": "Prairies améliorées, réensemencées et fortement fertilisées",
         "E5.1": "Végétations herbacées anthropiques",
         "E5.4": "Lisières et prairies humides ou mouilleuses à grandes herbacées",
         "F3.11": "Fourrés médio-européens sur sols riches", "F9.2": "Saussaies marécageuses",
         "FA": "Haies", "G1.A1": "Boisements sur sols eutrophes et mésotrophes à chênes, frênes et charmes",
         "G1.C1": "Plantations de peupliers", "G5.6": "Stades initiaux et régénérations forestières",
         "H5.6": "Zones piétinées", "I1.5": "Friches, jachères ou terres arables récemment abandonnées",
         "J1.4": "Sites industriels et commerciaux en activité", "J1.5": "Constructions abandonnées",
         "J4.2": "Réseaux routiers", "J6": "Dépôts de déchets"}
ETATS = ["Bon", "Moyen", "Dégradé", "Non évalué"]


def couche_vide(nom, geom, champs):
    f = QgsFields()
    for n, t, l in champs:
        f.append(QgsField(n, t, len=l))
    opts = QgsVectorFileWriter.SaveVectorOptions()
    opts.driverName = "GPKG"
    opts.layerName = nom
    opts.actionOnExistingFile = (QgsVectorFileWriter.CreateOrOverwriteLayer if GPKG.exists()
                                 else QgsVectorFileWriter.CreateOrOverwriteFile)
    w = QgsVectorFileWriter.create(str(GPKG), f, geom, QgsCoordinateReferenceSystem("EPSG:2154"),
                                   QgsCoordinateTransformContext(), opts)
    del w


def liste(lyr, champ, valeurs):
    idx = lyr.fields().indexOf(champ)
    lyr.setEditorWidgetSetup(idx, QgsEditorWidgetSetup("ValueMap", {"map": [{v: v} for v in valeurs]}))


def defaut(lyr, champ, expression, a_la_mise_a_jour=False):
    lyr.setDefaultValueDefinition(lyr.fields().indexOf(champ), QgsDefaultValue(expression, a_la_mise_a_jour))


def obligatoire(lyr, champ, expression=None, message=""):
    idx = lyr.fields().indexOf(champ)
    lyr.setFieldConstraint(idx, QgsFieldConstraints.ConstraintNotNull, QgsFieldConstraints.ConstraintStrengthHard)
    if expression:
        lyr.setConstraintExpression(idx, expression, message)
        lyr.setFieldConstraint(idx, QgsFieldConstraints.ConstraintExpression,
                               QgsFieldConstraints.ConstraintStrengthHard)


def onglets(lyr, plan):
    """plan : [(titre de l'onglet, [champs])] ; formulaire en onglets, lisible sur téléphone."""
    cfg = lyr.editFormConfig()
    cfg.setLayout(QgsEditFormConfig.TabLayout)
    racine = cfg.invisibleRootContainer()
    racine.clear()
    for titre, champs in plan:
        onglet = QgsAttributeEditorContainer(titre, racine)
        for c in champs:
            onglet.addChildElement(QgsAttributeEditorField(c, lyr.fields().indexOf(c), onglet))
        racine.addChildElement(onglet)
    lyr.setEditFormConfig(cfg)


def main():
    DOSSIER.mkdir(parents=True, exist_ok=True)
    if GPKG.exists():
        GPKG.unlink()
    S, I, D, B = QVariant.String, QVariant.Int, QVariant.Date, QVariant.Bool
    couche_vide("observation", QgsWkbTypes.Point,
                [("uuid", S, 38), ("date_obs", D, 0), ("observateur", S, 80), ("groupe", S, 40),
                 ("taxon", S, 120), ("taxon_libre", S, 120), ("effectif", I, 0), ("comportement", S, 40),
                 ("remarque", S, 500), ("photo", S, 255)])
    couche_vide("habitat", QgsWkbTypes.MultiPolygon,
                [("uuid", S, 38), ("date_obs", D, 0), ("observateur", S, 80), ("code_eunis", S, 10),
                 ("etat_conservation", S, 20), ("zone_humide", B, 0), ("remarque", S, 500)])
    # référentiels en consultation, copiés depuis les données de l'étude
    with sqlite3.connect(SOURCE) as cx:
        especes = cx.execute("SELECT nom_scientifique, coalesce(nom_francais, ''), groupe, "
                             "patrimoniale FROM t_especes ORDER BY nom_francais").fetchall()
    with sqlite3.connect(GPKG) as cx:
        cx.execute("CREATE TABLE taxon_connu (fid INTEGER PRIMARY KEY, nom TEXT, nom_scientifique TEXT, "
                   "groupe TEXT, patrimoniale INTEGER)")
        cx.executemany("INSERT INTO taxon_connu (nom, nom_scientifique, groupe, patrimoniale) VALUES (?, ?, ?, ?)",
                       [((f"{fr} ({sc})" if fr else sc), sc, g, int(p)) for sc, fr, g, p in especes])
        cx.execute("INSERT INTO gpkg_contents (table_name, data_type, identifier) "
                   "VALUES ('taxon_connu', 'attributes', 'taxon_connu')")
    for nom in ("projet", "aire_etude", "enjeu"):
        src = QgsVectorLayer(f"{SOURCE}|layername={nom}", nom, "ogr")
        opts = QgsVectorFileWriter.SaveVectorOptions()
        opts.driverName, opts.layerName = "GPKG", nom  # mêmes noms : la charte de l'atlas s'applique
        opts.actionOnExistingFile = QgsVectorFileWriter.CreateOrOverwriteLayer
        QgsVectorFileWriter.writeAsVectorFormatV3(src, str(GPKG), QgsCoordinateTransformContext(), opts)

    projet = QgsProject.instance()
    projet.clear()
    projet.setCrs(QgsCoordinateReferenceSystem("EPSG:3857"))  # fond de plan en tuiles, sans reprojection
    projet.setFileName(str(QGZ))
    projet.writeEntryBool("Paths", "/Absolute", False)
    C = AQ.Couches(GPKG, DOSSIER, projet)
    # couches de saisie (vides : Couches.vecteur les ignorerait, elles sont ajoutées directement)
    obs = QgsVectorLayer(f"{GPKG}|layername=observation", "Observations faune-flore", "ogr")
    hab = QgsVectorLayer(f"{GPKG}|layername=habitat", "Habitats", "ogr")
    taxons = QgsVectorLayer(f"{GPKG}|layername=taxon_connu", "Espèces déjà connues", "ogr")
    for lyr in (obs, hab, taxons):
        projet.addMapLayer(lyr, lyr is taxons)
    g = projet.layerTreeRoot().addGroup("Saisie")
    g.addLayer(obs)
    g.addLayer(hab)

    # --- formulaire des observations
    defaut(obs, "uuid", "uuid()")
    obs.setEditorWidgetSetup(obs.fields().indexOf("uuid"), QgsEditorWidgetSetup("Hidden", {}))
    defaut(obs, "date_obs", "now()")
    obs.setEditorWidgetSetup(obs.fields().indexOf("date_obs"), QgsEditorWidgetSetup(
        "DateTime", {"display_format": "dd/MM/yyyy", "field_format": "yyyy-MM-dd", "calendar_popup": True}))
    defaut(obs, "observateur", "coalesce(@qfield_cloud_username, @user_full_name)")
    obligatoire(obs, "observateur")
    liste(obs, "groupe", GROUPES)
    obligatoire(obs, "groupe")
    obs.setEditorWidgetSetup(obs.fields().indexOf("taxon"), QgsEditorWidgetSetup("ValueRelation", {
        "Layer": taxons.id(), "Key": "nom_scientifique", "Value": "nom", "AllowNull": False,
        "UseCompleter": True, "OrderByValue": True, "FilterExpression": ""}))
    # espèce absente de la liste des espèces connues : saisie libre, l'une ou l'autre est exigée
    obs.setConstraintExpression(obs.fields().indexOf("taxon_libre"), '"taxon" IS NOT NULL OR "taxon_libre" <> ''',
                                "Choisir une espèce dans la liste ou la saisir")
    obs.setFieldConstraint(obs.fields().indexOf("taxon_libre"), QgsFieldConstraints.ConstraintExpression,
                           QgsFieldConstraints.ConstraintStrengthHard)
    obligatoire(obs, "effectif", '"effectif" > 0', "L'effectif doit être un entier positif")
    defaut(obs, "effectif", "1")
    liste(obs, "comportement", COMPORTEMENTS)
    obs.setConstraintExpression(obs.fields().indexOf("date_obs"), '"date_obs" <= now()',
                                "La date ne peut pas être dans le futur")
    obs.setEditorWidgetSetup(obs.fields().indexOf("photo"), QgsEditorWidgetSetup(
        "ExternalResource", {"DocumentViewer": 1, "RelativeStorage": 1, "StorageMode": 0,
                             "DefaultRoot": "", "FileWidget": True}))
    defaut(obs, "photo", "'DCIM/obs_' || format_date(now(), 'yyyyMMdd_HHmmss') || '.jpg'")
    obs.setEditorWidgetSetup(obs.fields().indexOf("remarque"), QgsEditorWidgetSetup(
        "TextEdit", {"IsMultiline": True}))
    onglets(obs, [("Espèce", ["groupe", "taxon", "taxon_libre", "effectif", "comportement"]),
                  ("Relevé", ["date_obs", "observateur", "remarque", "photo"])])
    AQ.categories(obs, "groupe", {g: (g, c) for g, c in zip(GROUPES, [
        "#1f78b4", "#6a3d9a", "#b15928", "#33a02c", "#e31a1c", "#00a3c4", "#ff7f00", "#cab2d6",
        "#fdbf6f", "#4daf4a", "#7f7f7f"])}, lambda c: AQ.point(c, 3.2))
    AQ.etiquettes(obs, 'coalesce("taxon", "taxon_libre")', 8)

    # --- formulaire des habitats
    defaut(hab, "uuid", "uuid()")
    hab.setEditorWidgetSetup(hab.fields().indexOf("uuid"), QgsEditorWidgetSetup("Hidden", {}))
    defaut(hab, "date_obs", "now()")
    defaut(hab, "observateur", "coalesce(@qfield_cloud_username, @user_full_name)")
    obligatoire(hab, "observateur")
    hab.setEditorWidgetSetup(hab.fields().indexOf("code_eunis"), QgsEditorWidgetSetup(
        "ValueMap", {"map": [{f"{k} - {v}": k} for k, v in EUNIS.items()]}))
    obligatoire(hab, "code_eunis")
    liste(hab, "etat_conservation", ETATS)
    defaut(hab, "etat_conservation", "'Non évalué'")
    hab.setEditorWidgetSetup(hab.fields().indexOf("zone_humide"), QgsEditorWidgetSetup(
        "CheckBox", {"CheckedState": "true", "UncheckedState": "false"}))
    onglets(hab, [("Habitat", ["code_eunis", "etat_conservation", "zone_humide"]),
                  ("Relevé", ["date_obs", "observateur", "remarque"])])
    AQ.unique(hab, AQ.remplissage("#a6d96a", "#1a9641", 0.6, alpha=0.35))
    AQ.etiquettes(hab, '"code_eunis"', 8, "#1a9641", gras=True)

    # --- consultation : périmètre, aires, enjeux ; fond en ligne (ou tuiles hors ligne via QFieldSync)
    AQ.charger(C)
    projet.write(str(QGZ))
    print(f"Projet QField : {QGZ}")
    print(f"  {len(especes)} espèces déjà connues proposées à la saisie")


main()
app.exitQgis()
