"""Étape 7 - Documents : atlas assemblé, aperçus, carte de criblage, note méthodologique,
bordereau de livraison. Les textes sont composés en Times New Roman et tirés des tableaux
de l'étude : aucun chiffre propre au site n'est écrit en dur.

    python 07_documents.py
"""
import json
from datetime import date

import config
import geopandas as gpd
import matplotlib
import pandas as pd
import pymupdf
import pyogrio
from reportlab.lib import colors
from reportlab.lib.enums import TA_JUSTIFY
from reportlab.lib.pagesizes import A3, A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from etat_initial.parametres import CATALOGUE
from outils import log, psql

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

SIG = config.LIVRABLES / "02_Donnees_SIG"
GPKG = SIG / "etat_initial.gpkg"
ATLAS_DIR = config.LIVRABLES / "03_Atlas"
DOCS_DIR = config.LIVRABLES / "01_Documents"
IMG = config.RACINE / "docs" / "img"
BLEU = colors.HexColor("#1d3557")
NIVEAU = {"Très fort": "#7f0000", "Fort": "#d7301f", "Modéré": "#fc8d59", "Faible": "#fdd49e", "Nul": "#f0f0f0"}
DATE = "octobre 2026"

for nom, fichier in (("Times", "times.ttf"), ("Times-Gras", "timesbd.ttf"), ("Times-Ital", "timesi.ttf"),
                     ("Times-GrasItal", "timesbi.ttf")):
    pdfmetrics.registerFont(TTFont(nom, f"C:/Windows/Fonts/{fichier}"))
pdfmetrics.registerFontFamily("Times", normal="Times", bold="Times-Gras", italic="Times-Ital",
                              boldItalic="Times-GrasItal")
plt.rcParams.update({"font.family": "Times New Roman", "font.size": 9})


def table(nom):
    return pyogrio.read_dataframe(GPKG, layer=nom, read_geometry=False)


def nombre(x, dec=1):
    return f"{x:,.{dec}f}".replace(",", " ").replace(".", ",")


def distance(m):
    return f"{nombre(m / 1000)} km" if m >= 1000 else f"{int(m)} m"


def site():
    crib = table("criblage_friches").sort_values("rang")
    s = crib.iloc[0]
    nom = s["site_nom"].replace("(d'hydrocarbure)", "d'hydrocarbures")
    return {"nom": nom, "commune": s["commune"], "surface": s["surface_ha"], "nb_friches": len(crib),
            "titre": nom[0].lower() + nom[1:]}


# --- Atlas -------------------------------------------------------------------------------------
PLANCHES = sorted((ATLAS_DIR / "planches").glob("Carte_*.pdf"))


def titres_planches():
    """Titres des planches, d'après l'index écrit par 06_atlas_qgis.py."""
    index = json.loads((ATLAS_DIR / "planches" / "index.json").read_text(encoding="utf-8"))
    titres = {p["num"]: p["titre"] for p in index}
    return [titres.get(p.stem.split("_")[-1], p.stem) for p in PLANCHES]


def couverture_atlas(fichier, titres, S):
    W, H = landscape(A3)
    c = canvas.Canvas(str(fichier), pagesize=(W, H))
    c.setFillColor(BLEU)
    c.rect(0, H - 120 * mm, W, 120 * mm, fill=1, stroke=0)
    c.setFillColor(colors.white)
    c.setFont("Times-Gras", 40)
    c.drawString(25 * mm, H - 55 * mm, "État initial de l'environnement")
    c.setFont("Times", 22)
    c.drawString(25 * mm, H - 72 * mm, "Atlas cartographique : étude de cas d'une centrale photovoltaïque au sol")
    c.setFont("Times-Ital", 16)
    c.drawString(25 * mm, H - 88 * mm, f"{S['nom']}, {S['commune']} (Nord), Douaisis Agglo")
    c.setFillColor(colors.black)
    c.setFont("Times-Gras", 15)
    c.drawString(25 * mm, H - 140 * mm, "Sommaire")
    c.setFont("Times", 12)
    for i, t in enumerate(titres):
        col, lig = divmod(i, 9)
        x, y = 25 * mm + col * 190 * mm, H - 152 * mm - lig * 9.5 * mm
        c.drawString(x, y, f"Carte {i + 1:02d}")
        c.drawString(x + 22 * mm, y, t)
    c.setFont("Times-Ital", 11)
    c.setFillColor(colors.HexColor("#555555"))
    c.drawString(25 * mm, 18 * mm, config.CARTOUCHE + " Sources : IGN, INPN, MNHN, BRGM, Géoportail de "
                 "l'Urbanisme, Cerema, Géo2France, CESBIO, GBIF.")
    c.drawString(25 * mm, 12 * mm, f"Réalisation : {config.AUTEUR}, {DATE}. RGF93 / Lambert-93.")
    c.showPage()
    c.save()


