"""Analyses de l'état initial : inventaire des zonages, occupation du sol, urbanisme,
servitudes, foncier, risques, réseaux, effets cumulés et données naturalistes.

Chaque fonction prend les couches collectées (dict {nom: GeoDataFrame}) et les aires
d'étude, et renvoie un tableau prêt pour l'atlas, le tableur et la note.
"""
import ast
import re

import geopandas as gpd
import pandas as pd

from .aires import AIRES, geom_aire, positionner
from .parametres import CATALOGUE, LIBELLE_AIRE, OCSGE_COUVERTURE, OCSGE_USAGE, SUP_LIBELLES

ORDRE_AIRE = {a: i for i, a in enumerate(AIRES + ("hors",))}
POSITION = {"zip": "Dans la ZIP", "immediate": "Aire immédiate", "rapprochee": "Aire rapprochée",
            "eloignee": "Aire éloignée", "hors": "Hors aires"}


def _vide(d, nom):
    return nom not in d or d[nom] is None or d[nom].empty


def part_zip(gdf, aires):
    """Part de la ZIP couverte par la couche (0 à 1), sans double compte."""
    if gdf.empty:
        return 0.0
    z = geom_aire(aires, "zip")
    inter = gdf[gdf.intersects(z)]
    if inter.empty:
        return 0.0
    return round(inter.geometry.intersection(z).union_all().area / z.area, 3)


# --- Zonages ---------------------------------------------------------------------------------------
ZONAGES = ["zsc", "zps", "apb", "rnn", "rnr", "rb", "cen", "ramsar", "pnr", "znieff1", "znieff2",
           "unesco_bien", "unesco_tampon", "terril_unesco", "ppr_inond", "ppr_mvt", "ppr_minier", "pprt"]
THEME_ZONAGE = {"nature": "Milieu naturel", "patrimoine": "Paysage et patrimoine",
                "risques": "Milieu physique et risques", "eau": "Milieu physique et risques"}


def inventaire_zonages(d, aires):
    """Un objet par ligne : type, nom, aire atteinte, distance à la ZIP, part de la ZIP couverte."""
    lignes = []
    for code in ZONAGES:
        if _vide(d, code):
            continue
        g = positionner(d[code], aires)
        for _, o in g.iterrows():
            fiche = CATALOGUE[code]
            nom = o.get("nom") or o.get("element") or ""
            if code == "unesco_tampon":
                nom = "Zone tampon du Bassin minier"
            lignes.append({
                "theme": THEME_ZONAGE[fiche["theme"]], "code_couche": code, "type": fiche["libelle"],
                "identifiant": o.get("code") or o.get("terril") or o.get("element"),
                "nom": nom, "position": o["position"], "aire": POSITION[o["position"]],
                "distance_zip_m": int(o["distance_zip_m"]),
                "part_zip": part_zip(gpd.GeoDataFrame([o], crs=g.crs), aires),
                "surface_totale_ha": o.get("surface_totale_ha"), "url": o.get("url")})
    tab = pd.DataFrame(lignes)
    if tab.empty:
        return tab
    # un même zonage peut être livré en plusieurs morceaux : on garde le plus proche
    tab = (tab.sort_values("distance_zip_m")
              .drop_duplicates(["code_couche", "identifiant", "nom"])
              .assign(o=lambda t: t["position"].map(ORDRE_AIRE))
              .sort_values(["theme", "o", "distance_zip_m"]).drop(columns="o"))
    return tab.reset_index(drop=True)


def zones_humides(d, aires):
    """Zones à dominante humide : surface par milieu dans chaque aire."""
    if _vide(d, "zdh"):
        return pd.DataFrame()
    lignes = []
    for _, a in aires.iterrows():
        z = d["zdh"].clip(a.geometry)
        if z.empty:
            continue
        for milieu, s in z.assign(ha=z.area / 10_000).groupby("milieu")["ha"].sum().items():
            lignes.append({"aire": LIBELLE_AIRE[a["aire"]], "milieu": str(milieu).capitalize(),
                           "surface_ha": round(s, 2)})
    return pd.DataFrame(lignes)


