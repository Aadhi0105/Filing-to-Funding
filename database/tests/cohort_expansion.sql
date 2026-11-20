DO $check$
DECLARE
    expected record;
    actual numeric;
BEGIN
    FOR expected IN SELECT * FROM (VALUES
        ('0000091142', 'aos_reviewed', 546000000, 162900000, 549000000, DATE '2026-10-29'),
        ('0000832101', 'iex_reviewed', 616800000, 214300000, 1130600000, DATE '2026-10-28'),
        ('0000059527', 'leco_reviewed', 534199000, 174538000, 870474000, DATE '2026-10-27')
    ) AS checks(cik, scope, annual_fcf, quarter_fcf, working_capital, filed_on)
    LOOP
        IF (SELECT count(*) FROM core.filings WHERE cik = expected.cik AND accepted_at IS NOT NULL) <> 27 THEN
            RAISE EXCEPTION 'Expanded filing inventory mismatch for %', expected.cik;
        END IF;
        SELECT free_cash_flow INTO actual FROM analytics.historical_annual_cash_flow(
            expected.cik, 2025, 'consolidated', expected.scope, NULL
        );
        IF actual IS DISTINCT FROM expected.annual_fcf THEN
            RAISE EXCEPTION 'Annual FCF mismatch for %', expected.cik;
        END IF;
        SELECT free_cash_flow INTO actual FROM analytics.historical_quarter_cash_flow(
            expected.cik, 2026, 3, 'consolidated', expected.scope, expected.filed_on - 1
        );
        IF actual IS NOT NULL THEN
            RAISE EXCEPTION 'Pre-filing FCF leaked for %', expected.cik;
        END IF;
        SELECT free_cash_flow INTO actual FROM analytics.historical_quarter_cash_flow(
            expected.cik, 2026, 3, 'consolidated', expected.scope, expected.filed_on
        );
        IF actual IS DISTINCT FROM expected.quarter_fcf THEN
            RAISE EXCEPTION 'Quarterly FCF mismatch for %', expected.cik;
        END IF;
        SELECT value INTO actual FROM analytics.pilot_balance_sheet(
            expected.cik, DATE '2026-09-30', 'historical_balance_sheet', expected.filed_on
        ) WHERE metric = 'working_capital';
        IF actual IS DISTINCT FROM expected.working_capital THEN
            RAISE EXCEPTION 'Working capital mismatch for %', expected.cik;
        END IF;
    END LOOP;
END;
$check$;
