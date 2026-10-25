"""Les 18 planches de l'atlas de l'état initial et leur production (PyQGIS).

Partagé par la chaîne (scripts/06_atlas_qgis.py) et par l'extension QGIS : le contenu des
planches (couches, légendes, textes) se déduit du seul GeoPackage de l'étude.
"""
import json
import sqlite3
from pathlib import Path

from qgis.core import QgsCoordinateReferenceSystem, QgsProject

from . import atlas_qgis as AQ

SRC_IGN = "IGN (ADMIN EXPRESS, BD TOPO)"
SRC_INPN = "INPN / PatriNat (MNHN, OFB)"


class Contexte:
    """Tables et chiffres de l'étude, lus dans le GeoPackage."""

    def __init__(self, gpkg, site=None):
        self.gpkg = Path(gpkg)
        self.enjeux = {r["sujet"]: r for r in self.table("t_enjeux")}
        self.annee = " et ".join(str(a) for (a,) in self._sql("SELECT DISTINCT millesime FROM ocsge ORDER BY 1"))
        self.nom_projet = self.table("projet")[0]["nom"]
        self.site = site or {}

    def _sql(self, requete):
        with sqlite3.connect(self.gpkg) as cx:
            try:
                return cx.execute(requete).fetchall()
            except sqlite3.OperationalError:
                return []

    def table(self, nom):
        with sqlite3.connect(self.gpkg) as cx:
            cx.row_factory = sqlite3.Row
            try:
                return [dict(r) for r in cx.execute(f'SELECT * FROM "{nom}"')]
            except sqlite3.OperationalError:
                return []

    # --- textes des encadrés -------------------------------------------------------------------
    @staticmethod
    def premiere_phrase(t, maxi=230):
        t = t.split(". ")[0].rstrip(".") + "."
        return t if len(t) <= maxi else t[:maxi - 1].rsplit(" ", 1)[0] + "…"

    def bloc_enjeux(self, sujets, intro=None):
        lignes = ["ENJEUX DE L'ÉTAT INITIAL"]
        if intro:
            lignes.append(intro)
        for s in sujets:
            e = self.enjeux.get(s)
            if e:
                lignes.append(f"{s} : enjeu {e['niveau'].lower()}.\n{self.premiere_phrase(e['justification'])}")
        return "\n\n".join(lignes)  # une ligne vide entre deux enjeux

    def ocs_zip(self):
        par_cs = {}
        for r in self.table("t_occupation"):
            if r["aire"] == "Zone d'implantation potentielle":
                par_cs[r["couverture"]] = par_cs.get(r["couverture"], 0) + r["part"]
        top = sorted(par_cs.items(), key=lambda x: -x[1])[:4]
        return (f"Couverture de la ZIP (OCS GE {self.annee}) : "
                + ", ".join(f"{k.lower()} {v:.0%}" for k, v in top) + ".") if top else ""

    def accords(self):
        lib = {"zip": "ZIP", "rapprochee": "aire rapprochée"}
        lignes = ["CONCORDANCE DES SOURCES (part des pixels de 10 m classés pareil ; kappa de Cohen)"]
        for r in self.table("t_ocs_accords"):
            if r["aire"] in lib:
                lignes.append(f"{lib[r['aire']]}, {r['comparaison']} : {r['accord']:.0%}, kappa {r['kappa']:.2f}"
                              .replace(".", ","))
        lignes.append("Corine Land Cover (unité minimale de 25 ha) ne décrit pas un site de cette taille ; "
                      "OSO (pixels de 10 m) confond jardins, friches herbacées et prairies ; l'OCS GE reste "
                      "la référence à l'échelle du projet, à vérifier sur le terrain.")
        return "\n".join(lignes)

    def evolution(self):
        rows = self._sql("SELECT sens, round(sum(surface_ha), 1), count(*) FROM ocsge_evolution "
                         "GROUP BY sens ORDER BY 2 DESC")
        periodes = " et ".join(p for (p,) in self._sql("SELECT DISTINCT periode FROM ocsge_evolution ORDER BY 1"))
        lignes = [f"ÉVOLUTION {periodes} DANS L'AIRE RAPPROCHÉE (OCS GE différentielle)"]
        lignes += [f"{sens} : {ha} ha ({n} polygones)".replace(".", ",") for sens, ha, n in rows]
        lignes.append("Le différentiel situe les changements récents : chantiers, friches qui se boisent, "
                      "terrains renaturés. Il sert aussi au suivi de l'artificialisation (objectif ZAN).")
        return "\n".join(lignes)

    def docs_urba(self):
        n = {}
        for r in self.table("doc_urba"):
            n[r["type_document"]] = n.get(r["type_document"], 0) + 1
        return ("DOCUMENTS D'URBANISME DES COMMUNES DE L'AIRE ÉLOIGNÉE (Géoportail de l'Urbanisme)\n"
                + "\n".join(f"{k} : {v} commune(s)" for k, v in sorted(n.items(), key=lambda x: -x[1]))
                + "\nLes communes sans document publié relèvent du document en vigueur en mairie ou du RNU : "
                  "vérification à faire auprès de la commune.")

    def synthese(self):
        n = {}
        for e in self.enjeux.values():
            n[e["niveau"]] = n.get(e["niveau"], 0) + 1
        forts = [s for s, e in self.enjeux.items() if e["niveau"] in ("Très fort", "Fort")]
        return ("SYNTHÈSE DE LA HIÉRARCHISATION (grille indicative)\n"
                + ", ".join(f"{k.lower()} : {n.get(k, 0)}" for k in ("Très fort", "Fort", "Modéré", "Faible", "Nul"))
                + ("\nEnjeux forts : " + ", ".join(forts) + "." if forts else "\nAucun enjeu fort.")
                + "\nSeuls les enjeux qui ont une emprise sont cartographiés. Les niveaux seront consolidés "
                  "après les inventaires de terrain (quatre saisons) et la délimitation des zones humides.")

    def presentation(self, surface_ha):
        s = self.site
        sous = f"{surface_ha:.1f} ha".replace(".", ",")
        if s.get("nom"):
            sous += f" à {s.get('commune', '')} : {s['nom'][0].lower() + s['nom'][1:]}"
        texte = "L'ÉTUDE DE CAS\n" + (s.get("presentation") or self.nom_projet) + \
            "\nAires d'étude : immédiate, rapprochée et éloignée autour de la zone d'implantation potentielle " \
            "(ZIP), selon des ordres de grandeur courants à justifier thème par thème."
        return sous, texte


