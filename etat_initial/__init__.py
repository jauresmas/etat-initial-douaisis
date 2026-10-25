"""Production automatisée de l'état initial de l'environnement d'un projet.

Bibliothèque commune à la chaîne de démonstration (scripts/) et à l'extension
QGIS (extension/). Elle ne dépend que de geopandas, shapely et requests : elle
fonctionne aussi bien avec le Python du poste qu'avec celui de QGIS.

    from etat_initial import aires, sources, analyse, enjeux
"""
__version__ = "1.0.0"
