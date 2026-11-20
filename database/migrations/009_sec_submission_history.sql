ALTER TABLE raw.source_fetches
    DROP CONSTRAINT source_fetches_source_kind_check,
    ADD CONSTRAINT source_fetches_source_kind_check CHECK (source_kind IN (
        'sec_submissions', 'sec_submissions_history', 'sec_company_facts', 'sec_filing_index', 'sec_filing',
        'treasury_daily_par_yields', 'sec_filing_review', 'treasury_yield_review'
    ));
