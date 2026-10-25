"""Paramètres de l'outil : aires d'étude, services de données, catalogue des couches, nomenclatures.

Ce fichier est le seul à modifier pour ajouter une couche ou changer une distance.
"""
CRS = "EPSG:2154"  # Lambert-93

# --- Aires d'étude --------------------------------------------------------------------------
# Distances (m) autour de la zone d'implantation potentielle (ZIP). Ce sont des ordres de
# grandeur couramment retenus : chaque étude doit les justifier (relief, visibilité,
# fonctionnement écologique) et peut les adapter thème par thème.
TYPES_PROJET = {
    "photovoltaique": {"libelle": "Centrale photovoltaïque au sol",
                       "immediate": 200, "rapprochee": 1000, "eloignee": 5000},
    "eolien": {"libelle": "Parc éolien terrestre",
               "immediate": 600, "rapprochee": 6000, "eloignee": 18000},
    "amenagement": {"libelle": "Projet d'aménagement (ZAC, lotissement, zone d'activités)",
                    "immediate": 100, "rapprochee": 500, "eloignee": 3000},
}
AIRES = ("zip", "immediate", "rapprochee", "eloignee")
LIBELLE_AIRE = {"zip": "Zone d'implantation potentielle", "immediate": "Aire d'étude immédiate",
                "rapprochee": "Aire d'étude rapprochée", "eloignee": "Aire d'étude éloignée"}

# --- Services ----------------------------------------------------------------------------
SERVICES = {
    "geopf": {"url": "https://data.geopf.fr/wfs/ows", "format": "application/json",
              "pagination": True, "page": 5000,
              "producteur": "IGN Géoplateforme"},
    "geo2france": {"url": "https://www.geo2france.fr/geoserver/ows", "format": "application/json",
                   "pagination": True, "page": 5000,
                   "producteur": "Géo2France (plateforme régionale Hauts-de-France)"},
    "brgm": {"url": "https://mapsref.brgm.fr/wxs/georisques/risques", "format": "geojson",
             "pagination": False, "page": 0,
             "producteur": "BRGM / Géorisques"},
}
GPU_API = "https://apicarto.ign.fr/api/gpu"
GBIF_API = "https://api.gbif.org/v1"
OCSGE_TELECHARGEMENT = "https://data.geopf.fr/telechargement"

# --- Catalogue des couches ------------------------------------------------------------------
# aire   : étendue interrogée (les données sont ensuite découpées sur cette aire)
# garder : colonnes conservées ; renommer : harmonisation des noms
# Les zonages du patrimoine naturel partagent la même structure (INPN / PatriNat).
_INPN = {"garder": ["id_mnhn", "nom_site", "url_fiche", "gest_site", "date_crea"],
         "renommer": {"id_mnhn": "code", "nom_site": "nom", "url_fiche": "url",
                      "gest_site": "gestionnaire"}}


def _inpn(couche, libelle, famille):
    return {"service": "geopf", "couche": couche, "theme": "nature", "famille": famille,
            "libelle": libelle, "aire": "eloignee", **_INPN}


