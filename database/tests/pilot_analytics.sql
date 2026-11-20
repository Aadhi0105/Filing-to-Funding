\set ON_ERROR_STOP on

BEGIN;
-- New York eligibility must be independent of the database session time zone.
SET LOCAL TIME ZONE 'Asia/Kolkata';

DO $test$
DECLARE
    failures text;
    candidate record;
    rockwell_acceptance_known boolean;
BEGIN
    SELECT accepted_at IS NOT NULL INTO STRICT rockwell_acceptance_known
    FROM core.filings WHERE accession = '0001024478-26-000048';

    WITH cases(label, cik, fiscal_year, quarter, fy_start, basis, scope, filed_by, cfo, capex, fcf, status) AS (
        VALUES
            ('ITW Q1', '0000049826', 2026, 1, DATE '2026-01-01', 'consolidated', 'as_reported',
             DATE '2026-05-07', 623000000, 95000000, 528000000, 'available'),
            ('ITW Q2 day before filing', '0000049826', 2026, 2, DATE '2026-01-01', 'consolidated', 'as_reported',
             DATE '2026-08-05', NULL, NULL, NULL, 'missing_compatible_operands'),
            ('ITW Q2 on filing day', '0000049826', 2026, 2, DATE '2026-01-01', 'consolidated', 'as_reported',
             DATE '2026-08-06', 723000000, 92000000, 631000000, 'available'),
            ('Dover Q3 when originally filed', '0000029905', 2024, 3, DATE '2024-01-01',
             'continuing_operations', 'esg_excluded', DATE '2024-10-24',
             NULL, NULL, NULL, 'missing_compatible_operands'),
            ('Dover Q3 just before comparative', '0000029905', 2024, 3, DATE '2024-01-01',
             'continuing_operations', 'esg_excluded', DATE '2025-07-23',
             NULL, NULL, NULL, 'missing_compatible_operands'),
            ('Dover Q3 with eligible comparative', '0000029905', 2024, 3, DATE '2024-01-01',
             'continuing_operations', 'esg_excluded', DATE '2025-07-24',
             353244000, 37754000, 315490000, 'available'),
            ('Rockwell Q4 latest', '0001024478', 2026, 4, DATE '2025-10-01', 'consolidated', 'as_reported',
             NULL, 680000000, 78000000, 602000000, 'available'),
            ('Rockwell Q4 before filing', '0001024478', 2026, 4, DATE '2025-10-01',
             'consolidated', 'as_reported', DATE '2026-11-11',
             NULL, NULL, NULL, 'missing_compatible_operands'),
            ('Rockwell Q4 on filing day', '0001024478', 2026, 4, DATE '2025-10-01',
             'consolidated', 'as_reported', DATE '2026-11-12',
             CASE WHEN rockwell_acceptance_known THEN 680000000 END,
             CASE WHEN rockwell_acceptance_known THEN 78000000 END,
             CASE WHEN rockwell_acceptance_known THEN 602000000 END,
             CASE WHEN rockwell_acceptance_known THEN 'available' ELSE 'missing_compatible_operands' END),
            ('Rockwell wrong fiscal start', '0001024478', 2026, 4, DATE '2026-01-01',
             'consolidated', 'as_reported', NULL, NULL, NULL, NULL, 'unsupported_fiscal_period')
    )
    SELECT string_agg(c.label, ', ') INTO failures
    FROM cases AS c
    LEFT JOIN LATERAL analytics.pilot_quarter_cash_flow(
        c.cik, c.fiscal_year, c.quarter, c.fy_start, c.basis, c.scope, c.filed_by
    ) AS actual ON true
    WHERE (actual.status, actual.operating_cash_flow, actual.cash_capex, actual.free_cash_flow)
       IS DISTINCT FROM (c.status, c.cfo, c.capex, c.fcf);
    IF failures IS NOT NULL THEN
        RAISE EXCEPTION 'Quarterly reconciliation failed: %', failures;
    END IF;

    SELECT * INTO STRICT candidate
    FROM analytics.pilot_quarter_cash_flow(
        '0000029905', 2024, 3, DATE '2024-01-01', 'continuing_operations', 'esg_excluded', DATE '2025-07-24'
    );
    IF candidate.quarter_start IS DISTINCT FROM DATE '2024-07-01'
       OR candidate.quarter_end IS DISTINCT FROM DATE '2024-09-30'
       OR cardinality(candidate.fact_ids) IS DISTINCT FROM 4
       OR candidate.source_accessions IS DISTINCT FROM ARRAY['0000029905-24-000045', '0000029905-25-000024'] THEN
        RAISE EXCEPTION 'Dover Q3 lacks the four reviewed operands or both source accessions';
    END IF;

    SELECT * INTO STRICT candidate
    FROM analytics.pilot_facts(
        '0000029905', DATE '2024-01-01', DATE '2024-06-30', 'consolidated', 'esg_included', DATE '2025-07-24'
    )
    WHERE concept = 'operating_cash_flow';
    IF candidate.value IS DISTINCT FROM 370255000
       OR candidate.source_accessions IS DISTINCT FROM ARRAY['0000029905-24-000035'] THEN
        RAISE EXCEPTION 'Later continuing-operations comparative replaced Dover''s original scoped fact';
    END IF;

    SELECT * INTO STRICT candidate
    FROM analytics.pilot_quarter_cash_flow(
        '0001024478', 2026, 4, DATE '2025-10-01', 'consolidated', 'as_reported'
    );
    IF candidate.quarter_start IS DISTINCT FROM DATE '2026-07-01'
       OR candidate.quarter_end IS DISTINCT FROM DATE '2026-09-30' THEN
        RAISE EXCEPTION 'Rockwell fiscal Q4 did not use the September year-end';
    END IF;

    WITH cases(label, cik, report_date, scope, filed_by, metric, expected, status) AS (
        VALUES
            ('ITW working capital', '0000049826', DATE '2026-06-30', 'as_reported', DATE '2026-08-06',
             'working_capital', 647000000::numeric, 'available'),
            ('ITW current ratio', '0000049826', DATE '2026-06-30', 'as_reported', DATE '2026-08-06',
             'current_ratio', 1.108685, 'available'),
            ('ITW net debt', '0000049826', DATE '2026-06-30', 'as_reported', DATE '2026-08-06',
             'reported_net_debt', 8855000000, 'available'),
            ('Dover working capital', '0000029905', DATE '2024-09-30', 'esg_held_for_sale', DATE '2024-10-24',
             'working_capital', 1358698000, 'available'),
            ('Dover cash excludes cash held for sale', '0000029905', DATE '2024-09-30', 'esg_held_for_sale',
             DATE '2024-10-24', 'cash_ratio', 0.162016, 'available'),
            ('Dover reported debt', '0000029905', DATE '2024-09-30', 'esg_held_for_sale', DATE '2024-10-24',
             'reported_debt', 3387115000, 'available'),
            ('Rockwell reported debt', '0001024478', DATE '2026-09-30', 'as_reported', NULL,
             'reported_debt', 3280000000, 'available'),
            ('Rockwell borrowing debt excluding finance leases', '0001024478', DATE '2026-09-30',
             'as_reported', NULL, 'borrowing_debt_excluding_finance_leases', 3276000000, 'available'),
            ('Rockwell net borrowing debt', '0001024478', DATE '2026-09-30',
             'as_reported', NULL, 'net_borrowing_debt_excluding_finance_leases', 2843000000, 'available'),
            ('Rockwell no June lease note', '0001024478', DATE '2026-06-30', 'as_reported', NULL,
             'borrowing_debt_excluding_finance_leases', NULL, 'missing_compatible_operands')
    )
    SELECT string_agg(c.label, ', ') INTO failures
    FROM cases AS c
    LEFT JOIN LATERAL analytics.pilot_balance_sheet(c.cik, c.report_date, c.scope, c.filed_by) AS actual
        ON actual.metric = c.metric
    WHERE (actual.status, round(actual.value, 6)) IS DISTINCT FROM (c.status, c.expected);
    IF failures IS NOT NULL THEN
        RAISE EXCEPTION 'Balance-sheet reconciliation failed: %', failures;
    END IF;
