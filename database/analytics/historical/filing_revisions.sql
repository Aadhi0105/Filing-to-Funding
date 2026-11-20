CREATE FUNCTION analytics.revision_filings(
    p_cik text,
    p_filed_by date
)
RETURNS SETOF core.filings
LANGUAGE sql
STABLE
AS $function$
    SELECT filing.*
    FROM core.filings AS filing
    WHERE filing.cik = p_cik
      AND (
          p_filed_by IS NULL
          OR (
              filing.filed_on <= p_filed_by
              AND filing.accepted_at < ((p_filed_by + 1)::timestamp AT TIME ZONE 'America/New_York')
          )
      );
$function$;

CREATE FUNCTION analytics.filing_amendments(
    p_cik text,
    p_filed_by date DEFAULT NULL
)
RETURNS TABLE (
    original_accession text, amendment_accession text, report_date date,
    original_filed_on date, amendment_filed_on date,
    original_url text, amendment_url text, relationship_reason text
)
LANGUAGE sql
STABLE
AS $function$
    WITH eligible AS (
        SELECT * FROM analytics.revision_filings(p_cik, p_filed_by)
    )
    SELECT original.accession, amendment.accession, period.ends_on,
           original.filed_on, amendment.filed_on, original.filing_url, amendment.filing_url,
           CASE
               WHEN (original.accession, amendment.accession) = ('0000049826-21-000059', '0000049826-21-000064')
                   THEN 'certification_signature_correction'
               ELSE 'unique_original_for_report_and_form'
           END
    FROM eligible AS amendment
    CROSS JOIN LATERAL (
        SELECT filing.*, count(*) OVER () AS candidate_count
        FROM eligible AS filing
        WHERE filing.report_period_id = amendment.report_period_id
          AND amendment.form_type = filing.form_type || '/A'
          AND filing.filed_on <= amendment.filed_on
          AND (filing.accepted_at IS NULL OR filing.accepted_at < amendment.accepted_at)
    ) AS original
    JOIN core.reporting_periods AS period ON period.period_id = original.report_period_id
    WHERE amendment.accepted_at IS NOT NULL AND original.accepted_at IS NOT NULL
      AND original.candidate_count = 1
      AND (p_filed_by IS NULL OR period.ends_on <= p_filed_by)
    ORDER BY amendment.filed_on, amendment.accepted_at, amendment.accession;
$function$;