CATALOGUE = {
    # Patrimoine naturel : zonages d'inventaire
    "znieff1": _inpn("patrinat_znieff1:znieff1", "ZNIEFF de type I", "inventaire"),
    "znieff2": _inpn("patrinat_znieff2:znieff2", "ZNIEFF de type II", "inventaire"),
    # Patrimoine naturel : protections réglementaires, contractuelles et foncières
    "zsc": _inpn("patrinat_sic:sic", "Natura 2000 - Zone spéciale de conservation (directive Habitats)",
                 "natura2000"),
    "zps": _inpn("patrinat_zps:zps", "Natura 2000 - Zone de protection spéciale (directive Oiseaux)",
                 "natura2000"),
    "apb": _inpn("patrinat_apb:apb", "Arrêté préfectoral de protection de biotope", "reglementaire"),
    "rnn": _inpn("patrinat_rnn:rnn", "Réserve naturelle nationale", "reglementaire"),
    "rnr": _inpn("patrinat_rnr:rnr", "Réserve naturelle régionale", "reglementaire"),
    "rb": _inpn("patrinat_rb:rb", "Réserve biologique", "reglementaire"),
    "cen": _inpn("patrinat_cen:cen", "Site d'un conservatoire d'espaces naturels", "foncier"),
    "ramsar": _inpn("patrinat_ramsar:ramsar", "Zone humide d'importance internationale (Ramsar)",
                    "contractuel"),
    "pnr": _inpn("patrinat_pnr:pnr", "Parc naturel régional", "contractuel"),

    # Eau et milieux humides
    "zdh": {"service": "geo2france", "couche": "orb:ZDH_HdF", "theme": "eau", "famille": "humide",
            "libelle": "Zone à dominante humide (SDAGE)", "aire": "eloignee",
            "garder": ["OCC_SOL_ZDH", "CODE_CONFIANCE_HDF"],
            "renommer": {"OCC_SOL_ZDH": "milieu", "CODE_CONFIANCE_HDF": "confiance"}},
    "cours_eau": {"service": "geopf", "couche": "BDTOPO_V3:cours_d_eau", "theme": "eau",
                  "famille": "hydrographie", "libelle": "Cours d'eau", "aire": "eloignee",
                  "garder": ["cleabs", "toponyme", "importance", "caractere_permanent"],
                  "renommer": {"toponyme": "nom"}},
    "plan_eau": {"service": "geopf", "couche": "BDTOPO_V3:plan_d_eau", "theme": "eau",
                 "famille": "hydrographie", "libelle": "Plan d'eau", "aire": "eloignee",
                 "garder": ["cleabs", "nature", "toponyme"], "renommer": {"toponyme": "nom"}},

    # Occupation du sol, agriculture, éléments boisés
    "clc": {"service": "geopf", "couche": "LANDCOVER.CLC18_FR:clc18_fr", "theme": "sol",
            "famille": "occupation", "libelle": "Corine Land Cover 2018", "aire": "eloignee",
            "garder": ["code_18"], "renommer": {"code_18": "code"}},
    "rpg": {"service": "geopf", "couche": "RPG.2024:parcelles_graphiques", "theme": "sol",
            "famille": "agriculture", "libelle": "Registre parcellaire graphique 2024",
            "aire": "rapprochee", "garder": ["id_parcel", "surf_parc", "code_cultu", "code_group"],
            "renommer": {}},
    "foret": {"service": "geopf", "couche": "LANDCOVER.FORESTINVENTORY.V2:formation_vegetale",
              "theme": "sol", "famille": "boise", "libelle": "BD Forêt v2 (formations végétales)",
              "aire": "eloignee", "garder": ["code_tfv", "tfv", "tfv_g11", "essence"], "renommer": {}},
    "haie": {"service": "geopf", "couche": "BDTOPO_V3:haie", "theme": "sol", "famille": "boise",
             "libelle": "Haies (BD TOPO)", "aire": "rapprochee", "garder": ["cleabs", "sources"],
             "renommer": {}},

    # Patrimoine culturel et paysage (Bassin minier inscrit au patrimoine mondial)
    "unesco_bien": {"service": "geo2france",
                    "couche": "mission_bassin_minier:bien_inscrit_perimetre_du_bien_inscrit",
                    "theme": "patrimoine", "famille": "unesco",
                    "libelle": "Bassin minier patrimoine mondial - Bien inscrit", "aire": "eloignee",
                    "garder": ["NO_ELEMENT", "Nom"], "renommer": {"NO_ELEMENT": "element", "Nom": "nom"}},
    "unesco_tampon": {"service": "geo2france",
                      "couche": "mission_bassin_minier:zt_perimetre_zone_tampon",
                      "theme": "patrimoine", "famille": "unesco",
                      "libelle": "Bassin minier patrimoine mondial - Zone tampon", "aire": "eloignee",
                      "garder": ["ID"], "renommer": {"ID": "element"}},
    "terril_unesco": {"service": "geo2france", "couche": "mission_bassin_minier:bien_inscrit_terrils",
                      "theme": "patrimoine", "famille": "unesco",
                      "libelle": "Terril inscrit au patrimoine mondial", "aire": "eloignee",
                      "garder": ["NO_TERRIL", "NOM", "COMMUNE1", "FORME", "PROTECTION_CODE_PAT_ENVT"],
                      "renommer": {"NO_TERRIL": "terril", "NOM": "nom", "COMMUNE1": "commune",
                                   "FORME": "forme", "PROTECTION_CODE_PAT_ENVT": "protection"}},

    # Risques naturels et technologiques
    "ppr_inond": {"service": "brgm", "couche": "ms:PPRN_PERIMETRE_INOND", "theme": "risques",
                  "famille": "ppr", "libelle": "Plan de prévention du risque inondation (périmètre)",
                  "aire": "eloignee", "garder": ["lib_ppr", "libelle_sous_etat", "dat_approbation"],
                  "renommer": {"lib_ppr": "nom", "libelle_sous_etat": "etat"}},
    "ppr_mvt": {"service": "brgm", "couche": "ms:PPRN_PERIMETRE_MVT", "theme": "risques",
                "famille": "ppr", "libelle": "Plan de prévention mouvements de terrain (périmètre)",
                "aire": "eloignee", "garder": ["lib_ppr", "libelle_sous_etat", "dat_approbation"],
                "renommer": {"lib_ppr": "nom", "libelle_sous_etat": "etat"}},
    "ppr_minier": {"service": "brgm", "couche": "ms:PPRM_PERIMETRE_MINIER", "theme": "risques",
                   "famille": "ppr", "libelle": "Plan de prévention des risques miniers (périmètre)",
                   "aire": "eloignee", "garder": ["lib_ppr", "libelle_sous_etat", "dat_approbation"],
                   "renommer": {"lib_ppr": "nom", "libelle_sous_etat": "etat"}},
    "pprt": {"service": "brgm", "couche": "ms:PPRT_PERIMETRE_RISQIND", "theme": "risques",
             "famille": "ppr", "libelle": "Plan de prévention des risques technologiques (périmètre)",
             "aire": "eloignee", "garder": ["lib_ppr", "libelle_sous_etat", "dat_approbation"],
             "renommer": {"lib_ppr": "nom", "libelle_sous_etat": "etat"}},
    "cavite": {"service": "brgm", "couche": "ms:CAVITE_LOCALISEE", "theme": "risques",
               "famille": "sol", "libelle": "Cavité souterraine recensée", "aire": "rapprochee",
               "garder": ["identifiant", "nom_cavite", "type_cavite"],
               "renommer": {"nom_cavite": "nom", "type_cavite": "type"}},
    "mvt": {"service": "brgm", "couche": "ms:MVT_LOCALISE", "theme": "risques", "famille": "sol",
            "libelle": "Mouvement de terrain recensé", "aire": "rapprochee",
            "garder": ["id_mvt", "lieu_dit", "type_mvt", "date_deb_mvt"], "renommer": {}},
    "nappe": {"service": "brgm", "couche": "ms:REMNAPPE", "theme": "risques", "famille": "eau",
              "libelle": "Sensibilité aux remontées de nappe", "aire": "rapprochee",
              "garder": ["classe", "fiab_tot"], "renommer": {"fiab_tot": "fiabilite"}},
    "sis": {"service": "brgm", "couche": "ms:SSP_CLASSIF_SIS_GE", "theme": "risques",
            "famille": "pollution", "libelle": "Secteur d'information sur les sols (SIS)",
            "aire": "rapprochee", "garder": ["autre_identifiant", "nom_site", "adresse", "nom_commune"],
            "renommer": {"autre_identifiant": "code", "nom_site": "nom", "nom_commune": "commune"}},
    "ssp": {"service": "brgm", "couche": "ms:SSP_INSTR_GE_POLYGON", "theme": "risques",
            "famille": "pollution", "libelle": "Site pollué ou potentiellement pollué (instruction)",
            "aire": "rapprochee", "garder": ["autre_identifiant", "nom_site", "statut_instruction",
                                            "nom_commune"],
            "renommer": {"autre_identifiant": "code", "nom_site": "nom",
                         "statut_instruction": "statut", "nom_commune": "commune"}},

    # Réseaux et projets connus (effets cumulés)
    "ligne_elec": {"service": "geopf", "couche": "BDTOPO_V3:ligne_electrique", "theme": "reseaux",
                   "famille": "energie", "libelle": "Ligne électrique (transport)", "aire": "eloignee",
                   "garder": ["cleabs", "voltage", "gestionnaire"], "renommer": {}},
    "poste_elec": {"service": "geopf", "couche": "BDTOPO_V3:poste_de_transformation",
                   "theme": "reseaux", "famille": "energie", "libelle": "Poste de transformation électrique",
                   "aire": "eloignee", "garder": ["cleabs", "toponyme", "importance"],
                   "renommer": {"toponyme": "nom"}},
    "parc_pv": {"service": "geopf",
                "couche": "igngpf_4902_20260309_tables_sans_tirets:parcs_photovoltaiques",
                "theme": "reseaux", "famille": "cumul", "libelle": "Parc photovoltaïque au sol existant",
                "aire": "eloignee", "tri": "id",  # pagination impossible sans tri explicite
                "garder": ["id", "millesime", "surf_parc", "nom_com", "agrivolt"], "renommer": {}},
    "eolienne": {"service": "brgm", "couche": "ms:eolienne_wfs", "theme": "reseaux", "famille": "cumul",
                 "libelle": "Éolienne (parc construit ou autorisé)", "aire": "eloignee",
                 "garder": ["id_aerogenerateur", "nom_usuel", "nom_commune", "puissance_mw",
                            "hauteur_totale", "etat_parc"],
                 "renommer": {"nom_usuel": "parc", "nom_commune": "commune"}},

    # Contexte et fond de plan
    "route": {"service": "geopf", "couche": "BDTOPO_V3:troncon_de_route", "theme": "contexte",
              "famille": "transport", "libelle": "Route principale", "aire": "eloignee",
              "filtre": "importance IN ('1','2','3')",
              "garder": ["cleabs", "nature", "importance", "cpx_numero"], "renommer": {"cpx_numero": "numero"}},
    "voie_ferree": {"service": "geopf", "couche": "BDTOPO_V3:troncon_de_voie_ferree",
                    "theme": "contexte", "famille": "transport", "libelle": "Voie ferrée",
                    "aire": "eloignee", "filtre": "etat_de_l_objet = 'En service'",
                    "garder": ["cleabs", "nature"], "renommer": {}},
    "batiment": {"service": "geopf", "couche": "BDTOPO_V3:batiment", "theme": "contexte",
                 "famille": "bati", "libelle": "Bâtiment", "aire": "immediate",
                 "garder": ["cleabs", "nature", "usage_1", "nombre_de_logements"], "renommer": {}},
}