def atlas(S):
    if not PLANCHES:
        log("Aucune planche : lancer d'abord 06_atlas_qgis.py")
        return []
    titres = titres_planches()
    couv = ATLAS_DIR / "_couverture.pdf"
    couverture_atlas(couv, titres, S)
    doc = pymupdf.open(couv)
    for p in PLANCHES:
        doc.insert_pdf(pymupdf.open(p))
    sortie = ATLAS_DIR / "Atlas_etat_initial.pdf"
    doc.save(sortie, garbage=3, deflate=True)
    n = len(doc)
    doc.close()  # la couverture reste ouverte tant que le document l'est
    couv.unlink()
    log(f"Atlas : {sortie.name} ({n} pages, {sortie.stat().st_size / 1e6:.1f} Mo)")
    IMG.mkdir(parents=True, exist_ok=True)
    for ancien in IMG.glob("carte_*.png"):  # anciens aperçus PNG, trop lourds pour le dépôt
        ancien.unlink()
    for p in PLANCHES:  # aperçus JPEG légers pour le README et la carte web
        pymupdf.open(p)[0].get_pixmap(dpi=90).save(IMG / f"{p.stem.lower()}.jpg", jpg_quality=82)
    log(f"  {len(PLANCHES)} aperçus dans docs/img")
    return titres


# --- Figures ------------------------------------------------------------------------------------
def carte_criblage(S):
    f = gpd.read_file(GPKG, layer="criblage_friches")
    com = gpd.read_file(GPKG, layer="contexte_commune")
    epci = gpd.read_file(GPKG, layer="contexte_epci")
    couleurs = {"Favorable": "#1a9850", "À approfondir": "#fee08b", "Défavorable": "#f46d43", "Exclu": "#bdbdbd"}
    fig, ax = plt.subplots(figsize=(7.2, 6.2), dpi=200)
    com.boundary.plot(ax=ax, color="#c8c8c8", linewidth=0.4)
    epci.boundary.plot(ax=ax, color="#1d3557", linewidth=1.0)
    pts = f.copy()
    pts["geometry"] = f.geometry.representative_point()
    for _, c in com.iterrows():
        p = c.geometry.representative_point()
        ax.text(p.x, p.y, c["nom"], fontsize=4.8, color="#9a9a9a", ha="center", zorder=2)
    for classe, coul in couleurs.items():
        sous = pts[pts["classe"] == classe]
        ax.scatter(sous.geometry.x, sous.geometry.y, s=8 + sous["surface_ha"] * 3, color=coul,
                   edgecolor="#333333", linewidth=0.4, label=f"{classe} ({len(sous)})", zorder=3)
    for _, r in pts.sort_values("rang").head(4).iterrows():
        ax.annotate(f"{int(r['rang'])}. {r['site_nom'][:40]}", (r.geometry.x, r.geometry.y), fontsize=6.5,
                    xytext=(5, 4), textcoords="offset points", zorder=4)
    ax.legend(title="Classe de criblage (nombre de friches)", fontsize=7, title_fontsize=7.5, loc="lower left")
    ax.set_axis_off()
    ax.set_title(f"Criblage des {S['nb_friches']} friches de Douaisis Agglo pour une centrale photovoltaïque "
                 "au sol", fontsize=9.5)
    fig.savefig(IMG / "criblage_friches.png", bbox_inches="tight")
    plt.close(fig)


