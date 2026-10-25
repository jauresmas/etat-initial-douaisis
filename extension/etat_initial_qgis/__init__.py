"""Extension QGIS « État initial de l'environnement »."""


def classFactory(iface):  # noqa: N802 (nom imposé par QGIS)
    from .extension import Extension
    return Extension(iface)