# Familles de servitudes d'utilité publique les plus courantes (code GPU -> libellé court)
SUP_LIBELLES = {
    "AC1": "Monument historique (abords)", "AC2": "Site inscrit ou classé",
    "AC4": "Site patrimonial remarquable", "AS1": "Protection des captages d'eau",
    "EL7": "Plan d'alignement", "EL11": "Interdiction d'accès (voie express)",
    "I1": "Canalisation d'hydrocarbures", "I3": "Canalisation de gaz", "I4": "Ligne électrique",
    "I6": "Mines et carrières", "INT1": "Voisinage des cimetières", "JS1": "Équipement sportif",
    "PM1": "Plan de prévention des risques naturels", "PM2": "Installation classée (servitude)",
    "PM3": "Plan de prévention des risques technologiques", "PT1": "Télécommunications (perturbations)",
    "PT2": "Télécommunications (obstacles)", "PT3": "Réseau de télécommunication",
    "T1": "Voie ferrée", "T4": "Balisage aérien", "T5": "Dégagement aérien", "T7": "Hors dégagement aérien",
    "EL3": "Halage et marchepied", "A4": "Terrain riverain de cours d'eau", "A5": "Canalisation publique d'eau",
}

# --- Nomenclatures d'occupation du sol ----------------------------------------------------
CLC_LIBELLES = {
    "111": "Tissu urbain continu", "112": "Tissu urbain discontinu",
    "121": "Zones industrielles ou commerciales", "122": "Réseaux routier et ferroviaire",
    "123": "Zones portuaires", "124": "Aéroports", "131": "Extraction de matériaux",
    "132": "Décharges", "133": "Chantiers", "141": "Espaces verts urbains",
    "142": "Équipements sportifs et de loisirs", "211": "Terres arables hors irrigation",
    "212": "Périmètres irrigués", "213": "Rizières", "221": "Vignobles", "222": "Vergers",
    "223": "Oliveraies", "231": "Prairies", "241": "Cultures annuelles et permanentes",
    "242": "Systèmes culturaux complexes", "243": "Agriculture et espaces naturels",
    "244": "Territoires agroforestiers", "311": "Forêts de feuillus", "312": "Forêts de conifères",
    "313": "Forêts mélangées", "321": "Pelouses et pâturages naturels", "322": "Landes et broussailles",
    "323": "Végétation sclérophylle", "324": "Forêt et végétation arbustive en mutation",
    "331": "Plages, dunes et sable", "332": "Roches nues", "333": "Végétation clairsemée",
    "334": "Zones incendiées", "335": "Glaciers et neiges éternelles", "411": "Marais intérieurs",
    "412": "Tourbières", "421": "Marais maritimes", "422": "Marais salants", "423": "Zones intertidales",
    "511": "Cours et voies d'eau", "512": "Plans d'eau", "521": "Lagunes littorales",
    "522": "Estuaires", "523": "Mers et océans",
}

