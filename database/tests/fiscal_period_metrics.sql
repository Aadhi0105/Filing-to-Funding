\set ON_ERROR_STOP on

BEGIN;
SET LOCAL TIME ZONE 'Asia/Kolkata';

DO $test$
BEGIN
    IF NOT EXISTS (
        SELECT FROM analytics.historical_annual_cash_flow(
            '0001024478', 2026, 'consolidated', 'rok_sensia_transition_year', DATE '2026-11-12'
        )
        WHERE (period_start, period_end, period_days, calendar_type)
              = (DATE '2025-10-01', DATE '2026-09-30', 365, 'calendar_year')
          AND (operating_cash_flow, cash_capex, free_cash_flow) = (1958000000, 257000000, 1701000000)
          AND status = 'available' AND source_accessions = ARRAY['0001024478-26-000048']
    ) OR EXISTS (
        SELECT FROM analytics.historical_annual_cash_flow(
            '0001024478', 2026, 'consolidated', 'rok_sensia_transition_year', DATE '2026-11-11'
        ) WHERE free_cash_flow IS NOT NULL OR status <> 'missing_compatible_operands'
    ) THEN
        RAISE EXCEPTION 'Rockwell annual cash flow lost its fiscal dates, filing lineage, or cutoff';
    END IF;

    IF (
        SELECT count(*) FROM analytics.historical_cash_flow_ratios(
            '0001024478', 2026, NULL, 'consolidated', 'rok_sensia_transition_year', 'annual', DATE '2026-11-12'
        )
        WHERE status = 'available' AND source_accessions = ARRAY['0001024478-26-000048']
          AND ((metric = 'fcf_margin' AND numerator = 1701000000 AND round(value, 4) = 0.1892)
               OR (metric = 'cash_conversion' AND numerator = 1958000000 AND round(value, 3) = 1.392))
    ) <> 2 THEN
        RAISE EXCEPTION 'Rockwell annual ratios lost their direct annual operands or provenance';
    END IF;

    IF EXISTS (
        SELECT FROM analytics.historical_cash_flow_changes(
            '0000049826', 2024, NULL, 'consolidated', 'itw_from_fifo_change', 'annual', DATE '2026-11-19',
            'consolidated', 'itw_before_fifo_change'
        ) WHERE status <> 'incompatible_reporting_scope' OR absolute_change IS NOT NULL OR percentage_growth IS NOT NULL
    ) THEN
        RAISE EXCEPTION 'The ITW FIFO accounting break created a year-over-year change';
    END IF;
END
$test$;

INSERT INTO core.issuers (cik, legal_name) VALUES
    ('0000999001', 'Synthetic Leap Calendar'), ('0000999002', 'Synthetic Weekly Calendar');

INSERT INTO core.reporting_periods (cik, fiscal_year, fiscal_quarter, starts_on, ends_on) VALUES
    ('0000999001', 2023, NULL, '2022-03-01', '2023-02-28'),
    ('0000999001', 2024, NULL, '2023-03-01', '2024-02-29'),
    ('0000999001', 2025, NULL, '2024-03-01', '2025-02-28'),
    ('0000999002', 2023, NULL, '2023-01-01', '2023-12-30'),
    ('0000999002', 2024, NULL, '2023-12-31', '2025-01-04'),
    ('0000999002', 2024, 1, '2023-12-31', '2024-03-30'),
    ('0000999002', 2024, 2, '2024-03-31', '2024-06-29'),
    ('0000999002', 2024, 3, '2024-06-30', '2024-09-28'),
    ('0000999002', 2025, NULL, '2025-01-05', '2025-06-30'),
    ('0000999002', 2025, 1, '2025-01-05', '2025-04-05');

