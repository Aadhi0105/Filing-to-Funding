# Filing-to-Funding CV project entry

## Project summary

Filing-to-Funding is a live financial research platform for six U.S. industrial companies. It reconstructs historical liquidity and cash flow from SEC disclosures eligible by a selected filing date, links calculations to their source filings, and replays four published dataset versions. It also supports peer comparisons and Treasury-based funding scenarios. [Live app](https://filing-to-funding.vercel.app/overview) · [Repository](https://github.com/Aadhi0105/Filing-to-Funding)

## CV entry

**Filing-to-Funding | Corporate Liquidity and Financial Resilience Platform**

Next.js, TypeScript, Python, FastAPI, PostgreSQL, Vercel, and Google Cloud Run

- Built and deployed a full-stack SEC filing research platform covering six U.S. industrial companies, 160 filings, and 1,133 qualified statement observations.
- Implemented historical filing cutoffs, accession-linked financial calculations, and replay of four published datasets with their original methodology.
- Verified snapshot restoration and rollback. Measured a slowest warm endpoint p95 of 0.85 seconds in a 120-request, low-load production benchmark.

## Evidence for interviews

The public benchmark used six endpoints, three warmups and 20 measured requests per endpoint, and up to two requests per second. The recovery example comes from a controlled hosted rehearsal. Use the walkthrough to show the results and the case study to explain the source data and calculations. [Demo walkthrough](demo_walkthrough.md) · [Portfolio case study](portfolio_case_study.md) · [Technical evidence](technical_evidence.md)
