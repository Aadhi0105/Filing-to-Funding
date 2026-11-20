CREATE TEMP TABLE live_sources ON COMMIT DROP AS
SELECT source.*
FROM live_input
CROSS JOIN LATERAL jsonb_to_recordset(document->'sources') AS source(
    kind text, url text, retrieved_at timestamptz, sha256 text, storage_key text, byte_count bigint
);

CREATE TEMP TABLE live_facts ON COMMIT DROP AS
SELECT document->>'accession' AS accession, fact.*
FROM live_input
CROSS JOIN LATERAL jsonb_to_recordset(document->'facts') AS fact(
    concept text, reviewed_concept text, reviewed_sign integer, value numeric,
    period_start date, period_end date, reported_decimals text, source_locator text
);

CREATE TEMP TABLE live_yields ON COMMIT DROP AS
SELECT rate.*
FROM live_input
CROSS JOIN LATERAL jsonb_to_recordset(document->'rates') AS rate(
    observation_date date, maturity_months smallint, yield_percent numeric
);

DO $reconcile$
BEGIN
    IF (SELECT count(*) FROM live_facts) <> 7 OR EXISTS (
        SELECT FROM live_facts AS sample
        WHERE NOT EXISTS (
            SELECT FROM core.reported_facts AS reviewed
            JOIN raw.source_fetches AS source ON source.fetch_id = reviewed.source_fetch_id
            WHERE source.source_kind = 'sec_filing_review'
              AND reviewed.accession = sample.accession
              AND reviewed.taxonomy = 'filing-line'
              AND reviewed.concept = sample.reviewed_concept
              AND reviewed.unit = 'USD'
              AND reviewed.period_start IS NOT DISTINCT FROM sample.period_start
              AND reviewed.period_end = sample.period_end
              AND reviewed.dimensions = '{}'::jsonb
              AND reviewed.reporting_basis = 'consolidated'
              AND reviewed.scope_key = 'as_reported'
              AND reviewed.value = sample.value * sample.reviewed_sign
              AND reviewed.reported_decimals = sample.reported_decimals
        )
    ) THEN
        RAISE EXCEPTION 'SEC sample differs from the reviewed filing';
    END IF;
    IF (SELECT count(*) FROM live_yields) <> 15 OR EXISTS (
        SELECT FROM live_yields AS sample
        WHERE NOT EXISTS (
            SELECT FROM core.treasury_yield_observations AS reviewed
            JOIN raw.source_fetches AS source ON source.fetch_id = reviewed.source_fetch_id
            WHERE source.source_kind = 'treasury_yield_review'
              AND reviewed.observation_date = sample.observation_date
              AND reviewed.maturity_months = sample.maturity_months
              AND reviewed.yield_percent = sample.yield_percent
        )
    ) THEN
        RAISE EXCEPTION 'Treasury sample differs from the reviewed yields';
    END IF;
END
$reconcile$;

INSERT INTO raw.source_payloads (sha256, storage_key, byte_count)
SELECT sha256, storage_key, byte_count
FROM live_sources
ON CONFLICT (sha256) DO NOTHING;

DO $archive$
BEGIN
    IF EXISTS (
        SELECT FROM live_sources AS source
        JOIN raw.source_payloads AS saved USING (sha256)
        WHERE (source.storage_key, source.byte_count) <> (saved.storage_key, saved.byte_count)
    ) THEN
        RAISE EXCEPTION 'Archived payload metadata conflicts with the source response';
    END IF;
END
$archive$;

INSERT INTO raw.source_fetches (source_kind, source_url, retrieved_at, payload_sha256)
SELECT kind, url, retrieved_at, sha256
FROM live_sources
ON CONFLICT (source_kind, source_url, retrieved_at, payload_sha256) DO NOTHING;

CREATE TEMP VIEW live_fetches AS
SELECT source.kind, saved_fetch.fetch_id
FROM live_sources AS source
JOIN raw.source_fetches AS saved_fetch
  ON (saved_fetch.source_kind, saved_fetch.source_url, saved_fetch.retrieved_at, saved_fetch.payload_sha256)
   = (source.kind, source.url, source.retrieved_at, source.sha256);

INSERT INTO core.reported_facts (
    accession, taxonomy, concept, unit, period_start, period_end, reporting_basis,
    scope_key, value, reported_decimals, source_fetch_id, source_locator
)
SELECT
    fact.accession, 'us-gaap', fact.concept, 'USD', fact.period_start, fact.period_end,
    'consolidated', 'as_reported', fact.value, fact.reported_decimals, source.fetch_id, fact.source_locator
FROM live_facts AS fact
CROSS JOIN live_fetches AS source
WHERE source.kind = 'sec_filing'
ON CONFLICT ON CONSTRAINT reported_facts_exact_observation DO NOTHING;

INSERT INTO core.treasury_yield_observations (
    observation_date, maturity_months, yield_percent, source_fetch_id
)
SELECT rate.observation_date, rate.maturity_months, rate.yield_percent, source.fetch_id
FROM live_yields AS rate
CROSS JOIN live_fetches AS source
WHERE source.kind = 'treasury_daily_par_yields'
ON CONFLICT (observation_date, maturity_months, source_fetch_id) DO NOTHING;

DO $verify$
BEGIN
    IF EXISTS (
        SELECT FROM live_facts AS sample
        WHERE NOT EXISTS (
            SELECT FROM core.reported_facts AS saved
            JOIN raw.source_fetches AS saved_fetch ON saved_fetch.fetch_id = saved.source_fetch_id
            WHERE saved_fetch.source_kind = 'sec_filing'
              AND (saved_fetch.source_url, saved_fetch.payload_sha256) = (
                  SELECT url, sha256 FROM live_sources WHERE kind = 'sec_filing'
              )
              AND saved.accession = sample.accession
              AND saved.taxonomy = 'us-gaap'
              AND saved.concept = sample.concept
              AND saved.unit = 'USD'
              AND saved.period_start IS NOT DISTINCT FROM sample.period_start
              AND saved.period_end = sample.period_end
              AND saved.dimensions = '{}'::jsonb
              AND saved.reporting_basis = 'consolidated'
              AND saved.scope_key = 'as_reported'
              AND saved.value = sample.value
              AND saved.reported_decimals = sample.reported_decimals
              AND saved.source_locator = sample.source_locator
        )
    ) THEN
        RAISE EXCEPTION 'Database lacks the verified SEC facts with matching source lineage';
    END IF;
    IF EXISTS (
        SELECT FROM live_yields AS sample
        CROSS JOIN live_fetches AS source
        WHERE source.kind = 'treasury_daily_par_yields'
          AND NOT EXISTS (
              SELECT FROM core.treasury_yield_observations AS saved
              WHERE saved.source_fetch_id = source.fetch_id
                AND saved.observation_date = sample.observation_date
                AND saved.maturity_months = sample.maturity_months
                AND saved.yield_percent = sample.yield_percent
                AND saved.source_published_at IS NULL
          )
    ) THEN
        RAISE EXCEPTION 'Database lacks the verified Treasury yields with matching source lineage';
    END IF;
END
$verify$;

SELECT kind, url, retrieved_at, sha256, byte_count, storage_key
FROM live_sources
ORDER BY kind;

COMMIT;
