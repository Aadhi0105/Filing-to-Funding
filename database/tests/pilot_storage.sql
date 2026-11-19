\set ON_ERROR_STOP on

BEGIN;

DO $test$
DECLARE
    early_period_id bigint;
    later_period_id bigint;
    annual_period_id bigint;
    original_fetch_id bigint;
    later_fetch_id bigint;
    treasury_fetch_id bigint;
    amount numeric;
    payload_hash text;
    matching_rows integer;
BEGIN
    -- Isolated test issuers. The comparative amounts are from the Dover Task 2 example.
    INSERT INTO core.issuers (cik, legal_name) VALUES
        ('9999999001', 'Pilot test issuer'),
        ('9999999002', 'September year-end test issuer');

    INSERT INTO core.reporting_periods (cik, fiscal_year, fiscal_quarter, starts_on, ends_on)
    VALUES ('9999999001', 2024, 2, '2024-04-01', '2024-06-30')
    RETURNING period_id INTO early_period_id;

    INSERT INTO core.reporting_periods (cik, fiscal_year, fiscal_quarter, starts_on, ends_on)
    VALUES ('9999999001', 2025, 2, '2025-04-01', '2025-06-30')
    RETURNING period_id INTO later_period_id;

    INSERT INTO core.reporting_periods (cik, fiscal_year, fiscal_quarter, starts_on, ends_on)
    VALUES ('9999999002', 2026, NULL, '2025-10-01', '2026-09-30')
    RETURNING period_id INTO annual_period_id;

    INSERT INTO core.reporting_periods (cik, fiscal_year, fiscal_quarter, starts_on, ends_on)
    VALUES ('9999999002', 2026, 4, '2026-07-01', '2026-09-30');

    BEGIN
        INSERT INTO core.reporting_periods (cik, fiscal_year, fiscal_quarter, starts_on, ends_on)
        VALUES ('9999999002', 2026, NULL, '2025-10-01', '2026-09-30');
        RAISE EXCEPTION 'Duplicate annual reporting period was accepted';
    EXCEPTION WHEN unique_violation THEN
        NULL;
    END;

    INSERT INTO raw.source_payloads (sha256, storage_key, byte_count) VALUES
        (repeat('a', 64), 'tests/original.html', 10),
        (repeat('b', 64), 'tests/comparative.html', 20),
        (repeat('c', 64), 'tests/treasury.xml', 30);

    INSERT INTO raw.source_fetches (source_kind, source_url, retrieved_at, payload_sha256)
    VALUES ('sec_filing', 'https://example.test/original', '2026-11-19 12:00+00', repeat('a', 64))
    RETURNING fetch_id INTO original_fetch_id;

    INSERT INTO raw.source_fetches (source_kind, source_url, retrieved_at, payload_sha256)
    VALUES ('sec_filing', 'https://example.test/comparative', '2026-11-19 12:05+00', repeat('b', 64))
    RETURNING fetch_id INTO later_fetch_id;

    INSERT INTO raw.source_fetches (source_kind, source_url, retrieved_at, payload_sha256)
    VALUES ('treasury_daily_par_yields', 'https://example.test/treasury', '2026-11-19 12:10+00', repeat('c', 64))
    RETURNING fetch_id INTO treasury_fetch_id;

    INSERT INTO core.filings (
        accession, cik, report_period_id, form_type, filed_on, accepted_at,
        acceptance_timezone, filing_url, metadata_fetch_id
    ) VALUES
        ('9999999001-24-000001', '9999999001', early_period_id, '10-Q',
         '2024-07-25', '2024-07-25 06:39:50-04', 'America/New_York',
         'https://www.sec.gov/Archives/edgar/data/9999999001/original.htm', original_fetch_id),
        ('9999999001-25-000002', '9999999001', later_period_id, '10-Q',
         '2025-07-24', '2025-07-24 06:45:44-04', 'America/New_York',
         'https://www.sec.gov/Archives/edgar/data/9999999001/comparative.htm', later_fetch_id),
        ('9999999002-26-000001', '9999999002', annual_period_id, '10-K',
         '2026-11-12', NULL, NULL,
         'https://www.sec.gov/Archives/edgar/data/9999999002/annual.htm', later_fetch_id);

    BEGIN
        INSERT INTO core.filings (
            accession, cik, report_period_id, form_type, filed_on, filing_url, metadata_fetch_id
        ) VALUES (
            '9999999001-26-000003', '9999999001', annual_period_id, '10-K', '2026-11-12',
            'https://www.sec.gov/Archives/edgar/data/9999999001/mismatched.htm', later_fetch_id
        );
        RAISE EXCEPTION 'Filing was linked to another issuer''s reporting period';
    EXCEPTION WHEN foreign_key_violation THEN
        NULL;
    END;

    INSERT INTO core.reported_facts (
        accession, taxonomy, concept, unit, period_start, period_end, reporting_basis,
        scope_key, value, reported_decimals, source_fetch_id, source_locator
    ) VALUES
        ('9999999001-24-000001', 'us-gaap', 'OperatingCashFlowExample', 'USD',
         '2024-01-01', '2024-06-30', 'consolidated', 'includes_disposed_business',
         370255000, '-3', original_fetch_id, 'original-cfo'),
        ('9999999001-25-000002', 'us-gaap', 'OperatingCashFlowExample', 'USD',
         '2024-01-01', '2024-06-30', 'continuing_operations', 'excludes_disposed_business',
         295637000, '-3', later_fetch_id, 'comparative-cfo'),
        ('9999999001-24-000001', 'us-gaap', 'AssetsCurrent', 'USD',
         NULL, '2024-06-30', 'consolidated', 'as_reported',
         3265969000, NULL, original_fetch_id, 'original-current-assets'),
        ('9999999001-24-000001', 'us-gaap', 'AssetsCurrent', 'USD',
         NULL, '2024-06-30', 'consolidated', 'as_reported',
         3265968000, NULL, original_fetch_id, 'conflicting-current-assets');

    -- An instant with unknown precision still has an identity. Both NULLs must compare equal.
    BEGIN
        INSERT INTO core.reported_facts (
            accession, taxonomy, concept, unit, period_end, reporting_basis,
            scope_key, value, source_fetch_id, source_locator
        ) VALUES (
            '9999999001-24-000001', 'us-gaap', 'AssetsCurrent', 'USD', '2024-06-30',
            'consolidated', 'as_reported', 3265969000, original_fetch_id, 'repeated-source'
        );
        RAISE EXCEPTION 'Exact duplicate instant fact was accepted';
    EXCEPTION WHEN unique_violation THEN
        NULL;
    END;

    SELECT count(*) INTO matching_rows
    FROM core.reported_facts
    WHERE accession = '9999999001-24-000001' AND concept = 'AssetsCurrent';
    IF matching_rows <> 2 THEN
        RAISE EXCEPTION 'Conflicting same-context values must remain available for inspection';
    END IF;

    -- Recording these disclosures in 2026 must not change their SEC filing availability.
    SELECT obs.value, evidence.payload_sha256 INTO STRICT amount, payload_hash
    FROM core.reported_facts AS obs
    JOIN core.filings AS filing USING (accession)
    JOIN raw.source_fetches AS evidence ON evidence.fetch_id = obs.source_fetch_id
    WHERE filing.cik = '9999999001'
      AND obs.concept = 'OperatingCashFlowExample'
      AND filing.filed_on <= DATE '2024-10-24'
      AND filing.accepted_at < (TIMESTAMP '2024-10-25 00:00:00' AT TIME ZONE 'America/New_York');
    IF amount <> 370255000 OR payload_hash <> repeat('a', 64) THEN
        RAISE EXCEPTION 'Original value or source was lost';
    END IF;

    SELECT obs.value INTO STRICT amount
    FROM core.reported_facts AS obs
    JOIN core.filings AS filing USING (accession)
    WHERE filing.cik = '9999999001'
      AND obs.period_start = DATE '2024-01-01'
      AND obs.period_end = DATE '2024-06-30'
      AND obs.reporting_basis = 'continuing_operations'
      AND filing.filed_on <= DATE '2025-07-24'
      AND filing.accepted_at < (TIMESTAMP '2025-07-25 00:00:00' AT TIME ZONE 'America/New_York');
    IF amount <> 295637000 THEN
        RAISE EXCEPTION 'Later comparative value or its period was lost';
    END IF;

    INSERT INTO core.treasury_yield_observations (
        observation_date, maturity_months, yield_percent, source_fetch_id
    ) VALUES ('2026-11-18', 60, 4.125, treasury_fetch_id);

    SELECT yield_percent INTO STRICT amount
    FROM core.treasury_yield_observations
    WHERE source_fetch_id = treasury_fetch_id AND source_published_at IS NULL;
    IF amount <> 4.125 THEN
        RAISE EXCEPTION 'Treasury observation was rounded or given an invented publication time';
    END IF;

    RAISE NOTICE 'Pilot storage checks passed';
END
$test$;

ROLLBACK;
