"""Étape 11 - Planche de concertation (SVG Inkscape à calques, export PDF et PNG par Inkscape).

Une planche A3 pour une réunion publique : un plan simplifié du site, les points d'attention
numérotés et trois encadrés en langage courant. Le fichier SVG est organisé en calques
Inkscape (fond de plan, site, points d'attention, textes) : on le retouche dans Inkscape,
puis on relance l'export ou on exporte depuis Inkscape.

    python 11_planche_concertation.py
"""
import subprocess
from xml.sax.saxutils import escape

import config
import geopandas as gpd
import pyogrio
import shapely
from shapely.geometry import box
from shapely.ops import nearest_points

from outils import log

GPKG = config.LIVRABLES / "02_Donnees_SIG" / "etat_initial.gpkg"
SORTIE = config.LIVRABLES / "05_Concertation"
POLICE = "Times New Roman"
W, H = 420, 297                       # A3 paysage, en millimètres
CADRE = (12, 42, 250, 243)           # x, y, largeur, hauteur du plan
COUL = {"fond": "#f7f4ee", "bati": "#d9d2c5", "habitat": "#cdb9a5", "route": "#ffffff", "rail": "#8a8a8a",
        "eau": "#9cc3e0", "vegetation": "#cfe3c0", "site": "#f4a259", "texte": "#1f2a36", "accent": "#b5452a",
        "bandeau": "#1d3557"}


def lire(nom):
    try:
        return gpd.read_file(GPKG, layer=nom)
    except Exception:
        return gpd.GeoDataFrame(geometry=[], crs=2154)


class Plan:
    """Projection des coordonnées Lambert-93 dans le cadre du plan (en mm)."""

    def __init__(self, emprise):
        x, y, w, h = CADRE
        xmin, ymin, xmax, ymax = emprise
        self.e = min(w / (xmax - xmin), h / (ymax - ymin))
        cx, cy = (xmin + xmax) / 2, (ymin + ymax) / 2
        self.x0 = x + w / 2 - cx * self.e
        self.y0 = y + h / 2 + cy * self.e
        # emprise réelle du cadre (plus large que l'emprise demandée sur un des deux axes)
        dx, dy = w / 2 / self.e, h / 2 / self.e
        self.zone = box(cx - dx, cy - dy, cx + dx, cy + dy)

    def pt(self, x, y):
        return self.x0 + x * self.e, self.y0 - y * self.e

    def chemin(self, geom, simplifier=0.8):
        geom = geom.intersection(self.zone).simplify(simplifier)
        morceaux = []
        for g in shapely.get_parts(geom):
            anneaux = [g.exterior, *g.interiors] if g.geom_type == "Polygon" else [g] \
                if g.geom_type == "LineString" else []
            for a in anneaux:
                pts = [self.pt(x, y) for x, y in a.coords]
                if len(pts) < 2:
                    continue
                d = "M" + " L".join(f"{px:.2f},{py:.2f}" for px, py in pts)
                morceaux.append(d + (" Z" if g.geom_type == "Polygon" else ""))
        return " ".join(morceaux)


def calque(ident, nom, contenu):
    return (f'<g inkscape:groupmode="layer" id="{ident}" inkscape:label="{escape(nom)}">\n'
            + "\n".join(contenu) + "\n</g>")


def texte(x, y, t, taille, couleur=COUL["texte"], gras=False, italique=False, ancre="start"):
    """taille en points ; le document est en millimètres (1 pt = 0,3528 mm)."""
    return (f'<text x="{x:.1f}" y="{y:.1f}" font-family="{POLICE}" font-size="{taille * 0.3528:.2f}" fill="{couleur}" '
            f'font-weight="{"bold" if gras else "normal"}" font-style="{"italic" if italique else "normal"}" '
            f'text-anchor="{ancre}">{escape(t)}</text>')


def paragraphe(x, y, t, taille, largeur_car, interligne=1.35, **kw):
    """Texte multiligne (coupure aux mots) ; renvoie les éléments et la position finale."""
    lignes, courante = [], ""
    for mot in t.split():
        if len(courante) + len(mot) + 1 > largeur_car:
            lignes.append(courante)
            courante = mot
        else:
            courante = f"{courante} {mot}".strip()
    lignes.append(courante)
    pas = taille * interligne * 0.3528  # points -> mm
    elems = [texte(x, y + i * pas, l, taille, **kw) for i, l in enumerate(lignes)]
    return elems, y + len(lignes) * pas