# --- Occupation du sol -----------------------------------------------------------------------------
def occupation_ocsge(occ, aires, aires_retenues=("zip", "immediate", "rapprochee")):
    """Couverture et usage OCS GE (ha et part) dans les aires demandées."""
    lignes = []
    for aire in aires_retenues:
        g = geom_aire(aires, aire)
        o = occ.clip(g)
        o = o.assign(ha=o.area / 10_000)
        tot = g.area / 10_000
        for (cs, us), s in o.groupby(["code_cs", "code_us"])["ha"].sum().items():
            lignes.append({"aire": LIBELLE_AIRE[aire], "code_cs": cs,
                           "couverture": OCSGE_COUVERTURE.get(cs, cs), "code_us": us,
                           "usage": OCSGE_USAGE.get(us, us), "surface_ha": round(s, 2),
                           "part": round(s / tot, 4)})
    return pd.DataFrame(lignes)


def evolution_ocsge(diff, aires):
    """Changements de couverture 2021-2025 (OCS GE différentielle) dans l'aire rapprochée."""
    if diff is None or diff.empty:
        return pd.DataFrame()
    g = positionner(diff, aires)
    g = g[g["position"].isin(["zip", "immediate", "rapprochee"])].copy()
    g["surface_ha"] = (g.area / 10_000).round(2)
    g["avant"] = g["cs_avant"].map(OCSGE_COUVERTURE).fillna(g["cs_avant"])
    g["apres"] = g["cs_apres"].map(OCSGE_COUVERTURE).fillna(g["cs_apres"])
    artif = lambda cs: str(cs).startswith("CS1.1")  # noqa: E731
    g["sens"] = [("Artificialisation" if artif(b) and not artif(a) else
                  "Renaturation" if artif(a) and not artif(b) else "Autre changement")
                 for a, b in zip(g["cs_avant"], g["cs_apres"])]
    return g


# --- Urbanisme ---------------------------------------------------------------------------------------
TYPEZONE = {"U": "Zone urbaine (U)", "AUc": "Zone à urbaniser ouverte (AUc)",
            "AUs": "Zone à urbaniser fermée (AUs)", "A": "Zone agricole (A)", "N": "Zone naturelle (N)",
            "Nh": "Secteur de taille et capacité limitées (Nh)", "Ah": "Secteur de taille et capacité limitées (Ah)"}
# Types de prescriptions du standard CNIG dont le sens est vérifié dans les données ; pour les
# autres, le libellé le plus fréquent du document sert de catégorie
TYPEPSC = {"01": "Espace boisé classé", "02": "Constructibilité limitée (risques, nuisances, environnement)",
           "05": "Emplacement réservé", "07": "Patrimoine bâti, paysager ou écologique protégé",
           "16": "Bâtiment pouvant changer de destination", "18": "Orientation d'aménagement (OAP)",
           "22": "Linéaire de diversité commerciale", "24": "Chemin ou cheminement à conserver",
           "25": "Continuité écologique (trame verte et bleue)"}


def zonage_site(d, aires):
    """Zones du document d'urbanisme recoupant la ZIP et l'aire immédiate, avec leur surface."""
    if _vide(d, "zone_urba"):
        return pd.DataFrame()
    lignes = []
    for aire in ("zip", "immediate"):
        g = geom_aire(aires, aire)
        z = d["zone_urba"].clip(g)
        z = z.assign(ha=z.area / 10_000)
        for (lib, typ, long_), s in z.groupby(["libelle", "typezone", "libelong"], dropna=False)["ha"].sum().items():
            if s < 0.01:
                continue
            lignes.append({"aire": LIBELLE_AIRE[aire], "zone": lib, "type": TYPEZONE.get(typ, typ),
                           "intitule": long_, "surface_ha": round(s, 2),
                           "part": round(s / (g.area / 10_000), 3)})
    return pd.DataFrame(lignes)


