"""Projet QGIS et atlas A3 de l'état initial (PyQGIS).

À partir du GeoPackage d'une étude (couches et tables t_*), construit un projet QGIS
symbolisé, un thème de carte et une mise en page A3 par planche, puis exporte chaque
planche en PDF et en PNG. Utilisé par la chaîne (scripts/06_atlas_qgis.py) et par
l'extension QGIS : le gabarit est le même pour tous les sites.
"""
import csv
from pathlib import Path

from qgis.core import (QgsApplication, QgsCategorizedSymbolRenderer, QgsCoordinateReferenceSystem,
                       QgsFillSymbol, QgsLayerTreeLayer, QgsLayoutExporter, QgsLayoutItemLabel,
                       QgsLayoutItemLegend, QgsLayoutItemMap, QgsLayoutItemPicture,
                       QgsLayoutItemScaleBar, QgsLayoutItemShape, QgsLayoutPoint, QgsLayoutSize,
                       QgsLegendStyle, QgsLineSymbol, QgsMapThemeCollection, QgsMarkerSymbol,
                       QgsPalettedRasterRenderer, QgsPalLayerSettings, QgsPrintLayout, QgsProject,
                       QgsRasterLayer, QgsRectangle, QgsRendererCategory, QgsRuleBasedRenderer,
                       QgsScaleBarSettings, QgsSingleSymbolRenderer, QgsTextBufferSettings,
                       QgsTextFormat, QgsUnitTypes, QgsVectorLayer, QgsVectorLayerSimpleLabeling,
                       QgsHueSaturationFilter, QgsMapLayerLegendUtils)
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor, QFont

MM = QgsUnitTypes.LayoutMillimeters
POLICE = "Times New Roman"
BLEU_NUIT = "#1d3557"
COULEUR_NIVEAU = {"Très fort": "#7f0000", "Fort": "#d7301f", "Modéré": "#fc8d59",
                  "Faible": "#fdd49e", "Nul": "#f0f0f0"}
WMTS = ("crs=EPSG:3857&dpiMode=7&format={fmt}&layers={couche}&styles=normal&tileMatrixSet=PM"
        "&url=https://data.geopf.fr/wmts?SERVICE%3DWMTS%26REQUEST%3DGetCapabilities")

CLASSES_HARMONISEES = {1: ("Surfaces artificialisées", "#c8102e"),
                       2: ("Terres agricoles", "#f2d16b"),
                       3: ("Autres formations herbacées", "#a8d672"),
                       4: ("Forêts et formations ligneuses", "#2f7d32"),
                       5: ("Eau et zones humides", "#3a86c8"),
                       6: ("Sols nus et milieux minéraux", "#b9a98f")}
CONCORDANCE = {3: ("Les trois sources concordent", "#1b7837"),
               2: ("OCS GE et OSO concordent", "#7fbf7b"),
               1: ("OCS GE et CLC concordent", "#d9f0d3"),
               4: ("CLC et OSO, contre OCS GE", "#e7d4e8"),
               5: ("Aucune concordance", "#762a83")}
OSO_CLASSES = {1: "Bâti dense", 2: "Bâti diffus", 3: "Zones industrielles et commerciales",
               4: "Surfaces routes", 5: "Colza", 6: "Céréales à paille", 7: "Protéagineux", 8: "Soja",
               9: "Tournesol", 10: "Maïs", 11: "Riz", 12: "Tubercules et racines", 13: "Prairies",
               14: "Vergers", 15: "Vignes", 16: "Forêts de feuillus", 17: "Forêts de conifères",
               18: "Pelouses", 19: "Landes ligneuses", 20: "Surfaces minérales", 21: "Plages et dunes",
               22: "Glaciers ou neiges", 23: "Eau", 24: "Serres"}
# palette officielle du produit OSO (table de couleurs du GeoTIFF diffusé)
OSO_COULEURS = {1: "#ff00ff", 2: "#ff55ff", 3: "#ffaaff", 4: "#00ffff", 5: "#ffff00", 6: "#d0ff00",
                7: "#a1d600", 8: "#ffab44", 9: "#d6d600", 10: "#ff5500", 11: "#c5ffff", 12: "#aaaa61",
                13: "#aaaa00", 14: "#aaaaff", 15: "#550000", 16: "#009c00", 17: "#003200", 18: "#aaff00",
                19: "#55aa7f", 20: "#ff0000", 21: "#ffb802", 22: "#bebebe", 23: "#0000ff", 24: "#4479c8"}
CLC_COULEURS = {"111": "#e6004d", "112": "#ff0000", "121": "#cc4df2", "122": "#cc0000", "123": "#e6cccc",
                "124": "#e6cce6", "131": "#a600cc", "132": "#a64d00", "133": "#ff4dff", "141": "#ffa6ff",
                "142": "#ffe6ff", "211": "#ffffa8", "212": "#ffff00", "221": "#e68000", "222": "#f2a64d",
                "231": "#e6e64d", "241": "#ffe6a6", "242": "#ffe64d", "243": "#e6cc4d", "311": "#80ff00",
                "312": "#00a600", "313": "#4dff00", "321": "#ccf24d", "322": "#a6ff80", "324": "#a6f200",
                "331": "#e6e6e6", "332": "#cccccc", "333": "#ccffcc", "411": "#a6a6ff", "412": "#4d4dff",
                "511": "#00ccf2", "512": "#80f2e6"}


