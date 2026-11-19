ALTER TABLE raw.source_fetches
    DROP CONSTRAINT source_fetches_source_kind_check,
    ALTER COLUMN retrieved_at DROP NOT NULL,
    ADD CONSTRAINT source_fetches_source_kind_check CHECK (source_kind IN (
        'sec_submissions', 'sec_company_facts', 'sec_filing_index', 'sec_filing',
        'treasury_daily_par_yields', 'sec_filing_review', 'treasury_yield_review'
    )),
    ADD CONSTRAINT source_fetches_review_retrieval_time CHECK (
        (retrieved_at IS NULL) = (source_kind IN ('sec_filing_review', 'treasury_yield_review'))
    );

-- A reviewed source represents an archived extract, with no verified HTTP fetch time.
CREATE UNIQUE INDEX source_fetches_review_identity
    ON raw.source_fetches (source_kind, source_url, payload_sha256)
    WHERE source_kind IN ('sec_filing_review', 'treasury_yield_review');
