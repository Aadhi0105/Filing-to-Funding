# Pilot Task 2 — filing reconciliation

Reviewed 19 November 2026. These expected values were transcribed by hand from seven SEC periodic reports and checked independently of any ingestion pipeline. They cover the three companies in the [pilot coverage matrix](coverage_matrix.md).

## Filing references and units

| Reference | Form and reporting date | Filing date and SEC acceptance time (Eastern time) | Accession and financial statements |
|---|---|---|---|
| ITW Q1 | 10-Q, 2026-03-31 | 2026-05-07 16:05:23 | [0000049826-26-000028](https://www.sec.gov/Archives/edgar/data/49826/000004982626000028/0000049826-26-000028-index.htm) · [Report](https://www.sec.gov/Archives/edgar/data/49826/000004982626000028/itw-20260331.htm) |
| ITW Q2 | 10-Q, 2026-06-30 | 2026-08-06 15:34:23 | [0000049826-26-000049](https://www.sec.gov/Archives/edgar/data/49826/000004982626000049/0000049826-26-000049-index.htm) · [Report](https://www.sec.gov/Archives/edgar/data/49826/000004982626000049/itw-20260630.htm) |
| DOV Q2 original | 10-Q, 2024-06-30 | 2024-07-25 06:39:50 | [0000029905-24-000035](https://www.sec.gov/Archives/edgar/data/29905/000002990524000035/0000029905-24-000035-index.htm) · [Report](https://www.sec.gov/Archives/edgar/data/29905/000002990524000035/dov-20240630.htm) |
| DOV Q3 | 10-Q, 2024-09-30 | 2024-10-24 06:36:52 | [0000029905-24-000045](https://www.sec.gov/Archives/edgar/data/29905/000002990524000045/0000029905-24-000045-index.html) · [Report](https://www.sec.gov/Archives/edgar/data/29905/000002990524000045/dov-20240930.htm) |
| DOV Q2 comparative | 10-Q, 2025-06-30. Use the 2024 comparative column. | 2025-07-24 06:45:44 | [0000029905-25-000024](https://www.sec.gov/Archives/edgar/data/29905/000002990525000024/0000029905-25-000024-index.htm) · [Report](https://www.sec.gov/Archives/edgar/data/29905/000002990525000024/dov-20250630.htm) |
| ROK FY2026 Q3 | 10-Q, 2026-06-30 | 2026-08-04 14:03:44 | [0001024478-26-000030](https://www.sec.gov/Archives/edgar/data/1024478/000102447826000030/0001024478-26-000030-index.htm) · [Report](https://www.sec.gov/Archives/edgar/data/1024478/000102447826000030/rok-20260630.htm) |
| ROK FY2026 | 10-K, 2026-09-30 | 2026-11-12. Exact acceptance time still to be checked against the SEC index. | [0001024478-26-000048](https://www.sec.gov/Archives/edgar/data/1024478/000102447826000048/rok-20260930.htm) · [Balance sheet](https://www.sec.gov/Archives/edgar/data/1024478/000102447826000048/R3.htm) · [Cash-flow statement](https://www.sec.gov/Archives/edgar/data/1024478/000102447826000048/R8.htm) |

All amounts are in USD. ITW and ROK present amounts in millions. DOV presents amounts in thousands. Carry that precision into the fixture. Parentheses in a cash-flow statement indicate an outflow. Convert cash capex to a positive magnitude before subtracting it from operating cash flow. Balance-sheet values are measured at the reporting date. Cash-flow values cover the stated interval.

## Illinois Tool Works — derive standalone Q2 cash flow

USD millions. Use the current-year columns in the Statement of Financial Position and Statement of Cash Flows.

| Filing line | ITW Q1 | ITW Q2 |
|---|---:|---:|
| Cash and equivalents | 827 | 839 |
| Total current assets | 6,335 | 6,600 |
| Total current liabilities | 5,331 | 5,953 |
| Short-term debt | 2,545 | 3,145 |
| Long-term debt | 6,603 | 6,549 |
| Net cash provided by operating activities | 623 | 1,346 |
| Additions to plant and equipment, as displayed | (95) | (187) |

The Q1 flows cover 2026-01-01 through 2026-03-31. The Q2 filing's cash-flow statement covers 2026-01-01 through 2026-06-30.

| Expected calculation | Result |
|---|---:|
| Q2 working capital, 6,600 − 5,953 | 647 |
| Q2 current ratio, 6,600 ÷ 5,953 | 1.108685×, rounded |
| Q2 reported debt, 3,145 + 6,549 | 9,694 |
| Q2 reported net debt, 9,694 − 839 | 8,855 |
| Standalone Q2 operating cash flow, 1,346 − 623 | 723 |
| Standalone Q2 cash capex, 187 − 95 | 92 |
| Standalone Q2 free cash flow, 723 − 92 | 631 |

The Q2 management discussion independently shows 723 of operating cash flow, 92 of capex and 631 of free cash flow in its three-month column. The debt note confirms that the short-term amount already includes commercial paper and the notes due in November 2026. Use the two non-overlapping balance-sheet rows. In end-of-day **Filed by date** mode, the standalone Q2 figures are unavailable on 2026-08-05 and available on 2026-08-06 from these filings. [ITW Q2 report](https://www.sec.gov/Archives/edgar/data/49826/000004982626000049/itw-20260630.htm)

## Dover — keep both reporting scopes and respect the cutoff

USD thousands. Use the Condensed Consolidated Balance Sheets and Statements of Cash Flows, and read Note 4 in the Q3 and later comparative filings.

| Balance-sheet line | DOV Q2 original | DOV Q3 |
|---|---:|---:|
| Cash and cash equivalents | 328,752 | 386,766 |
| Total current assets | 3,265,969 | 3,745,901 |
| Total current liabilities | 2,134,159 | 2,387,203 |
| Short-term borrowings | 210,471 | 379,295 |
| Long-term debt | 2,960,914 | 3,007,820 |

The Q3 balance sheet yields working capital of **1,358,698** and reported debt of **3,387,115**. The cash-flow statement reconciles ending cash of 396,766 as the balance-sheet cash of 386,766 plus 10,000 of cash held for sale. The pilot cash ratio uses the balance-sheet line, so the expected Q3 ratio is **0.162016×**, rounded. [DOV Q3 report](https://www.sec.gov/Archives/edgar/data/29905/000002990524000045/dov-20240930.htm)

| Cash-flow line | Original H1 2024, includes ESG | Nine months 2024, continuing scope | Comparative H1 2024, continuing scope |
|---|---:|---:|---:|
| Duration | 2024-01-01 to 2024-06-30 | 2024-01-01 to 2024-09-30 | 2024-01-01 to 2024-06-30 |
| Net cash provided by operating activities | 370,255 | 648,881 | 295,637 |
| Additions to property, plant and equipment, as displayed | (85,347) | (113,626) | (75,872) |
| Operating cash flow from discontinued operations, separately presented | Outside this sample | 108,284 | 74,619 |
| Computed free cash flow on the same scope as the inputs | 284,908 | 535,255 | 219,765 |

ESG is Dover's Environmental Solutions Group. The September 2024 filing classified it as discontinued. The July 2025 filing supplies a first-half 2024 comparative on that basis. Preserve the original **370,255** and the later continuing-operations **295,637** with their own scope and accession. This is a recast following a disposal. The filings do not identify it as a correction of error. The discontinued operating cash-flow line is separate from discontinued investing cash flow. [Original H1](https://www.sec.gov/Archives/edgar/data/29905/000002990524000035/dov-20240630.htm) · [September filing](https://www.sec.gov/Archives/edgar/data/29905/000002990524000045/dov-20240930.htm) · [Later comparative](https://www.sec.gov/Archives/edgar/data/29905/000002990525000024/dov-20250630.htm)

- **2024-10-24 cutoff with this filing set:** the compatible first-half continuing series is unavailable. Suppress standalone continuing Q3. Subtracting 370,255 from 648,881 produces 278,626, a negative control that the test must reject because the operands have different scopes.
- **2025-07-24 cutoff with this filing set:** the compatible comparative is eligible. Continuing-operations Q3 operating cash flow is **353,244** (648,881 − 295,637). Cash capex is **37,754** (113,626 − 75,872). Free cash flow is **315,490**. Track both accessions in the calculation.

These expectations apply to the selected filing set. A full-history check must still look for other eligible comparative disclosures before assigning the first date a recast was available.

## Rockwell Automation — September year-end and finance leases

USD millions. Use the Consolidated Balance Sheet and Consolidated Statement of Cash Flows. The June report covers the nine months beginning 2025-10-01. The annual report begins on the same date and ends 2026-09-30.

| Filing line | ROK FY2026 Q3 | ROK FY2026 |
|---|---:|---:|
| Cash and cash equivalents | 479 | 433 |
| Total current assets | 3,948 | 3,882 |
| Total current liabilities | 3,672 | 3,768 |
| Short-term debt | 686 | 709 |
| Current portion of long-term debt | 2 | 2 |
| Long-term debt | 2,570 | 2,569 |
| Cash provided by operating activities | 1,278 | 1,958 |
| Capital expenditures, as displayed | (179) | (257) |

| Expected calculation | Result |
|---|---:|
| September working capital, 3,882 − 3,768 | 114 |
| September debt including finance leases, 709 + 2 + 2,569 | 3,280 |
| September borrowing debt excluding disclosed finance leases, 3,280 − 4 | 3,276 |
| September net borrowing debt, 3,276 − 433 | 2,843 |
| Standalone fiscal Q4 operating cash flow, 1,958 − 1,278 | 680 |
| Standalone fiscal Q4 cash capex, 257 − 179 | 78 |
| Standalone fiscal Q4 free cash flow, 680 − 78 | 602 |

The annual filing's debt note gives 2,571 as the subtotal before deducting the current portion. It equals 2 + 2,569, so use either representation once. The lease disclosure identifies 4 of finance lease liabilities as of the same date and explains that finance leases sit within the current and noncurrent debt lines. The 3,276 result uses that note at filing precision. The June sample verifies reported debt of 3,258 before any lease adjustment. Keep that observation on its reported basis until a June-specific note amount is verified. Both cash-flow reports include Sensia's dissolution in the earlier part of the same fiscal year. Preserve that event annotation for cross-period comparisons. [ROK Q3 report](https://www.sec.gov/Archives/edgar/data/1024478/000102447826000030/rok-20260630.htm) · [ROK annual report, debt and lease disclosures](https://www.sec.gov/Archives/edgar/data/1024478/000102447826000048/rok-20260930.htm)

The issuer's 8-K earnings exhibit independently shows 680 of Q4 operating cash flow and 602 of Q4 free cash flow. That exhibit is a cross-check. The pilot's periodic-filing historical view uses the 10-Q and 10-K accessions. [ROK earnings exhibit](https://www.sec.gov/Archives/edgar/data/1024478/000102447826000045/fy2026ex99.htm)

## Verification boundary

The sample establishes expected balances, flows, dates, and reporting scopes for future ingestion and SQL tests. Arithmetic was checked at the precision shown in the filings. Full historical accession and amendment coverage, XBRL tag mapping, and the remaining ROK acceptance timestamp are open for the source and ingestion work.