INSERT INTO core.filings (
    accession, cik, report_period_id, form_type, filed_on, accepted_at, acceptance_timezone, filing_url, metadata_fetch_id
)
SELECT period.cik || '-26-' || lpad(row_number() OVER (ORDER BY period.period_id)::text, 6, '0'),
       period.cik, period.period_id, CASE WHEN period.fiscal_quarter IS NULL THEN '10-K' ELSE '10-Q' END,
       period.ends_on + 28, (period.ends_on + 28 + TIME '15:00') AT TIME ZONE 'UTC', 'UTC',
       'https://www.sec.gov/Archives/edgar/data/' || period.cik || '/synthetic.htm', sample.metadata_fetch_id
FROM core.reporting_periods AS period
CROSS JOIN core.filings AS sample
WHERE period.cik IN ('0000999001', '0000999002') AND sample.accession = '0001024478-26-000048';

INSERT INTO core.reported_facts (
    accession, taxonomy, concept, unit, period_start, period_end, reporting_basis, scope_key,
    value, reported_decimals, source_fetch_id, source_locator
)
SELECT filing.accession, 'filing-statement-v1', amount.concept, 'USD',
       annual.starts_on, period.ends_on, 'consolidated', 'test_scope', amount.value, '0',
       filing.metadata_fetch_id, 'synthetic.htm#' || amount.concept
FROM (VALUES
    ('0000999001', 2023, 0, 0, -10, 100, 0),
    ('0000999001', 2024, 0, 20, 0, 100, 4),
    ('0000999001', 2025, 0, 40, -20, 100, 8),
    ('0000999002', 2023, 0, 100, -20, 700, 50),
    ('0000999002', 2024, 0, 120, -30, 800, 60),
    ('0000999002', 2024, 1, 20, -5, 150, 10),
    ('0000999002', 2024, 2, 55, -15, 350, 25),
    ('0000999002', 2024, 3, 80, -20, 550, 40),
    ('0000999002', 2025, 0, 55, -15, 350, 25),
    ('0000999002', 2025, 1, 30, -5, 170, 12)
) AS input(cik, year, quarter, cfo, capex, revenue, income)
JOIN core.reporting_periods AS period
  ON (period.cik, period.fiscal_year, coalesce(period.fiscal_quarter, 0)) = (input.cik, input.year, input.quarter)
JOIN core.reporting_periods AS annual
  ON annual.cik = period.cik AND annual.fiscal_year = period.fiscal_year AND annual.fiscal_quarter IS NULL
JOIN core.filings AS filing ON filing.report_period_id = period.period_id
CROSS JOIN LATERAL (VALUES
    ('operating_cash_flow', input.cfo), ('cash_capex_outflow', input.capex),
    ('revenue', input.revenue), ('net_income', input.income)
) AS amount(concept, value);

