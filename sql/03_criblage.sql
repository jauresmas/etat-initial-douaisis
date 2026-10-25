-- Criblage des friches du territoire pour une centrale photovoltaïque au sol.
-- Chaque critère de criblage.regle est calculé pour chaque friche (vue criblage.critere),
-- puis la grille donne une classe et un rang (vue matérialisée criblage.resultat).
-- C'est une aide au choix d'un site à étudier, pas une évaluation environnementale.

DROP MATERIALIZED VIEW IF EXISTS criblage.resultat CASCADE;
DROP VIEW IF EXISTS criblage.critere CASCADE;

-- Part (0 à 1) d'une géométrie couverte par une couche surfacique, sans double compte
-- des recouvrements entre objets de la couche
CREATE OR REPLACE FUNCTION criblage.part_couverte(g geometry, couche regclass)
RETURNS numeric LANGUAGE plpgsql STABLE AS $$
DECLARE s double precision;
BEGIN
    EXECUTE format('SELECT ST_Area(ST_Union(ST_Intersection(c.geom, $1))) FROM %s c '
                   'WHERE ST_Intersects(c.geom, $1)', couche) INTO s USING g;
    RETURN round((coalesce(s, 0) / NULLIF(ST_Area(g), 0))::numeric, 3);
END $$;

