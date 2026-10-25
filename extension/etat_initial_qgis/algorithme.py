"""Algorithme « Produire l'état initial d'un périmètre ».

Enchaîne, pour un polygone quelconque en France métropolitaine, la même méthode que la chaîne
de démonstration : aires d'étude, collecte des données ouvertes, analyses, hiérarchisation
des enjeux, GeoPackage, projet QGIS et atlas A3.
"""
from pathlib import Path

from qgis.core import (QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsGeometry, QgsProcessing,
                       QgsProcessingAlgorithm, QgsProcessingException, QgsProcessingOutputFile,
                       QgsProcessingOutputFolder, QgsProcessingParameterBoolean, QgsProcessingParameterEnum,
                       QgsProcessingParameterFeatureSource, QgsProcessingParameterFile,
                       QgsProcessingParameterFolderDestination, QgsProcessingParameterString, QgsProject)

TYPES = [("photovoltaique", "Centrale photovoltaïque au sol (aires : 200 m, 1 km, 5 km)"),
         ("eolien", "Parc éolien terrestre (aires : 600 m, 6 km, 18 km)"),
         ("amenagement", "Projet d'aménagement (aires : 100 m, 500 m, 3 km)")]


class AlgoEtatInitial(QgsProcessingAlgorithm):
    PERIMETRE, NOM, TYPE, OCSGE, FONCIER, ESPECES, OSO, ATLAS, DOSSIER = (
        "PERIMETRE", "NOM", "TYPE", "OCSGE", "FONCIER", "ESPECES", "OSO", "ATLAS", "DOSSIER")

    def name(self):
        return "etat_initial"

    def displayName(self):  # noqa: N802
        return "Produire l'état initial d'un périmètre"

    def shortHelpString(self):  # noqa: N802
        return ("À partir de la zone d'implantation potentielle (ZIP) d'un projet, calcule les aires d'étude, "
                "rassemble les données ouvertes (zonages naturels, eau, occupation du sol, urbanisme, "
                "servitudes, foncier, risques, réseaux, espèces connues), hiérarchise les enjeux et produit un "
                "GeoPackage, un projet QGIS et un atlas A3 de 18 cartes.<br><br>"
                "La hiérarchisation est indicative : elle prépare le travail des experts de terrain. "
                "Compter de 5 à 15 minutes selon les options (l'OCS GE pèse environ 150 Mo par département).")

    def flags(self):
        # les mises en page et les projets QGIS se manipulent dans le fil principal
        return super().flags() | QgsProcessingAlgorithm.FlagNoThreading

    def createInstance(self):  # noqa: N802
        return AlgoEtatInitial()

    def initAlgorithm(self, config=None):  # noqa: N802
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.PERIMETRE, "Périmètre du projet (zone d'implantation potentielle)",
            [QgsProcessing.TypeVectorPolygon]))
        self.addParameter(QgsProcessingParameterString(self.NOM, "Nom de l'étude", "Projet étudié"))
        self.addParameter(QgsProcessingParameterEnum(self.TYPE, "Type de projet", [t[1] for t in TYPES],
                                                     defaultValue=0))
        self.addParameter(QgsProcessingParameterBoolean(
            self.OCSGE, "Télécharger l'OCS GE des départements concernés (environ 150 Mo chacun)", True))
        self.addParameter(QgsProcessingParameterBoolean(
            self.ESPECES, "Données naturalistes (GBIF) et statuts des espèces (TAXREF)", True))
        self.addParameter(QgsProcessingParameterBoolean(
            self.FONCIER, "Propriétaires personnes morales (fichier DGFiP, environ 170 Mo)", False))
        self.addParameter(QgsProcessingParameterFile(
            self.OSO, "Raster OSO du CESBIO, pour comparer les sources d'occupation du sol (facultatif)",
            optional=True, fileFilter="GeoTIFF (*.tif *.tiff)"))
        self.addParameter(QgsProcessingParameterBoolean(self.ATLAS, "Construire le projet QGIS et l'atlas A3",
                                                        True))
        self.addParameter(QgsProcessingParameterFolderDestination(self.DOSSIER, "Dossier de l'étude"))
        self.addOutput(QgsProcessingOutputFile("GPKG", "GeoPackage de l'étude"))
        self.addOutput(QgsProcessingOutputFile("QGZ", "Projet QGIS"))
        self.addOutput(QgsProcessingOutputFolder("ATLAS", "Planches de l'atlas (PDF)"))

    def processAlgorithm(self, parameters, context, feedback):  # noqa: N802
        import geopandas as gpd
        import shapely

        from .etat_initial import aires as A
        from .etat_initial import etude, reseau

        reseau.definir_journal(feedback.pushInfo)
        source = self.parameterAsSource(parameters, self.PERIMETRE, context)
        if source is None:
            raise QgsProcessingException("Périmètre invalide")
        l93 = QgsCoordinateReferenceSystem("EPSG:2154")
        tr = QgsCoordinateTransform(source.sourceCrs(), l93, context.transformContext())
        geoms = []
        for f in source.getFeatures():
            g = QgsGeometry(f.geometry())
            g.transform(tr)
            geoms.append(g)
        if not geoms:
            raise QgsProcessingException("Le périmètre ne contient aucun polygone")
        zip_geom = shapely.from_wkb(bytes(QgsGeometry.unaryUnion(geoms).asWkb()))
        nom = self.parameterAsString(parameters, self.NOM, context) or "Projet étudié"
        type_projet = TYPES[self.parameterAsEnum(parameters, self.TYPE, context)][0]
        dossier = Path(self.parameterAsString(parameters, self.DOSSIER, context))
        dossier.mkdir(parents=True, exist_ok=True)
        gpkg = dossier / "etat_initial.gpkg"
        if gpkg.exists():
            gpkg.unlink()

        def etape(texte, part):
            if feedback.isCanceled():
                raise QgsProcessingException("Traitement annulé")
            if texte:
                feedback.setProgressText(texte)
            feedback.setProgress(part)

        aires = A.aires_etude(zip_geom, type_projet)
        feedback.pushInfo("Aires d'étude : " + ", ".join(f"{r.aire} {r.surface_ha:.0f} ha" for r in aires.itertuples()))
        etude.ecrire_gpkg(gpd.GeoDataFrame({"nom": [nom], "type_projet": [type_projet]}, geometry=[zip_geom],
                                           crs="EPSG:2154"), "projet", gpkg)
        etude.ecrire_gpkg(aires.drop(columns="couronne"), "aire_etude", gpkg)

        d = etude.collecter(aires, dossier / "cache",
                            ocsge=self.parameterAsBool(parameters, self.OCSGE, context),
                            foncier_pm=self.parameterAsBool(parameters, self.FONCIER, context),
                            especes=self.parameterAsBool(parameters, self.ESPECES, context), journal_etape=etape)
        etape("Écriture des données collectées", 80)
        for cle, gdf in d.items():
            if gdf is not None and len(gdf):
                etude.ecrire_gpkg(gdf, cle, gpkg)

        oso = self.parameterAsFile(parameters, self.OSO, context)
        oso_site = None
        if oso:
            oso_site = self._decouper_oso(oso, A.geom_aire(aires, "eloignee"), dossier / "rasters")
        etape("Analyses et hiérarchisation des enjeux", 85)
        t, enj, couches = etude.analyser(d, aires, oso_tif=oso_site, dossier_rasters=dossier / "rasters")
        etude.ecrire_resultats(t, enj, couches, gpkg, etude.ecrire_gpkg)

        qgz, planches = dossier / "etat_initial.qgz", dossier / "atlas"
        if self.parameterAsBool(parameters, self.ATLAS, context):
            etape("Projet QGIS et atlas", 92)
            from .etat_initial.atlas_planches import produire
            commune = ""
            com = d.get("commune")
            if com is not None and not com.empty:
                dedans = com[com.contains(zip_geom.representative_point())]
                commune = dedans["nom"].iloc[0] if not dedans.empty else ""
            libelle = TYPES[self.parameterAsEnum(parameters, self.TYPE, context)][1].split(" (")[0]
            nomenclature = next((dossier / "cache" / "ocsge").rglob("NomenclatureOCSGE.csv"), None) \
                if (dossier / "cache" / "ocsge").exists() else None
            produire(gpkg, dossier / "rasters", planches, qgz,
                     cartouche="Atlas produit par l'extension QGIS « État initial » à partir de données ouvertes. "
                               "Hiérarchisation indicative, à consolider par les inventaires de terrain.",
                     nomenclature=nomenclature,
                     site={"nom": nom, "commune": commune, "presentation": f"{libelle} : {nom}."},
                     titre=f"État initial de l'environnement - {nom}", journal=feedback.pushInfo,
                     projet=QgsProject())
        feedback.setProgress(100)
        return {"GPKG": str(gpkg), "QGZ": str(qgz), "ATLAS": str(planches)}

    @staticmethod
    def _decouper_oso(chemin, zone, dossier):
        import rasterio
        from rasterio.mask import mask
        dossier.mkdir(parents=True, exist_ok=True)
        sortie = dossier / "oso_site.tif"
        with rasterio.open(chemin) as src:
            data, transform = mask(src, [zone], crop=True, nodata=0)
            profil = src.profile | {"height": data.shape[1], "width": data.shape[2], "transform": transform,
                                    "crs": "EPSG:2154"}
            try:
                palette = src.colormap(1)
            except ValueError:
                palette = None
        with rasterio.open(sortie, "w", **profil) as dst:
            dst.write(data)
            if palette:
                dst.write_colormap(1, palette)
        return sortie
