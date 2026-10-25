-- Après chargement du référentiel : catalogue, index spatiaux, clés, droits et commentaires.

-- Catalogue : fusion de l'import (le journal de veille des couches connues est conservé)
INSERT INTO meta.catalogue (code, libelle, theme, famille, producteur, service, couche_source,
                            table_ref, nb_objets, empreinte, date_maj)
SELECT code, libelle, theme, famille, producteur, service, couche_source, table_ref,
       nb_objets, empreinte, date_maj
FROM meta.catalogue_import
ON CONFLICT (code) DO UPDATE SET
    libelle = EXCLUDED.libelle, theme = EXCLUDED.theme, famille = EXCLUDED.famille,
    producteur = EXCLUDED.producteur, service = EXCLUDED.service,
    couche_source = EXCLUDED.couche_source, table_ref = EXCLUDED.table_ref,
    nb_objets = EXCLUDED.nb_objets, empreinte = EXCLUDED.empreinte, date_maj = EXCLUDED.date_maj;
DROP TABLE meta.catalogue_import;

-- Index spatial et clé primaire technique sur chaque table du référentiel
DO $$
DECLARE t record;
BEGIN
    FOR t IN SELECT f_table_name AS nom FROM geometry_columns WHERE f_table_schema = 'ref' LOOP
        EXECUTE format('ALTER TABLE ref.%I ADD COLUMN gid serial PRIMARY KEY', t.nom);
        EXECUTE format('CREATE INDEX %I ON ref.%I USING gist (geom)', t.nom || '_geom_idx', t.nom);
        EXECUTE format('COMMENT ON TABLE ref.%I IS %L', t.nom,
                       (SELECT libelle || ' - ' || coalesce(producteur, '') FROM meta.catalogue
                        WHERE code = t.nom));
    END LOOP;
END $$;

ALTER TABLE ref.friche ADD CONSTRAINT friche_site_id_uniq UNIQUE (site_id);
CREATE INDEX ON ref.ocsge_2025 (code_cs);
CREATE INDEX ON ref.ocsge_2025 (code_us);

-- Droits : le schéma a été recréé, les privilèges par défaut sont à reposer
GRANT USAGE ON SCHEMA ref TO lecteur;
GRANT SELECT ON ALL TABLES IN SCHEMA ref TO lecteur;
ALTER DEFAULT PRIVILEGES IN SCHEMA ref GRANT SELECT ON TABLES TO lecteur;

ANALYZE;