def prescriptions_site(d, aires):
    lignes = []
    for nom in ("prescription_surf", "prescription_lin", "prescription_pct", "info_surf"):
        if _vide(d, nom):
            continue
        g = positionner(d[nom], aires)
        g = g[g["position"].isin(["zip", "immediate"])]
        champ = "typepsc" if "typepsc" in g.columns else "typeinf"
        frequent = g.groupby(champ)["libelle"].agg(lambda s: s.value_counts().index[0][:70])
        for (lib, typ, pos), grp in g.groupby(["libelle", champ, "position"]):
            lignes.append({"nature": "Information" if nom == "info_surf" else "Prescription",
                           "categorie": TYPEPSC.get(typ, frequent[typ]) if nom != "info_surf" else "Information",
                           "libelle": lib, "position": POSITION[pos], "nb_objets": len(grp),
                           "distance_zip_m": int(grp["distance_zip_m"].min())})
    return pd.DataFrame(lignes).sort_values(["position", "categorie"]) if lignes else pd.DataFrame()


def servitudes_site(d, aires):
    """Servitudes d'utilité publique (assiettes) par type et par aire atteinte."""
    morceaux = [d[n] for n in ("assiette_sup_s", "assiette_sup_l", "assiette_sup_p") if not _vide(d, n)]
    if not morceaux:
        return pd.DataFrame()
    g = positionner(gpd.GeoDataFrame(pd.concat(morceaux, ignore_index=True), crs=morceaux[0].crs), aires)
    lignes = []
    for (sup, pos), grp in g.groupby(["suptype", "position"]):
        lignes.append({"code": sup, "servitude": SUP_LIBELLES.get(sup, sup), "position": POSITION[pos],
                       "o": ORDRE_AIRE[pos], "nb_objets": len(grp),
                       "distance_zip_m": int(grp["distance_zip_m"].min()),
                       "exemples": ", ".join(sorted(set(str(x) for x in grp["nomass"].dropna()))[:3])})
    return pd.DataFrame(lignes).sort_values(["o", "code"]).drop(columns="o").reset_index(drop=True)


# --- Foncier ----------------------------------------------------------------------------------------------
GROUPES_PUBLICS = ("1 -", "2 -", "3 -", "4 -", "5 -", "6 -", "9 -")  # État, région, département, commune...


def foncier_site(d, aires):
    """Parcelles de la ZIP et nature des propriétaires (personnes morales seulement).

    Les personnes morales de droit privé sont regroupées sans être nommées ; les personnes
    physiques ne figurent dans aucune source ouverte et ne sont pas recherchées.
    """
    if _vide(d, "parcelle"):
        return pd.DataFrame(), pd.DataFrame()
    p = d["parcelle"].copy()
    p = p[p["part_dans_zip"] >= 0.05]  # parcelles réellement concernées par la ZIP
    pm = d.get("proprietaire_pm", pd.DataFrame(columns=["idu", "groupe", "denomination"]))
    p = p.merge(pm[["idu", "groupe", "denomination"]].drop_duplicates("idu"), on="idu", how="left")
    p["groupe"] = p["groupe"].fillna("Propriétaire non diffusé (hors fichier des personnes morales)")
    p["proprietaire"] = [
        den.title() if isinstance(den, str) and str(gr).startswith(GROUPES_PUBLICS) else
        ("Personne morale de droit privé" if str(gr).startswith(("0 -", "7 -", "8 -")) else
         "Propriétaire non diffusé" if str(gr).startswith("Propriétaire non diffusé") else gr)
        for den, gr in zip(p["denomination"], p["groupe"])]
    p["groupe"] = p["groupe"].str.replace(r"^\d+ - ", "", regex=True)
    p["surface_zip_ha"] = (p.geometry.intersection(geom_aire(aires, "zip")).area / 10_000).round(2)
    synthese = (p.groupby(["groupe", "proprietaire"])
                 .agg(nb_parcelles=("idu", "count"), surface_zip_ha=("surface_zip_ha", "sum"))
                 .reset_index().sort_values("surface_zip_ha", ascending=False))
    return p.drop(columns=["denomination"]), synthese


