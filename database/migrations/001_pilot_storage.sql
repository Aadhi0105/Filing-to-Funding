CREATE SCHEMA core;
CREATE SCHEMA analytics;

CREATE TABLE raw.source_payloads (
    sha256 text PRIMARY KEY CHECK (sha256 ~ '^[0-9a-f]{64}$'),
    storage_key text NOT NULL UNIQUE CHECK (btrim(storage_key) <> ''),
    byte_count bigint NOT NULL CHECK (byte_count >= 0)
);

CREATE TABLE raw.source_fetches (
    fetch_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_kind text NOT NULL CHECK (source_kind IN (
        'sec_submissions', 'sec_company_facts', 'sec_filing_index',
        'sec_filing', 'treasury_daily_par_yields'
    )),
    source_url text NOT NULL CHECK (source_url ~ '^https://[^[:space:]]+$'),
    retrieved_at timestamptz NOT NULL,
    payload_sha256 text NOT NULL REFERENCES raw.source_payloads (sha256),
    recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (source_kind, source_url, retrieved_at, payload_sha256)
);

CREATE TABLE core.issuers (
    cik text PRIMARY KEY CHECK (cik ~ '^[0-9]{10}$'),
    legal_name text NOT NULL CHECK (btrim(legal_name) <> '')
);

CREATE TABLE core.issuer_aliases (
    cik text NOT NULL REFERENCES core.issuers (cik),
    alias_kind text NOT NULL CHECK (alias_kind IN ('ticker', 'legal_name')),
    alias text NOT NULL CHECK (btrim(alias) <> ''),
    valid_from date NOT NULL,
    valid_until date,
    PRIMARY KEY (cik, alias_kind, alias, valid_from),
    CHECK (valid_until IS NULL OR valid_until > valid_from)
);

CREATE TABLE core.reporting_periods (
    period_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    cik text NOT NULL REFERENCES core.issuers (cik),
    fiscal_year smallint NOT NULL CHECK (fiscal_year BETWEEN 1900 AND 9999),
    fiscal_quarter smallint CHECK (fiscal_quarter BETWEEN 1 AND 4),
    starts_on date NOT NULL,
    ends_on date NOT NULL,
    CHECK (ends_on >= starts_on),
    UNIQUE NULLS NOT DISTINCT (cik, fiscal_year, fiscal_quarter),
    UNIQUE (period_id, cik)
);

CREATE TABLE core.filings (
    accession text PRIMARY KEY CHECK (accession ~ '^[0-9]{10}-[0-9]{2}-[0-9]{6}$'),
    cik text NOT NULL,
    report_period_id bigint NOT NULL,
    form_type text NOT NULL CHECK (form_type IN ('10-K', '10-K/A', '10-Q', '10-Q/A')),
    filed_on date NOT NULL,
    accepted_at timestamptz,
    acceptance_timezone text CHECK (acceptance_timezone IN ('America/New_York', 'UTC')),
    filing_url text NOT NULL CHECK (filing_url ~ '^https://www[.]sec[.]gov/Archives/edgar/data/[^[:space:]]+$'),
    metadata_fetch_id bigint NOT NULL REFERENCES raw.source_fetches (fetch_id),
    recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    FOREIGN KEY (report_period_id, cik) REFERENCES core.reporting_periods (period_id, cik),
    CHECK ((accepted_at IS NULL) = (acceptance_timezone IS NULL))
);

CREATE INDEX filings_by_issuer_and_availability
    ON core.filings (cik, filed_on, accepted_at);

CREATE TABLE core.reported_facts (
    fact_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    accession text NOT NULL REFERENCES core.filings (accession),
    taxonomy text NOT NULL CHECK (btrim(taxonomy) <> ''),
    concept text NOT NULL CHECK (btrim(concept) <> ''),
    unit text NOT NULL CHECK (btrim(unit) <> ''),
    period_start date,
    period_end date NOT NULL,
    dimensions jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(dimensions) = 'object'),
    reporting_basis text NOT NULL CHECK (reporting_basis IN (
        'consolidated', 'continuing_operations', 'discontinued_operations', 'unclassified'
    )),
    scope_key text NOT NULL CHECK (btrim(scope_key) <> ''),
    value numeric NOT NULL CHECK (value NOT IN ('NaN'::numeric, 'Infinity'::numeric, '-Infinity'::numeric)),
    reported_decimals text CHECK (reported_decimals ~ '^(INF|[+-]?[0-9]+)$'),
    source_fetch_id bigint NOT NULL REFERENCES raw.source_fetches (fetch_id),
    source_locator text NOT NULL CHECK (btrim(source_locator) <> ''),
    recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CHECK (period_start IS NULL OR period_end >= period_start),
    -- Preserve different values in the same context for later reconciliation.
    CONSTRAINT reported_facts_exact_observation
        UNIQUE NULLS NOT DISTINCT (
            accession, taxonomy, concept, unit, period_start, period_end,
            dimensions, reporting_basis, scope_key, value, reported_decimals
        )
);

CREATE INDEX reported_facts_by_concept_and_period
    ON core.reported_facts (taxonomy, concept, period_end, period_start);

CREATE TABLE core.treasury_yield_observations (
    yield_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    observation_date date NOT NULL,
    maturity_months smallint NOT NULL CHECK (maturity_months IN (24, 60, 120)),
    yield_percent numeric NOT NULL CHECK (
        yield_percent NOT IN ('NaN'::numeric, 'Infinity'::numeric, '-Infinity'::numeric)
    ),
    source_published_at timestamptz,
    source_fetch_id bigint NOT NULL REFERENCES raw.source_fetches (fetch_id),
    recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (observation_date, maturity_months, source_fetch_id)
);
