-- Structure de la base « etat_initial » : référentiel territorial, catalogue et veille,
-- criblage de sites, études. Les tables du référentiel (schéma ref) sont créées par la
-- chaîne Python (01_referentiel.py) ; ce script pose le cadre, les rôles et les droits.

CREATE EXTENSION IF NOT EXISTS postgis;

-- --- Schémas -----------------------------------------------------------------------------------
CREATE SCHEMA IF NOT EXISTS ref;       -- référentiel territorial (données ouvertes, mises à jour par flux)
CREATE SCHEMA IF NOT EXISTS meta;      -- catalogue des couches et journal de veille
CREATE SCHEMA IF NOT EXISTS criblage;  -- règles et résultats du criblage multi-sites
CREATE SCHEMA IF NOT EXISTS etude;     -- projets étudiés : périmètres, aires, enjeux, relevés terrain

COMMENT ON SCHEMA ref IS 'Référentiel territorial : couches ouvertes découpées sur le territoire et sa marge de 5 km';
COMMENT ON SCHEMA meta IS 'Catalogue des couches (source, date, volume) et journal des mises à jour (veille)';
COMMENT ON SCHEMA criblage IS 'Criblage des friches pour l''implantation d''une centrale photovoltaïque au sol';
COMMENT ON SCHEMA etude IS 'Études en cours : projets, aires d''étude, enjeux hiérarchisés, observations de terrain';

-- --- Rôles -----------------------------------------------------------------------------------------
-- lecteur : consultation (QGIS, cartographes) ; charge_etudes : saisie des études et du terrain
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'lecteur') THEN
        CREATE ROLE lecteur NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'charge_etudes') THEN
        CREATE ROLE charge_etudes NOLOGIN IN ROLE lecteur;
    END IF;
END $$;

GRANT CONNECT ON DATABASE etat_initial TO lecteur;
GRANT USAGE ON SCHEMA ref, meta, criblage, etude TO lecteur;
ALTER DEFAULT PRIVILEGES IN SCHEMA ref, meta, criblage, etude GRANT SELECT ON TABLES TO lecteur;
ALTER DEFAULT PRIVILEGES IN SCHEMA etude GRANT INSERT, UPDATE, DELETE ON TABLES TO charge_etudes;
ALTER DEFAULT PRIVILEGES IN SCHEMA etude GRANT USAGE ON SEQUENCES TO charge_etudes;

-- --- Catalogue et veille -------------------------------------------------------------------------
CREATE TABLE meta.catalogue (
    code          text PRIMARY KEY,
    libelle       text NOT NULL,
    theme         text NOT NULL,
    famille       text,
    producteur    text,
    service       text,
    couche_source text,
    table_ref     text,
    nb_objets     integer,
    empreinte     text,          -- somme de contrôle des identifiants, pour détecter un changement
    date_maj      timestamptz
);
COMMENT ON TABLE meta.catalogue IS 'Une ligne par couche du référentiel : origine, volume, date de dernière mise à jour';

CREATE TABLE meta.journal_maj (
    id          bigserial PRIMARY KEY,
    code        text REFERENCES meta.catalogue (code) ON DELETE CASCADE,
    date_controle timestamptz NOT NULL DEFAULT now(),
    nb_avant    integer,
    nb_apres    integer,
    changement  boolean,
    commentaire text
);
COMMENT ON TABLE meta.journal_maj IS 'Veille : résultat de chaque contrôle de mise à jour d''une couche';

-- --- Criblage ----------------------------------------------------------------------------------------
CREATE TABLE criblage.regle (
    critere   text PRIMARY KEY,
    effet     text NOT NULL CHECK (effet IN ('exclusion', 'fort', 'modere', 'favorable', 'information')),
    points    integer NOT NULL DEFAULT 0,
    libelle   text NOT NULL,
    seuil     numeric
);
COMMENT ON TABLE criblage.regle IS 'Grille du criblage : chaque critère exclut le site, le pénalise ou le favorise';

