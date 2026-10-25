"""Accès aux services en ligne : requêtes avec reprise, flux WFS paginés, téléchargements."""
import time
import warnings
from pathlib import Path

import geopandas as gpd
import pandas as pd
import requests

from .parametres import CRS, SERVICES

warnings.filterwarnings("ignore", module="requests")  # avertissement de versions urllib3/chardet

SESSION = requests.Session()
SESSION.headers["User-Agent"] = "etat-initial (outil SIG d'aide a l'etude d'impact)"

_journal = print


def definir_journal(fonction):
    """Redirige les messages (print par défaut, QgsProcessingFeedback dans QGIS)."""
    global _journal
    _journal = fonction


def log(msg):
    _journal(f"[{time.strftime('%H:%M:%S')}] {msg}")


def requete(url, params=None, timeout=180, essais=4, flux=False, entetes=None):
    """GET avec reprise automatique en cas d'erreur réseau ou de serveur surchargé.
    Une erreur de la requête elle-même (4xx, sauf 429) est renvoyée tout de suite."""
    for essai in range(essais):
        try:
            r = SESSION.get(url, params=params, timeout=timeout, stream=flux, headers=entetes)
            r.raise_for_status()
            return r
        except requests.RequestException as err:
            code = getattr(err.response, "status_code", None)
            if essai == essais - 1 or (code and 400 <= code < 500 and code != 429):
                raise
            log(f"  nouvel essai ({err.__class__.__name__})")
            time.sleep(5 * (essai + 1))


def wfs(service, couche, bbox=None, cql=None, page=None, tri=None, champ_geom="geometrie"):
    """Télécharge une couche WFS 2.0, page par page, en Lambert-93.

    service    : clé de SERVICES (geopf, geo2france, brgm)
    bbox       : (xmin, ymin, xmax, ymax) en Lambert-93
    cql        : filtre CQL (serveurs GeoServer uniquement : geopf, geo2france)
    champ_geom : nom de la géométrie, utile seulement quand bbox et cql sont combinés
    """
    srv = SERVICES[service]
    page = page or srv["page"]
    params = {"service": "WFS", "version": "2.0.0", "request": "GetFeature",
              "typeNames": couche, "outputFormat": srv["format"], "srsName": CRS}
    if srv["pagination"]:
        params["count"] = page
    emprise = ",".join(f"{v:.1f}" for v in bbox) if bbox is not None else None
    if cql and emprise:
        # GeoServer refuse BBOX et CQL_FILTER ensemble : l'emprise passe dans le filtre
        params["CQL_FILTER"] = f"BBOX({champ_geom},{emprise},'{CRS}') AND ({cql})"
    elif cql:
        params["CQL_FILTER"] = cql
    elif emprise:
        params["BBOX" if srv["pagination"] else "bbox"] = f"{emprise},{CRS}"
    if tri and srv["pagination"]:
        params["sortBy"] = tri

    morceaux, debut = [], 0
    while True:
        if srv["pagination"]:
            params["startIndex"] = debut
        r = requete(srv["url"], params=params)
        if not r.content.strip():  # MapServer renvoie un corps vide quand rien ne répond au filtre
            break
        feats = r.json().get("features", [])
        if not feats:
            break
        morceaux.append(gpd.GeoDataFrame.from_features(feats, crs=CRS))
        debut += len(feats)
        if not srv["pagination"] or len(feats) < page:
            break
    if not morceaux:
        return gpd.GeoDataFrame(geometry=[], crs=CRS)
    gdf = gpd.GeoDataFrame(pd.concat(morceaux, ignore_index=True), crs=CRS)
    return gdf[gdf.geometry.notna()].reset_index(drop=True)


def telecharger(url, cible, taille_attendue=None):
    """Télécharge un fichier (reprise si un fichier partiel existe déjà)."""
    cible = Path(cible)
    if cible.exists() and (taille_attendue is None or cible.stat().st_size == taille_attendue):
        return cible
    cible.parent.mkdir(parents=True, exist_ok=True)
    partiel = cible.with_suffix(cible.suffix + ".partiel")
    deja = partiel.stat().st_size if partiel.exists() else 0
    entetes = {"Range": f"bytes={deja}-"} if deja else {}
    debut = time.time()
    with SESSION.get(url, headers=entetes, stream=True, timeout=300) as r:
        r.raise_for_status()
        mode = "ab" if deja and r.status_code == 206 else "wb"
        total = int(r.headers.get("Content-Length", 0)) + (deja if mode == "ab" else 0)
        recu = deja if mode == "ab" else 0
        with open(partiel, mode) as f:
            for bloc in r.iter_content(chunk_size=1 << 20):
                f.write(bloc)
                recu += len(bloc)
    duree = max(time.time() - debut, 0.1)
    log(f"  {cible.name} : {recu / 1e6:.1f} Mo en {duree:.0f} s ({recu / 1e6 / duree:.1f} Mo/s)")
    if total and recu < total:
        raise IOError(f"téléchargement incomplet de {cible.name} ({recu} / {total} octets)")
    partiel.replace(cible)
    return cible