def graphique_ocs():
    s = table("t_ocs_sources")
    s = s[s["aire"] == "rapprochee"]
    piv = s.pivot_table(index="source", columns="libelle", values="surface_ha", aggfunc="sum")
    ordre = ["Surfaces artificialisées", "Terres agricoles (cultures et prairies)", "Autres formations herbacées",
             "Forêts et formations ligneuses", "Eau et zones humides", "Sols nus et milieux minéraux"]
    coul = ["#c8102e", "#f2d16b", "#a8d672", "#2f7d32", "#3a86c8", "#b9a98f"]
    piv = piv[[o for o in ordre if o in piv.columns]]
    fig, ax = plt.subplots(figsize=(7.2, 2.4), dpi=200)
    gauche = pd.Series(0.0, index=piv.index)
    for col, c in zip(piv.columns, coul):
        ax.barh(piv.index, piv[col], left=gauche, color=c, label=col, edgecolor="white", linewidth=0.5)
        gauche += piv[col]
    ax.set_xlabel("Surface dans l'aire rapprochée (ha)")
    ax.legend(fontsize=6.5, ncol=3, loc="upper center", bbox_to_anchor=(0.5, -0.3), frameon=False)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    fig.savefig(IMG / "graphique_trois_sources.png", bbox_inches="tight")
    plt.close(fig)


# --- Mise en forme ----------------------------------------------------------------------------------
STY = {
    "titre": ParagraphStyle("titre", fontName="Times-Gras", fontSize=22, leading=26, textColor=BLEU, spaceAfter=6),
    "sous": ParagraphStyle("sous", fontName="Times-Ital", fontSize=12.5, leading=16,
                           textColor=colors.HexColor("#444444")),
    "h1": ParagraphStyle("h1", fontName="Times-Gras", fontSize=14.5, leading=18, textColor=BLEU, spaceBefore=12,
                         spaceAfter=5),
    "h2": ParagraphStyle("h2", fontName="Times-Gras", fontSize=11.5, leading=14, spaceBefore=8, spaceAfter=3),
    "p": ParagraphStyle("p", fontName="Times", fontSize=10.5, leading=14, alignment=TA_JUSTIFY, spaceAfter=5),
    "liste": ParagraphStyle("liste", fontName="Times", fontSize=10.5, leading=14, leftIndent=12, bulletIndent=2,
                            spaceAfter=2),
    "cell": ParagraphStyle("cell", fontName="Times", fontSize=8.5, leading=10.5),
    "cellg": ParagraphStyle("cellg", fontName="Times-Gras", fontSize=8.5, leading=10.5, textColor=colors.white),
    "leg": ParagraphStyle("leg", fontName="Times-Ital", fontSize=8.5, leading=11,
                          textColor=colors.HexColor("#555555"), spaceAfter=8),
    "enc": ParagraphStyle("enc", fontName="Times", fontSize=10, leading=13.5, backColor=colors.HexColor("#f2f4f7"),
                          borderPadding=6, spaceBefore=4, spaceAfter=10),
}


def P(t, s="p"):
    return Paragraph(t, STY[s])


def puces(items):
    return [Paragraph(i, STY["liste"], bulletText="•") for i in items]


def tableau(df, largeurs, entete=None, couleur_col=None):
    lignes = [[Paragraph(str(c), STY["cellg"]) for c in (entete or df.columns)]]
    for _, r in df.iterrows():
        lignes.append([Paragraph("" if pd.isna(v) else str(v), STY["cell"]) for v in r.values])
    t = Table(lignes, colWidths=[w * mm for w in largeurs], repeatRows=1)
    style = [("BACKGROUND", (0, 0), (-1, 0), BLEU), ("VALIGN", (0, 0), (-1, -1), "TOP"),
             ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#c8c8c8")),
             ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f6f7f9")]),
             ("TOPPADDING", (0, 0), (-1, -1), 2.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5)]
    if couleur_col is not None:
        for i, v in enumerate(df.iloc[:, couleur_col], start=1):
            if v in NIVEAU:
                style.append(("BACKGROUND", (couleur_col, i), (couleur_col, i), colors.HexColor(NIVEAU[v])))
    t.setStyle(TableStyle(style))
    return t


def pied(c, doc):
    c.saveState()
    c.setFont("Times-Ital", 8)
    c.setFillColor(colors.HexColor("#666666"))
    c.drawString(20 * mm, 12 * mm, "État initial de l'environnement, étude de cas : note méthodologique")
    c.drawRightString(190 * mm, 12 * mm, f"{config.AUTEUR}, {DATE}, page {doc.page}")
    c.restoreState()


