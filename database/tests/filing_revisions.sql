\set ON_ERROR_STOP on

BEGIN;
SET LOCAL TIME ZONE 'Asia/Kolkata';

DO $test$
BEGIN
    IF EXISTS (
        SELECT FROM analytics.filing_amendments('0000049826', DATE '2021-08-05')
        WHERE amendment_accession = '0000049826-21-000064'
    ) OR NOT EXISTS (
        SELECT FROM analytics.filing_amendments('0000049826', DATE '2021-08-06')
        WHERE original_accession = '0000049826-21-000059'
          AND amendment_accession = '0000049826-21-000064'
          AND report_date = DATE '2021-06-30'
          AND original_filed_on = DATE '2021-08-05' AND amendment_filed_on = DATE '2021-08-06'
          AND relationship_reason = 'certification_signature_correction'
    ) THEN
        RAISE EXCEPTION 'ITW certification amendment lost its original or used a future filing';
    END IF;

    IF NOT EXISTS (
        SELECT FROM analytics.filing_fact_revisions('0000049826', DATE '2021-06-30', DATE '2021-08-06')
        WHERE concept = 'cash_and_equivalents'
          AND prior_accession = '0000049826-21-000059' AND later_accession = '0000049826-21-000064'
          AND relationship = 'unchanged_amendment' AND relationship_reason = 'certification_signature_correction'
          AND prior_value = 2058000000 AND later_value = prior_value AND unit = 'USD'
          AND cardinality(prior_fact_ids) = 1 AND cardinality(later_fact_ids) = 1
          AND prior_fact_ids <> later_fact_ids
          AND prior_url LIKE '%000004982621000059/%' AND later_url LIKE '%000004982621000064/%'
    ) OR EXISTS (
        SELECT FROM analytics.filing_fact_revisions('0000049826', DATE '2021-06-30', DATE '2021-08-05')
        WHERE later_accession = '0000049826-21-000064'
    ) THEN
        RAISE EXCEPTION 'ITW unchanged cash observation lost the evidence for either side of the amendment';
    END IF;

    IF EXISTS (
        SELECT FROM analytics.filing_fact_revisions('0000029905', DATE '2024-06-30', DATE '2025-07-23')
        WHERE relationship = 'scope_change'
    ) OR (
        SELECT count(*) FROM analytics.filing_fact_revisions('0000029905', DATE '2024-06-30', DATE '2025-07-24')
        WHERE relationship = 'scope_change' AND relationship_reason = 'esg_discontinued_operations'
          AND prior_accession = '0000029905-24-000035' AND later_accession = '0000029905-25-000024'
          AND prior_scope = 'dov_including_esg' AND later_scope = 'dov_excluding_esg'
          AND prior_basis = 'consolidated' AND later_basis = 'continuing_operations'
          AND period_start = DATE '2024-01-01'
          AND (concept, prior_value, later_value) IN (
              ('operating_cash_flow', 370255000, 295637000),
              ('cash_capex_outflow', -85347000, -75872000)
          )
    ) <> 2 OR EXISTS (
        SELECT FROM analytics.filing_fact_revisions('0000029905', DATE '2024-06-30', DATE '2025-07-24')
        WHERE relationship = 'changed_value' AND prior_scope <> later_scope
    ) THEN
        RAISE EXCEPTION 'Dover scope change lost a filing or was treated as a comparable revision';
    END IF;
END
$test$;

-- Synthetic amendments test a changed amount and an omitted observation in the same series.
INSERT INTO core.filings (
    accession, cik, report_period_id, form_type, filed_on, accepted_at, acceptance_timezone, filing_url, metadata_fetch_id
)
SELECT test.accession, filing.cik, filing.report_period_id, '10-Q/A', test.filed_on, test.accepted_at, 'UTC',
       'https://www.sec.gov/Archives/edgar/data/49826/' || replace(test.accession, '-', '') || '/synthetic.htm',
       filing.metadata_fetch_id
