\set ON_ERROR_STOP on

DO $test$
DECLARE
    observed numeric;
    accepted_time timestamptz;
BEGIN
    IF (SELECT count(*) FROM raw.source_fetches
        WHERE source_kind IN ('sec_filing_review', 'treasury_yield_review')) <> 8
       OR (SELECT count(*) FROM core.filings
           JOIN raw.source_fetches ON fetch_id = metadata_fetch_id
           WHERE source_kind = 'sec_filing_review') <> 7
       OR (SELECT count(*) FROM core.reported_facts WHERE taxonomy = 'filing-line') <> 51
       OR (SELECT count(*) FROM core.treasury_yield_observations
           JOIN raw.source_fetches ON fetch_id = source_fetch_id
           WHERE source_kind = 'treasury_yield_review') <> 15 THEN
        RAISE EXCEPTION 'Reviewed pilot batch counts do not match the seven filings and five market dates';
    END IF;

    -- Task 2 put these facts on the same period but on different reporting scopes.
    SELECT value INTO STRICT observed
    FROM core.reported_facts
    WHERE accession = '0000029905-24-000035'
      AND concept = 'operating_cash_flow'
      AND period_end = DATE '2024-06-30'
      AND scope_key = 'esg_included'
      AND unit = 'USD' AND reported_decimals = '-3';
    IF observed <> 370255000 THEN
        RAISE EXCEPTION 'Dover original half-year cash flow was changed or scaled incorrectly';
    END IF;

    SELECT fact.value INTO STRICT observed
    FROM core.reported_facts AS fact
    JOIN core.filings AS filing USING (accession)
    JOIN core.reporting_periods AS period ON period.period_id = filing.report_period_id
    JOIN raw.source_fetches AS source ON source.fetch_id = fact.source_fetch_id
    WHERE fact.accession = '0000029905-25-000024'
      AND fact.concept = 'operating_cash_flow'
      AND fact.period_start = DATE '2024-01-01'
      AND fact.period_end = DATE '2024-06-30'
      AND period.ends_on = DATE '2025-06-30'
      AND fact.scope_key = 'esg_excluded'
      AND source.source_kind = 'sec_filing_review'
      AND source.retrieved_at IS NULL
      AND fact.source_locator LIKE '/filings/%/statements/%/lines/%';
    IF observed <> 295637000 THEN
        RAISE EXCEPTION 'Dover comparative dates, scale, or provenance were lost';
    END IF;

    SELECT accepted_at INTO STRICT accepted_time
    FROM core.filings WHERE accession = '0000049826-26-000049';
    IF accepted_time IS DISTINCT FROM TIMESTAMPTZ '2026-08-06 19:34:23+00' THEN
        RAISE EXCEPTION 'Eastern acceptance was not converted to the correct UTC instant';
    END IF;

    SELECT accepted_at INTO STRICT accepted_time
    FROM core.filings WHERE accession = '0001024478-26-000048';
    IF accepted_time IS NOT NULL THEN
        RAISE EXCEPTION 'Rockwell acceptance was inferred from a filing date or retrieval time';
    END IF;

    SELECT yield_percent INTO STRICT observed
    FROM core.treasury_yield_observations AS observation
    JOIN raw.source_fetches AS source ON source.fetch_id = observation.source_fetch_id
    WHERE observation_date = DATE '2024-10-24' AND maturity_months = 120
      AND source.source_kind = 'treasury_yield_review'
      AND source_published_at IS NULL;
    IF observed <> 4.21 THEN
        RAISE EXCEPTION 'The 10-year Treasury sample was rounded or given an invented publication time';
    END IF;

    RAISE NOTICE 'Pilot import checks passed';
END
$test$;