INSERT INTO criblage.regle (critere, effet, points, libelle, seuil) VALUES
    ('surface_insuffisante', 'exclusion', 0, 'Surface inférieure au seuil (ha)', 3),
    ('projet_en_cours',      'exclusion', 0, 'Friche ayant déjà un projet de reconversion', NULL),
    ('protection_forte',     'exclusion', 0, 'Réserve naturelle, arrêté de biotope ou réserve biologique sur le site', NULL),
    ('bien_unesco',          'exclusion', 0, 'Élément du bien inscrit au patrimoine mondial (Bassin minier) sur le site', NULL),
    ('deja_reconverti',      'exclusion', 0, 'Site déjà reconverti : usage économique, logistique, technique ou résidentiel sur plus de 30 % de la surface (OCS GE)', 0.30),
    ('natura2000',           'fort',     -3, 'Site Natura 2000 recoupant la friche', NULL),
    ('znieff1',              'fort',     -3, 'ZNIEFF de type I sur plus de 10 % de la friche', 0.10),
    ('zone_humide',          'fort',     -3, 'Zone à dominante humide sur plus de 10 % de la friche', 0.10),
    ('ppr',                  'fort',     -3, 'Périmètre de plan de prévention (inondation, minier, technologique)', NULL),
    ('natura2000_proche',    'modere',   -2, 'Site Natura 2000 à moins de 1 km (m)', 1000),
    ('znieff2',              'modere',   -1, 'ZNIEFF de type II sur la friche', NULL),
    ('tampon_unesco',        'modere',   -1, 'Zone tampon du bien inscrit au patrimoine mondial', NULL),
    ('riverains',            'modere',   -1, 'Habitat à moins de 100 m (part du pourtour en usage résidentiel, OCS GE)', 0.25),
    ('sol_pollue',           'favorable', 2, 'Sol pollué connu (SIS ou site en instruction) : usage agricole ou résidentiel exclu', NULL),
    ('reseau_proche',        'favorable', 1, 'Ligne électrique haute tension à moins de 2 km (m)', 2000),
    ('artificialise',        'favorable', 1, 'Site majoritairement artificialisé ou en friche selon l''OCS GE', 0.50),
    ('grande_surface',       'favorable', 1, 'Surface d''au moins 10 ha (centrale de l''ordre de 10 MWc)', 10);

-- --- Études ---------------------------------------------------------------------------------------------
CREATE TABLE etude.projet (
    id           serial PRIMARY KEY,
    nom          text NOT NULL,
    type_projet  text NOT NULL CHECK (type_projet IN ('photovoltaique', 'eolien', 'amenagement')),
    commentaire  text,
    date_creation timestamptz NOT NULL DEFAULT now(),
    geom         geometry(MultiPolygon, 2154) NOT NULL
);
COMMENT ON TABLE etude.projet IS 'Zone d''implantation potentielle (ZIP) de chaque projet étudié';

CREATE TABLE etude.aire (
    projet_id  integer REFERENCES etude.projet (id) ON DELETE CASCADE,
    aire       text NOT NULL CHECK (aire IN ('zip', 'immediate', 'rapprochee', 'eloignee')),
    distance_m integer NOT NULL,
    geom       geometry(MultiPolygon, 2154) NOT NULL,
    PRIMARY KEY (projet_id, aire)
);

CREATE TABLE etude.enjeu (
    id         serial PRIMARY KEY,
    projet_id  integer REFERENCES etude.projet (id) ON DELETE CASCADE,
    theme      text NOT NULL,
    sujet      text NOT NULL,
    niveau     text NOT NULL CHECK (niveau IN ('Très fort', 'Fort', 'Modéré', 'Faible', 'Nul')),
    justification text,
    geom       geometry(MultiPolygon, 2154)
);
COMMENT ON TABLE etude.enjeu IS 'Enjeux hiérarchisés de l''état initial (grille indicative, à valider par les experts)';