def planches(C, X):
    """Définition des 18 planches : couches affichées (du dessus vers le dessous) et légende."""
    zip_, aires = C.get("projet"), C.get("aire_etude")
    plan, ortho = C.get("plan"), C.get("ortho")
    base = zip_ + aires
    surface = sum(f.geometry().area() for f in C.c["projet"].getFeatures()) / 10_000
    sous_titre, presentation = X.presentation(surface)
    an = X.annee or ""
    return [
        dict(num="01", theme="Présentation", titre="Localisation du projet et aires d'étude",
             sous_titre=sous_titre, emprise="eloignee",
             couches=base + C.get("commune", "route", "voie_ferree") + plan,
             legende=base + C.get("commune", "route", "voie_ferree"), texte=presentation,
             sources=SRC_IGN + ", Cartofriches (Cerema)"),
        dict(num="02", theme="Présentation", titre="Le site sur photographie aérienne",
             sous_titre="Zone d'implantation potentielle et aire d'étude immédiate",
             emprise="immediate", couches=base + C.get("parcelle") + ortho, legende=base + C.get("parcelle"),
             texte="LECTURE DU SITE\n" + X.ocs_zip() + "\nLa photographie aérienne guide la première "
                   "visite : accès, clôtures, bâti résiduel, boisements spontanés.",
             sources="IGN BD ORTHO, Parcellaire Express (PCI)"),
        dict(num="03", theme="Milieu naturel", titre="Zonages d'inventaire du patrimoine naturel",
             sous_titre="Zones naturelles d'intérêt écologique, faunistique et floristique",
             emprise="eloignee", couches=base + C.get("znieff1", "znieff2", "commune") + plan,
             legende=base + C.get("znieff1", "znieff2"),
             enjeux=["ZNIEFF de type I", "ZNIEFF de type II"], sources=SRC_INPN),
        dict(num="04", theme="Milieu naturel", titre="Zonages réglementaires et contractuels",
             sous_titre="Natura 2000, réserves naturelles, parc naturel régional, sites gérés, Ramsar",
             emprise="eloignee",
             couches=base + C.get("zsc", "zps", "rnn", "rnr", "cen", "ramsar", "pnr", "commune") + plan,
             legende=base + C.get("zsc", "zps", "rnn", "rnr", "cen", "ramsar", "pnr"),
             enjeux=["Sites Natura 2000", "Protections réglementaires (réserves, arrêtés de biotope)",
                     "Parc naturel régional, conservatoire, Ramsar"], sources=SRC_INPN),
        dict(num="05", theme="Milieu physique", titre="Eaux superficielles, souterraines et zones humides",
             sous_titre="Réseau hydrographique, zones à dominante humide, remontées de nappe",
             emprise="rapprochee", couches=base + C.get("cours_eau", "plan_eau", "zdh", "nappe") + plan,
             legende=base + C.get("cours_eau", "plan_eau", "zdh", "nappe"),
             enjeux=["Eaux superficielles", "Zones humides", "Eaux souterraines (remontées de nappe)"],
             sources="IGN BD TOPO, Agence de l'eau Artois-Picardie / Géo2France (ZDH), BRGM"),
        dict(num="06", theme="Occupation du sol", titre=f"Occupation du sol (OCS GE {an})",
             sous_titre="Couverture du sol de l'aire rapprochée, nomenclature nationale OCS GE 2.0",
             emprise="rapprochee", couches=base + C.get("ocsge"), legende=base + C.get("ocsge"),
             enjeux=["Végétation spontanée de la friche"], intro=X.ocs_zip(),
             sources=f"IGN OCS GE 2.0 ({an})"),
        dict(num="07", theme="Occupation du sol", titre="Évolution récente de l'occupation du sol",
             sous_titre="Changements de couverture détectés par l'OCS GE différentielle",
             emprise="rapprochee", couches=base + C.get("ocsge_evolution") + plan,
             legende=base + C.get("ocsge_evolution"), texte=X.evolution(),
             sources="IGN OCS GE 2.0, différentiel"),
        dict(num="08", theme="Occupation du sol", titre="Trois sources d'occupation du sol comparées",
             sous_titre="OCS GE, Corine Land Cover et OSO ramenées à six classes communes (grille de 10 m)",
             emprise="rapprochee", couches=[], legende=C.get("h_ocsge", "concordance") + base,
             comparaison=[(f"OCS GE {an}", base + C.get("h_ocsge")),
                          ("Corine Land Cover 2018", base + C.get("h_clc")),
                          ("OSO 2023 (CESBIO)", base + C.get("h_oso")),
                          ("Concordance des trois sources", base + C.get("concordance"))],
             texte=X.accords(), sources="IGN OCS GE, Copernicus / SDES (Corine Land Cover), CESBIO / Theia (OSO)"),
        dict(num="09", theme="Milieu naturel", titre="Agriculture, boisements et haies",
             sous_titre="Parcelles déclarées à la PAC, formations végétales et linéaires de haies",
             emprise="immediate", couches=base + C.get("haie", "foret", "rpg") + ortho,
             legende=base + C.get("haie", "foret", "rpg"), enjeux=["Boisements et haies", "Agriculture"],
             sources="IGN BD Forêt v2, BD TOPO (haies), ASP / IGN (RPG 2024)"),
        dict(num="10", theme="Milieu humain", titre="Documents d'urbanisme applicables",
             sous_titre="Document en vigueur publié sur le Géoportail de l'Urbanisme, par commune",
             emprise="eloignee", couches=base + C.get("doc_urba") + plan, legende=base + C.get("doc_urba"),
             texte=X.docs_urba(), sources="Géoportail de l'Urbanisme (API Carto IGN)"),
        dict(num="11", theme="Milieu humain", titre="Zonage et prescriptions du document d'urbanisme",
             sous_titre="Standard CNIG : zones, prescriptions surfaciques, linéaires et ponctuelles",
             emprise="immediate",
             couches=base + C.get("prescription_pct", "prescription_lin", "prescription_surf", "zone_urba") + plan,
             legende=base + C.get("zone_urba", "prescription_surf", "prescription_lin", "prescription_pct"),
             enjeux=["Document d'urbanisme", "Prescriptions du PLU",
                     "Héritage minier (puits, périmètres inconstructibles)"],
             sources="Géoportail de l'Urbanisme (documents au standard CNIG)"),
        dict(num="12", theme="Milieu humain", titre="Servitudes d'utilité publique",
             sous_titre="Assiettes des servitudes publiées sur le Géoportail de l'Urbanisme",
             emprise="immediate",
             couches=base + C.get("generateur_sup_l", "assiette_sup_s", "ligne_elec") + plan,
             legende=base + C.get("assiette_sup_s", "generateur_sup_l", "ligne_elec"),
             enjeux=["Servitudes d'utilité publique", "Réseaux et raccordement"],
             sources="Géoportail de l'Urbanisme (servitudes), IGN BD TOPO, RTE"),
        dict(num="13", theme="Milieu humain", titre="Parcellaire et maîtrise foncière",
             sous_titre="Parcelles de la ZIP et nature des propriétaires (personnes morales seulement)",
             emprise="zip", couches=base + C.get("parcelle_zip", "parcelle") + ortho,
             legende=base + C.get("parcelle_zip", "parcelle"), enjeux=["Maîtrise foncière"],
             intro="Les propriétaires personnes physiques ne figurent dans aucune source ouverte et ne sont "
                   "pas recherchés ; les personnes morales de droit privé ne sont pas nommées.",
             sources="IGN Parcellaire Express (PCI), DGFiP (fichier des parcelles des personnes morales 2025)"),
        dict(num="14", theme="Paysage et patrimoine", titre="Patrimoine mondial et patrimoine protégé",
             sous_titre="Bassin minier Nord-Pas-de-Calais : éléments inscrits, terrils et zone tampon",
             emprise="eloignee",
             couches=base + C.get("terril_unesco", "unesco_bien", "unesco_tampon", "commune") + plan,
             legende=base + C.get("unesco_bien", "terril_unesco", "unesco_tampon"),
             enjeux=["Bassin minier patrimoine mondial (bien inscrit)", "Zone tampon du patrimoine mondial",
                     "Monuments historiques (abords)"],
             sources="Mission Bassin Minier / Géo2France, Géoportail de l'Urbanisme (AC1, AC2)"),
        dict(num="15", theme="Milieu physique", titre="Risques naturels, miniers et technologiques",
             sous_titre="Plans de prévention, cavités, sols pollués et prescriptions de risque du PLU",
             emprise="rapprochee",
             couches=base + C.get("cavite", "prescription_pct", "sis", "ssp", "pprt", "ppr_inond", "ppr_minier",
                                  "prescription_surf") + plan,
             legende=base + C.get("pprt", "ppr_inond", "ppr_minier", "cavite", "sis", "ssp",
                                  "prescription_surf", "prescription_pct"),
             enjeux=["Risques technologiques (PPRT)", "Héritage minier (puits, périmètres inconstructibles)",
                     "Sols pollués", "Cavités et mouvements de terrain"],
             sources="BRGM / Géorisques (PPR, cavités, SIS), Géoportail de l'Urbanisme"),
        dict(num="16", theme="Milieu humain", titre="Réseaux, riverains et effets cumulés",
             sous_titre="Réseau électrique, bâti proche, installations d'énergie existantes",
             emprise="eloignee",
             couches=base + C.get("eolienne", "parc_pv", "poste_elec", "ligne_elec", "commune") + plan,
             legende=base + C.get("ligne_elec", "poste_elec", "parc_pv", "eolienne"),
             enjeux=["Réseaux et raccordement", "Riverains", "Effets cumulés avec d'autres projets"],
             sources="IGN BD TOPO, Géorisques (éoliennes), IGN (parcs photovoltaïques)"),
        dict(num="17", theme="Milieu naturel", titre="Données naturalistes connues",
             sous_titre="Observations d'espèces patrimoniales depuis 2010 dans l'aire rapprochée (GBIF)",
             emprise="rapprochee", couches=base + C.get("observation_patrimoniale", "znieff1") + plan,
             legende=base + C.get("observation_patrimoniale", "znieff1"),
             enjeux=["Espèces connues (bibliographie)"], sources="GBIF (occurrences), MNHN TAXREF (statuts), INPN"),
        dict(num="18", theme="Synthèse", titre="Synthèse des enjeux spatialisés",
             sous_titre="Hiérarchisation indicative : à consolider par les inventaires de terrain",
             emprise="immediate", couches=base + C.get("enjeu") + ortho, legende=base + C.get("enjeu"),
             texte=X.synthese(), sources="Analyse de l'auteur à partir des cartes 01 à 17"),
    ]