# --- Symboles --------------------------------------------------------------------------------
def _rgba(couleur, alpha=1.0):
    c = QColor(couleur)
    return f"{c.red()},{c.green()},{c.blue()},{int(255 * alpha)}"


def remplissage(couleur="#ffffff", contour="#000000", largeur=0.2, alpha=1.0, style="solid",
                style_contour="solid", alpha_contour=1.0):
    return QgsFillSymbol.createSimple({
        "color": _rgba(couleur, alpha) if style != "no" else "0,0,0,0", "style": style,
        "outline_color": _rgba(contour, alpha_contour) if contour else "0,0,0,0",
        "outline_width": str(largeur), "outline_style": style_contour if contour else "no"})


def trait(couleur, largeur=0.4, style="solid", alpha=1.0):
    return QgsLineSymbol.createSimple({"line_color": _rgba(couleur, alpha), "line_width": str(largeur),
                                       "line_style": style, "capstyle": "round"})


def point(couleur, taille=2.2, forme="circle", contour="#ffffff"):
    return QgsMarkerSymbol.createSimple({"name": forme, "color": couleur, "size": str(taille),
                                         "outline_color": contour, "outline_width": "0.3"})


def unique(lyr, symbole):
    lyr.setRenderer(QgsSingleSymbolRenderer(symbole))


def categories(lyr, champ, table, fabrique, autre=None):
    """table : {valeur: (libellé, couleur)} ; fabrique(couleur) -> symbole."""
    cats = [QgsRendererCategory(v, fabrique(c), lib) for v, (lib, c) in table.items()]
    if autre:
        cats.append(QgsRendererCategory("", fabrique(autre[1]), autre[0]))
    lyr.setRenderer(QgsCategorizedSymbolRenderer(champ, cats))


def regles(lyr, liste):
    """liste : [(libellé, expression, symbole)]."""
    racine = QgsRuleBasedRenderer.Rule(None)
    for lib, expr, sym in liste:
        racine.appendChild(QgsRuleBasedRenderer.Rule(sym, 0, 0, expr, lib))
    lyr.setRenderer(QgsRuleBasedRenderer(racine))


def format_texte(taille=8, couleur="#222222", gras=False, italique=False, tampon=False):
    fmt = QgsTextFormat()
    f = QFont(POLICE)
    f.setBold(gras)
    f.setItalic(italique)
    fmt.setFont(f)
    fmt.setSize(taille)
    fmt.setSizeUnit(QgsUnitTypes.RenderPoints)
    fmt.setColor(QColor(couleur))
    if tampon:
        b = QgsTextBufferSettings()
        b.setEnabled(True)
        b.setSize(0.8)
        b.setColor(QColor("white"))
        fmt.setBuffer(b)
    return fmt


def etiquettes(lyr, expression, taille=7, couleur="#333333", gras=False):
    s = QgsPalLayerSettings()
    s.fieldName = expression
    s.isExpression = True
    s.setFormat(format_texte(taille, couleur, gras=gras, tampon=True))
    lyr.setLabeling(QgsVectorLayerSimpleLabeling(s))
    lyr.setLabelsEnabled(True)


# --- Couches ------------------------------------------------------------------------------------
class Couches:
    """Charge et symbolise les couches d'un GeoPackage d'étude ; ignore les couches absentes."""

    def __init__(self, gpkg, rasters, projet):
        self.gpkg, self.rasters, self.projet = Path(gpkg), Path(rasters), projet
        self.c = {}
        self.racine = projet.layerTreeRoot()

    def vecteur(self, nom, titre, groupe):
        lyr = QgsVectorLayer(f"{self.gpkg}|layername={nom}", titre, "ogr")
        if not lyr.isValid() or lyr.featureCount() == 0:
            return None
        self.projet.addMapLayer(lyr, False)
        self._groupe(groupe).addLayer(lyr)
        self.c[nom] = lyr
        return lyr

    def raster(self, nom, fichier, titre, groupe, classes=None):
        chemin = self.rasters / fichier
        if not chemin.exists():
            return None
        lyr = QgsRasterLayer(str(chemin), titre)
        if not lyr.isValid():
            return None
        if classes:
            cl = [QgsPalettedRasterRenderer.Class(v, QColor(c), lib) for v, (lib, c) in classes.items()]
            lyr.setRenderer(QgsPalettedRasterRenderer(lyr.dataProvider(), 1, cl))
        self.projet.addMapLayer(lyr, False)
        self._groupe(groupe).addLayer(lyr)
        self.c[nom] = lyr
        return lyr

    def fond(self, nom, couche, titre, fmt="image/png", gris=True, opacite=0.6):
        lyr = QgsRasterLayer(WMTS.format(couche=couche, fmt=fmt), titre, "wms")
        if not lyr.isValid():
            return None
        if gris:
            lyr.hueSaturationFilter().setGrayscaleMode(QgsHueSaturationFilter.GrayscaleLuminosity)
        lyr.renderer().setOpacity(opacite)
        self.projet.addMapLayer(lyr, False)
        self._groupe("Fonds de plan").addLayer(lyr)
        self.c[nom] = lyr
        return lyr

    def _groupe(self, nom):
        g = self.racine.findGroup(nom)
        return g or self.racine.addGroup(nom)

    def get(self, *noms):
        return [self.c[n] for n in noms if n in self.c]