# --- Risques, réseaux, effets cumulés ------------------------------------------------------------------------
def risques_site(d, aires):
    lignes = []
    for code in ("ppr_inond", "ppr_mvt", "ppr_minier", "pprt", "cavite", "mvt", "nappe", "sis",
                 "ssp"):
        if _vide(d, code):
            lignes.append({"risque": CATALOGUE[code]["libelle"], "present": "Aucun objet recensé",
                           "position": "-", "distance_zip_m": None, "detail": ""})
            continue
        g = positionner(d[code], aires).sort_values("distance_zip_m")
        o = g.iloc[0]
        detail = o.get("nom") or o.get("classe") or o.get("type") or ""
        if code == "nappe":
            g_zip = g[g["position"] == "zip"]
            detail = "; ".join(sorted(set(g_zip["classe"]))) if not g_zip.empty else detail
        lignes.append({"risque": CATALOGUE[code]["libelle"], "present": f"{len(g)} objet(s)",
                       "position": POSITION[o["position"]], "distance_zip_m": int(o["distance_zip_m"]),
                       "detail": str(detail)})
    return pd.DataFrame(lignes)


def reseaux_site(d, aires):
    lignes = []
    if not _vide(d, "ligne_elec"):
        g = positionner(d["ligne_elec"], aires)
        for v, grp in g.groupby("voltage"):
            lignes.append({"objet": f"Ligne électrique {v}", "nombre": len(grp),
                           "distance_zip_m": int(grp["distance_zip_m"].min()),
                           "position": POSITION[grp.sort_values("distance_zip_m")["position"].iloc[0]]})
    if not _vide(d, "poste_elec"):
        g = positionner(d["poste_elec"], aires)
        lignes.append({"objet": "Poste de transformation électrique", "nombre": len(g),
                       "distance_zip_m": int(g["distance_zip_m"].min()),
                       "position": POSITION[g.sort_values("distance_zip_m")["position"].iloc[0]]})
    for code, lib in (("parc_pv", "Parc photovoltaïque au sol existant"), ("eolienne", "Éolienne")):
        if _vide(d, code):
            lignes.append({"objet": lib, "nombre": 0, "distance_zip_m": None, "position": "-"})
            continue
        g = positionner(d[code], aires)
        detail = ""
        if code == "eolienne":
            detail = ", ".join(sorted(set(str(x).title() for x in g["parc"].dropna())))
        lignes.append({"objet": lib + (f" ({detail})" if detail else ""), "nombre": len(g),
                       "distance_zip_m": int(g["distance_zip_m"].min()),
                       "position": POSITION[g.sort_values("distance_zip_m")["position"].iloc[0]]})
    return pd.DataFrame(lignes)


def riverains(d, aires):
    """Bâtiments d'habitation dans l'aire immédiate et distance du plus proche."""
    if _vide(d, "batiment"):
        return {"nb_habitations": 0, "distance_min_m": None}
    b = positionner(d["batiment"], aires)
    hab = b[b["usage_1"].isin(["Résidentiel", "Indifférencié"]) & b["position"].isin(["zip", "immediate"])]
    return {"nb_habitations": int((hab["usage_1"] == "Résidentiel").sum()),
            "nb_logements": int(pd.to_numeric(hab["nombre_de_logements"], errors="coerce").fillna(0).sum()),
            "distance_min_m": int(hab["distance_zip_m"].min()) if not hab.empty else None}


