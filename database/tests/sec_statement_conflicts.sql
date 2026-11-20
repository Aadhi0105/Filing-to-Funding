\set ON_ERROR_STOP on

DO $check$
DECLARE
    conflict record;
BEGIN
    SELECT accession, concept, period_start, period_end, reporting_basis, scope_key
    INTO conflict
    FROM core.reported_facts
    WHERE taxonomy = 'filing-statement-v1'
    GROUP BY accession, concept, unit, period_start, period_end, dimensions, reporting_basis, scope_key
    HAVING count(DISTINCT value) > 1
    ORDER BY accession, concept, period_end, period_start, reporting_basis, scope_key
    LIMIT 1;

    IF FOUND THEN
        RAISE EXCEPTION 'SEC statement conflict in %, % (% through %, basis %, scope %)',
            conflict.accession, conflict.concept, coalesce(conflict.period_start, conflict.period_end),
            conflict.period_end, conflict.reporting_basis, conflict.scope_key;
    END IF;
END
$check$;