CREATE VIEW criblage.critere AS
WITH f AS (
    SELECT site_id, site_nom, commune, site_statut, activite_libelle, urba_zone_type,
           surface_ha, geom, ST_Difference(ST_Buffer(geom, 100), geom) AS pourtour
    FROM ref.friche
), n2000 AS (
    SELECT geom FROM ref.zsc UNION ALL SELECT geom FROM ref.zps
), protection AS (
    SELECT geom FROM ref.rnn UNION ALL SELECT geom FROM ref.rnr
    UNION ALL SELECT geom FROM ref.apb UNION ALL SELECT geom FROM ref.rb
), unesco AS (
    SELECT geom FROM ref.unesco_bien UNION ALL SELECT geom FROM ref.terril_unesco
), ppr AS (
    SELECT geom FROM ref.ppr_inond UNION ALL SELECT geom FROM ref.ppr_minier
    UNION ALL SELECT geom FROM ref.pprt
), pollution AS (
    SELECT geom FROM ref.sis UNION ALL SELECT geom FROM ref.ssp
), htb AS (  -- lignes de 63 kV et plus (raccordement d'une centrale de quelques MWc)
    SELECT geom FROM ref.ligne_elec
    WHERE substring(voltage FROM '([0-9]+) kV')::int >= 63
)
SELECT
    f.site_id, f.site_nom, f.commune, f.site_statut, f.activite_libelle, f.urba_zone_type,
    f.surface_ha,
    -- exclusions
    f.surface_ha < (SELECT seuil FROM criblage.regle WHERE critere = 'surface_insuffisante')
        AS surface_insuffisante,
    coalesce(f.site_statut = 'friche avec projet', false) AS projet_en_cours,
    EXISTS (SELECT 1 FROM protection p WHERE ST_Intersects(p.geom, f.geom)
            AND ST_Area(ST_Intersection(p.geom, f.geom)) > 100) AS protection_forte,
    EXISTS (SELECT 1 FROM unesco u WHERE ST_Intersects(u.geom, f.geom)
            AND ST_Area(ST_Intersection(u.geom, f.geom)) > 100) AS bien_unesco,
    -- contrôle de la donnée : Cartofriches recense des friches « potentielles » (anciens sites
    -- industriels) dont certaines ont été reconstruites depuis ; l'usage OCS GE le révèle
    round((SELECT coalesce(sum(ST_Area(ST_Intersection(o.geom, f.geom))), 0)
           FROM ref.ocsge_2025 o
           WHERE o.code_us IN ('US2', 'US3', 'US235', 'US4.2', 'US4.3', 'US5')
             AND ST_Intersects(o.geom, f.geom))::numeric / ST_Area(f.geom)::numeric, 3) AS part_en_activite,
    -- enjeux forts
    EXISTS (SELECT 1 FROM n2000 n WHERE ST_Intersects(n.geom, f.geom)
            AND ST_Area(ST_Intersection(n.geom, f.geom)) > 100) AS natura2000,
    criblage.part_couverte(f.geom, 'ref.znieff1') AS part_znieff1,
    criblage.part_couverte(f.geom, 'ref.zdh') AS part_zone_humide,
    EXISTS (SELECT 1 FROM ppr p WHERE ST_Intersects(p.geom, f.geom)
            AND ST_Area(ST_Intersection(p.geom, f.geom)) > 100) AS ppr,
    -- enjeux modérés
    round((SELECT min(ST_Distance(n.geom, f.geom)) FROM n2000 n)::numeric) AS distance_natura2000_m,
    EXISTS (SELECT 1 FROM ref.znieff2 z WHERE ST_Intersects(z.geom, f.geom)) AS znieff2,
    EXISTS (SELECT 1 FROM ref.unesco_tampon t WHERE ST_Intersects(t.geom, f.geom)) AS tampon_unesco,
    round((SELECT coalesce(sum(ST_Area(ST_Intersection(o.geom, f.pourtour))), 0)
           FROM ref.ocsge_2025 o
           WHERE o.code_us = 'US5' AND ST_Intersects(o.geom, f.pourtour))::numeric
          / ST_Area(f.pourtour)::numeric, 3) AS part_residentiel_100m,
    -- atouts
    EXISTS (SELECT 1 FROM pollution p WHERE ST_Intersects(p.geom, f.geom)) AS sol_pollue,
    round((SELECT min(ST_Distance(h.geom, f.geom)) FROM htb h)::numeric) AS distance_htb_m,
    round((SELECT coalesce(sum(ST_Area(ST_Intersection(o.geom, f.geom))), 0)
           FROM ref.ocsge_2025 o
           WHERE (o.code_cs LIKE 'CS1%' OR o.code_us IN ('US6.1', 'US6.2', 'US6.3', 'US1.3'))
             AND ST_Intersects(o.geom, f.geom))::numeric / ST_Area(f.geom)::numeric, 3)
        AS part_artificialisee,
    f.geom
FROM f;

COMMENT ON VIEW criblage.critere IS 'Valeur de chaque critère du criblage pour chaque friche';

CREATE MATERIALIZED VIEW criblage.resultat AS
WITH seuils AS (SELECT critere, seuil FROM criblage.regle),
declenche AS (  -- critères déclenchés, en appliquant les seuils de la grille
    SELECT c.site_id, r.critere, r.effet, r.points, r.libelle
    FROM criblage.critere c
    CROSS JOIN LATERAL (VALUES
        ('surface_insuffisante', c.surface_insuffisante),
        ('projet_en_cours', c.projet_en_cours),
        ('protection_forte', c.protection_forte),
        ('bien_unesco', c.bien_unesco),
        ('deja_reconverti', c.part_en_activite > (SELECT seuil FROM seuils WHERE critere = 'deja_reconverti')),
        ('natura2000', c.natura2000),
        ('znieff1', c.part_znieff1 > (SELECT seuil FROM seuils WHERE critere = 'znieff1')),
        ('zone_humide', c.part_zone_humide > (SELECT seuil FROM seuils WHERE critere = 'zone_humide')),
        ('ppr', c.ppr),
        ('natura2000_proche', NOT c.natura2000 AND c.distance_natura2000_m
            <= (SELECT seuil FROM seuils WHERE critere = 'natura2000_proche')),
        ('znieff2', c.znieff2),
        ('tampon_unesco', c.tampon_unesco),
        ('riverains', c.part_residentiel_100m > (SELECT seuil FROM seuils WHERE critere = 'riverains')),
        ('sol_pollue', c.sol_pollue),
        ('reseau_proche', c.distance_htb_m <= (SELECT seuil FROM seuils WHERE critere = 'reseau_proche')),
        ('artificialise', c.part_artificialisee > (SELECT seuil FROM seuils WHERE critere = 'artificialise')),
        ('grande_surface', c.surface_ha >= (SELECT seuil FROM seuils WHERE critere = 'grande_surface'))
    ) AS v (critere, actif)
    JOIN criblage.regle r USING (critere)
    WHERE v.actif
),
synthese AS (
    SELECT site_id,
           bool_or(effet = 'exclusion') AS exclu,
           count(*) FILTER (WHERE effet = 'fort') AS nb_forts,
           count(*) FILTER (WHERE effet = 'modere') AS nb_moderes,
           coalesce(sum(points), 0) AS points,
           string_agg(libelle, ' ; ' ORDER BY effet, critere) FILTER (WHERE effet <> 'favorable')
               AS contraintes,
           string_agg(libelle, ' ; ' ORDER BY critere) FILTER (WHERE effet = 'favorable') AS atouts
    FROM declenche
    GROUP BY site_id
)
SELECT c.site_id, c.site_nom, c.commune, c.surface_ha, c.site_statut, c.urba_zone_type,
       c.part_en_activite, c.part_znieff1, c.part_zone_humide, c.distance_natura2000_m, c.part_residentiel_100m,
       c.distance_htb_m, c.part_artificialisee,
       coalesce(s.points, 0) AS points,
       CASE WHEN s.exclu THEN 'Exclu'
            WHEN s.nb_forts > 0 THEN 'Défavorable'
            WHEN coalesce(s.nb_moderes, 0) > 0 THEN 'À approfondir'
            ELSE 'Favorable' END AS classe,
       s.contraintes, s.atouts,
       c.geom
FROM criblage.critere c
LEFT JOIN synthese s USING (site_id);

CREATE UNIQUE INDEX ON criblage.resultat (site_id);
CREATE INDEX ON criblage.resultat USING gist (geom);
COMMENT ON MATERIALIZED VIEW criblage.resultat IS
    'Classe et points de chaque friche ; rafraîchir après une mise à jour du référentiel';

-- Classement : les classes dans l'ordre, puis les points, puis la surface
CREATE VIEW criblage.classement AS
SELECT row_number() OVER (ORDER BY array_position(ARRAY['Favorable', 'À approfondir', 'Défavorable', 'Exclu'],
                                                  classe), points DESC, surface_ha DESC) AS rang,
       *
FROM criblage.resultat;

GRANT SELECT ON ALL TABLES IN SCHEMA criblage TO lecteur;