def charger(couches, nomenclature_ocsge=None):
    """Charge toutes les couches connues et leur applique la charte."""
    C = couches
    v = C.vecteur
    # --- projet et contexte
    if v("projet", "Zone d'implantation potentielle (ZIP)", "Projet"):
        unique(C.c["projet"], remplissage(contour="#e31a1c", largeur=0.9, style="no"))
    if v("aire_etude", "Aires d'étude", "Projet"):
        lyr = C.c["aire_etude"]
        dist = {f["aire"]: f["distance_m"] for f in lyr.getFeatures()}
        categories(lyr, "aire", {
            "immediate": (f"Aire d'étude immédiate ({dist.get('immediate', 0):.0f} m)", "#ff7f00"),
            "rapprochee": (f"Aire d'étude rapprochée ({dist.get('rapprochee', 0) / 1000:.0f} km)", "#6a3d9a"),
            "eloignee": (f"Aire d'étude éloignée ({dist.get('eloignee', 0) / 1000:.0f} km)", "#252525")},
            lambda c: remplissage(contour=c, largeur=0.55, style="no", style_contour="dash"))
    if v("commune", "Limites communales", "Contexte"):
        unique(C.c["commune"], remplissage(contour="#8a8a8a", largeur=0.25, style="no"))
        etiquettes(C.c["commune"], '"nom"', 6.5, "#555555")
    # couches de la carte de situation
    if v("contexte_departement", "Départements", "Contexte"):
        unique(C.c["contexte_departement"], remplissage("#f4f1ea", "#9a9a9a", 0.25))
    if v("contexte_epci", "Douaisis Agglo", "Contexte"):
        unique(C.c["contexte_epci"], remplissage("#d9e2ef", "#1d3557", 0.3))
    if v("contexte_site", "Site étudié", "Contexte"):
        unique(C.c["contexte_site"], point("#e31a1c", 2.6, "circle", "#ffffff"))
    if v("route", "Routes principales", "Contexte"):
        regles(C.c["route"], [("Route principale", "\"importance\" IN ('1','2')", trait("#9a9a9a", 0.6)),
                              ("Route secondaire", "\"importance\" = '3'", trait("#bdbdbd", 0.35))])
    if v("voie_ferree", "Voie ferrée", "Contexte"):
        unique(C.c["voie_ferree"], trait("#5a5a5a", 0.45, "dash"))
    if v("batiment", "Bâti", "Contexte"):
        regles(C.c["batiment"], [("Bâtiment résidentiel", "\"usage_1\" = 'Résidentiel'",
                                  remplissage("#e6a37c", "#b0704a", 0.1)),
                                 ("Autre bâtiment", "ELSE", remplissage("#c8c8c8", "#9a9a9a", 0.1))])
    # --- patrimoine naturel
    if v("znieff1", "ZNIEFF de type I", "Milieu naturel"):
        unique(C.c["znieff1"], remplissage("#4daf4a", "#2e7d32", 0.4, alpha=0.35))
        etiquettes(C.c["znieff1"], '"nom"', 6.5, "#1b5e20")
    if v("znieff2", "ZNIEFF de type II", "Milieu naturel"):
        unique(C.c["znieff2"], remplissage("#7fbf7b", "#5a9e56", 0.4, style="f_diagonal"))
    if v("zsc", "Natura 2000 - ZSC (directive Habitats)", "Milieu naturel"):
        unique(C.c["zsc"], remplissage("#1f78b4", "#1f78b4", 0.6, style="b_diagonal"))
        etiquettes(C.c["zsc"], '"nom"', 6.5, "#0d3d63")
    if v("zps", "Natura 2000 - ZPS (directive Oiseaux)", "Milieu naturel"):
        unique(C.c["zps"], remplissage("#6a3d9a", "#6a3d9a", 0.6, style="f_diagonal"))
    for nom, titre, coul in (("rnn", "Réserve naturelle nationale", "#00441b"),
                             ("rnr", "Réserve naturelle régionale", "#1b7837"),
                             ("cen", "Site du conservatoire d'espaces naturels", "#a6761d")):
        if v(nom, titre, "Milieu naturel"):
            unique(C.c[nom], remplissage(coul, coul, 0.4, alpha=0.6))
    if v("pnr", "Parc naturel régional", "Milieu naturel"):
        unique(C.c["pnr"], remplissage(contour="#33a02c", largeur=1.0, style="no", style_contour="dash"))
    if v("ramsar", "Site Ramsar", "Milieu naturel"):
        unique(C.c["ramsar"], remplissage(contour="#00a3c4", largeur=0.8, style="no", style_contour="dot"))
    if v("observation_patrimoniale", "Observation d'espèce patrimoniale (GBIF)", "Milieu naturel"):
        groupes = {"Oiseaux": "#1f78b4", "Amphibiens": "#33a02c", "Reptiles": "#e31a1c",
                   "Insectes": "#ff7f00", "Mammifères": "#b15928", "Plantes à fleurs": "#6a3d9a"}
        categories(C.c["observation_patrimoniale"], "groupe", {g: (g, c) for g, c in groupes.items()},
                   lambda c: point(c, 2.0), autre=("Autres groupes", "#7f7f7f"))
    # --- eau
    if v("zdh", "Zone à dominante humide (SDAGE)", "Eau"):
        unique(C.c["zdh"], remplissage("#9ecae1", "#6baed6", 0.1, alpha=0.65))
    if v("cours_eau", "Cours d'eau", "Eau"):
        unique(C.c["cours_eau"], trait("#2171b5", 0.6))
        etiquettes(C.c["cours_eau"], '"nom"', 6, "#08519c")
    if v("plan_eau", "Plan d'eau", "Eau"):
        unique(C.c["plan_eau"], remplissage("#6baed6", "#2171b5", 0.2))
    if v("nappe", "Sensibilité aux remontées de nappe", "Eau"):
        regles(C.c["nappe"], [("Débordement de nappe possible", "\"classe\" ILIKE '%débordement%'",
                               remplissage("#2171b5", None, 0, alpha=0.16, style="dense6")),
                              ("Inondation de cave possible", "\"classe\" ILIKE '%cave%'",
                               remplissage("#6baed6", None, 0, alpha=0.10))])
    # --- occupation du sol
    if v("ocsge", "OCS GE - couverture du sol", "Occupation du sol"):
        millesimes = sorted({str(f["millesime"]) for f in C.c["ocsge"].getFeatures()})
        C.c["ocsge"].setName(f"OCS GE {' et '.join(millesimes)} - couverture du sol")
        table = {k: (lib, c) for k, (lib, c) in (nomenclature_ocsge or {}).items() if k.startswith("CS")}
        categories(C.c["ocsge"], "code_cs", table, lambda c: remplissage(c, "#ffffff", 0.05))
    if v("ocsge_evolution", "Changements récents (OCS GE différentielle)", "Occupation du sol"):
        categories(C.c["ocsge_evolution"], "sens", {
            "Artificialisation": ("Artificialisation", "#c8102e"),
            "Renaturation": ("Renaturation", "#1a9850"),
            "Autre changement": ("Autre changement de couverture", "#fdae61")},
            lambda c: remplissage(c, c, 0.2, alpha=0.85))
    if v("clc", "Corine Land Cover 2018", "Occupation du sol"):
        categories(C.c["clc"], "code", {k: (k, c) for k, c in CLC_COULEURS.items()},
                   lambda c: remplissage(c, "#ffffff", 0.1))
    if v("rpg", "Parcelle agricole déclarée (RPG 2024)", "Occupation du sol"):
        unique(C.c["rpg"], remplissage("#f2d16b", "#c9a227", 0.2, alpha=0.75))
    if v("foret", "Formations végétales (BD Forêt)", "Occupation du sol"):
        regles(C.c["foret"], [("Formation boisée", "NOT (\"tfv\" ILIKE '%herbac%' OR \"tfv\" ILIKE '%lande%')",
                               remplissage("#31a354", "#006d2c", 0.15, alpha=0.7)),
                              ("Lande ou formation herbacée", "ELSE",
                               remplissage("#c7e9c0", "#74c476", 0.15, alpha=0.7))])
    if v("haie", "Haie", "Occupation du sol"):
        unique(C.c["haie"], trait("#006d2c", 0.8))
    C.raster("oso", "oso_site.tif", "OSO 2023 (CESBIO)", "Occupation du sol",
             {k: (lib, OSO_COULEURS[k]) for k, lib in OSO_CLASSES.items()})
    for s, titre in (("ocsge", "OCS GE"), ("clc", "Corine Land Cover"), ("oso", "OSO (CESBIO)")):
        C.raster(f"h_{s}", f"ocs_harmonise_{s}.tif", f"{titre} - classes harmonisées", "Occupation du sol",
                 CLASSES_HARMONISEES)
    C.raster("concordance", "concordance_ocs.tif", "Concordance des trois sources", "Occupation du sol",
             CONCORDANCE)
    # --- urbanisme
    if v("doc_urba", "Document d'urbanisme applicable", "Urbanisme"):
        categories(C.c["doc_urba"], "type_document", {
            "PLUi": ("PLU intercommunal", "#d6604d"), "PLU": ("Plan local d'urbanisme", "#f4a582"),
            "CC": ("Carte communale", "#92c5de"), "PSMV": ("Plan de sauvegarde (PSMV)", "#b2abd2"),
            "RNU": ("Règlement national d'urbanisme", "#e0e0e0"),
            "Aucun document publié": ("Aucun document publié sur le GPU", "#f7f7f7")},
            lambda c: remplissage(c, "#ffffff", 0.4, alpha=0.85))
        etiquettes(C.c["doc_urba"], "\"commune\" || '\\n' || \"type_document\"", 6.5, "#333333")
    if v("zone_urba", "Zonage du PLU", "Urbanisme"):
        categories(C.c["zone_urba"], "typezone", {
            "U": ("Zone urbaine (U)", "#e41a1c"), "AUc": ("Zone à urbaniser ouverte (AU)", "#ff7f00"),
            "AUs": ("Zone à urbaniser fermée (AU strict)", "#ffbf80"), "A": ("Zone agricole (A)", "#ffd92f"),
            "N": ("Zone naturelle (N)", "#4daf4a")},
            lambda c: remplissage(c, "#555555", 0.25, alpha=0.4))
        etiquettes(C.c["zone_urba"], '"libelle"', 7, "#222222", gras=True)
    if v("prescription_surf", "Prescriptions surfaciques du PLU", "Urbanisme"):
        regles(C.c["prescription_surf"], [
            ("Espace boisé classé", "\"typepsc\" = '01'", remplissage("#1a9850", "#1a9850", 0.5, style="cross")),
            ("Constructibilité limitée (risques)", "\"typepsc\" = '02'",
             remplissage("#d7301f", "#d7301f", 0.5, style="b_diagonal")),
            ("Emplacement réservé", "\"typepsc\" = '05'", remplissage("#984ea3", "#984ea3", 0.5, style="dense6")),
            ("Autre prescription surfacique", "ELSE", remplissage(contour="#4a4a4a", largeur=0.5, style="no",
                                                                  style_contour="dot"))])
    if v("prescription_lin", "Prescriptions linéaires du PLU", "Urbanisme"):
        regles(C.c["prescription_lin"], [
            ("Haie ou cours d'eau protégé", "\"typepsc\" = '07'", trait("#1a9850", 0.6, "dash")),
            ("Chemin à conserver", "\"typepsc\" = '24'", trait("#8c510a", 0.5, "dot")),
            ("Autre prescription linéaire", "ELSE", trait("#d7301f", 0.5, "dash"))])
    if v("prescription_pct", "Prescriptions ponctuelles du PLU", "Urbanisme"):
        regles(C.c["prescription_pct"], [
            ("Puits de mine", "\"libelle\" ILIKE '%puits%'", point("#000000", 2.6, "square", "#ffffff")),
            ("Patrimoine protégé", "\"typepsc\" = '07'", point("#b2182b", 2.0, "star")),
            ("Autre prescription ponctuelle", "ELSE", point("#4a4a4a", 1.6))])
    sup = {"A4": ("Terrain riverain de cours d'eau (A4)", "#2171b5"), "AC1": ("Abords de monument historique (AC1)", "#b2182b"),
           "AC2": ("Site inscrit ou classé (AC2)", "#c51b7d"), "AS1": ("Captage d'eau potable (AS1)", "#08519c"),
           "I3": ("Canalisation de gaz (I3)", "#ff7f00"), "I4": ("Ligne électrique (I4)", "#252525"),
           "PM1": ("Plan de prévention des risques (PM1)", "#d7301f"), "PM3": ("PPRT (PM3)", "#762a83"),
           "PT2": ("Télécommunications (PT2)", "#636363"), "T1": ("Voie ferrée (T1)", "#8c510a"),
           "T5": ("Dégagement aérien (T5)", "#9e9ac8"), "T7": ("Hors dégagement aérien (T7)", "#cbc9e2")}
    if v("assiette_sup_s", "Servitudes d'utilité publique", "Urbanisme"):
        categories(C.c["assiette_sup_s"], "suptype", sup,
                   lambda c: remplissage(c, c, 0.4, alpha=0.25, style="solid"),
                   autre=("Autre servitude", "#969696"))
    if v("generateur_sup_l", "Ligne électrique (générateur de servitude I4)", "Urbanisme"):
        unique(C.c["generateur_sup_l"], trait("#252525", 0.7, "dash"))
    # --- foncier
    if v("parcelle", "Parcellaire cadastral", "Foncier"):
        unique(C.c["parcelle"], remplissage(contour="#6e6e6e", largeur=0.15, style="no"))
    if v("parcelle_zip", "Parcelles de la ZIP par propriétaire", "Foncier"):
        lyr = C.c["parcelle_zip"]
        valeurs = sorted({f["proprietaire"] for f in lyr.getFeatures()})
        palette = ["#8dd3c7", "#fdb462", "#bebada", "#fb8072", "#80b1d3", "#b3de69", "#fccde5", "#d9d9d9"]
        categories(lyr, "proprietaire", {p: (p, palette[i % len(palette)]) for i, p in enumerate(valeurs)},
                   lambda c: remplissage(c, "#4d4d4d", 0.3, alpha=0.8))
        etiquettes(lyr, '"section" || \' \' || "numero"', 6, "#222222")
    # --- patrimoine
    if v("unesco_bien", "Bien inscrit au patrimoine mondial (Bassin minier)", "Patrimoine"):
        unique(C.c["unesco_bien"], remplissage("#b2182b", "#67001f", 0.3, alpha=0.75))
        etiquettes(C.c["unesco_bien"], '"nom"', 6, "#67001f")
    if v("unesco_tampon", "Zone tampon du bien inscrit", "Patrimoine"):
        unique(C.c["unesco_tampon"], remplissage("#f4a582", "#d6604d", 0.4, style="f_diagonal"))
    if v("terril_unesco", "Terril inscrit au patrimoine mondial", "Patrimoine"):
        unique(C.c["terril_unesco"], remplissage("#5d4037", "#3e2723", 0.3, alpha=0.85))
    # --- risques
    if v("pprt", "Périmètre de PPRT", "Risques"):
        unique(C.c["pprt"], remplissage("#762a83", "#762a83", 0.5, style="cross"))
        etiquettes(C.c["pprt"], '"nom"', 6.5, "#40004b")
    for nom, titre, coul in (("ppr_inond", "Périmètre de PPR inondation", "#2166ac"),
                             ("ppr_minier", "Périmètre de PPR minier", "#8c510a")):
        if v(nom, titre, "Risques"):
            unique(C.c[nom], remplissage(coul, coul, 0.5, style="b_diagonal"))
    if v("cavite", "Cavité souterraine", "Risques"):
        unique(C.c["cavite"], point("#000000", 2.4, "triangle"))
    for nom, titre in (("sis", "Secteur d'information sur les sols"), ("ssp", "Site pollué (instruction)")):
        if v(nom, titre, "Risques"):
            unique(C.c[nom], remplissage("#8c2d04", "#8c2d04", 0.4, style="dense5"))
    # --- réseaux et cumuls
    if v("ligne_elec", "Ligne électrique haute tension", "Réseaux"):
        unique(C.c["ligne_elec"], trait("#000000", 0.6, "dash"))
        etiquettes(C.c["ligne_elec"], '"voltage"', 6, "#000000")
    if v("poste_elec", "Poste électrique", "Réseaux"):
        unique(C.c["poste_elec"], remplissage("#000000", "#000000", 0.2))
    if v("parc_pv", "Parc photovoltaïque au sol existant", "Réseaux"):
        unique(C.c["parc_pv"], remplissage("#fec44f", "#b8860b", 0.4))
    if v("eolienne", "Éolienne existante ou autorisée", "Réseaux"):
        unique(C.c["eolienne"], point("#4a4a4a", 3.0, "triangle"))
    # --- synthèse
    if v("enjeu", "Enjeux spatialisés", "Synthèse"):
        lyr = C.c["enjeu"]
        # filtre dans le style et non setSubsetString, qui verrouille le GeoPackage ; les règles
        # sont dessinées de la dernière à la première : les enjeux forts passent au-dessus
        regles(lyr, [(f"Enjeu {n.lower()}", f"\"niveau\" = '{n}'",
                      remplissage(COULEUR_NIVEAU[n], COULEUR_NIVEAU[n], 0.6, alpha=0.38))
                     for n in ("Très fort", "Fort", "Modéré")])
        lyr.renderer().setUsingSymbolLevels(True)
        etiquettes(lyr, "CASE WHEN \"niveau\" IN ('Très fort', 'Fort', 'Modéré') THEN \"sujet\" END",
                   6.5, "#3d0000", gras=True)
    # fonds de plan (en dernier : sous toutes les couches)
    C.fond("plan", "GEOGRAPHICALGRIDSYSTEMS.PLANIGNV2", "Plan IGN v2", gris=True, opacite=0.55)
    C.fond("ortho", "ORTHOIMAGERY.ORTHOPHOTOS", "Photographies aériennes (IGN)", fmt="image/jpeg",
           gris=False, opacite=1.0)
    return C