CREATE FUNCTION analytics.filing_fact_revisions(
    p_cik text,
    p_period_end date,
    p_filed_by date DEFAULT NULL
)
RETURNS TABLE (
    concept text, period_start date, period_end date, unit text,
    relationship text, relationship_reason text,
    prior_accession text, later_accession text, prior_filed_on date, later_filed_on date,
    prior_url text, later_url text, prior_value numeric, later_value numeric,
    prior_basis text, later_basis text, prior_scope text, later_scope text,
    prior_fact_ids bigint[], later_fact_ids bigint[]
)
LANGUAGE sql
STABLE
AS $function$
    WITH eligible AS (
        SELECT * FROM analytics.revision_filings(p_cik, p_filed_by)
        WHERE p_filed_by IS NULL OR p_period_end <= p_filed_by
    ), fact_groups AS (
        SELECT fact.accession, fact.concept, fact.period_start, fact.period_end, fact.unit,
               fact.reporting_basis, fact.scope_key, filing.report_period_id, filing.form_type,
               filing.filed_on, filing.accepted_at, filing.filing_url,
               min(fact.value) AS reported_value, count(DISTINCT fact.value) = 1 AS values_agree,
               array_agg(fact.fact_id ORDER BY fact.fact_id) AS fact_ids
        FROM eligible AS filing
        JOIN core.reported_facts AS fact USING (accession)
        WHERE fact.period_end = p_period_end
          AND fact.taxonomy IN ('filing-line', 'filing-statement-v1')
          AND fact.unit = 'USD' AND fact.dimensions = '{}'::jsonb
        GROUP BY fact.accession, fact.concept, fact.period_start, fact.period_end, fact.unit,
                 fact.reporting_basis, fact.scope_key, filing.report_period_id, filing.form_type,
                 filing.filed_on, filing.accepted_at, filing.filing_url
    ), ordered AS (
        SELECT grouped.*,
               count(*) OVER (PARTITION BY concept, period_start, period_end, unit,
                                           reporting_basis, scope_key, filed_on, accepted_at) AS simultaneous,
               bool_or(accepted_at IS NULL) OVER (PARTITION BY concept, period_start, period_end, unit,
                                                               reporting_basis, scope_key, filed_on) AS day_has_unknown,
               lag(accession) OVER (
                   series ORDER BY filed_on, accepted_at, accession
               ) AS previous_accession
        FROM fact_groups AS grouped
        WINDOW series AS (PARTITION BY concept, period_start, period_end, unit, reporting_basis, scope_key)
    ), comparable AS (
        SELECT prior AS older, later AS newer,
               CASE WHEN prior.reported_value <> later.reported_value THEN 'changed_value'
                    ELSE 'unchanged_amendment' END AS kind,
               CASE
                   WHEN prior.reported_value <> later.reported_value THEN 'different_reported_amount'
                   ELSE coalesce(review.relationship_reason, 'same_reported_amount')
               END AS reason
        FROM ordered AS later
        JOIN ordered AS prior
          ON prior.accession = later.previous_accession
         AND (prior.concept, prior.period_start, prior.period_end, prior.unit, prior.reporting_basis, prior.scope_key)
             IS NOT DISTINCT FROM
             (later.concept, later.period_start, later.period_end, later.unit, later.reporting_basis, later.scope_key)
        LEFT JOIN analytics.filing_amendments(p_cik, p_filed_by) AS review
          ON review.original_accession = prior.accession AND review.amendment_accession = later.accession
         AND review.relationship_reason = 'certification_signature_correction'
        WHERE prior.values_agree AND later.values_agree
          AND prior.simultaneous = 1 AND later.simultaneous = 1
          AND NOT prior.day_has_unknown AND NOT later.day_has_unknown
          AND prior.accepted_at < later.accepted_at
          AND (
              prior.reported_value <> later.reported_value
              OR (
                  later.form_type LIKE '%/A'
                  AND prior.report_period_id = later.report_period_id
                  AND split_part(prior.form_type, '/', 1) = split_part(later.form_type, '/', 1)
              )
          )
    ), scope_changes AS (
        -- Dover Note 4 documents the ESG disposition and the continuing-operations comparative.
        SELECT prior AS older, later AS newer, 'scope_change' AS kind, 'esg_discontinued_operations' AS reason
        FROM ordered AS prior
        JOIN ordered AS later
          ON (prior.concept, prior.period_start, prior.period_end, prior.unit)
             = (later.concept, later.period_start, later.period_end, later.unit)
        WHERE prior.accession = '0000029905-24-000035'
          AND later.accession = '0000029905-25-000024'
          AND prior.concept IN ('operating_cash_flow', 'cash_capex_outflow')
          AND prior.period_start = DATE '2024-01-01' AND prior.period_end = DATE '2024-06-30'
          AND (prior.reporting_basis, prior.scope_key) = ('consolidated', 'dov_including_esg')
          AND (later.reporting_basis, later.scope_key) = ('continuing_operations', 'dov_excluding_esg')
          AND prior.values_agree AND later.values_agree
          AND (prior.filed_on, prior.accepted_at) < (later.filed_on, later.accepted_at)
    ), relationships AS (
        SELECT * FROM comparable
        UNION ALL
        SELECT * FROM scope_changes
    )
    SELECT (newer).concept, (newer).period_start, (newer).period_end, (newer).unit,
           kind, reason,
           (older).accession, (newer).accession, (older).filed_on, (newer).filed_on,
           (older).filing_url, (newer).filing_url, (older).reported_value, (newer).reported_value,
           (older).reporting_basis, (newer).reporting_basis, (older).scope_key, (newer).scope_key,
           (older).fact_ids, (newer).fact_ids
    FROM relationships
    ORDER BY (newer).filed_on, (newer).accepted_at, (newer).accession,
             (newer).concept, (newer).period_start, (newer).scope_key;
$function$;
