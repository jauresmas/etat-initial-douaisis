"""Hiérarchisation des enjeux de l'état initial.

La grille est indicative : elle classe chaque sujet de « Nul » à « Très fort » selon la
présence de l'enjeu sur le site et sa distance, à partir des seules données disponibles
à distance. Elle prépare le travail des experts (écologues, paysagistes) sans le
remplacer : les inventaires de terrain peuvent relever ou abaisser chaque niveau.
"""
import geopandas as gpd
import pandas as pd

from .aires import geom_aire, positionner
from .analyse import POSITION, part_zip
from .parametres import CATALOGUE, CRS

NIVEAUX = ["Nul", "Faible", "Modéré", "Fort", "Très fort"]
COULEUR_NIVEAU = {"Très fort": "#7f0000", "Fort": "#d7301f", "Modéré": "#fc8d59",
                  "Faible": "#fdd49e", "Nul": "#f0f0f0"}
THEMES = ["Milieu physique et risques", "Milieu naturel", "Paysage et patrimoine", "Milieu humain"]


def _ha(x):
    return f"{x:.1f}".replace(".", ",") + " ha"


def _dist(m):
    if m is None or pd.isna(m):
        return "-"
    return f"{m / 1000:.1f}".replace(".", ",") + " km" if m >= 1000 else f"{int(m)} m"


def _ou(m):
    """« dans la ZIP » ou « à 350 m de la ZIP »."""
    return "dans la ZIP" if m is not None and not pd.isna(m) and m <= 0 else f"à {_dist(m)} de la ZIP"

MINIER = r"puits|mines?|minier|dynamit"


def _plus_proche(d, codes, aires):
    """Objet le plus proche de la ZIP parmi plusieurs couches ; None si aucune donnée."""
    morceaux = [d[c].assign(couche=c) for c in codes if c in d and not d[c].empty]
    if not morceaux:
        return None, None
    g = positionner(gpd.GeoDataFrame(pd.concat(morceaux, ignore_index=True), crs=CRS), aires)
    g = g.sort_values("distance_zip_m")
    return g.iloc[0], g


def _niveau(position, grille):
    """grille : niveaux pour (zip, immediate, rapprochee, eloignee, hors)."""
    ordre = ["zip", "immediate", "rapprochee", "eloignee", "hors"]
    return grille[ordre.index(position)] if position in ordre else grille[-1]


def _decoupe(g, aires, aire="rapprochee"):
    if g is None or g.empty:
        return None
    zone = geom_aire(aires, aire)
    geom = g.geometry.intersection(zone)
    geom = geom[~geom.is_empty]
    if geom.empty:
        return None
    return geom.union_all()


class Grille:
    def __init__(self, d, aires, tables):
        self.d, self.aires, self.t = d, aires, tables
        self.lignes = []

    def ajouter(self, theme, sujet, niveau, justification, geom=None, regle=""):
        self.lignes.append({"theme": theme, "sujet": sujet, "niveau": niveau,
                            "justification": justification, "regle": regle, "geometry": geom})

    def zonage(self, theme, sujet, codes, grille, conseil, regle):
        o, g = _plus_proche(self.d, codes, self.aires)
        if o is None or o["position"] == "hors":
            self.ajouter(theme, sujet, "Nul", "Aucun zonage dans l'aire éloignée.", regle=regle)
            return
        niveau = _niveau(o["position"], grille)
        nom = o.get("nom") if isinstance(o.get("nom"), str) and o.get("nom") else ""
        ident = o.get("code") if isinstance(o.get("code"), str) else ""
        lib = CATALOGUE[o["couche"]]["libelle"]
        if o["position"] == "zip":
            pz = part_zip(g[g["position"] == "zip"], self.aires)
            ou = f"recoupe la ZIP ({pz:.0%} de sa surface)"
        else:
            ou = f"à {_dist(o['distance_zip_m'])} de la ZIP ({POSITION[o['position']].lower()})"
        n_proches = int(g["position"].isin(["zip", "immediate", "rapprochee"]).sum())
        texte = " ".join(x for x in (lib, ident, f"« {nom} »" if nom else "", ou) if x)
        if n_proches > 1:
            texte += f" ; {n_proches} zonages de ce type dans l'aire rapprochée"
        self.ajouter(theme, sujet, niveau, f"{texte}. {conseil}", _decoupe(g, self.aires), regle)


