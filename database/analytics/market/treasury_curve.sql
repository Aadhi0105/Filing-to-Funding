CREATE FUNCTION analytics.treasury_curve(
    p_cutoff date,
    p_retrieved_by timestamptz DEFAULT NULL
)
RETURNS TABLE (
    cutoff_date date,
    observation_date date,
    observation_age_days integer,
    status text,
    vintage_status text,
    two_year_percent numeric,
    five_year_percent numeric,
    ten_year_percent numeric,
    ten_minus_two_bps numeric,
    source_fetch_id bigint,
    source_url text,
    source_retrieved_at timestamptz,
    source_published_at timestamptz,
    source_payload_sha256 text
)
LANGUAGE sql
STABLE
AS $function$
    WITH curves AS (
        SELECT observation.observation_date, source.fetch_id, source.source_url,
               source.retrieved_at, source.payload_sha256,
               max(observation.yield_percent) FILTER (WHERE observation.maturity_months = 24) AS two_year,
               max(observation.yield_percent) FILTER (WHERE observation.maturity_months = 60) AS five_year,
               max(observation.yield_percent) FILTER (WHERE observation.maturity_months = 120) AS ten_year,
               CASE WHEN count(observation.source_published_at) = 3
                          AND min(observation.source_published_at) = max(observation.source_published_at)
                    THEN min(observation.source_published_at) END AS published_at
        FROM core.treasury_yield_observations AS observation
        JOIN raw.source_fetches AS source ON source.fetch_id = observation.source_fetch_id
        WHERE isfinite(p_cutoff) AND observation.observation_date <= p_cutoff
          AND source.source_kind = 'treasury_daily_par_yields'
          AND (p_retrieved_by IS NULL OR source.retrieved_at <= p_retrieved_by)
          AND (
              observation.source_published_at IS NULL
              OR observation.source_published_at < ((p_cutoff + 1)::timestamp AT TIME ZONE 'America/New_York')
          )
        GROUP BY observation.observation_date, source.fetch_id
    ), newest AS (
        SELECT curve.*
        FROM curves AS curve
        WHERE (curve.observation_date, curve.retrieved_at) = (
            SELECT observation_date, retrieved_at FROM curves
            ORDER BY observation_date DESC, retrieved_at DESC LIMIT 1
        )
    ), selected AS (
        SELECT * FROM newest
        ORDER BY source_url COLLATE "C", payload_sha256 COLLATE "C"
        LIMIT 1
    ), agreement AS (
        SELECT count(DISTINCT (two_year, five_year, ten_year)) <= 1 AS rate_agreement
        FROM newest
    ), result AS (
        SELECT selected.*, agreement.rate_agreement,
               CASE
                   WHEN p_cutoff IS NULL OR NOT isfinite(p_cutoff) THEN 'invalid_cutoff'
                   WHEN selected.observation_date IS NULL THEN 'missing_observation'
                   WHEN NOT agreement.rate_agreement THEN 'conflicting_observations'
                   WHEN selected.two_year IS NULL OR selected.five_year IS NULL OR selected.ten_year IS NULL
                       THEN 'incomplete_curve'
                   WHEN selected.observation_date < p_cutoff THEN 'carried_forward'
                   ELSE 'observed_on_cutoff'
               END AS quality
        FROM agreement LEFT JOIN selected ON true
    )
    SELECT p_cutoff, result.observation_date,
           CASE WHEN result.observation_date IS NOT NULL THEN p_cutoff - result.observation_date END,
           result.quality,
           CASE WHEN result.observation_date IS NOT NULL THEN 'historical_vintage_unverified' END,
           CASE WHEN result.quality IN ('observed_on_cutoff', 'carried_forward') THEN result.two_year END,
           CASE WHEN result.quality IN ('observed_on_cutoff', 'carried_forward') THEN result.five_year END,
           CASE WHEN result.quality IN ('observed_on_cutoff', 'carried_forward') THEN result.ten_year END,
           CASE WHEN result.quality IN ('observed_on_cutoff', 'carried_forward')
                THEN (result.ten_year - result.two_year) * 100 END,
           CASE WHEN result.rate_agreement THEN result.fetch_id END,
           CASE WHEN result.rate_agreement THEN result.source_url END,
           CASE WHEN result.rate_agreement THEN result.retrieved_at END,
           CASE WHEN result.rate_agreement THEN result.published_at END,
           CASE WHEN result.rate_agreement THEN result.payload_sha256 END
    FROM result;
$function$;