# --- Note méthodologique -------------------------------------------------------------------------------
def criblage_chiffres():
    r = psql("SELECT count(*) FILTER (WHERE surface_insuffisante), "
             "count(*) FILTER (WHERE part_en_activite > 0.30 AND NOT surface_insuffisante) FROM criblage.critere")
    petits, reconvertis = (int(x) for x in r.split("|"))
    ex = psql("SELECT site_nom || '|' || commune || '|' || surface_ha FROM criblage.critere "
              "WHERE part_en_activite > 0.30 AND NOT surface_insuffisante ORDER BY surface_ha DESC LIMIT 3")
    exemples = [ligne.split("|") for ligne in ex.splitlines()]
    return petits, reconvertis, exemples


def note(titres, S):
    enj = table("t_enjeux")
    crib = table("criblage_friches")
    regles = table("criblage_regles")
    acc = table("t_ocs_accords")
    zon = table("t_zonages")
    esp = table("t_especes")
    grp = table("t_especes_groupes")
    fon = table("t_foncier")
    serv = table("t_servitudes")
    zonage = table("t_zonage")
    sources_ocs = table("t_ocs_sources")
    zz = zonage[zonage["aire"] == "Zone d'implantation potentielle"].sort_values("part", ascending=False)
    pv = zz[zz["intitule"].fillna("").str.contains("photovolta", case=False)]
    n_classes = crib["classe"].value_counts()
    petits, reconvertis, exemples = criblage_chiffres()

    sortie = DOCS_DIR / "01_Note_methodologique.pdf"
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(str(sortie), pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm, topMargin=18 * mm,
                            bottomMargin=20 * mm, title="Note méthodologique - état initial", author=config.AUTEUR)
    E = [P("État initial de l'environnement d'une centrale photovoltaïque au sol", "titre"),
         P(f"Étude de cas : {S['titre']}, à {S['commune']} (Nord). Note méthodologique", "sous"), Spacer(1, 8)]
    enc = (f"<b>Le site.</b> {nombre(S['surface'])} ha de friche industrielle, seul site retenu par le criblage "
           f"des {S['nb_friches']} friches de Douaisis Agglo. <b>Le projet étudié.</b> Une centrale photovoltaïque "
           "au sol. ")
    if not pv.empty:
        enc += (f"<b>Le document d'urbanisme.</b> Le PLU classe déjà {pv['part'].sum():.0%} du site en secteur "
                f"{', '.join(pv['zone'])} (« {pv['intitule'].iloc[0][0].lower() + pv['intitule'].iloc[0][1:]} ») : le criblage, "
                "conduit avec les seules données ouvertes, retrouve un choix déjà inscrit par la collectivité. ")
    enc += f"<b>Le statut.</b> {config.CARTOUCHE}"
    E.append(P(enc, "enc"))

    E.append(P("1. Objet et démarche", "h1"))
    E.append(P("Avant un projet soumis à étude d'impact, le bureau d'études décrit l'état du site et de ses abords : "
               "milieux naturels, eau, sols, risques, paysage et patrimoine, urbanisme, foncier, voisinage. Le "
               "cartographe en produit les cartes, dont la plupart reviennent d'un dossier à l'autre. Ce travail "
               "automatise la partie qui peut l'être : à partir d'un périmètre, l'outil rassemble les données "
               "ouvertes, mesure la position de chaque enjeu, propose une première hiérarchisation et compose "
               "l'atlas. Le temps gagné va aux experts de terrain."))
    E += puces([f"<b>Criblage</b> : les friches de Cartofriches (Cerema) sur Douaisis Agglo sont classées dans "
                f"PostGIS selon une grille de {len(regles)} critères (section 2).",
                "<b>Aires d'étude</b> : immédiate (200 m), rapprochée (1 km) et éloignée (5 km) autour de la zone "
                "d'implantation potentielle (ZIP), ordres de grandeur courants pour une centrale au sol, à "
                "justifier thème par thème.",
                f"<b>Collecte</b> : {len(CATALOGUE)} couches interrogées par flux (WFS de l'IGN, de Géo2France et du "
                "BRGM), l'API du Géoportail de l'Urbanisme, GBIF et TAXREF, plus l'OCS GE et l'OSO téléchargées.",
                f"<b>Analyses et enjeux</b> : {len(enj)} sujets classés de « nul » à « très fort » par des règles "
                "explicites, reportées dans le tableur.",
                f"<b>Atlas</b> : {len(titres)} cartes A3 au même gabarit ; le projet QGIS et ses mises en page "
                "sont livrés."])
    E.append(P("Outils : QGIS, puis Python", "h2"))
    E.append(P("Les traitements ont été réalisés avec les outils de QGIS 3.34 : tampons pour les aires d'étude, "
               "jointure par plus proche voisin pour la distance des zonages au projet, intersection et "
               "statistiques par catégorie pour l'occupation du sol, symbologie, mises en page et atlas. Ces "
               "étapes sont enchaînées dans trois modèles du modeleur graphique, livrés avec le projet "
               "(dossier <i>modeles</i>) et réutilisables sur un autre site."))
    E.append(P("Les mêmes traitements sont reproduits en Python (geopandas, PostGIS et PyQGIS pour les mises en "
               "page). La chaîne est reproductible : une seule commande relance toute l'étude et redonne les "
               "mêmes résultats. Elle est rapide : environ sept minutes une fois les données téléchargées. Elle "
               "permet aussi de mettre l'étude à jour quand un producteur publie un nouveau millésime."))
    ctl = json.loads((config.TRAVAIL / "controle_qgis_python.json").read_text(encoding="utf-8")) \
        if (config.TRAVAIL / "controle_qgis_python.json").exists() else None
    if ctl:
        z, o, a = ctl["zonages"], ctl["occupation"], ctl["aires"]
        E.append(P("<b>Contrôle croisé.</b> Les modèles QGIS ont été lancés sur les données de l'étude et comparés à "
                   f"la chaîne Python. Les surfaces des aires d'étude diffèrent au plus de {nombre(a['ecart_max_ha'], 2)} ha "
                   f"(arrondis des tampons). Les distances des {z['nb']} zonages comparés diffèrent au plus de "
                   f"{nombre(z['ecart_max_m'])} m, et leur aire d'étude est la même dans {z['positions_identiques']} cas "
                   f"sur {z['nb']}. Les surfaces d'occupation du sol ({o['nb']} couples aire et couverture) diffèrent "
                   f"au plus de {nombre(o['ecart_max_ha'], 2)} ha, soit {nombre(o['ecart_total_pct'], 2)} % du total."))

    E.append(P("2. Criblage des friches", "h1"))
    E.append(P(f"Sur {S['nb_friches']} friches (après retrait des fiches en double), {n_classes.get('Exclu', 0)} sont "
               f"exclues, {n_classes.get('Défavorable', 0)} sont défavorables (un enjeu fort : Natura 2000, ZNIEFF "
               f"de type I, zone humide, plan de prévention), {n_classes.get('À approfondir', 0)} sont à "
               f"approfondir et {n_classes.get('Favorable', 0)} favorable(s). {petits} friches font moins de 3 ha. "
               "Le calcul est une vue de la base (<i>criblage.critere</i>) ; la grille est une table "
               "(<i>criblage.regle</i>) qu'on modifie sans toucher au code."))
    if exemples:
        ex = ", ".join(f"{e[0]} ({e[1]}, {nombre(float(e[2]))} ha)" for e in exemples)
        E.append(P(f"<b>Un contrôle indispensable de la donnée.</b> Cartofriches recense des friches « potentielles », "
                   "souvent issues d'anciens inventaires industriels. Croisées avec l'usage du sol de l'OCS GE "
                   f"{config.OCSGE_ANNEE}, {reconvertis} friches de plus de 3 ha se révèlent déjà reconstruites ou en "
                   f"activité, par exemple {ex}. Sans ce contrôle, le premier site classé était une plateforme "
                   "logistique construite entre 2021 et 2025 : la photographie aérienne et l'OCS GE différentielle "
                   "l'ont montré, et le critère « site déjà reconverti » a été ajouté à la grille."))
    img = IMG / "criblage_friches.png"
    if img.exists():
        E += [Image(str(img), width=160 * mm, height=138 * mm),
              P("Figure 1. Classe de chaque friche ; taille des cercles proportionnelle à la surface.", "leg")]
    reg = regles[["effet", "points", "libelle", "seuil"]].copy()
    reg["effet"] = reg["effet"].map({"exclusion": "Exclusion", "fort": "Enjeu fort", "modere": "Enjeu modéré",
                                     "favorable": "Atout", "information": "Information"})
    reg["seuil"] = reg["seuil"].map(lambda v: "" if pd.isna(v) else nombre(v, 2).rstrip("0").rstrip(","))
    E += [P("Grille de criblage", "h2"), tableau(reg, [22, 14, 112, 22], ["Effet", "Points", "Critère", "Seuil"])]
    top = crib.sort_values("rang").head(8)[["rang", "site_nom", "commune", "surface_ha", "classe", "contraintes"]]
    top = top.assign(surface_ha=top["surface_ha"].map(nombre), contraintes=top["contraintes"].fillna("aucune"))
    E += [P("Les huit premières friches du classement", "h2"),
          tableau(top, [10, 48, 26, 14, 20, 52], ["N°", "Friche", "Commune", "ha", "Classe", "Contraintes"])]

    E.append(PageBreak())
    E.append(P("3. Principaux résultats", "h1"))
    E.append(P("Milieu naturel", "h2"))
    n2000 = zon[zon["code_couche"].isin(["zsc", "zps"])]
    z1 = zon[zon["code_couche"] == "znieff1"]
    txt = f"{len(zon)} zonages du patrimoine naturel, paysager ou de risque sont recensés dans l'aire éloignée. "
    if not z1.empty:
        o = z1.sort_values("distance_zip_m").iloc[0]
        txt += (f"La ZNIEFF de type I la plus proche, « {o['nom']} », est "
                + ("sur la ZIP" if o["distance_zip_m"] == 0 else f"à {distance(o['distance_zip_m'])}") + ". ")
    txt += ("Aucun site Natura 2000 n'est présent dans l'aire éloignée ; l'évaluation des incidences reste à "
            "conduire, par simple vérification de l'absence d'effet." if n2000.empty else
            f"Le site Natura 2000 le plus proche est à {distance(n2000['distance_zip_m'].min())}.")
    E.append(P(txt))
    pat = esp[esp["patrimoniale"]]
    annexes = esp[esp["directives"].fillna("") != ""]
    E.append(P(f"Les données publiées sur GBIF depuis 2010 citent {len(esp)} espèces dans l'aire rapprochée, dont "
               f"{int(esp['protegee'].sum())} protégées et {len(pat)} patrimoniales (listes rouges nationale et "
               "régionale, directives européennes, espèces déterminantes de ZNIEFF)."
               + (" Espèces inscrites aux annexes des directives : " + ", ".join(
                   f"{r.nom_francais or r.nom_scientifique} ({r.directives})" for r in annexes.head(5).itertuples())
                  + "." if not annexes.empty else "")
               + " Ces données sont opportunistes : elles disent où chercher, pas ce qui manque."))
    E.append(tableau(grp.head(8)[["groupe", "especes", "protegees", "patrimoniales", "donnees"]],
                     [50, 28, 28, 30, 28], ["Groupe", "Espèces", "Protégées", "Patrimoniales", "Données"]))
    t = pat.head(10)[["nom_francais", "groupe", "protegee", "directives", "liste_rouge_nationale",
                      "liste_rouge_regionale"]].copy()
    t["protegee"] = t["protegee"].map(lambda v: "oui" if v else "non")
    E += [Spacer(1, 5), tableau(t, [42, 22, 18, 30, 26, 26], ["Espèce", "Groupe", "Protégée", "Directives",
                                                              "Liste rouge France", "Liste rouge régionale"]),
          P("Tableau. Les espèces patrimoniales les plus citées (statuts TAXREF du MNHN).", "leg")]

    E.append(P("Occupation du sol : trois sources comparées", "h2"))
    E.append(P("L'OCS GE de l'IGN (vecteur, produite en partie par apprentissage profond), Corine Land Cover "
               "(photo-interprétation, unité minimale de 25 ha) et OSO du CESBIO (classification automatique "
               "d'images Sentinel-2 à 10 m) ont été ramenées à six classes communes sur la grille d'OSO. Leur "
               "accord est mesuré par la part de pixels classés pareil et par le kappa de Cohen, qui retire "
               "l'accord dû au hasard."))
    a = acc[acc["aire"].isin(["zip", "rapprochee", "eloignee"])].copy()
    a["aire"] = a["aire"].map({"zip": "ZIP", "rapprochee": "Aire rapprochée", "eloignee": "Aire éloignée"})
    a["accord"] = a["accord"].map(lambda v: f"{v:.0%}")
    a["kappa"] = a["kappa"].map(lambda v: nombre(v, 2))
    E.append(tableau(a[["aire", "comparaison", "accord", "kappa"]], [32, 78, 25, 25],
                     ["Aire", "Comparaison", "Accord", "Kappa"]))
    if (IMG / "graphique_trois_sources.png").exists():
        E += [Spacer(1, 4), Image(str(IMG / "graphique_trois_sources.png"), width=165 * mm, height=60 * mm),
              P("Figure 2. Répartition des six classes selon chaque source dans l'aire rapprochée.", "leg")]
    zs = sources_ocs[sources_ocs["aire"] == "zip"]
    dom = zs.sort_values("surface_ha", ascending=False).groupby("source").head(1)
    E.append(P("Dans la ZIP, la classe dominante est « " + " », « ".join(
        f"{r.libelle.lower()} » pour {r.source} ({nombre(r.surface_ha)} ha" for r in dom.itertuples()) + ") . "
        "Corine Land Cover ne suit pas les limites d'un site de quelques hectares ; OSO repère les surfaces "
        "artificialisées mais confond friches herbacées, jardins et prairies. L'OCS GE reste la référence pour "
        "décrire le site, les deux autres servent au contexte de l'aire éloignée."))

    E.append(P("Urbanisme, servitudes et foncier", "h2"))
    if not zz.empty:
        E.append(P("Zones du document d'urbanisme sur la ZIP : " + "; ".join(
            f"{r.zone}, {r.part:.0%} ({r.intitule[0].lower() + r.intitule[1:]})" for r in zz.itertuples()) + "."))
    sz = serv[serv["position"] == "Dans la ZIP"] if not serv.empty else serv
    if not sz.empty:
        E.append(P("Servitudes d'utilité publique sur la ZIP : " + ", ".join(sorted(set(sz["servitude"].str.lower())))
                   + ". Les gestionnaires sont à consulter dès la conception."))
    if not fon.empty:
        E.append(P(f"Les {int(fon['nb_parcelles'].sum())} parcelles de la ZIP relèvent de "
                   + "; ".join(f"{r.proprietaire.lower()} ({r.nb_parcelles} parcelle(s), {nombre(r.surface_zip_ha)} ha)"
                               for r in fon.itertuples())
                   + ". Seul le fichier des personnes morales de la DGFiP est ouvert ; par discrétion, les "
                     "personnes morales de droit privé ne sont pas nommées et les personnes physiques ne sont pas "
                     "recherchées (leurs données relèvent des fichiers fonciers, diffusés sous convention)."))

    E.append(PageBreak())
    E.append(P("4. Hiérarchisation des enjeux", "h1"))
    E.append(P("Chaque sujet reçoit un niveau selon des règles écrites à l'avance (colonne « règle » du tableur). La "
               "grille est indicative : elle prépare le travail des experts sans le remplacer, et les inventaires "
               "de terrain pourront relever ou abaisser chaque niveau."))
    t = enj[["theme", "sujet", "niveau", "justification"]].copy()
    t["justification"] = t["justification"].map(lambda s: s if len(s) < 330 else s[:327].rsplit(" ", 1)[0] + "…")
    E.append(tableau(t, [26, 34, 16, 94], ["Thème", "Sujet", "Niveau", "Justification"], couleur_col=2))

    E.append(P("5. Limites et suites à donner", "h1"))
    E += puces([
        "Les inventaires faune-flore sur un cycle biologique complet et la délimitation réglementaire des zones "
        "humides (critères sol et végétation) restent indispensables.",
        "Cartofriches doit être contrôlé : une partie des friches recensées est déjà reconstruite. Le croisement "
        "avec l'usage OCS GE et la photographie aérienne fait partie de la méthode.",
        "Les données GBIF sont hétérogènes (sciences participatives, jeux de données associatifs) et ne "
        "remplacent pas une extraction des bases naturalistes régionales.",
        "Le service des installations classées du BRGM était indisponible lors de la production ; les PPRT et "
        "les servitudes PM2 et PM3 couvrent les installations à risque.",
        "Les fichiers fonciers (DGFiP / Cerema) ne sont pas ouverts : avec la convention d'un bureau d'études, ils "
        "compléteraient l'analyse de la maîtrise foncière.",
        "Les aires d'étude sont des distances fixes ; une analyse de visibilité sur modèle numérique de terrain "
        "affinerait l'aire éloignée pour le paysage."])
    E.append(P("6. Reproduire et réutiliser", "h1"))
    E.append(P("La chaîne se relance avec <i>python scripts/run_all.py</i>. Pour un autre site, l'extension QGIS "
               "« État initial » produit les mêmes données, le même projet et le même atlas à partir d'un polygone "
               "dessiné ou importé, n'importe où en France métropolitaine. Les relevés des écologues saisis avec "
               "QField reviennent dans la base après contrôle (<i>scripts/10_import_terrain.py</i>)."))
    E.append(P("Sources", "h2"))
    E.append(P("IGN (ADMIN EXPRESS, BD TOPO, BD Forêt v2, Parcellaire Express, OCS GE 2.0, RPG 2024, BD ORTHO, "
               "Plan IGN v2) ; INPN / PatriNat (zonages) ; MNHN (TAXREF, statuts) ; GBIF ; Géo2France (zones à "
               "dominante humide, Mission Bassin Minier, Cartofriches du Cerema) ; BRGM / Géorisques ; Géoportail "
               "de l'Urbanisme ; DGFiP (personnes morales) ; Copernicus / SDES (Corine Land Cover 2018) ; CESBIO / "
               "Theia (OSO 2023). Données sous Licence Ouverte 2.0 ou licences des producteurs."))
    doc.build(E, onFirstPage=pied, onLaterPages=pied)
    log(f"Note : {sortie.name} ({len(pymupdf.open(sortie))} pages)")


