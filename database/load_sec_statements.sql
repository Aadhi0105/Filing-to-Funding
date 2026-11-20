SELECT pg_catalog.pg_advisory_xact_lock(2004228903);

CREATE TEMP TABLE statement_sources ON COMMIT DROP AS
SELECT source.*
FROM statement_input
CROSS JOIN LATERAL jsonb_to_record(document->'source') AS source(
    accession text, source_kind text, source_url text, retrieved_at timestamptz,
    sha256 text, storage_key text, byte_count bigint
);

DO $check$
BEGIN
    IF EXISTS (
        SELECT FROM statement_sources AS source
        LEFT JOIN core.filings AS filing USING (accession)
        WHERE filing.accession IS NULL
           OR source.source_url NOT IN (
               filing.filing_url,
               regexp_replace(filing.filing_url, '[^/]+$', '') || filing.accession || '-xbrl.zip'
           )
    ) THEN
        RAISE EXCEPTION 'Load the matching SEC accession inventory before statement qualification';
    END IF;
END
$check$;

INSERT INTO raw.source_payloads (sha256, storage_key, byte_count)
SELECT DISTINCT sha256, storage_key, byte_count FROM statement_sources
ON CONFLICT (sha256) DO NOTHING;

DO $check$
BEGIN
    IF EXISTS (
        SELECT FROM statement_sources AS expected JOIN raw.source_payloads AS saved USING (sha256)
        WHERE (expected.storage_key, expected.byte_count) <> (saved.storage_key, saved.byte_count)
    ) THEN
        RAISE EXCEPTION 'Stored archive metadata conflicts with the statement evidence';
    END IF;
END
$check$;

INSERT INTO raw.source_fetches (source_kind, source_url, retrieved_at, payload_sha256)
SELECT source_kind, source_url, retrieved_at, sha256 FROM statement_sources
ON CONFLICT (source_kind, source_url, retrieved_at, payload_sha256) DO NOTHING;

INSERT INTO core.reported_facts (
    accession, taxonomy, concept, unit, period_start, period_end, reporting_basis,
    scope_key, value, reported_decimals, source_fetch_id, source_locator
)
SELECT fact.accession, 'filing-statement-v1', fact.concept, 'USD', fact.period_start, fact.period_end,
       fact.reporting_basis, fact.scope_key, fact.value, fact.reported_decimals,
       source_record.fetch_id, fact.source_locator
FROM statement_input AS input
CROSS JOIN LATERAL jsonb_to_recordset(document->'facts') AS fact(
    accession text, concept text, period_start date, period_end date, reporting_basis text,
    scope_key text, value numeric, reported_decimals text, source_locator text
)
JOIN statement_sources AS source ON source.accession = fact.accession
JOIN raw.source_fetches AS source_record
  ON (source.source_kind, source.source_url, source.retrieved_at, source.sha256)
   = (source_record.source_kind, source_record.source_url, source_record.retrieved_at, source_record.payload_sha256)
ON CONFLICT ON CONSTRAINT reported_facts_exact_observation DO NOTHING;

COMMIT;
