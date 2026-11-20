\set ON_ERROR_STOP on

BEGIN;
SET LOCAL TIME ZONE 'Asia/Kolkata';

DO $test$
DECLARE
    failures text;
    sample record;
BEGIN
    IF (
        SELECT count(DISTINCT fact.accession)
        FROM core.reported_facts AS fact
        JOIN raw.source_fetches AS source ON source.fetch_id = fact.source_fetch_id
        WHERE fact.taxonomy = 'filing-statement-v1' AND source.source_kind = 'sec_filing'
          AND source.retrieved_at IS NOT NULL AND fact.reported_decimals IS NOT NULL
    ) <> 79 OR (SELECT count(*) FROM core.reported_facts WHERE taxonomy = 'filing-statement-v1') <> 689 THEN
        RAISE EXCEPTION 'The frozen statement capture or source lineage is incomplete';
    END IF;

    WITH cases(label, cik, year, quarter, basis, scope, cutoff, q_status, q_fcf, ttm_status, ttm_fcf) AS (
        VALUES
            ('ITW opening TTM', '0000049826', 2021, 1, 'consolidated', 'itw_before_fifo_change',
                DATE '2021-05-06', 'available', 541000000, 'available', 2558000000),
            ('ITW FIFO transition', '0000049826', 2024, 1, 'consolidated', 'itw_from_fifo_change',
                NULL, 'available', 494000000, 'missing_compatible_quarters', NULL),
            ('ITW four quarters on FIFO basis', '0000049826', 2024, 4, 'consolidated', 'itw_from_fifo_change',
                NULL, 'available', 996000000, 'available', 2844000000),
            ('ITW acceptance before SEC filing date', '0000049826', 2024, 2, 'consolidated', 'itw_from_fifo_change',
                DATE '2024-08-01', 'missing_compatible_operands', NULL, 'missing_compatible_quarters', NULL),
            ('ITW official filing date', '0000049826', 2024, 2, 'consolidated', 'itw_from_fifo_change',
                DATE '2024-08-02', 'available', 571000000, 'missing_compatible_quarters', NULL),
            ('Dover before matching H1 comparative', '0000029905', 2024, 3, 'continuing_operations', 'dov_excluding_esg',
                DATE '2024-10-24', 'missing_compatible_operands', NULL, 'missing_compatible_quarters', NULL),
            ('Dover after matching H1 comparative', '0000029905', 2024, 3, 'continuing_operations', 'dov_excluding_esg',
                DATE '2025-07-24', 'available', 315490000, 'missing_compatible_quarters', NULL),
            ('Rockwell productive-assets capex', '0001024478', 2025, 4, 'consolidated', 'rok_before_sensia_transition',
                DATE '2025-11-12', 'available', 405000000, 'available', 1358000000),
            ('Rockwell only three transition-year quarters', '0001024478', 2026, 3, 'consolidated', 'rok_sensia_transition_year',
                DATE '2026-08-04', 'available', 654000000, 'missing_compatible_quarters', NULL),
            ('Rockwell full transition year as reported', '0001024478', 2026, 4, 'consolidated', 'rok_sensia_transition_year',
                DATE '2026-11-12', 'available', 602000000, 'available', 1701000000)
    )
    SELECT string_agg(label, ', ') INTO failures
    FROM cases
    CROSS JOIN LATERAL analytics.historical_quarter_cash_flow(cik, year, quarter, basis, scope, cutoff) AS q
    CROSS JOIN LATERAL analytics.historical_ttm_cash_flow(cik, year, quarter, basis, scope, cutoff) AS t
    WHERE (q.status, q.free_cash_flow, t.status, t.free_cash_flow)
       IS DISTINCT FROM (q_status, q_fcf, ttm_status, ttm_fcf);
    IF failures IS NOT NULL THEN
        RAISE EXCEPTION 'Historical cash flow failed for %', failures;
    END IF;

    SELECT * INTO STRICT sample
    FROM analytics.historical_ttm_cash_flow(
        '0000049826', 2021, 1, 'consolidated', 'itw_before_fifo_change', DATE '2021-05-06'
    );
    IF (sample.period_start, sample.period_end) IS DISTINCT FROM (DATE '2020-04-01', DATE '2021-03-31')
       OR sample.source_accessions IS DISTINCT FROM ARRAY[
           '0000049826-20-000099', '0000049826-20-000106', '0000049826-21-000007', '0000049826-21-000020'
       ] THEN
        RAISE EXCEPTION 'Opening TTM lost a fiscal interval or its filing evidence';
    END IF;

    SELECT * INTO STRICT sample
    FROM analytics.historical_quarter_cash_flow(
        '0000029905', 2024, 3, 'continuing_operations', 'dov_excluding_esg', DATE '2025-07-24'
    );
    IF sample.source_accessions IS DISTINCT FROM ARRAY['0000029905-24-000045','0000029905-25-000024'] THEN
        RAISE EXCEPTION 'Dover quarterly comparative lost its original filing lineage';
    END IF;

    IF NOT EXISTS (
        SELECT FROM core.reported_facts
        WHERE accession = '0000029905-24-000045' AND taxonomy = 'filing-statement-v1'
          AND concept = 'cash_and_equivalents' AND value = 386766000 AND reported_decimals = '-3'
    ) THEN
        RAISE EXCEPTION 'Dover balance-sheet cash was replaced with cash including held-for-sale amounts';
    END IF;

    SELECT * INTO STRICT sample
    FROM analytics.pilot_balance_sheet('0001024478', DATE '2026-09-30', 'historical_balance_sheet', DATE '2026-11-12')
    WHERE metric = 'borrowing_debt_excluding_finance_leases';
    IF (sample.value, sample.status) IS DISTINCT FROM (3276000000::numeric, 'available') THEN
        RAISE EXCEPTION 'Rockwell annual borrowing debt failed to deduct the disclosed lease amount';
    END IF;

    SELECT * INTO STRICT sample
    FROM analytics.pilot_balance_sheet('0001024478', DATE '2022-09-30', 'historical_balance_sheet', DATE '2022-11-08')
    WHERE metric = 'borrowing_debt_excluding_finance_leases';
    IF sample.value IS NOT NULL OR sample.status <> 'missing_compatible_operands' THEN
        RAISE EXCEPTION 'Rockwell deducted the total lease amount under the older liability presentation';
    END IF;
END
$test$;

-- Another amount reported for the same accession and context must invalidate a calculation.
INSERT INTO core.reported_facts (
    accession, taxonomy, concept, unit, period_start, period_end, reporting_basis, scope_key,
    value, reported_decimals, source_fetch_id, source_locator
)
SELECT accession, taxonomy, concept, unit, period_start, period_end, reporting_basis, scope_key,
       value + 1000000, reported_decimals, source_fetch_id, 'synthetic conflict for historical checks'
FROM core.reported_facts
WHERE accession = '0000049826-26-000049' AND taxonomy = 'filing-statement-v1'
  AND concept = 'operating_cash_flow' AND period_end = DATE '2026-06-30';

DO $test$
BEGIN
    IF NOT EXISTS (
        SELECT FROM analytics.historical_ttm_cash_flow(
            '0000049826', 2026, 2, 'consolidated', 'itw_from_fifo_change', DATE '2026-08-06'
        )
        WHERE status = 'conflicting_observations' AND free_cash_flow IS NULL
    ) THEN
        RAISE EXCEPTION 'TTM published a partial total despite a conflicting quarter';
    END IF;
    RAISE NOTICE 'Historical statement qualification and calculations passed';
END
$test$;

ROLLBACK;