END
$test$;

-- Synthetic in-transaction amendment, after midnight UTC but still on the filing day in New York.
INSERT INTO core.filings (
    accession, cik, report_period_id, form_type, filed_on, accepted_at, acceptance_timezone,
    filing_url, metadata_fetch_id
)
SELECT '0000049826-26-999999', cik, report_period_id, '10-Q/A', DATE '2026-08-06',
       TIMESTAMPTZ '2026-08-07 01:30:00+00', 'America/New_York',
       'https://www.sec.gov/Archives/edgar/data/49826/pilot-test-only.htm', metadata_fetch_id
FROM core.filings WHERE accession = '0000049826-26-000049';

INSERT INTO core.reported_facts (
    accession, taxonomy, concept, unit, period_end, reporting_basis, scope_key,
    value, reported_decimals, source_fetch_id, source_locator
)
SELECT '0000049826-26-999999', 'filing-line', 'current_assets', 'USD', DATE '2026-06-30',
       'consolidated', 'as_reported', 6700000000, '-6', metadata_fetch_id, 'synthetic test only'
FROM core.filings WHERE accession = '0000049826-26-999999';

DO $test$
DECLARE candidate record;
BEGIN
    SELECT * INTO STRICT candidate
    FROM analytics.pilot_facts('0000049826', NULL, DATE '2026-06-30',
                               'consolidated', 'as_reported', DATE '2026-08-06')
    WHERE concept = 'current_assets';
    IF candidate.value IS DISTINCT FROM 6700000000 THEN
        RAISE EXCEPTION 'End-of-day eligibility used UTC or the session zone instead of New York';
    END IF;

    SELECT * INTO STRICT candidate
    FROM analytics.pilot_balance_sheet('0000049826', DATE '2026-06-30', 'as_reported', DATE '2026-08-06')
    WHERE metric = 'working_capital';
    IF candidate.status IS DISTINCT FROM 'mixed_filings' OR candidate.value IS NOT NULL THEN
        RAISE EXCEPTION 'Balance-sheet operands from different filings were combined';
    END IF;
