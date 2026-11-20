\set ON_ERROR_STOP on
BEGIN;
SET LOCAL TIME ZONE 'Asia/Kolkata';

DO $test$
DECLARE
    failures text;
BEGIN
    IF (
        SELECT count(DISTINCT (observation.observation_date, observation.maturity_months))
        FROM core.treasury_yield_observations AS observation
        JOIN raw.source_fetches AS source ON source.fetch_id = observation.source_fetch_id
        WHERE source.source_kind = 'treasury_daily_par_yields'
          AND source.source_url LIKE '%&field_tdr_date_value=%'
          AND source.retrieved_at IS NOT NULL
          AND observation.source_published_at IS NULL
    ) <> 5166 THEN
        RAISE EXCEPTION 'The frozen Treasury capture must cover 1,722 dates and three maturities';
    END IF;

    IF (
        SELECT count(*)
        FROM core.treasury_yield_observations AS reviewed
        JOIN raw.source_fetches AS review_source ON review_source.fetch_id = reviewed.source_fetch_id
        WHERE review_source.source_kind = 'treasury_yield_review'
          AND EXISTS (
              SELECT
              FROM core.treasury_yield_observations AS annual
              JOIN raw.source_fetches AS source ON source.fetch_id = annual.source_fetch_id
              WHERE source.source_kind = 'treasury_daily_par_yields'
                AND source.source_url LIKE '%&field_tdr_date_value=2024'
                AND (annual.observation_date, annual.maturity_months, annual.yield_percent)
                  = (reviewed.observation_date, reviewed.maturity_months, reviewed.yield_percent)
          )
    ) <> 15 THEN
        RAISE EXCEPTION 'The annual Treasury archive differs from the reviewed October sample';
    END IF;

    WITH examples(label, cutoff, observed, age, quality, two_year, five_year, ten_year, spread) AS (
        VALUES
            ('before the archive', DATE '2020-01-01', NULL, NULL, 'missing_observation', NULL, NULL, NULL, NULL),
            ('inversion', DATE '2023-03-08', DATE '2023-03-08', 0, 'observed_on_cutoff', 5.05, 4.34, 3.98, -107),
            ('same date', DATE '2024-10-24', DATE '2024-10-24', 0, 'observed_on_cutoff', 4.07, 4.03, 4.21, 14),
            ('Saturday', DATE '2024-10-26', DATE '2024-10-25', 1, 'carried_forward', 4.11, 4.07, 4.25, 14),
            ('Veterans Day', DATE '2024-11-11', DATE '2024-11-08', 3, 'carried_forward', 4.26, 4.20, 4.30, 4),
            ('Christmas Day', DATE '2024-12-25', DATE '2024-12-24', 1, 'carried_forward', 4.29, 4.43, 4.59, 30),
            ('end of coverage', DATE '2026-11-19', DATE '2026-11-19', 0, 'observed_on_cutoff', 4.76, 4.86, 5.04, 28),
            ('after coverage', DATE '2026-11-20', DATE '2026-11-19', 1, 'carried_forward', 4.76, 4.86, 5.04, 28),
            ('invalid cutoff', NULL, NULL, NULL, 'invalid_cutoff', NULL, NULL, NULL, NULL)
    )
    SELECT string_agg(example.label, ', ') INTO failures
    FROM examples AS example
    CROSS JOIN LATERAL analytics.treasury_curve(example.cutoff) AS actual
    WHERE (actual.observation_date, actual.observation_age_days, actual.status, actual.two_year_percent,
           actual.five_year_percent, actual.ten_year_percent, actual.ten_minus_two_bps)
        IS DISTINCT FROM
          (example.observed, example.age, example.quality, example.two_year, example.five_year,
           example.ten_year, example.spread)
       OR (example.observed IS NOT NULL AND (
           actual.vintage_status IS DISTINCT FROM 'historical_vintage_unverified'
           OR actual.source_published_at IS NOT NULL
           OR actual.source_fetch_id IS NULL OR actual.source_payload_sha256 IS NULL
       ));
    IF failures IS NOT NULL THEN
        RAISE EXCEPTION 'Treasury cutoff, yield, or lineage failed for %', failures;
    END IF;

    IF (SELECT status FROM analytics.treasury_curve(DATE '2024-10-24',
                                                   TIMESTAMPTZ '2024-10-24 23:59:59-04')) <> 'missing_observation' THEN
        RAISE EXCEPTION 'A historical archive view used bytes retrieved after its archive cutoff';
    END IF;