DO $test$
BEGIN
    IF NOT EXISTS (
        SELECT FROM analytics.historical_annual_cash_flow('0000999001', 2024, 'consolidated', 'test_scope', DATE '2024-03-28')
        WHERE period_end = DATE '2024-02-29' AND period_days = 366 AND calendar_type = 'calendar_year'
          AND free_cash_flow = 20 AND status = 'available'
    ) OR EXISTS (
        SELECT FROM analytics.historical_annual_cash_flow('0000999001', 2024, 'consolidated', 'test_scope', DATE '2024-03-27')
        WHERE free_cash_flow IS NOT NULL
    ) THEN
        RAISE EXCEPTION 'The leap-day fiscal year was truncated or used before its filing';
    END IF;

    IF (
        SELECT count(*) FROM analytics.historical_cash_flow_changes(
            '0000999001', 2024, NULL, 'consolidated', 'test_scope', 'annual', DATE '2024-03-28'
        )
        WHERE status = 'available' AND growth_status = 'nonpositive_prior_value' AND percentage_growth IS NULL
          AND (metric, prior_value, current_value, absolute_change) IN (
              ('operating_cash_flow', 0, 20, 20), ('free_cash_flow', -10, 20, 30)
          )
    ) <> 2 OR NOT EXISTS (
        SELECT FROM analytics.historical_cash_flow_changes('0000999001', 2025, NULL, 'consolidated', 'test_scope', 'year')
        WHERE metric = 'operating_cash_flow' AND absolute_change = 20 AND percentage_growth = 100
          AND status = 'available' AND growth_status = 'available'
          AND cardinality(prior_accessions) = 1 AND cardinality(current_accessions) = 1
    ) OR NOT EXISTS (
        SELECT FROM analytics.historical_cash_flow_ratios('0000999001', 2023, NULL, 'consolidated', 'test_scope', 'annual')
        WHERE metric = 'cash_conversion' AND denominator = 0 AND value IS NULL AND status = 'nonpositive_denominator'
    ) THEN
        RAISE EXCEPTION 'Comparable changes, percentage growth, or ratio denominator rules failed';
    END IF;

    IF NOT EXISTS (
        SELECT FROM analytics.historical_annual_cash_flow('0000999002', 2023, 'consolidated', 'test_scope')
        WHERE (calendar_type, period_days, free_cash_flow) = ('52_week_year', 364, 80)
    ) OR NOT EXISTS (
        SELECT FROM analytics.historical_annual_cash_flow('0000999002', 2024, 'consolidated', 'test_scope')
        WHERE (calendar_type, period_days, free_cash_flow) = ('53_week_year', 371, 90)
    ) OR NOT EXISTS (
        SELECT FROM analytics.historical_quarter_cash_flow('0000999002', 2024, 4, 'consolidated', 'test_scope')
        WHERE quarter_start = DATE '2024-09-29' AND quarter_end = DATE '2025-01-04' AND free_cash_flow = 30
    ) OR NOT EXISTS (
        SELECT FROM analytics.historical_ttm_cash_flow('0000999002', 2024, 4, 'consolidated', 'test_scope')
        WHERE period_start = DATE '2023-12-31' AND period_end = DATE '2025-01-04' AND free_cash_flow = 90
    ) OR NOT EXISTS (
        SELECT FROM analytics.historical_cash_flow_changes('0000999002', 2024, NULL, 'consolidated', 'test_scope', 'annual')
        WHERE metric = 'free_cash_flow' AND prior_value = 80 AND current_value = 90
          AND status = 'incompatible_fiscal_periods' AND absolute_change IS NULL AND percentage_growth IS NULL
    ) THEN
        RAISE EXCEPTION 'The 53rd week was lost or was compared as if the prior period were the same length';
    END IF;

    IF NOT EXISTS (
        SELECT FROM analytics.historical_annual_cash_flow('0000999002', 2025, 'consolidated', 'test_scope')
        WHERE calendar_type = 'short_fiscal_year' AND period_start = DATE '2025-01-05' AND period_end = DATE '2025-06-30'
          AND status = 'unsupported_fiscal_period' AND free_cash_flow IS NULL
    ) OR NOT EXISTS (
        SELECT FROM analytics.historical_ttm_cash_flow('0000999002', 2025, 1, 'consolidated', 'test_scope')
        WHERE status = 'missing_compatible_quarters' AND free_cash_flow IS NULL
    ) THEN
        RAISE EXCEPTION 'The short transition period was accepted as a full year or complete trailing window';
    END IF;
END
$test$;

DELETE FROM core.reported_facts AS fact
USING core.filings AS filing, core.reporting_periods AS period
WHERE fact.accession = filing.accession AND filing.report_period_id = period.period_id
  AND period.cik = '0000999001' AND period.fiscal_year = 2025 AND fact.concept = 'cash_capex_outflow';

DO $test$
BEGIN
    IF (
        SELECT count(*) FROM analytics.historical_cash_flow_ratios('0000999001', 2025, NULL, 'consolidated', 'test_scope', 'annual')
        WHERE (metric, status) IN (('cash_conversion', 'available'), ('fcf_margin', 'missing_compatible_operands'))
    ) <> 2 THEN
        RAISE EXCEPTION 'Missing capex improperly changed annual cash conversion';
    END IF;
    RAISE NOTICE 'Fiscal-calendar, annual metrics and year-over-year change checks passed';
END
$test$;

ROLLBACK;
