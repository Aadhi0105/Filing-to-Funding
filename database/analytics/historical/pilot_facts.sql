CREATE FUNCTION analytics.pilot_facts(
    p_cik text,
    p_period_start date,
    p_period_end date,
    p_reporting_basis text,
    p_scope_key text,
    p_filed_by date DEFAULT NULL
)
RETURNS TABLE (
    concept text,
    value numeric,
    status text,
    fact_ids bigint[],
    source_accessions text[]
)
LANGUAGE sql
STABLE
AS $function$
    WITH eligible AS (
        SELECT fact.concept, fact.value, fact.fact_id, filing.accession, filing.accepted_at,
               filing.filed_on, max(filing.filed_on) OVER (PARTITION BY fact.concept) AS newest_day
        FROM core.reported_facts AS fact
        JOIN core.filings AS filing USING (accession)
        WHERE filing.cik = p_cik
          AND fact.taxonomy = 'filing-line'
          AND fact.unit = 'USD'
          AND fact.dimensions = '{}'::jsonb
          AND fact.period_start IS NOT DISTINCT FROM p_period_start
          AND fact.period_end = p_period_end
          AND fact.reporting_basis = p_reporting_basis
          AND fact.scope_key = p_scope_key
          AND (
              p_filed_by IS NULL
              OR (
                  p_period_end <= p_filed_by
                  AND filing.filed_on <= p_filed_by
                  AND filing.accepted_at < ((p_filed_by + 1)::timestamp AT TIME ZONE 'America/New_York')
              )
          )
    ), latest_day AS (
        SELECT eligible.*,
               max(eligible.accepted_at) OVER (PARTITION BY eligible.concept) AS latest_time,
               bool_or(eligible.accepted_at IS NULL) OVER (PARTITION BY eligible.concept) AS has_unknown_time
        FROM eligible
        WHERE eligible.filed_on = eligible.newest_day
    )
    SELECT latest.concept,
           CASE WHEN count(DISTINCT latest.value) = 1 THEN min(latest.value) END,
           CASE WHEN count(DISTINCT latest.value) = 1 THEN 'available' ELSE 'conflicting_observations' END,
           array_agg(latest.fact_id ORDER BY latest.fact_id),
           array_agg(DISTINCT latest.accession ORDER BY latest.accession)
    FROM latest_day AS latest
    -- Unknown time on the newest day prevents ordering those disclosures within the day.
    WHERE latest.has_unknown_time OR latest.accepted_at = latest.latest_time
    GROUP BY latest.concept;
$function$;