def points_attention(aires, zip_geom):
    """Points d'attention tirés des données de l'étude, avec leur position et une phrase simple."""
    enj = pyogrio.read_dataframe(GPKG, layer="t_enjeux", read_geometry=False).set_index("sujet")
    niveau = enj["niveau"].to_dict()
    pts = []
    bat = lire("batiment")
    hab = bat[bat["usage_1"] == "Résidentiel"] if not bat.empty else bat
    if not hab.empty:
        p = hab.iloc[[hab.distance(zip_geom).argmin()]].geometry.iloc[0].representative_point()
        pts.append(("Les riverains", p, "Des maisons bordent le site. Hauteur des panneaux, clôture, reflets et "
                    "bruit du chantier seront étudiés avec les habitants."))
    ce = lire("cours_eau")
    if not ce.empty:
        o = ce.iloc[ce.distance(zip_geom).argmin()]
        p = nearest_points(zip_geom, o.geometry)[1]
        nom = f"Le cours d'eau « {o['nom']} »" if isinstance(o.get("nom"), str) else "Un cours d'eau"
        pts.append(("L'eau", p, f"{nom} passe à {int(o.geometry.distance(zip_geom))} m. Aucune pollution ne "
                    "doit l'atteindre, ni pendant le chantier ni ensuite."))
    vf = lire("voie_ferree")
    if not vf.empty:
        p = nearest_points(zip_geom, vf.iloc[vf.distance(zip_geom).argmin()].geometry)[1]
        pts.append(("La voie ferrée", p, "Elle longe le site : les distances de sécurité seront fixées avec "
                    "le gestionnaire du réseau."))
    occ = lire("ocsge")
    veg = occ[occ["code_cs"].str.startswith("CS2") & (occ["code_us"] != "US1.1")] if not occ.empty else occ
    veg_zip = veg.clip(zip_geom) if not veg.empty else veg
    if not veg_zip.empty:
        p = veg_zip.geometry.union_all().representative_point()
        part = veg_zip.area.sum() / zip_geom.area
        pts.append(("La nature sur la friche", p, f"Herbes et arbustes couvrent {part:.0%} du site. Un "
                    "inventaire sur une année dira quelles espèces y vivent avant de dessiner le projet."))
    pts.append(("Les sols", zip_geom.representative_point(), "L'ancien dépôt d'hydrocarbures impose un "
                "diagnostic de pollution. Des panneaux posés sur lests, sans terrassement profond, sont un "
                "usage adapté à un sol pollué."))
    return pts, niveau