OCSGE_COUVERTURE = {
    "CS1.1.1.1": "Zones bâties", "CS1.1.1.2": "Zones non bâties (revêtues)",
    "CS1.1.2.1": "Zones à matériaux minéraux", "CS1.1.2.2": "Zones à autres matériaux composites",
    "CS1.2.1": "Sols nus", "CS1.2.2": "Surfaces d'eau", "CS1.2.3": "Névés et glaciers",
    "CS2.1.1.1": "Peuplements de feuillus", "CS2.1.1.2": "Peuplements de conifères",
    "CS2.1.1.3": "Peuplements mixtes", "CS2.1.2": "Formations arbustives et sous-arbrisseaux",
    "CS2.1.3": "Autres formations ligneuses", "CS2.2.1": "Formations herbacées",
    "CS2.2.2": "Autres formations non ligneuses",
}

OCSGE_USAGE = {
    "US1.1": "Agriculture", "US1.2": "Sylviculture", "US1.3": "Activités d'extraction",
    "US1.4": "Pêche et aquaculture", "US1.5": "Autre production primaire",
    "US2": "Production secondaire", "US3": "Production tertiaire", "US235": "Usage mixte",
    "US4.1.1": "Réseaux routiers", "US4.1.2": "Réseaux ferrés", "US4.1.3": "Réseaux aériens",
    "US4.1.4": "Réseaux de transport fluvial et maritime", "US4.1.5": "Autres réseaux de transport",
    "US4.2": "Services de logistique et de stockage", "US4.3": "Réseaux d'utilité publique",
    "US5": "Usage résidentiel", "US6.1": "Zones en transition", "US6.2": "Zones abandonnées",
    "US6.3": "Sans usage", "US6.6": "Usage inconnu",
}

# Classes harmonisées pour comparer OCS GE, Corine Land Cover et OSO
CLASSES_HARMONISEES = {
    1: ("Surfaces artificialisées", "#c8102e"),
    2: ("Terres agricoles (cultures et prairies)", "#f2d16b"),
    3: ("Autres formations herbacées", "#a8d672"),
    4: ("Forêts et formations ligneuses", "#2f7d32"),
    5: ("Eau et zones humides", "#3a86c8"),
    6: ("Sols nus et milieux minéraux", "#b9a98f"),
}
