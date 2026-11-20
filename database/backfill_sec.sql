SELECT pg_catalog.pg_advisory_xact_lock(2004228903);

CREATE TEMP TABLE edgar_sources ON COMMIT DROP AS
SELECT source.*
FROM edgar_input
CROSS JOIN LATERAL jsonb_to_recordset(document->'sources') AS source(
    cik text, source_kind text, source_url text, retrieved_at timestamptz,
    sha256 text, storage_key text, byte_count bigint
);

CREATE TEMP TABLE edgar_filings ON COMMIT DROP AS
SELECT document->>'cik' AS cik, filing.*
FROM edgar_input
CROSS JOIN LATERAL jsonb_to_recordset(document->'filings') AS filing(
    accession text, form_type text, filed_on date, accepted_at timestamptz, filing_url text,
    fiscal_year smallint, fiscal_quarter smallint, starts_on date, ends_on date
);

INSERT INTO raw.source_payloads (sha256, storage_key, byte_count)
SELECT DISTINCT sha256, storage_key, byte_count FROM edgar_sources
ON CONFLICT (sha256) DO NOTHING;

DO $validate$
BEGIN
    IF EXISTS (
        SELECT FROM edgar_sources AS expected JOIN raw.source_payloads AS saved USING (sha256)
        WHERE (expected.storage_key, expected.byte_count) <> (saved.storage_key, saved.byte_count)
    ) THEN
        RAISE EXCEPTION 'Stored archive metadata conflicts with this EDGAR capture';
    END IF;
END
$validate$;

INSERT INTO raw.source_fetches (source_kind, source_url, retrieved_at, payload_sha256)
SELECT source_kind, source_url, retrieved_at, sha256 FROM edgar_sources
ON CONFLICT (source_kind, source_url, retrieved_at, payload_sha256) DO NOTHING;

CREATE TEMP VIEW edgar_fetches AS
SELECT source.cik, source.source_kind, saved.fetch_id
FROM edgar_sources AS source
JOIN raw.source_fetches AS saved
  ON (source.source_kind, source.source_url, source.retrieved_at, source.sha256)
   = (saved.source_kind, saved.source_url, saved.retrieved_at, saved.payload_sha256);

INSERT INTO core.issuers (cik, legal_name)
SELECT document->>'cik', document->>'legal_name' FROM edgar_input
ON CONFLICT (cik) DO NOTHING;

INSERT INTO core.issuer_aliases (cik, alias_kind, alias, valid_from)
SELECT input.document->>'cik', 'ticker', input.document->>'ticker', min(filing.filed_on)
FROM edgar_input AS input
JOIN edgar_filings AS filing ON filing.cik = input.document->>'cik'
WHERE NOT EXISTS (
    SELECT FROM core.issuer_aliases AS alias
    WHERE alias.cik = filing.cik AND alias.alias_kind = 'ticker' AND alias.alias = input.document->>'ticker'
)
GROUP BY input.document->>'cik', input.document->>'ticker'
ON CONFLICT DO NOTHING;

INSERT INTO core.reporting_periods (cik, fiscal_year, fiscal_quarter, starts_on, ends_on)
SELECT DISTINCT cik, fiscal_year, fiscal_quarter, starts_on, ends_on FROM edgar_filings
ON CONFLICT (cik, fiscal_year, fiscal_quarter) DO NOTHING;

CREATE TEMP VIEW edgar_matches AS
SELECT filing.*, period.period_id, period.starts_on AS stored_start, period.ends_on AS stored_end,
       source.fetch_id
FROM edgar_filings AS filing
JOIN core.reporting_periods AS period
  ON period.cik = filing.cik AND period.fiscal_year = filing.fiscal_year
 AND period.fiscal_quarter IS NOT DISTINCT FROM filing.fiscal_quarter
JOIN edgar_fetches AS source ON source.cik = filing.cik AND source.source_kind = 'sec_submissions';

DO $validate$
BEGIN
    IF EXISTS (SELECT FROM edgar_matches WHERE (starts_on, ends_on) <> (stored_start, stored_end)) THEN
        RAISE EXCEPTION 'EDGAR reporting dates conflict with a stored period';
    END IF;
    IF EXISTS (
        SELECT FROM edgar_matches AS expected JOIN core.filings AS saved USING (accession)
        WHERE (saved.cik, saved.report_period_id, saved.form_type, saved.filed_on, saved.filing_url)
           <> (expected.cik, expected.period_id, expected.form_type, expected.filed_on, expected.filing_url)
           OR (saved.accepted_at IS NOT NULL AND expected.accepted_at IS NOT NULL
               AND saved.accepted_at <> expected.accepted_at)
    ) THEN
        RAISE EXCEPTION 'EDGAR metadata conflicts with a stored filing';
    END IF;
END
$validate$;

-- A reviewed timestamp can be upgraded to SEC Submissions evidence for the same accession.
UPDATE core.filings AS saved
SET accepted_at = expected.accepted_at,
    acceptance_timezone = CASE WHEN expected.accepted_at IS NOT NULL THEN 'UTC' END,
    metadata_fetch_id = expected.fetch_id
FROM edgar_matches AS expected, raw.source_fetches AS previous
WHERE saved.accession = expected.accession AND previous.fetch_id = saved.metadata_fetch_id
  AND (expected.accepted_at IS NOT NULL OR saved.accepted_at IS NULL)
  AND (previous.source_kind = 'sec_filing_review'
       OR (saved.accepted_at IS NULL AND expected.accepted_at IS NOT NULL));

INSERT INTO core.filings (
    accession, cik, report_period_id, form_type, filed_on, accepted_at, acceptance_timezone,
    filing_url, metadata_fetch_id
)
SELECT accession, cik, period_id, form_type, filed_on, accepted_at,
       CASE WHEN accepted_at IS NOT NULL THEN 'UTC' END, filing_url, fetch_id
FROM edgar_matches
ON CONFLICT (accession) DO NOTHING;

INSERT INTO core.reported_facts (
    accession, taxonomy, concept, unit, period_start, period_end, reporting_basis,
    scope_key, value, reported_decimals, source_fetch_id, source_locator
)
SELECT fact.accession, 'us-gaap', fact.concept, 'USD', fact.period_start, fact.period_end,
       'unclassified', 'companyfacts_unreviewed', fact.value, NULL, source.fetch_id, fact.source_locator
FROM edgar_input AS input
JOIN edgar_fetches AS source
  ON source.cik = input.document->>'cik' AND source.source_kind = 'sec_company_facts'
CROSS JOIN LATERAL jsonb_to_recordset(input.document->'facts') AS fact(
    accession text, concept text, period_start date, period_end date, value numeric, source_locator text
)
ORDER BY fact.accession, fact.concept, fact.source_locator COLLATE "C"
ON CONFLICT ON CONSTRAINT reported_facts_exact_observation DO NOTHING;

SELECT cik, count(*) FILTER (WHERE form_type NOT LIKE '%/A') AS base_filings,
       count(*) FILTER (WHERE form_type LIKE '%/A') AS amendments,
       count(*) FILTER (WHERE accepted_at IS NULL) AS unknown_acceptance
FROM edgar_filings
GROUP BY cik ORDER BY cik;

COMMIT;