FROM core.filings AS filing
CROSS JOIN (VALUES
    ('0000049826-21-900001', DATE '2021-08-09', TIMESTAMPTZ '2021-08-10 01:00:00+00'),
    ('0000049826-21-900002', DATE '2021-08-10', TIMESTAMPTZ '2021-08-10 22:00:00+00')
) AS test(accession, filed_on, accepted_at)
WHERE filing.accession = '0000049826-21-000064';

INSERT INTO core.reported_facts (
    accession, taxonomy, concept, unit, period_start, period_end, dimensions, reporting_basis, scope_key,
    value, reported_decimals, source_fetch_id, source_locator
)
SELECT test.accession, fact.taxonomy, fact.concept, test.unit, NULL, fact.period_end, test.dimensions,
       fact.reporting_basis, fact.scope_key, test.value, fact.reported_decimals, fact.source_fetch_id, test.locator
FROM core.reported_facts AS fact
CROSS JOIN (VALUES
    ('0000049826-21-900001', 'USD', '{}'::jsonb, 1400000000, 'synthetic.htm#changed'),
    ('0000049826-21-900002', 'EUR', '{}'::jsonb, 950000000, 'synthetic.htm#other-currency'),
    ('0000049826-21-900002', 'USD', '{"segment":"example"}'::jsonb, 350000000, 'synthetic.htm#segment')
) AS test(accession, unit, dimensions, value, locator)
WHERE fact.accession = '0000049826-21-000064' AND fact.taxonomy = 'filing-statement-v1'
  AND fact.concept = 'cash_and_equivalents';

DO $test$
BEGIN
    IF EXISTS (
        SELECT FROM analytics.filing_fact_revisions('0000049826', DATE '2021-06-30', DATE '2021-08-08')
        WHERE later_accession = '0000049826-21-900001'
    ) OR NOT EXISTS (
        SELECT FROM analytics.filing_fact_revisions('0000049826', DATE '2021-06-30', DATE '2021-08-09')
        WHERE concept = 'cash_and_equivalents' AND prior_accession = '0000049826-21-000064'
          AND later_accession = '0000049826-21-900001' AND relationship = 'changed_value'
          AND relationship_reason = 'different_reported_amount'
          AND prior_value = 2058000000 AND later_value = 1400000000
    ) OR EXISTS (
        SELECT FROM analytics.filing_fact_revisions('0000049826', DATE '2021-06-30', DATE '2021-08-10')
        WHERE concept = 'cash_and_equivalents' AND later_accession = '0000049826-21-900002'
    ) OR NOT EXISTS (
        SELECT FROM analytics.filing_amendments('0000049826', DATE '2021-08-10')
        WHERE original_accession = '0000049826-21-000059' AND amendment_accession = '0000049826-21-900002'
    ) THEN
        RAISE EXCEPTION 'Controlled revision changed an earlier cutoff or matched incompatible facts';
    END IF;
END
$test$;

INSERT INTO core.reported_facts (
    accession, taxonomy, concept, unit, period_start, period_end, dimensions, reporting_basis, scope_key,
    value, reported_decimals, source_fetch_id, source_locator
)
SELECT accession, taxonomy, concept, unit, period_start, period_end, dimensions, reporting_basis, scope_key,
       1500000000, reported_decimals, source_fetch_id, 'synthetic.htm#conflict'
FROM core.reported_facts WHERE accession = '0000049826-21-900001';

DO $test$
BEGIN
    IF EXISTS (
        SELECT FROM analytics.filing_fact_revisions('0000049826', DATE '2021-06-30')
        WHERE '0000049826-21-900001' IN (prior_accession, later_accession)
    ) THEN
        RAISE EXCEPTION 'A conflicting disclosure was classified as a comparable value change';
    END IF;
    RAISE NOTICE 'Filing revision and amendment checks passed';
END
$test$;

ROLLBACK;
