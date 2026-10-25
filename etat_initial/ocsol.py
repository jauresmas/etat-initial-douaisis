"""Occupation du sol : harmonisation de trois sources et mesure de leur concordance.

OCS GE (IGN, vecteur, unité minimale de quelques centaines de m², produite en partie par
apprentissage profond), Corine Land Cover (photo-interprétation, unité minimale de 25 ha)
et OSO (CESBIO, classification automatique d'images Sentinel-2 à 10 m) ne répondent pas
à la même question. On les ramène à six classes communes, sur la grille de 10 m d'OSO,
pour montrer ce que chacune voit (ou ne voit pas) à l'échelle d'un site.
"""
import numpy as np
import pandas as pd
import rasterio
from rasterio import features

from .parametres import CLASSES_HARMONISEES

SOURCES = ("ocsge", "clc", "oso")
NOM_SOURCE = {"ocsge": "OCS GE", "clc": "Corine Land Cover", "oso": "OSO (CESBIO)"}

_US_AGRICOLE = {"US1.1"}


def classe_ocsge(cs, us):
    """Couverture OCS GE (+ usage agricole) -> classe harmonisée (1 à 6)."""
    cs = cs or ""
    if cs.startswith("CS1.1"):
        return 1
    if cs == "CS1.2.1":
        return 2 if us in _US_AGRICOLE else 6   # sol nu labouré au passage de l'avion
    if cs in ("CS1.2.2", "CS1.2.3"):
        return 5
    if cs.startswith("CS2.1.1") or cs == "CS2.1.2":
        return 4
    if cs == "CS2.1.3":
        return 2 if us in _US_AGRICOLE else 4   # vergers et vignes / autres ligneux
    if cs == "CS2.2.1":
        return 2 if us in _US_AGRICOLE else 3
    if cs == "CS2.2.2":
        return 3
    return 0


def classe_clc(code):
    code = str(code)
    if code.startswith("1"):
        return 1
    if code.startswith("2"):
        return 2
    if code in ("311", "312", "313", "322", "323", "324"):
        return 4
    if code in ("321", "333"):
        return 3
    if code in ("331", "332", "334", "335"):
        return 6
    if code.startswith("4") or code.startswith("5"):
        return 5
    return 0


_OSO = {**{k: 1 for k in (1, 2, 3, 4, 24)}, **{k: 2 for k in range(5, 16)},
        16: 4, 17: 4, 19: 4, 18: 3, 20: 6, 21: 6, 22: 6, 23: 5}


def classe_oso(code):
    return _OSO.get(int(code), 0)


def grilles(ocsge, clc, oso_tif, zone):
    """Les trois sources sur la grille OSO (10 m), masquées hors de la zone. Renvoie
    ({source: tableau}, transform, profil)."""
    with rasterio.open(oso_tif) as src:
        oso = src.read(1)
        transform, profil = src.transform, src.profile
    forme = oso.shape
    dedans = features.rasterize([(zone, 1)], out_shape=forme, transform=transform, fill=0,
                                dtype="uint8").astype(bool)
    vect = np.vectorize(classe_oso, otypes=[np.uint8])
    g_oso = np.where(oso > 0, vect(np.where(oso > 0, oso, 1)), 0).astype(np.uint8)

    def raster(gdf, col):
        formes = [(geom, int(v)) for geom, v in zip(gdf.geometry, gdf[col]) if v and geom is not None]
        return features.rasterize(formes, out_shape=forme, transform=transform, fill=0, dtype="uint8")

    ocsge = ocsge.assign(h=[classe_ocsge(c, u) for c, u in zip(ocsge["code_cs"], ocsge["code_us"])])
    clc = clc.assign(h=clc["code"].map(classe_clc))
    res = {"ocsge": raster(ocsge, "h"), "clc": raster(clc, "h"), "oso": g_oso}
    for k in res:
        res[k] = np.where(dedans, res[k], 0).astype(np.uint8)
    return res, transform, profil


def surfaces(grilles_, masque):
    """Surface (ha) de chaque classe harmonisée selon chaque source, dans le masque."""
    lignes = []
    for s in SOURCES:
        g = grilles_[s][masque]
        for c, (lib, _) in CLASSES_HARMONISEES.items():
            lignes.append({"source": NOM_SOURCE[s], "classe": c, "libelle": lib,
                           "surface_ha": round(float((g == c).sum()) * 0.01, 2)})  # pixel = 100 m²
    return pd.DataFrame(lignes)


def accord(a, b, masque):
    """Accord global et kappa de Cohen entre deux grilles (pixels classés dans les deux)."""
    ok = masque & (a > 0) & (b > 0)
    x, y = a[ok].astype(int), b[ok].astype(int)
    n = len(x)
    if n == 0:
        return np.nan, np.nan
    po = float((x == y).mean())
    pe = sum(float((x == c).mean()) * float((y == c).mean()) for c in CLASSES_HARMONISEES)
    kappa = (po - pe) / (1 - pe) if pe < 1 else np.nan
    return round(po, 3), round(kappa, 3)


def matrice(a, b, masque):
    """Matrice de confusion (ha) : lignes = a, colonnes = b."""
    ok = masque & (a > 0) & (b > 0)
    idx = list(CLASSES_HARMONISEES)
    m = pd.crosstab(pd.Categorical(a[ok], idx), pd.Categorical(b[ok], idx), dropna=False) * 0.01
    noms = {c: lib for c, (lib, _) in CLASSES_HARMONISEES.items()}
    return m.rename(index=noms, columns=noms).round(1)


def carte_concordance(grilles_):
    """3 = les trois sources concordent ; 2 = OCS GE et OSO seulement ; 1 = OCS GE et CLC
    seulement ; 4 = CLC et OSO seulement (contre OCS GE) ; 5 = aucune concordance ; 0 = hors zone."""
    o, c, s = grilles_["ocsge"], grilles_["clc"], grilles_["oso"]
    res = np.full(o.shape, 5, dtype=np.uint8)
    res[(o == s) & (o != c)] = 2
    res[(o == c) & (o != s)] = 1
    res[(c == s) & (o != c)] = 4
    res[(o == c) & (c == s)] = 3
    res[(o == 0) | (c == 0) | (s == 0)] = 0
    return res


LEGENDE_CONCORDANCE = {
    3: ("Les trois sources concordent", "#1b7837"),
    2: ("OCS GE et OSO concordent (CLC diffère)", "#7fbf7b"),
    1: ("OCS GE et CLC concordent (OSO diffère)", "#d9f0d3"),
    4: ("CLC et OSO concordent contre OCS GE", "#e7d4e8"),
    5: ("Aucune concordance", "#762a83"),
}