def main():
    SORTIE.mkdir(parents=True, exist_ok=True)
    zip_ = lire("projet")
    zip_geom = zip_.geometry.union_all()
    aires = lire("aire_etude")
    imm = aires[aires["aire"] == "immediate"].geometry.iloc[0]
    P = Plan(imm.buffer(60).bounds)
    crib = pyogrio.read_dataframe(GPKG, layer="criblage_friches", read_geometry=False).sort_values("rang")
    site = crib.iloc[0]
    nom_site = site["site_nom"].replace("(d'hydrocarbure)", "d'hydrocarbures")
    zonage = pyogrio.read_dataframe(GPKG, layer="t_zonage", read_geometry=False)
    pv = zonage[(zonage["aire"] == "Zone d'implantation potentielle")
                & zonage["intitule"].fillna("").str.contains("photovolta", case=False)]
    esp = pyogrio.read_dataframe(GPKG, layer="t_especes", read_geometry=False)

    # --- calque fond de plan
    fond = [f'<rect x="{CADRE[0]}" y="{CADRE[1]}" width="{CADRE[2]}" height="{CADRE[3]}" fill="{COUL["fond"]}"/>']
    for nom, coul in (("foret", COUL["vegetation"]), ("zdh", None)):
        g = lire(nom)
        if coul and not g.empty:
            g = g[~g["tfv"].fillna("").str.contains("herbac", case=False)] if "tfv" in g else g
            fond.append(f'<path d="{P.chemin(g.geometry.union_all(), 2)}" fill="{coul}" stroke="none"/>')
    for nom in ("plan_eau",):
        g = lire(nom)
        if not g.empty:
            fond.append(f'<path d="{P.chemin(g.geometry.union_all())}" fill="{COUL["eau"]}" stroke="none"/>')
    ce = lire("cours_eau")
    if not ce.empty:
        fond.append(f'<path d="{P.chemin(ce.geometry.union_all())}" fill="none" stroke="{COUL["eau"]}" '
                    'stroke-width="2.4" stroke-linecap="round"/>')
    rt = lire("route")
    if not rt.empty:
        fond.append(f'<path d="{P.chemin(rt.geometry.union_all())}" fill="none" stroke="#c9c2b6" '
                    'stroke-width="1.6" stroke-linecap="round"/>')
        fond.append(f'<path d="{P.chemin(rt.geometry.union_all())}" fill="none" stroke="{COUL["route"]}" '
                    'stroke-width="1.0" stroke-linecap="round"/>')
    vf = lire("voie_ferree")
    if not vf.empty:
        fond.append(f'<path d="{P.chemin(vf.geometry.union_all())}" fill="none" stroke="{COUL["rail"]}" '
                    'stroke-width="0.7" stroke-dasharray="2.5,1.2"/>')
    bat = lire("batiment")
    if not bat.empty:
        for usage, coul in (("Résidentiel", COUL["habitat"]), (None, COUL["bati"])):
            sel = bat[bat["usage_1"] == usage] if usage else bat[bat["usage_1"] != "Résidentiel"]
            if not sel.empty:
                fond.append(f'<path d="{P.chemin(sel.geometry.union_all(), 0.3)}" fill="{coul}" '
                            'stroke="#b3a894" stroke-width="0.15"/>')

    # --- calque site
    sx, sy = P.pt(*zip_geom.representative_point().coords[0])
    site_elems = [f'<path d="{P.chemin(zip_geom, 0.3)}" fill="{COUL["site"]}" fill-opacity="0.55" '
                  f'stroke="{COUL["accent"]}" stroke-width="1.1" stroke-dasharray="3,1.5"/>',
                  texte(sx - 92, sy + 26, f"Le site étudié : {site['surface_ha']:.1f} ha".replace(".", ","), 13,
                        COUL["accent"], gras=True),
                  f'<line x1="{sx - 52}" y1="{sy + 22}" x2="{sx - 10}" y2="{sy + 6}" stroke="{COUL["accent"]}" '
                  'stroke-width="0.4"/>']

    # --- calque points d'attention
    pts, niveau = points_attention(aires, zip_geom)
    attention = []
    for i, (titre, p, _) in enumerate(pts, start=1):
        px, py = P.pt(p.x, p.y)
        px = min(max(px, CADRE[0] + 6), CADRE[0] + CADRE[2] - 6)
        py = min(max(py, CADRE[1] + 6), CADRE[1] + CADRE[3] - 6)
        attention += [f'<circle cx="{px:.1f}" cy="{py:.1f}" r="5" fill="{COUL["bandeau"]}" stroke="#ffffff" '
                      'stroke-width="0.9"/>',
                      texte(px, py + 2.3, str(i), 12, "#ffffff", gras=True, ancre="middle")]

    # --- calque textes
    T = [f'<rect x="0" y="0" width="{W}" height="34" fill="{COUL["bandeau"]}"/>',
         texte(12, 16, f"Une centrale solaire sur l'{nom_site[0].lower() + nom_site[1:]} ?", 22, "#ffffff",
               gras=True),
         texte(12, 27, f"{site['commune']}. Ce que montre l'état initial de l'environnement, document pour "
                       "la réunion publique", 12, "#c9d6ea", italique=True)]
    X, Y, larg = 276, 50, 58
    T.append(texte(X, Y, "Le site aujourd'hui", 15, COUL["bandeau"], gras=True))
    faits = (f"Une friche industrielle de {site['surface_ha']:.1f} ha entre la voie ferrée et le canal, "
             "aujourd'hui inoccupée (photographie aérienne, OCS GE).").replace(".", ",", 1)
    if not pv.empty:
        faits += " Le plan local d'urbanisme réserve déjà ce terrain à une centrale photovoltaïque."
    faits += (f" Sur les {len(crib)} friches de l'agglomération, c'est la seule qui réunit taille suffisante, "
              "absence de protection naturelle forte et terrain libre.")
    e, Y = paragraphe(X, Y + 8, faits, 11, larg)
    T += e
    Y += 5
    T.append(texte(X, Y, "Les points d'attention", 15, COUL["bandeau"], gras=True))
    Y += 8
    for i, (titre, _, phrase) in enumerate(pts, start=1):
        T += [f'<circle cx="{X + 3.2}" cy="{Y - 1.3}" r="3.3" fill="{COUL["bandeau"]}"/>',
              texte(X + 3.2, Y + 0.3, str(i), 9, "#ffffff", gras=True, ancre="middle"),
              texte(X + 9, Y, titre, 11.5, COUL["texte"], gras=True)]
        e, Y = paragraphe(X + 9, Y + 4.8, phrase, 10, larg - 4)
        T += e
        Y += 2.5
    Y += 2
    T.append(texte(X, Y, "Et ensuite ?", 15, COUL["bandeau"], gras=True))
    suite = (f"Inventaires de la faune et de la flore sur quatre saisons ({len(esp)} espèces déjà connues "
             "alentour), diagnostic des sols, étude paysagère depuis les maisons voisines, puis présentation "
             "d'un projet précis avant l'enquête publique.")
    e, Y = paragraphe(X, Y + 8, suite, 11, larg)
    T += e
    # échelle, nord, sources
    lg = 100 * P.e  # 100 m
    bx, by = CADRE[0] + 6, CADRE[1] + CADRE[3] - 8
    T += [f'<rect x="{bx - 2}" y="{by - 7}" width="{lg + 16}" height="11" fill="#ffffff" fill-opacity="0.85"/>',
          f'<line x1="{bx}" y1="{by}" x2="{bx + lg:.1f}" y2="{by}" stroke="{COUL["texte"]}" stroke-width="1"/>',
          texte(bx, by - 2, "0", 8), texte(bx + lg, by - 2, "100 m", 8, ancre="middle"),
          f'<path d="M {CADRE[0] + CADRE[2] - 10} {CADRE[1] + 16} l 4 -10 l 4 10 l -4 -3 z" fill="{COUL["texte"]}"/>',
          texte(CADRE[0] + CADRE[2] - 6, CADRE[1] + 21, "N", 9, gras=True, ancre="middle"),
          texte(12, H - 6, "Sources : IGN (BD TOPO, OCS GE, BD Forêt, Parcellaire Express), Géoportail de "
                           "l'Urbanisme, Cerema (Cartofriches), GBIF. " + config.CARTOUCHE, 8,
                "#6b6b6b", italique=True)]

    svg = (f'<?xml version="1.0" encoding="UTF-8"?>\n'
           f'<svg xmlns="http://www.w3.org/2000/svg" '
           f'xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape" '
           f'width="{W}mm" height="{H}mm" viewBox="0 0 {W} {H}">\n'
           f'<title>Planche de concertation - {escape(nom_site)}</title>\n'
           f'<rect width="{W}" height="{H}" fill="#ffffff"/>\n'
           + calque("fond", "Fond de plan", fond) + "\n"
           + calque("site", "Site étudié", site_elems) + "\n"
           + calque("attention", "Points d'attention", attention) + "\n"
           + calque("textes", "Textes et habillage", T) + "\n</svg>\n")
    fichier = SORTIE / "Planche_concertation.svg"
    fichier.write_text(svg, encoding="utf-8")
    log(f"SVG Inkscape : {fichier.relative_to(config.RACINE)}")
    for typ, opts in (("pdf", []), ("png", ["--export-dpi=110"])):
        subprocess.run([str(config.INKSCAPE), str(fichier), f"--export-type={typ}",
                        f"--export-filename={fichier.with_suffix('.' + typ)}", *opts],
                       check=True, capture_output=True)
        log(f"  export Inkscape : {fichier.with_suffix('.' + typ).name}")


if __name__ == "__main__":
    main()