END
$test$;

-- Synthetic source captures test revision timing, conflicts, and a partial curve.
INSERT INTO raw.source_payloads (sha256, storage_key, byte_count)
SELECT repeat(code, 64), 'tests/treasury-vintage-' || code, 10
FROM (VALUES ('a'), ('b'), ('c'), ('d'), ('e')) AS captures(code);

INSERT INTO raw.source_fetches (source_kind, source_url, retrieved_at, payload_sha256)
SELECT 'treasury_daily_par_yields', 'https://example.test/treasury-' || capture.code,
       capture.retrieved_at, repeat(capture.code, 64)
FROM (VALUES
    ('a', TIMESTAMPTZ '2030-01-02 23:00+00'),
    ('b', TIMESTAMPTZ '2030-01-03 22:00+00'),
    ('c', TIMESTAMPTZ '2030-01-04 22:00+00'),
    ('d', TIMESTAMPTZ '2030-01-04 22:00+00'),
    ('e', TIMESTAMPTZ '2030-01-05 22:00+00')
) AS capture(code, retrieved_at);

INSERT INTO core.treasury_yield_observations (
    observation_date, maturity_months, yield_percent, source_fetch_id
)
SELECT DATE '2030-01-02', sample.maturity, sample.rate, source.fetch_id
FROM (VALUES
    ('a', 24, 3.00), ('a', 60, 3.10), ('a', 120, 3.20),
    ('b', 24, 3.01), ('b', 60, 3.10), ('b', 120, 3.20),
    ('c', 24, 3.02), ('c', 60, 3.10), ('c', 120, 3.20),
    ('d', 24, 3.03), ('d', 60, 3.10), ('d', 120, 3.20),
    ('e', 24, 3.04), ('e', 60, 3.10)
) AS sample(code, maturity, rate)
JOIN raw.source_fetches AS source ON source.payload_sha256 = repeat(sample.code, 64);

DO $test$
DECLARE
    earlier record;
    revised record;
    conflicting record;
    partial record;
BEGIN
    SELECT * INTO STRICT earlier
    FROM analytics.treasury_curve(DATE '2030-01-02', TIMESTAMPTZ '2030-01-02 23:00+00');
    SELECT * INTO STRICT revised
    FROM analytics.treasury_curve(DATE '2030-01-02', TIMESTAMPTZ '2030-01-03 22:00+00');
    IF (earlier.two_year_percent, earlier.ten_minus_two_bps, earlier.source_payload_sha256)
        IS DISTINCT FROM (3.00, 20::numeric, repeat('a', 64))
       OR (revised.two_year_percent, revised.ten_minus_two_bps, revised.source_payload_sha256)
        IS DISTINCT FROM (3.01, 19::numeric, repeat('b', 64))
       OR revised.vintage_status IS DISTINCT FROM 'historical_vintage_unverified' THEN
        RAISE EXCEPTION 'The archive cutoff lost the original or revised Treasury capture';
    END IF;

    SELECT * INTO STRICT conflicting
    FROM analytics.treasury_curve(DATE '2030-01-02', TIMESTAMPTZ '2030-01-04 22:00+00');
    IF conflicting.status <> 'conflicting_observations' OR conflicting.ten_minus_two_bps IS NOT NULL
       OR conflicting.source_fetch_id IS NOT NULL THEN
        RAISE EXCEPTION 'Conflicting simultaneous Treasury captures produced a chosen rate';
    END IF;

    SELECT * INTO STRICT partial FROM analytics.treasury_curve(DATE '2030-01-02');
    IF partial.status <> 'incomplete_curve' OR partial.ten_minus_two_bps IS NOT NULL
       OR partial.two_year_percent IS NOT NULL OR partial.source_fetch_id IS NULL THEN
        RAISE EXCEPTION 'A partial capture was completed with rates from an older capture';
    END IF;

    RAISE NOTICE 'Historical Treasury checks passed';
END
$test$;

ROLLBACK;