-- Relevés de terrain des écologues (projet QField), importés après contrôle
CREATE TABLE etude.observation (
    id           serial PRIMARY KEY,
    projet_id    integer REFERENCES etude.projet (id) ON DELETE CASCADE,
    uuid         uuid UNIQUE,
    date_obs     date NOT NULL,
    observateur  text NOT NULL,
    groupe       text NOT NULL,
    taxon        text NOT NULL,
    effectif     integer CHECK (effectif IS NULL OR effectif > 0),
    comportement text,
    statut_repro text,
    remarque     text,
    photo        text,
    geom         geometry(Point, 2154) NOT NULL
);

CREATE TABLE etude.habitat (
    id           serial PRIMARY KEY,
    projet_id    integer REFERENCES etude.projet (id) ON DELETE CASCADE,
    uuid         uuid UNIQUE,
    date_obs     date NOT NULL,
    observateur  text NOT NULL,
    code_eunis   text NOT NULL,
    libelle      text,
    etat_conservation text CHECK (etat_conservation IN ('Bon', 'Moyen', 'Dégradé', 'Non évalué')),
    zone_humide  boolean,     -- critère végétation de l'arrêté du 24 juin 2008
    remarque     text,
    geom         geometry(MultiPolygon, 2154) NOT NULL
);

CREATE INDEX ON etude.projet USING gist (geom);
CREATE INDEX ON etude.aire USING gist (geom);
CREATE INDEX ON etude.enjeu USING gist (geom);
CREATE INDEX ON etude.observation USING gist (geom);
CREATE INDEX ON etude.habitat USING gist (geom);

-- Aires d'étude calculées dans la base à la création d'un projet (mêmes distances que l'outil Python)
CREATE FUNCTION etude.distances(type_projet text, OUT immediate integer, OUT rapprochee integer,
                                OUT eloignee integer)
LANGUAGE sql IMMUTABLE AS $$
    SELECT CASE type_projet WHEN 'photovoltaique' THEN 200 WHEN 'eolien' THEN 600 ELSE 100 END,
           CASE type_projet WHEN 'photovoltaique' THEN 1000 WHEN 'eolien' THEN 6000 ELSE 500 END,
           CASE type_projet WHEN 'photovoltaique' THEN 5000 WHEN 'eolien' THEN 18000 ELSE 3000 END
$$;

CREATE FUNCTION etude.creer_aires() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE d record;
BEGIN
    SELECT * INTO d FROM etude.distances(NEW.type_projet);
    DELETE FROM etude.aire WHERE projet_id = NEW.id;
    INSERT INTO etude.aire (projet_id, aire, distance_m, geom) VALUES
        (NEW.id, 'zip', 0, ST_Multi(NEW.geom)),
        (NEW.id, 'immediate', d.immediate, ST_Multi(ST_Buffer(NEW.geom, d.immediate, 16))),
        (NEW.id, 'rapprochee', d.rapprochee, ST_Multi(ST_Buffer(NEW.geom, d.rapprochee, 16))),
        (NEW.id, 'eloignee', d.eloignee, ST_Multi(ST_Buffer(NEW.geom, d.eloignee, 16)));
    RETURN NEW;
END $$;

CREATE TRIGGER projet_aires AFTER INSERT OR UPDATE OF geom, type_projet ON etude.projet
    FOR EACH ROW EXECUTE FUNCTION etude.creer_aires();

-- Contrôle de saisie : une observation doit tomber dans l'aire rapprochée de son projet
CREATE FUNCTION etude.controle_observation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM etude.aire a WHERE a.projet_id = NEW.projet_id
                   AND a.aire = 'rapprochee' AND ST_Intersects(a.geom, NEW.geom)) THEN
        RAISE EXCEPTION 'Observation % hors de l''aire rapprochée du projet %', NEW.uuid, NEW.projet_id;
    END IF;
    IF NEW.date_obs > current_date THEN
        RAISE EXCEPTION 'Observation % datée dans le futur (%)', NEW.uuid, NEW.date_obs;
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER observation_controle BEFORE INSERT OR UPDATE ON etude.observation
    FOR EACH ROW EXECUTE FUNCTION etude.controle_observation();