def hierarchiser(d, aires, tables):
    """Renvoie un GeoDataFrame des enjeux (une ligne par sujet) et sa géométrie éventuelle."""
    G = Grille(d, aires, tables)
    MN, MP, PP, MH = THEMES[1], THEMES[0], THEMES[2], THEMES[3]
    z = geom_aire(aires, "zip")
    ha_zip = z.area / 10_000

    # --- Milieu naturel ------------------------------------------------------------------
    G.zonage(MN, "Sites Natura 2000", ["zsc", "zps"],
             ["Très fort", "Fort", "Modéré", "Faible", "Nul"],
             "Une évaluation des incidences Natura 2000 accompagne l'étude d'impact ; elle "
             "porte sur les espèces et habitats ayant justifié la désignation du site.",
             "ZIP : très fort ; aire immédiate : fort ; rapprochée : modéré ; éloignée : faible")
    G.zonage(MN, "Protections réglementaires (réserves, arrêtés de biotope)", ["rnn", "rnr", "apb", "rb"],
             ["Très fort", "Fort", "Modéré", "Faible", "Nul"],
             "Les fonctionnalités écologiques entre la réserve et le site sont à analyser.",
             "ZIP : très fort ; immédiate : fort ; rapprochée : modéré ; éloignée : faible")
    G.zonage(MN, "ZNIEFF de type I", ["znieff1"], ["Fort", "Modéré", "Faible", "Faible", "Nul"],
             "Les espèces déterminantes de la ZNIEFF orientent les inventaires de terrain.",
             "ZIP : fort ; immédiate : modéré ; rapprochée et éloignée : faible")
    G.zonage(MN, "ZNIEFF de type II", ["znieff2"], ["Modéré", "Faible", "Faible", "Faible", "Nul"],
             "Grand ensemble naturel : vérifier les continuités écologiques avec le site.",
             "ZIP : modéré ; ailleurs : faible")
    G.zonage(MN, "Parc naturel régional, conservatoire, Ramsar", ["pnr", "cen", "ramsar"],
             ["Modéré", "Faible", "Faible", "Faible", "Nul"],
             "Engagements de la charte du parc et sites gérés à prendre en compte.",
             "ZIP : modéré ; ailleurs : faible")

    # zones humides pré-localisées
    zdh = d.get("zdh")
    if zdh is not None and not zdh.empty:
        pz = part_zip(zdh, aires)
        g = positionner(zdh, aires)
        if pz > 0.10:
            niv = "Fort"
        elif pz > 0:
            niv = "Modéré"
        elif (g["position"] == "immediate").any():
            niv = "Faible"
        else:
            niv = "Faible" if (g["position"] == "rapprochee").any() else "Nul"
        dmin = g["distance_zip_m"].min()
        txt = (f"Zones à dominante humide du SDAGE sur {pz:.0%} de la ZIP" if pz > 0 else
               f"Zone à dominante humide la plus proche à {_dist(dmin)} (couche régionale)")
        psc_ = tables.get("prescriptions")
        if psc_ is not None and not psc_.empty:
            zh_plu = psc_[psc_["libelle"].str.contains("humide", case=False)
                          & (psc_["position"] == POSITION["zip"])]
            if not zh_plu.empty:  # le PLU reporte une zone humide que la couche régionale ne place pas
                niv = max(niv, "Modéré", key=NIVEAUX.index)
                txt += (f" ; le PLU reporte pourtant {int(zh_plu['nb_objets'].sum())} périmètre(s) de zone humide "
                        "sur la ZIP : les deux sources divergent")
        G.ajouter(MN, "Zones humides", niv,
                  txt + ". Pré-localisation seulement : la délimitation réglementaire (critères sol et "
                  "végétation) se fait sur le terrain.", _decoupe(g, aires, "immediate"),
                  "ZIP > 10 % : fort ; ZIP > 0 : modéré ; aire immédiate : faible")

    # boisements et haies dans la ZIP
    foret = d.get("foret")
    bois = foret[~foret["tfv"].fillna("").str.contains("herbac|Lande", case=False)] if foret is not None else None
    s_bois = bois.clip(z).area.sum() / 10_000 if bois is not None and not bois.empty else 0
    haies = d.get("haie")
    l_haie = haies.clip(z).length.sum() if haies is not None and not haies.empty else 0
    niv = "Fort" if s_bois > 1 else "Modéré" if (s_bois > 0 or l_haie > 0) else "Faible"
    geoms = [x for x in (_decoupe(bois, aires, "immediate") if bois is not None else None,
                         _decoupe(haies.assign(geometry=haies.buffer(5)), aires, "immediate")
                         if haies is not None and not haies.empty else None) if x is not None]
    G.ajouter(MN, "Boisements et haies", niv,
              f"{_ha(s_bois)} de formations boisées (BD Forêt) et {int(l_haie)} m de haies dans la ZIP. "
              "Habitats d'espèces (oiseaux nicheurs, chiroptères) : défrichement soumis à autorisation "
              "selon les seuils du code forestier.",
              gpd.GeoSeries(geoms, crs=CRS).union_all() if geoms else None,
              "> 1 ha boisé dans la ZIP : fort ; boisement ou haie présents : modéré ; sinon faible")

    # végétation spontanée de friche (OCS GE)
    occ = tables.get("occupation")
    if occ is not None and not occ.empty:
        o = occ[occ["aire"] == "Zone d'implantation potentielle"]
        veg = o[o["code_cs"].str.startswith("CS2") & (o["code_us"] != "US1.1")]["part"].sum()
        niv = "Modéré" if veg > 0.30 else "Faible"
        G.ajouter(MN, "Végétation spontanée de la friche", niv,
                  f"{veg:.0%} de la ZIP en formations herbacées ou ligneuses hors agriculture (OCS GE "
                  f"{tables.get('annee_ocsge', '')}). Les friches accueillent souvent une flore pionnière et "
                  "des espèces de milieux ouverts (reptiles, insectes, oiseaux) : enjeu à préciser par les inventaires.",
                  None, "> 30 % de la ZIP : modéré ; sinon faible")

    # données naturalistes connues
    esp = tables.get("especes")
    if esp is not None and not esp.empty:
        n_pat, n_prot, n = int(esp["patrimoniale"].sum()), int(esp["protegee"].sum()), len(esp)
        niv = "Fort" if n_pat >= 10 else "Modéré" if n_pat >= 1 else "Faible"
        exemples = ", ".join(esp[esp["patrimoniale"]].head(4)["nom_francais"].fillna(
            esp[esp["patrimoniale"]].head(4)["nom_scientifique"]))
        G.ajouter(MN, "Espèces connues (bibliographie)", niv,
                  f"{n} espèces observées depuis 2010 dans l'aire rapprochée (GBIF), dont {n_prot} protégées "
                  f"et {n_pat} patrimoniales (listes rouges, directives, déterminantes ZNIEFF)"
                  + (f", par exemple {exemples}" if exemples else "") +
                  ". Données opportunistes, non exhaustives : un inventaire sur un cycle biologique complet reste nécessaire.",
                  None, "≥ 10 espèces patrimoniales : fort ; 1 à 9 : modéré ; aucune : faible")

    # --- Milieu physique et risques ------------------------------------------------------------
    o, g = _plus_proche(d, ["cours_eau", "plan_eau"], aires)
    if o is not None:
        niv = _niveau(o["position"], ["Fort", "Modéré", "Faible", "Faible", "Nul"])
        G.ajouter(MP, "Eaux superficielles", niv,
                  f"{'Cours' if o['couche'] == 'cours_eau' else 'Plan'} d'eau le plus proche "
                  f"{('« ' + o['nom'] + ' » ') if isinstance(o.get('nom'), str) else ''}{_ou(o['distance_zip_m'])}. "
                  "Gestion des eaux pluviales et des pollutions de chantier à prévoir.",
                  _decoupe(g, aires, "immediate"), "ZIP : fort ; immédiate : modéré ; au-delà : faible")
    nappe = d.get("nappe")
    if nappe is not None and not nappe.empty:
        g = positionner(nappe, aires)
        dans = g[g["position"] == "zip"]
        deb = dans["classe"].str.contains("débordement", case=False).any()
        cave = dans["classe"].str.contains("cave", case=False).any()
        niv = "Modéré" if deb else "Faible" if cave or not dans.empty else "Nul"
        nappe_plu = [i for i in tables.get("info_zip", []) if "nappe" in i.lower()]
        info = f" Le PLU signale aussi : « {'; '.join(nappe_plu)} »." if nappe_plu else ""
        G.ajouter(MP, "Eaux souterraines (remontées de nappe)", niv,
                  ("Zone potentiellement sujette aux débordements de nappe sur la ZIP" if deb else
                   "Sensibilité aux inondations de cave sur la ZIP" if cave else
                   "Pas de sensibilité forte cartographiée sur la ZIP") + f" (BRGM).{info}"
                  " Fondations des structures et stockage de produits à adapter.",
                  None,  # enjeu diffus (mailles de 250 m) : non cartographié en synthèse
                  "débordement de nappe dans la ZIP : modéré ; inondation de cave : faible")
    for codes, sujet, grille, conseil in (
            (["ppr_inond", "ppr_mvt", "ppr_minier"], "Risques naturels et miniers (PPR)",
             ["Fort", "Modéré", "Faible", "Nul", "Nul"], "Le règlement du PPR s'impose au projet."),
            (["pprt"], "Risques technologiques (PPRT)", ["Fort", "Modéré", "Faible", "Nul", "Nul"],
             "Zonage réglementaire du PPRT à consulter (prescriptions sur les constructions)."),
            (["cavite", "mvt"], "Cavités et mouvements de terrain", ["Fort", "Modéré", "Faible", "Nul", "Nul"],
             "Étude géotechnique préalable à prévoir.")):
        o, g = _plus_proche(d, codes, aires)
        if o is None or o["position"] in ("eloignee", "hors"):
            G.ajouter(MP, sujet, "Nul", "Aucun objet recensé dans l'aire rapprochée.",
                      regle="ZIP : fort ; immédiate : modéré ; rapprochée : faible")
            continue
        niv = _niveau(o["position"], grille)
        G.ajouter(MP, sujet, niv, f"{CATALOGUE[o['couche']]['libelle']} « {o.get('nom') or o.get('identifiant') or ''} » "
                  f"à {_dist(o['distance_zip_m'])} ({POSITION[o['position']].lower()}). {conseil}".replace(" «  »", ""),
                  _decoupe(g, aires, "immediate"), "ZIP : fort ; immédiate : modéré ; rapprochée : faible")
    psc = tables.get("prescriptions")
    if psc is not None and not psc.empty:
        mine = psc[psc["libelle"].str.contains(MINIER, case=False, regex=True)]
        if not mine.empty:
            pos = mine.sort_values("distance_zip_m").iloc[0]
            niv = "Fort" if pos["position"] == POSITION["zip"] else "Modéré"
            G.ajouter(MP, "Héritage minier (puits, périmètres inconstructibles)", niv,
                      f"{pos['libelle']} : {int(mine['nb_objets'].sum())} objet(s) du PLU, le plus proche "
                      f"{_ou(pos['distance_zip_m'])}. "
                      "Les périmètres inconstructibles autour des puits sont à exclure de l'implantation.",
                      _decoupe(d["prescription_surf"][d["prescription_surf"]["libelle"].str.contains(
                          MINIER, case=False, regex=True)], aires, "immediate"),
                      "dans la ZIP : fort ; dans l'aire immédiate : modéré")
    o, g = _plus_proche(d, ["sis", "ssp"], aires)
    niv = "Nul" if o is None else _niveau(o["position"], ["Modéré", "Faible", "Faible", "Nul", "Nul"])
    texte = ("Aucun secteur d'information sur les sols ni site en instruction à proximité. "
             if o is None else f"{CATALOGUE[o['couche']]['libelle']} « {o.get('nom', '')} » "
             f"{_ou(o['distance_zip_m'])}. ")
    basias = psc[psc["libelle"].str.contains("basias|basol", case=False)] if psc is not None and not psc.empty         else pd.DataFrame()
    if not basias.empty:  # anciens sites industriels signalés par le PLU
        dans = (basias["position"] == POSITION["zip"]).any()
        niv = max(niv, "Modéré" if dans else "Faible", key=NIVEAUX.index)
        texte += (f"Le PLU signale {int(basias['nb_objets'].sum())} ancien(s) site(s) industriel(s) (BASIAS), "
                  f"{'dont un dans la ZIP' if dans else 'dans l’aire immédiate'}. ")
    pollu_plu = [i for i in tables.get("info_zip", []) if any(m in i.lower() for m in ("basol", "pollu"))]
    if pollu_plu:  # information du PLU portée sur le site lui-même
        niv = max(niv, "Modéré", key=NIVEAUX.index)
        texte += f"Le PLU reporte sur la ZIP : « {'; '.join(pollu_plu)} ». "
    G.ajouter(MP, "Sols pollués", niv, texte + "L'historique industriel du site justifie un "
              "diagnostic de pollution avant travaux (terrassements, gestion des déblais).",
              None, "site pollué ou ancien site industriel dans la ZIP : modéré ; à proximité : faible")

    # --- Paysage et patrimoine --------------------------------------------------------------------
    G.zonage(PP, "Bassin minier patrimoine mondial (bien inscrit)", ["unesco_bien", "terril_unesco"],
             ["Très fort", "Fort", "Modéré", "Faible", "Nul"],
             "Covisibilités avec les éléments inscrits à étudier (photomontages depuis les points de vue).",
             "ZIP : très fort ; immédiate : fort ; rapprochée : modéré ; éloignée : faible")
    G.zonage(PP, "Zone tampon du patrimoine mondial", ["unesco_tampon"],
             ["Fort", "Modéré", "Modéré", "Faible", "Nul"],
             "Insertion paysagère à justifier au regard de la valeur universelle exceptionnelle du bien.",
             "ZIP : fort ; immédiate et rapprochée : modéré ; éloignée : faible")
    sup = tables.get("servitudes")
    for code, sujet in (("AC1", "Monuments historiques (abords)"), ("AC2", "Sites inscrits et classés")):
        s = sup[sup["code"] == code] if sup is not None and not sup.empty else pd.DataFrame()
        if s.empty:
            G.ajouter(PP, sujet, "Nul", "Aucune servitude de ce type dans l'aire rapprochée (GPU).",
                      regle="ZIP : fort ; immédiate : modéré ; rapprochée : faible")
            continue
        pos = s.iloc[0]["position"]
        niv = {POSITION["zip"]: "Fort", POSITION["immediate"]: "Modéré"}.get(pos, "Faible")
        G.ajouter(PP, sujet, niv, f"{s.iloc[0]['servitude']} : {pos.lower()}, à "
                  f"{_dist(s.iloc[0]['distance_zip_m'])} ({s.iloc[0]['exemples']}). "
                  "Avis de l'architecte des Bâtiments de France si le projet est dans les abords.",
                  None, "ZIP : fort ; immédiate : modéré ; rapprochée : faible")

    # --- Milieu humain --------------------------------------------------------------------------------
    zon = tables.get("zonage")
    if zon is not None and not zon.empty:
        zz = zon[zon["aire"] == "Zone d'implantation potentielle"]
        an = zz[zz["type"].str.contains(r"\((?:A|N)\)", regex=True)]["part"].sum()
        zones = ", ".join(f"{r.zone} ({r.part:.0%})" for r in zz.sort_values("part", ascending=False).itertuples())
        dedie = zz[zz["intitule"].fillna("").str.contains("photovolta", case=False)]["part"].sum()
        niv = "Fort" if an > 0.10 else "Faible" if dedie > 0.5 else "Modéré"
        G.ajouter(MH, "Document d'urbanisme", niv,
                  f"Zones du PLU sur la ZIP : {zones}. "
                  + ("Les zones agricoles ou naturelles n'admettent une centrale au sol que si le règlement "
                     "le prévoit : compatibilité à vérifier, évolution du PLU possible." if an > 0.10 else
                     f"Le PLU destine déjà {dedie:.0%} du site à une centrale photovoltaïque ; le règlement "
                     "du secteur fixe les règles à respecter (hauteur, clôtures, recul)." if dedie > 0.5 else
                     "Le règlement de zone est à vérifier (destination, hauteur, clôtures)."),
                  _decoupe(d["zone_urba"][d["zone_urba"]["typezone"].isin(["A", "N"])], aires, "zip")
                  if an > 0 else None,
                  "zones A ou N sur plus de 10 % de la ZIP : fort ; sinon modéré")
    if psc is not None and not psc.empty:
        dans = psc[psc["position"] == POSITION["zip"]]
        ebc = dans[dans["categorie"] == "Espace boisé classé"]
        autres = dans[~dans["categorie"].isin(["Espace boisé classé", "Information"])]
        niv = "Fort" if not ebc.empty else "Modéré" if not autres.empty else "Faible"
        detail = ", ".join(f"{cat.lower()} ({n})" for cat, n in
                           dans.groupby("categorie")["nb_objets"].sum().sort_values(ascending=False).items())
        G.ajouter(MH, "Prescriptions du PLU", niv,
                  (f"Prescriptions dans la ZIP : {detail}. " if detail else "Aucune prescription dans la ZIP. ")
                  + ("Un espace boisé classé interdit tout défrichement : à exclure de l'implantation."
                     if not ebc.empty else ""),
                  _decoupe(d["prescription_surf"][d["prescription_surf"]["typepsc"] == "01"], aires, "immediate")
                  if "prescription_surf" in d else None,
                  "espace boisé classé dans la ZIP : fort ; autre prescription : modéré")
    if sup is not None and not sup.empty:
        dans = sup[sup["position"].isin([POSITION["zip"], POSITION["immediate"]])]
        fortes = dans[dans["code"].isin(["AS1", "PM1", "PM3"]) & (dans["position"] == POSITION["zip"])]
        niv = "Fort" if not fortes.empty else "Modéré" if (dans["position"] == POSITION["zip"]).any() else \
            "Faible" if not dans.empty else "Nul"
        detail = "; ".join(f"{r.servitude} ({r.position.lower()})" for r in dans.itertuples())
        G.ajouter(MH, "Servitudes d'utilité publique", niv,
                  (detail or "Aucune servitude dans l'aire immédiate") +
                  ". Les gestionnaires (RTE, SNCF, etc.) sont à consulter sur les distances à respecter.",
                  None, "captage ou PPR dans la ZIP : fort ; autre servitude dans la ZIP : modéré ; immédiate : faible")
    riv = tables.get("riverains", {})
    dmin = riv.get("distance_min_m")
    niv = "Fort" if dmin is not None and dmin < 50 else "Modéré" if dmin is not None else "Faible"
    G.ajouter(MH, "Riverains", niv,
              (f"{riv.get('nb_habitations', 0)} bâtiments résidentiels dans l'aire immédiate, le plus proche "
               f"{'en limite de la ZIP' if dmin == 0 else _ou(dmin)}. Perceptions, éblouissement et nuisances de "
               "chantier à étudier."
               if dmin is not None else "Aucune habitation dans l'aire immédiate."),
              None, "habitation à moins de 50 m : fort ; dans l'aire immédiate : modéré ; sinon faible")
    rpg = d.get("rpg")
    s_agri = rpg.clip(z).area.sum() / 10_000 if rpg is not None and not rpg.empty else 0
    G.ajouter(MH, "Agriculture", "Fort" if s_agri > 1 else "Modéré" if s_agri > 0 else "Faible",
              f"{_ha(s_agri)} de parcelles déclarées à la PAC (RPG 2024) dans la ZIP. "
              + ("Consommation de terres agricoles : étude préalable agricole et compensation selon les seuils."
                 if s_agri > 0 else "Projet sans prélèvement de terres agricoles déclarées : sobriété foncière."),
              _decoupe(rpg, aires, "immediate") if rpg is not None else None,
              "> 1 ha dans la ZIP : fort ; présence : modéré ; aucune : faible")
    fon = tables.get("foncier")
    if fon is not None and not fon.empty:
        n_prop = fon["proprietaire"].nunique()
        pub = fon[~fon["groupe"].str.contains("privé|non diffusé|non remarquables", case=False)]["surface_zip_ha"].sum()
        G.ajouter(MH, "Maîtrise foncière", "Modéré" if n_prop > 3 else "Faible",
                  f"{int(fon['nb_parcelles'].sum())} parcelles, "
                  f"{'un seul propriétaire ou groupe' if n_prop == 1 else f'{n_prop} propriétaires ou groupes'} "
                  f"({', '.join(sorted(set(fon['proprietaire'])))}) ; "
                  f"{_ha(pub)} de la ZIP appartiennent à des personnes publiques (DGFiP, personnes morales).",
                  None, "plus de 3 propriétaires : modéré ; sinon faible")
    res = tables.get("reseaux")
    if res is not None and not res.empty:
        htb = res[res["objet"].str.contains(r"\d+ kV", regex=True)]
        dmin = htb["distance_zip_m"].min() if not htb.empty else None
        traverse = (htb["distance_zip_m"] == 0).any() if not htb.empty else False
        cumul = res[res["objet"].str.contains("Parc photovoltaïque|Éolienne") & (res["nombre"] > 0)]
        G.ajouter(MH, "Réseaux et raccordement", "Modéré" if traverse else "Faible",
                  (f"Ligne haute tension à {_dist(dmin)} de la ZIP" if dmin is not None else "Pas de ligne haute tension proche")
                  + (" (elle traverse le site : servitude et distances de sécurité)" if traverse else "")
                  + (". La proximité du réseau facilite le raccordement." if dmin is not None and dmin <= 2000
                     else ". Le tracé et le coût du raccordement sont à étudier avec le gestionnaire de réseau."),
                  None,
                  "ligne traversant la ZIP : modéré ; sinon faible")
        if not cumul.empty:
            proche = cumul["position"].isin([POSITION["zip"], POSITION["immediate"], POSITION["rapprochee"]]).any()
            G.ajouter(MH, "Effets cumulés avec d'autres projets", "Modéré" if proche else "Faible",
                      "; ".join(f"{r.objet} : {r.nombre}, le plus proche à {_dist(r.distance_zip_m)}"
                                for r in cumul.itertuples()) + ".", None,
                      "installation d'énergie dans l'aire rapprochée : modéré ; éloignée : faible")
        else:
            G.ajouter(MH, "Effets cumulés avec d'autres projets", "Nul",
                      "Aucun parc photovoltaïque ni éolien recensé dans l'aire éloignée.", None,
                      "installation d'énergie dans l'aire rapprochée : modéré ; éloignée : faible")

    t = gpd.GeoDataFrame(G.lignes, geometry="geometry", crs=CRS)
    t["rang_niveau"] = t["niveau"].map({n: i for i, n in enumerate(NIVEAUX)})
    t["rang_theme"] = t["theme"].map({th: i for i, th in enumerate(THEMES)})
    t = t.sort_values(["rang_theme", "rang_niveau"], ascending=[True, False]).reset_index(drop=True)
    return t.drop(columns=["rang_theme"])
