SELECT pg_catalog.pg_advisory_xact_lock(2004228903);

CREATE TEMP TABLE treasury_sources ON COMMIT DROP AS
SELECT source.*
FROM treasury_input
CROSS JOIN LATERAL jsonb_to_record(document) AS source(
    year integer, source_url text, retrieved_at timestamptz, sha256 text, storage_key text, byte_count bigint
);

INSERT INTO raw.source_payloads (sha256, storage_key, byte_count)
SELECT DISTINCT sha256, storage_key, byte_count FROM treasury_sources
ON CONFLICT (sha256) DO NOTHING;

DO $check$
BEGIN
    IF EXISTS (
        SELECT FROM treasury_sources AS expected JOIN raw.source_payloads AS saved USING (sha256)
        WHERE (expected.storage_key, expected.byte_count) <> (saved.storage_key, saved.byte_count)
    ) THEN
        RAISE EXCEPTION 'Stored archive metadata conflicts with the Treasury capture';
    END IF;
END
$check$;

INSERT INTO raw.source_fetches (source_kind, source_url, retrieved_at, payload_sha256)
SELECT 'treasury_daily_par_yields', source_url, retrieved_at, sha256 FROM treasury_sources
ON CONFLICT (source_kind, source_url, retrieved_at, payload_sha256) DO NOTHING;

CREATE TEMP TABLE treasury_rates ON COMMIT DROP AS
SELECT source.year, rate.*, evidence.fetch_id
FROM treasury_sources AS source
JOIN raw.source_fetches AS evidence
  ON evidence.source_kind = 'treasury_daily_par_yields'
 AND (source.source_url, source.retrieved_at, source.sha256)
   = (evidence.source_url, evidence.retrieved_at, evidence.payload_sha256)
JOIN treasury_input AS input ON (input.document->>'year')::integer = source.year
CROSS JOIN LATERAL jsonb_to_recordset(input.document->'rates') AS rate(
    observation_date date, maturity_months smallint, yield_percent numeric
);

INSERT INTO core.treasury_yield_observations (
    observation_date, maturity_months, yield_percent, source_fetch_id
)
SELECT observation_date, maturity_months, yield_percent, fetch_id
FROM treasury_rates
ORDER BY observation_date, maturity_months
ON CONFLICT (observation_date, maturity_months, source_fetch_id) DO NOTHING;

DO $check$
BEGIN
    IF EXISTS (
        SELECT FROM treasury_rates AS expected
        LEFT JOIN core.treasury_yield_observations AS saved
          ON (saved.observation_date, saved.maturity_months, saved.source_fetch_id)
           = (expected.observation_date, expected.maturity_months, expected.fetch_id)
        WHERE saved.yield_percent IS DISTINCT FROM expected.yield_percent
           OR saved.source_published_at IS NOT NULL
    ) THEN
        RAISE EXCEPTION 'Stored Treasury observations conflict with the archived response';
    END IF;
END
$check$;

SELECT year, min(observation_date) AS first_observation, max(observation_date) AS last_observation,
       count(DISTINCT observation_date) AS observation_dates, count(*) AS yield_observations
FROM treasury_rates
GROUP BY year ORDER BY year;

COMMIT;
