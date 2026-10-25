"""Fournisseur de traitements « État initial »."""
from pathlib import Path

from qgis.core import QgsProcessingProvider
from qgis.PyQt.QtGui import QIcon

from .algorithme import AlgoEtatInitial


class Fournisseur(QgsProcessingProvider):
    def loadAlgorithms(self):  # noqa: N802
        self.addAlgorithm(AlgoEtatInitial())

    def id(self):
        return "etatinitial"

    def name(self):
        return "État initial de l'environnement"

    def icon(self):
        return QIcon(str(Path(__file__).with_name("icone.svg")))