def nomenclature_ocsge(csv_path):
    """Libellés et couleurs officiels de l'OCS GE (fichier NomenclatureOCSGE.csv de l'IGN)."""
    table = {}
    if csv_path and Path(csv_path).exists():
        with open(csv_path, encoding="utf-8", errors="replace") as f:
            for r in csv.DictReader(f, delimiter=";"):
                table[r["CODE"]] = (r["LIBELLE"].strip(), QColor(int(r["R"]), int(r["V"]), int(r["B"])).name())
    return table


# --- Mise en page -------------------------------------------------------------------------------
class Gabarit:
    """Mise en page A3 paysage commune à toutes les planches."""
    L, H = 420, 297
    CARTE = (8, 8, 292, 281)
    X, W = 306, 106

    def __init__(self, projet, meta):
        self.projet, self.meta = projet, meta

    def _label(self, mise, texte, x, y, w, h, fmt, align=Qt.AlignLeft, valign=Qt.AlignTop, fond=None, marge=0):
        if fond:
            self._rect(mise, x, y, w, h, fond)
        lab = QgsLayoutItemLabel(mise)
        lab.setText(texte)
        lab.setTextFormat(fmt)
        lab.setHAlign(align)
        lab.setVAlign(valign)
        lab.setMarginX(marge)
        lab.setMarginY(marge)
        mise.addLayoutItem(lab)
        lab.attemptMove(QgsLayoutPoint(x, y, MM))
        lab.attemptResize(QgsLayoutSize(w, h, MM))
        return lab

    def _rect(self, mise, x, y, w, h, couleur, contour=None):
        r = QgsLayoutItemShape(mise)
        r.setShapeType(QgsLayoutItemShape.Rectangle)
        r.setSymbol(remplissage(couleur, contour or couleur, 0.2 if contour else 0))
        mise.addLayoutItem(r)
        r.attemptMove(QgsLayoutPoint(x, y, MM))
        r.attemptResize(QgsLayoutSize(w, h, MM))
        return r

    def carte(self, mise, couches, emprise, x, y, w, h, cadre=True):
        m = QgsLayoutItemMap(mise)
        mise.addLayoutItem(m)
        m.attemptMove(QgsLayoutPoint(x, y, MM))
        m.attemptResize(QgsLayoutSize(w, h, MM))
        m.setCrs(QgsCoordinateReferenceSystem("EPSG:2154"))
        m.setLayers(couches)
        m.setKeepLayerSet(True)
        m.zoomToExtent(emprise)
        m.setFrameEnabled(cadre)
        m.setFrameStrokeColor(QColor("#4a4a4a"))
        m.setFrameStrokeWidth(QgsLayoutMeasurementMm(0.3))
        return m

    def page(self, planche, couches_carte, couches_legende, emprise, texte_enjeux, situation, colonnes=1):
        mise = QgsPrintLayout(self.projet)
        mise.initializeDefaults()
        mise.setName(f"{planche['num']} - {planche['titre']}")
        mise.pageCollection().page(0).setPageSize(QgsLayoutSize(self.L, self.H, MM))
        x0, y0, w0, h0 = self.CARTE
        if planche.get("comparaison"):
            cartes = self._comparaison(mise, planche, emprise)
            m = cartes[0]
        else:
            m = self.carte(mise, couches_carte, emprise, x0, y0, w0, h0)
        X, W = self.X, self.W
        # en-tête
        self._rect(mise, X, 8, W, 27, BLEU_NUIT)
        self._label(mise, f"CARTE {planche['num']}/{self.meta['nb_planches']}.  {planche['theme'].upper()}",
                    X + 4, 10, W - 8, 5, format_texte(6.5, "#a8c5e8", gras=True))
        self._label(mise, planche["titre"], X + 4, 15.5, W - 8, 19, format_texte(12.5, "#ffffff", gras=True))
        self._label(mise, planche.get("sous_titre", ""), X, 37, W, 10, format_texte(7.5, "#3a3a3a", italique=True))
        # enjeux
        self._label(mise, texte_enjeux, X, 48, W, 56, format_texte(6.8, "#222222"), fond="#f2f4f7", marge=2.5)
        # légende
        leg = QgsLayoutItemLegend(mise)
        leg.setTitle("Légende")
        leg.setLinkedMap(m)
        leg.setAutoUpdateModel(False)
        racine = leg.model().rootGroup()
        racine.removeAllChildren()
        for lyr in couches_legende:
            noeud = racine.addLayer(lyr)
            if isinstance(lyr, QgsRasterLayer):  # retire l'intitulé « Band 1 (Palette) »
                noeuds = leg.model().layerLegendNodes(noeud)
                if noeuds and "Band" in str(noeuds[0].data(Qt.DisplayRole)):
                    QgsMapLayerLegendUtils.setLegendNodeOrder(noeud, list(range(1, len(noeuds))))
                    leg.model().refreshLayerLegend(noeud)
        leg.setLegendFilterByMapEnabled(not planche.get("comparaison"))
        leg.setColumnCount(colonnes)
        leg.setSplitLayer(True)
        leg.setSymbolWidth(5.5)
        leg.setSymbolHeight(3.2)
        leg.setWrapString("|")
        leg.rstyle(QgsLegendStyle.Title).setTextFormat(format_texte(8, BLEU_NUIT, gras=True))
        leg.rstyle(QgsLegendStyle.Subgroup).setTextFormat(format_texte(6.8, "#222222", gras=True))
        leg.rstyle(QgsLegendStyle.SymbolLabel).setTextFormat(format_texte(6.3, "#333333"))
        leg.rstyle(QgsLegendStyle.Subgroup).setMargin(QgsLegendStyle.Top, 1.6)
        leg.rstyle(QgsLegendStyle.Symbol).setMargin(QgsLegendStyle.Top, 0.9)
        leg.setResizeToContents(False)
        mise.addLayoutItem(leg)
        leg.attemptMove(QgsLayoutPoint(X, 106, MM))
        leg.attemptResize(QgsLayoutSize(W, 100, MM))
        # carte de situation
        if situation:
            loc = self.carte(mise, situation["couches"], situation["emprise"], X, 208, 46, 44)
            ov = loc.overview()
            ov.setLinkedMap(m)
            ov.setFrameSymbol(remplissage("#e31a1c", "#e31a1c", 0.5, alpha=0.25))
            self._label(mise, "Situation", X + 1, 208.5, 20, 4, format_texte(6, "#333333", gras=True))
        # échelle et nord
        sb = QgsLayoutItemScaleBar(mise)
        sb.setStyle("Single Box")
        sb.setLinkedMap(m)
        sb.setUnits(QgsUnitTypes.DistanceKilometers)
        sb.setUnitLabel("km")
        sb.setNumberOfSegments(2)
        sb.setNumberOfSegmentsLeft(0)
        sb.setSegmentSizeMode(QgsScaleBarSettings.SegmentSizeFitWidth)
        sb.setMinimumBarWidth(22)
        sb.setMaximumBarWidth(42)
        sb.setHeight(2)
        sb.setTextFormat(format_texte(6.5))
        mise.addLayoutItem(sb)
        sb.attemptMove(QgsLayoutPoint(X + 50, 236, MM))
        nord = QgsLayoutItemPicture(mise)
        nord.setPicturePath(QgsApplication.svgPaths()[0] + "/arrows/NorthArrow_02.svg"
                            if (Path(QgsApplication.svgPaths()[0]) / "arrows/NorthArrow_02.svg").exists()
                            else "arrows/NorthArrow_02.svg")
        mise.addLayoutItem(nord)
        nord.attemptMove(QgsLayoutPoint(X + 96, 222, MM))
        nord.attemptResize(QgsLayoutSize(8, 12, MM))
        self._label(mise, f"Échelle 1:{round(m.scale(), -2):,.0f}".replace(",", " "), X + 50, 229, 46, 5,
                    format_texte(6.5, "#333333"))
        # sources et cartouche
        self._label(mise, "Sources : " + planche.get("sources", "") + ". Fond : © IGN Plan IGN v2 / BD ORTHO.",
                    X, 254, W, 22, format_texte(5.8, "#555555"))
        self._label(mise, self.meta["cartouche"], X, 277, W, 12, format_texte(5.8, "#7a1f1f", italique=True))
        self.projet.layoutManager().addLayout(mise)
        return mise

    def _comparaison(self, mise, planche, emprise):
        x0, y0, w0, h0 = self.CARTE
        w, h = (w0 - 4) / 2, (h0 - 4) / 2
        cartes = []
        for i, (titre, couches) in enumerate(planche["comparaison"]):
            x = x0 + (i % 2) * (w + 4)
            y = y0 + (i // 2) * (h + 4)
            m = self.carte(mise, couches, emprise, x, y, w, h)
            self._label(mise, titre, x + 2, y + 2, 70, 6, format_texte(8, BLEU_NUIT, gras=True),
                        fond="#ffffff", marge=1.2)
            cartes.append(m)
        return cartes


def QgsLayoutMeasurementMm(v):
    from qgis.core import QgsLayoutMeasurement
    return QgsLayoutMeasurement(v, MM)


def fixer_transformations(projet, paires=(("EPSG:2154", "EPSG:3857"), ("EPSG:2154", "EPSG:4326"))):
    """Inscrit dans le projet la transformation à utiliser entre Lambert-93 et les fonds de plan :
    sans elle, QGIS demande à l'ouverture de choisir une transformation, couche par couche."""
    from qgis.core import QgsDatumTransform
    contexte = projet.transformContext()
    for a, b in paires:
        for src, dst in ((a, b), (b, a)):
            s, d = QgsCoordinateReferenceSystem(src), QgsCoordinateReferenceSystem(dst)
            operations = QgsDatumTransform.operations(s, d)
            if operations:
                contexte.addCoordinateOperation(s, d, operations[0].proj)
    projet.setTransformContext(contexte)


def theme(projet, nom, couches):
    rec = QgsMapThemeCollection.MapThemeRecord()
    rec.setLayerRecords([QgsMapThemeCollection.MapThemeLayerRecord(c) for c in couches])
    projet.mapThemeCollection().insert(nom, rec)


def exporter(mise, pdf, png=None, dpi=150, dpi_png=110):
    ex = QgsLayoutExporter(mise)
    s = QgsLayoutExporter.PdfExportSettings()
    s.dpi = dpi
    s.rasterizeWholeImage = False
    s.forceVectorOutput = False
    r = ex.exportToPdf(str(pdf), s)
    if png:
        si = QgsLayoutExporter.ImageExportSettings()
        si.dpi = dpi_png
        ex.exportToImage(str(png), si)
    return r == QgsLayoutExporter.Success


def rectangle(geom_wkt_bounds, marge=0.06):
    xmin, ymin, xmax, ymax = geom_wkt_bounds
    dx, dy = (xmax - xmin) * marge, (ymax - ymin) * marge
    return QgsRectangle(xmin - dx, ymin - dy, xmax + dx, ymax + dy)