def bordereau(S):
    sortie = DOCS_DIR / "00_Bordereau_de_livraison.pdf"
    doc = SimpleDocTemplate(str(sortie), pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm,
                            topMargin=20 * mm, bottomMargin=20 * mm, title="Bordereau de livraison")
    lignes = [
        ("01_Documents", "00_Bordereau_de_livraison.pdf", "Ce bordereau"),
        ("01_Documents", "01_Note_methodologique.pdf", "Démarche, criblage, résultats, enjeux, limites"),
        ("02_Donnees_SIG", "etat_initial.gpkg", "GeoPackage : couches de l'étude et tableaux (QGIS)"),
        ("02_Donnees_SIG", "etat_initial.gdb", "Géodatabase fichier, mêmes données (ArcGIS Pro)"),
        ("02_Donnees_SIG", "etat_initial.qgz", "Projet QGIS : couches symbolisées, thèmes, 18 mises en page"),
        ("02_Donnees_SIG", "rasters/", "OSO 2023 découpé, classes harmonisées, concordance des sources"),
        ("02_Donnees_SIG", "modeles/", "Trois modèles du modeleur graphique QGIS (.model3), aussi intégrés au projet"),
        ("03_Atlas", "Atlas_etat_initial.pdf", "Atlas A3 : couverture, sommaire et 18 cartes"),
        ("03_Atlas", "planches/", "Chaque carte en PDF"),
        ("04_Tableaux", "Etat_initial_tableaux.xlsx", "Enjeux, zonages, occupation du sol, urbanisme, foncier, "
                                                      "risques, espèces"),
        ("05_Concertation", "Planche_concertation.svg et .pdf", "Planche pour réunion publique (Inkscape)"),
        ("06_Terrain", "qfield/", "Projet QField pour les inventaires des écologues"),
    ]
    E = [P("Bordereau de livraison", "titre"), P(f"État initial de l'environnement : {S['nom']} ({S['commune']})",
                                                 "sous"), Spacer(1, 10),
         tableau(pd.DataFrame(lignes, columns=["Dossier", "Fichier", "Contenu"]), [32, 58, 80]), Spacer(1, 10),
         P(f"Système de coordonnées : RGF93 / Lambert-93 (EPSG:2154). Date de production : {date.today():%d/%m/%Y}. "
           f"Réalisation : {config.AUTEUR}. {config.CARTOUCHE}")]
    doc.build(E, onFirstPage=pied, onLaterPages=pied)
    log(f"Bordereau : {sortie.name}")


if __name__ == "__main__":
    S = site()
    titres = atlas(S)
    carte_criblage(S)
    graphique_ocs()
    note(titres, S)
    bordereau(S)