# --- Données naturalistes -------------------------------------------------------------------------------------
REGION = ("Hauts-de-France", "Nord-Pas-de-Calais")
MENACE = {"CR": 4, "EN": 3, "VU": 2, "NT": 1}
GROUPES = {"Aves": "Oiseaux", "Mammalia": "Mammifères", "Amphibia": "Amphibiens",
           "Squamata": "Reptiles", "Testudines": "Reptiles", "Insecta": "Insectes",
           "Arachnida": "Arachnides", "Actinopterygii": "Poissons", "Gastropoda": "Mollusques",
           "Bivalvia": "Mollusques", "Magnoliopsida": "Plantes à fleurs", "Liliopsida": "Plantes à fleurs",
           "Polypodiopsida": "Fougères", "Pinopsida": "Conifères", "Bryopsida": "Mousses",
           "Lecanoromycetes": "Lichens", "Agaricomycetes": "Champignons"}


def _pire(codes):
    codes = [c for c in codes if c in MENACE]
    return max(codes, key=MENACE.get) if codes else None


def especes(tab):
    """Statuts utiles à l'étude d'impact pour chaque espèce citée dans l'aire rapprochée."""
    lignes = []
    for _, e in tab.iterrows():
        statuts = e["statuts"]
        if isinstance(statuts, str):
            statuts = ast.literal_eval(statuts)
        def pris(type_, lieux=None, prefixe=None):  # noqa: E306
            return [s["code"] for s in statuts if s["type"] == type_
                    and (lieux is None or s["lieu"] in lieux)
                    and (prefixe is None or str(s["code"]).startswith(prefixe))]
        protegee = bool(pris("Protection nationale", ("France métropolitaine",)))
        dh = sorted(set(pris("Directive Habitat", None)) | set(pris("Directive Habitats", None)))
        do = sorted(set(pris("Directive Oiseaux", None)))
        lrn = _pire(pris("Liste rouge nationale", ("France métropolitaine",)))
        lrr = _pire(pris("Liste rouge régionale", REGION))
        zdet = any(s["type"] == "ZNIEFF Déterminantes" and s["lieu"] in REGION for s in statuts)
        annexes = [c for c in dh if c in ("CDH2", "CDH4")] + [c for c in do if c == "CDO1"]
        lignes.append({
            "nom_scientifique": e["nom_scientifique"],
            # TAXREF place l'article en fin de nom (« Crapaud calamite (Le) ») : on le retire
            "nom_francais": re.sub(r"\s*\((Le|La|Les|L')\)$", "", e["nom_francais"])
            if isinstance(e.get("nom_francais"), str) else None,
            "groupe": GROUPES.get(e.get("classe")) or {"Fungi": "Champignons", "Plantae": "Autres plantes",
                                                       "Animalia": "Autres animaux"}.get(e.get("regne"), "Autres"),
            "nb_donnees": int(e["nb_donnees"]), "protegee": protegee,
            "directives": ", ".join({"CDH2": "DH annexe II", "CDH4": "DH annexe IV",
                                     "CDO1": "DO annexe I"}[c] for c in annexes),
            "liste_rouge_nationale": lrn, "liste_rouge_regionale": lrr, "determinante_znieff": zdet,
            "patrimoniale": bool(annexes or lrn or lrr or zdet), "cd_nom": e.get("cd_nom"),
            "species_key": e["species_key"]})
    t = pd.DataFrame(lignes)
    return t.sort_values(["patrimoniale", "protegee", "nb_donnees"], ascending=False).reset_index(drop=True)


def synthese_especes(t):
    if t.empty:
        return pd.DataFrame()
    return (t.groupby("groupe")
             .agg(especes=("nom_scientifique", "count"), protegees=("protegee", "sum"),
                  patrimoniales=("patrimoniale", "sum"), donnees=("nb_donnees", "sum"))
             .sort_values("especes", ascending=False).reset_index())