END
$test$;

INSERT INTO core.reported_facts (
    accession, taxonomy, concept, unit, period_end, reporting_basis, scope_key,
    value, reported_decimals, source_fetch_id, source_locator
)
SELECT '0000049826-26-999999', 'filing-line', test_line.concept, 'USD', DATE '2026-06-30',
       'consolidated', 'as_reported', test_line.value, '-6', metadata_fetch_id, 'synthetic test only'
FROM core.filings
CROSS JOIN (VALUES ('current_assets', 6800000000), ('current_liabilities', 0),
                   ('cash_and_equivalents', 839000000)) AS test_line(concept, value)
WHERE accession = '0000049826-26-999999';

DO $test$
DECLARE candidate record;
BEGIN
    SELECT * INTO STRICT candidate
    FROM analytics.pilot_balance_sheet('0000049826', DATE '2026-06-30', 'as_reported', DATE '2026-08-06')
    WHERE metric = 'working_capital';
    IF candidate.status IS DISTINCT FROM 'conflicting_observations' OR candidate.value IS NOT NULL THEN
        RAISE EXCEPTION 'Conflicting values in the latest disclosure were not suppressed';
    END IF;

    SELECT * INTO STRICT candidate
    FROM analytics.pilot_balance_sheet('0000049826', DATE '2026-06-30', 'as_reported', DATE '2026-08-06')
    WHERE metric = 'cash_ratio';
    IF candidate.status IS DISTINCT FROM 'nonpositive_denominator' OR candidate.value IS NOT NULL THEN
        RAISE EXCEPTION 'A zero current-liability denominator returned a cash ratio';
    END IF;

    RAISE NOTICE 'Pilot analytics checks passed';
END
$test$;

ROLLBACK;