def produire(gpkg, rasters, dossier_pdf, qgz, cartouche, nomenclature=None, site=None, choix=None,
             titre="État initial de l'environnement", journal=print, projet=None):
    """Construit le projet QGIS (qgz) et exporte les planches en PDF ; renvoie la liste des PDF."""
    projet = projet or QgsProject.instance()
    projet.clear()
    projet.setCrs(QgsCoordinateReferenceSystem("EPSG:2154"))
    projet.setTitle(titre)
    projet.setFileName(str(qgz))
    projet.writeEntryBool("Paths", "/Absolute", False)  # chemins relatifs : le dossier se déplace entier
    AQ.fixer_transformations(projet)
    C = AQ.charger(AQ.Couches(gpkg, rasters, projet), AQ.nomenclature_ocsge(nomenclature))
    X = Contexte(gpkg, site)
    journal(f"{len(C.c)} couches chargées")
    emprises = {f["aire"]: f.geometry().boundingBox() for f in C.c["aire_etude"].getFeatures()}
    emprises["zip"] = C.c["projet"].extent()
    pl = planches(C, X)
    gab = AQ.Gabarit(projet, {"nb_planches": len(pl), "cartouche": cartouche})
    if "contexte_departement" in C.c:
        situation = {"couches": C.get("contexte_site", "contexte_epci", "contexte_departement"),
                     "emprise": C.c["contexte_departement"].extent().buffered(3000)}
    else:  # extension : situation sur les communes de l'aire éloignée
        situation = {"couches": C.get("projet", "commune"), "emprise": emprises["eloignee"].buffered(2000)}
    Path(dossier_pdf).mkdir(parents=True, exist_ok=True)
    sorties = []
    for p in pl:
        if choix and p["num"] not in choix:
            continue
        r = emprises[p["emprise"]]
        emprise = r.buffered(max(r.width(), r.height()) * 0.04)
        texte = p.get("texte") or X.bloc_enjeux(p.get("enjeux") or [], p.get("intro"))
        mise = gab.page(p, p["couches"], p["legende"], emprise, texte, situation, p.get("colonnes", 1))
        AQ.theme(projet, f"{p['num']} {p['titre']}", p["couches"] or p["comparaison"][0][1])
        pdf = Path(dossier_pdf) / f"Carte_{p['num']}.pdf"
        ok = AQ.exporter(mise, pdf)
        journal(f"  carte {p['num']} {'exportée' if ok else 'ÉCHEC'} : {p['titre']}")
        if ok:
            sorties.append(pdf)
    # index des planches : titres pour le sommaire de l'atlas (assemblé hors de QGIS)
    (Path(dossier_pdf) / "index.json").write_text(json.dumps(
        [{"num": p["num"], "titre": p["titre"], "theme": p["theme"]} for p in pl], ensure_ascii=False, indent=1),
        encoding="utf-8")
    projet.write(str(qgz))
    journal(f"Projet : {qgz}")
    return sorties
