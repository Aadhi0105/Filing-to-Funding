\set ON_ERROR_STOP on

DO $test$
DECLARE
    filing_count integer;
    fact_count integer;
BEGIN
    SELECT count(*) INTO filing_count
    FROM core.filings AS filing
    JOIN raw.source_fetches AS source ON source.fetch_id = filing.metadata_fetch_id
    WHERE source.source_kind = 'sec_submissions';

    SELECT count(*) INTO fact_count
    FROM core.reported_facts AS fact
    JOIN raw.source_fetches AS source ON source.fetch_id = fact.source_fetch_id
    WHERE source.source_kind = 'sec_company_facts'
      AND fact.taxonomy = 'us-gaap' AND fact.unit = 'USD'
      AND fact.reporting_basis = 'unclassified' AND fact.scope_key = 'companyfacts_unreviewed'
      AND fact.reported_decimals IS NULL
      AND fact.source_locator LIKE '/facts/us-gaap/%/units/USD/%';

    IF filing_count <> 79 OR fact_count <> 2273 THEN
        RAISE EXCEPTION 'Frozen SEC capture requires 79 accessions and 2,273 sourced observations';
    END IF;

    -- An amendment retains its own accession, acceptance, and fact lineage.
    IF NOT EXISTS (
        SELECT
        FROM core.filings AS original
        JOIN core.filings AS amendment USING (cik, report_period_id)
        JOIN core.reported_facts AS first_fact ON first_fact.accession = original.accession
        JOIN core.reported_facts AS revised_fact ON revised_fact.accession = amendment.accession
        WHERE original.accession = '0000049826-21-000059' AND original.form_type = '10-Q'
          AND amendment.accession = '0000049826-21-000064' AND amendment.form_type = '10-Q/A'
          AND original.filed_on = DATE '2021-08-05' AND amendment.filed_on = DATE '2021-08-06'
          AND original.accepted_at < amendment.accepted_at
          AND first_fact.concept = 'AssetsCurrent' AND revised_fact.concept = first_fact.concept
          AND first_fact.period_end = DATE '2021-06-30'
          AND revised_fact.period_end = first_fact.period_end
          AND revised_fact.value = first_fact.value
    ) THEN
        RAISE EXCEPTION 'The existing ITW filing or its certification amendment was lost';
    END IF;

    IF NOT EXISTS (
        SELECT
        FROM core.filings AS filing
        JOIN core.reporting_periods AS period ON period.period_id = filing.report_period_id
        WHERE filing.accession = '0001024478-26-000005' AND period.fiscal_year = 2026
          AND period.fiscal_quarter = 1 AND period.starts_on = DATE '2025-10-01'
          AND period.ends_on = DATE '2025-12-31'
    ) THEN
        RAISE EXCEPTION 'The Rockwell December quarter was assigned to the wrong fiscal year';
    END IF;

    IF NOT EXISTS (
        SELECT FROM core.filings
        WHERE accession = '0000049826-24-000038'
          AND accepted_at = TIMESTAMPTZ '2024-08-01 22:26:02+00'
          AND filed_on = DATE '2024-08-02'
          AND acceptance_timezone = 'UTC'
    ) THEN
        RAISE EXCEPTION 'The after-hours ITW filing date or acceptance instant was changed';
    END IF;

    IF NOT EXISTS (
        SELECT FROM core.reported_facts
        WHERE accession = '0000029905-25-000024'
          AND concept = 'NetCashProvidedByUsedInOperatingActivitiesContinuingOperations'
          AND period_start = DATE '2024-01-01' AND period_end = DATE '2024-06-30'
          AND value = 295637000
    ) THEN
        RAISE EXCEPTION 'Dover comparative was collapsed into a current or original period';
    END IF;

    RAISE NOTICE 'Historical SEC backfill checks passed';
END
$test$;
