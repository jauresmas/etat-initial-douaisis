"""Enregistre le fournisseur de traitements et un bouton qui ouvre l'algorithme."""
from pathlib import Path

from qgis.core import QgsApplication
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction

from .fournisseur import Fournisseur


class Extension:
    def __init__(self, iface):
        self.iface = iface
        self.fournisseur = None
        self.action = None

    def initProcessing(self):  # noqa: N802
        self.fournisseur = Fournisseur()
        QgsApplication.processingRegistry().addProvider(self.fournisseur)

    def initGui(self):  # noqa: N802
        self.initProcessing()
        icone = QIcon(str(Path(__file__).with_name("icone.svg")))
        self.action = QAction(icone, "Produire l'état initial d'un périmètre", self.iface.mainWindow())
        self.action.triggered.connect(self.ouvrir)
        self.iface.addToolBarIcon(self.action)
        self.iface.addPluginToMenu("État initial", self.action)

    def ouvrir(self):
        import processing
        processing.execAlgorithmDialog("etatinitial:etat_initial")

    def unload(self):
        if self.action:
            self.iface.removeToolBarIcon(self.action)
            self.iface.removePluginMenu("État initial", self.action)
        if self.fournisseur:
            QgsApplication.processingRegistry().removeProvider(self.fournisseur)
