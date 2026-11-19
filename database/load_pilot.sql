-- The loader starts the transaction and COPYs reviewed records into pilot_input.
SELECT pg_catalog.pg_advisory_xact_lock(2004228903);

CREATE TEMP VIEW pilot_sources AS
SELECT src.*
FROM pilot_input AS input
CROSS JOIN LATERAL jsonb_to_record(input.document) AS src(
    source_kind text, source_url text, sha256 text, storage_key text, byte_count bigint,
    issuer jsonb, period jsonb, filing jsonb, facts jsonb, rates jsonb
);

INSERT INTO raw.source_payloads (sha256, storage_key, byte_count)
SELECT DISTINCT sha256, storage_key, byte_count FROM pilot_sources
ON CONFLICT (sha256) DO NOTHING;

INSERT INTO raw.source_fetches (source_kind, source_url, payload_sha256)
SELECT DISTINCT source_kind, source_url, sha256 FROM pilot_sources
ON CONFLICT (source_kind, source_url, payload_sha256)
    WHERE source_kind IN ('sec_filing_review', 'treasury_yield_review')
    DO NOTHING;

CREATE TEMP VIEW pilot_evidence AS
SELECT src.*, source_record.fetch_id
FROM pilot_sources AS src
JOIN raw.source_fetches AS source_record
  ON (source_record.source_kind, source_record.source_url, source_record.payload_sha256)
   = (src.source_kind, src.source_url, src.sha256);

CREATE TEMP VIEW pilot_filings AS
SELECT issuer.*, period.*, filing.*, evidence.source_url, evidence.fetch_id, evidence.facts
FROM pilot_evidence AS evidence
CROSS JOIN LATERAL jsonb_to_record(evidence.issuer) AS issuer(cik text, legal_name text, ticker text)
CROSS JOIN LATERAL jsonb_to_record(evidence.period) AS period(
    fiscal_year smallint, fiscal_quarter smallint, starts_on date, ends_on date
)
CROSS JOIN LATERAL jsonb_to_record(evidence.filing) AS filing(
    accession text, form_type text, filed_on date, accepted_at timestamptz, acceptance_timezone text
)
WHERE evidence.source_kind = 'sec_filing_review';

INSERT INTO core.issuers (cik, legal_name)
SELECT DISTINCT cik, legal_name FROM pilot_filings
ON CONFLICT (cik) DO NOTHING;

-- Alias coverage begins at the first filing in this pilot, not the actual listing date.
INSERT INTO core.issuer_aliases (cik, alias_kind, alias, valid_from)
SELECT cik, 'ticker', ticker, min(filed_on)
FROM pilot_filings
GROUP BY cik, ticker
ON CONFLICT (cik, alias_kind, alias, valid_from) DO NOTHING;

INSERT INTO core.reporting_periods (cik, fiscal_year, fiscal_quarter, starts_on, ends_on)
SELECT DISTINCT cik, fiscal_year, fiscal_quarter, starts_on, ends_on FROM pilot_filings
ON CONFLICT (cik, fiscal_year, fiscal_quarter) DO NOTHING;

CREATE TEMP VIEW pilot_period_matches AS
SELECT filing.*, period.period_id, period.starts_on AS stored_start, period.ends_on AS stored_end
FROM pilot_filings AS filing
JOIN core.reporting_periods AS period
  ON period.cik = filing.cik
 AND period.fiscal_year = filing.fiscal_year
 AND period.fiscal_quarter IS NOT DISTINCT FROM filing.fiscal_quarter;

DO $check$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pilot_period_matches
        WHERE (starts_on, ends_on) IS DISTINCT FROM (stored_start, stored_end)
    ) THEN
        RAISE EXCEPTION 'Pilot reporting dates conflict with a stored fiscal period';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM pilot_period_matches AS expected
        JOIN core.filings AS actual USING (accession)
        WHERE (actual.cik, actual.report_period_id, actual.form_type, actual.filed_on,
               actual.accepted_at, actual.acceptance_timezone, actual.filing_url)
           IS DISTINCT FROM
              (expected.cik, expected.period_id, expected.form_type, expected.filed_on,
               expected.accepted_at, expected.acceptance_timezone, expected.source_url)
    ) THEN
        RAISE EXCEPTION 'Pilot filing metadata conflicts with an existing accession';
    END IF;
END
$check$;

INSERT INTO core.filings (
    accession, cik, report_period_id, form_type, filed_on, accepted_at,
    acceptance_timezone, filing_url, metadata_fetch_id
)
SELECT accession, cik, period_id, form_type, filed_on, accepted_at,
       acceptance_timezone, source_url, fetch_id
FROM pilot_period_matches
ON CONFLICT (accession) DO NOTHING;

INSERT INTO core.reported_facts (
    accession, taxonomy, concept, unit, period_start, period_end, reporting_basis,
    scope_key, value, reported_decimals, source_fetch_id, source_locator
)
SELECT filing.accession, 'filing-line', fact.concept, 'USD', fact.period_start, fact.period_end,
       fact.reporting_basis, fact.scope_key, fact.value, fact.reported_decimals,
       filing.fetch_id, fact.source_locator
FROM pilot_filings AS filing
CROSS JOIN LATERAL jsonb_to_recordset(filing.facts) AS fact(
    concept text, period_start date, period_end date, reporting_basis text, scope_key text,
    value numeric, reported_decimals text, source_locator text
)
ON CONFLICT ON CONSTRAINT reported_facts_exact_observation DO NOTHING;

INSERT INTO core.treasury_yield_observations (
    observation_date, maturity_months, yield_percent, source_fetch_id
)
SELECT rate.observation_date, rate.maturity_months, rate.yield_percent, evidence.fetch_id
FROM pilot_evidence AS evidence
CROSS JOIN LATERAL jsonb_to_recordset(evidence.rates) AS rate(
    observation_date date, maturity_months smallint, yield_percent numeric
)
WHERE evidence.source_kind = 'treasury_yield_review'
ON CONFLICT (observation_date, maturity_months, source_fetch_id) DO NOTHING;

COMMIT;
