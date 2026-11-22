"""Versioned read-only company explorer API."""

import csv
import io
import os
from datetime import date, datetime
from decimal import Context as DecimalContext, Decimal, localcontext
from typing import Annotated, Literal

import psycopg
from fastapi import Depends, FastAPI, HTTPException, Path, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, StringConstraints

from apps.api import company_data as company, research
from apps.api.dataset_access import DATASETS, Duration, Mode, catalog_datasets, reader
from apps.api.funding_scenario import CALCULATION_PRECISION, calculate_funding_scenario, decimal_string
from apps.api.public_boundary import PublicBoundary, csv_cell
from pipelines import refresh_dataset

public = os.environ.get("FILING_API_PUBLIC") == "1"
app = FastAPI(
    title="Filing-to-Funding API", version="1.0.0",
    docs_url=None if public else "/docs", redoc_url=None if public else "/redoc",
    openapi_url=None if public else "/openapi.json",
)
app.add_middleware(PublicBoundary)
API = "/api/v1"
CIK = Annotated[str, Path(pattern=r"^[0-9]{10}$")]


class DatasetRecord(BaseModel):
    version: str
    snapshot_id: str
    methodology_version: str
    filing_cutoff: date
    treasury_start: date
    treasury_end: date
    published_at: datetime
    annual_and_revisions: bool
    validation_checks: tuple[str, ...]
    row_counts: dict[str, int]


class RefreshStatus(BaseModel):
    source_status: Literal["unknown", "running", "ok", "review_required", "failed", "overdue"]
    source_attempt_at: datetime | None
    source_success_at: datetime | None
    source_check_overdue: bool
    publication_status: Literal["unknown", "running", "ok", "failed"]
    publication_attempt_at: datetime | None
    publication_success_at: datetime | None
    filing_coverage_stale: bool
    treasury_coverage_stale: bool


class DatasetList(BaseModel):
    active_version: str
    versions: list[DatasetRecord]
    refresh: RefreshStatus


class Context(BaseModel):
    dataset_version: str
    methodology_version: str
    mode: Mode
    filed_by: date | None
    filing_cutoff: date
    cutoff_timezone: str = "America/New_York"


class Company(BaseModel):
    cik: str
    ticker: str
    name: str


class Period(BaseModel):
    fiscal_year: int
    quarter: int | None
    period_start: date | None
    period_end: date


class CompanyList(BaseModel):
    context: Context
    companies: list[Company]


class PeriodList(BaseModel):
    context: Context
    company: Company
    periods: list[Period]


class Metric(BaseModel):
    metric: str
    unit: str
    value: Decimal | None
    status: str
    period_start: date | None
    period_end: date | None
    reporting_basis: str
    scope_key: str
    fact_ids: list[int]
    source_accessions: list[str]
    numerator: Decimal | None = None
    denominator: Decimal | None = None
    debt_basis: str | None = None


class Point(Period):
    value: Decimal | None
    status: str
    reporting_basis: str
    scope_key: str
    source_accessions: list[str]


class FilingFact(BaseModel):
    fact_id: int
    accession: str
    concept: str
    unit: str
    value: Decimal
    reported_decimals: str | None
    period_start: date | None
    period_end: date
    filed_on: date
    accepted_at: datetime | None
    filing_url: str
    source_locator: str
    payload_sha256: str


class Revision(BaseModel):
    concept: str
    period_start: date | None
    period_end: date
    unit: str
    relationship: str
    relationship_reason: str
    prior_accession: str
    later_accession: str
    prior_url: str
    later_url: str
    prior_filed_on: date
    later_filed_on: date
    prior_value: Decimal
    later_value: Decimal
    prior_basis: str
    later_basis: str
    prior_scope: str
    later_scope: str
    prior_fact_ids: list[int]
    later_fact_ids: list[int]


class Analysis(BaseModel):
    context: Context
    company: Company
    period: Period
    duration: Duration
    metrics: list[Metric]
    series: list[Point]
    revisions: list[Revision]
    sources: list[FilingFact]


def current_catalog():
    try:
        active, versions = catalog_datasets()
    except (OSError, ValueError, KeyError) as error:
        raise HTTPException(503, "The local dataset catalog could not be read") from error
    if not any(record.version == active for record in versions):
        raise HTTPException(503, "No local dataset is published")
    return active, versions


def selection(
    mode: Mode = "latest",
    filed_by: date | None = None,
    dataset_version: Annotated[str | None, Query(pattern=r"^v[0-9]{4,8}$")] = None,
    expected_dataset_version: Annotated[str | None, Query(pattern=r"^v[0-9]{4,8}$")] = None,
):
    active, versions = current_catalog()
    if mode == "platform_snapshot":
        if dataset_version is None or filed_by is not None:
            raise HTTPException(422, "Platform snapshot mode requires a version and uses its own methodology")
    elif dataset_version is not None or (mode == "filed_by") != (filed_by is not None):
        raise HTTPException(422, "Supply a date only for Filed by date, or a version only for Platform snapshot")
    selected = next((record for record in versions if record.version == (dataset_version or active)), None)
    if selected is None:
        raise HTTPException(404, "Dataset version unavailable")
    if expected_dataset_version is not None and expected_dataset_version != selected.version:
        raise HTTPException(409, "The selected dataset changed. Reload this view to refresh its values.")
    if filed_by is not None and filed_by > selected.filing_cutoff:
        raise HTTPException(422, "The selected date is after the dataset's filing coverage")
    return selected, Context(
        dataset_version=selected.version, methodology_version=selected.methodology_version,
        mode=mode, filed_by=filed_by, filing_cutoff=selected.filing_cutoff,
    )


@app.exception_handler(psycopg.Error)
@app.exception_handler(OSError)
@app.exception_handler(ValueError)
async def unavailable(_: Request, error: Exception):
    return JSONResponse(status_code=503, content={"detail": "The selected local dataset is unavailable"})


@app.exception_handler(RequestValidationError)
async def invalid_request(_: Request, error: RequestValidationError):
    details = [
        {"loc": item["loc"][:1] if item["type"] == "extra_forbidden" else item["loc"],
         "msg": item["msg"], "type": item["type"]}
        for item in error.errors()
    ]
    return JSONResponse(status_code=422, content={"detail": details})


@app.get(f"{API}/datasets", response_model=DatasetList)
def datasets():
    active, versions = current_catalog()
    current = next(record for record in versions if record.version == active)
    return {
        "active_version": active, "versions": versions,
        "refresh": refresh_dataset.health(DATASETS, current.filing_cutoff, current.treasury_end),
    }


@app.get(f"{API}/companies", response_model=CompanyList)
def companies(selected=Depends(selection)):
    dataset, context = selected
    with reader(dataset) as connection:
        return {"context": context, "companies": company.company_rows(connection, context.filed_by)}


@app.get(f"{API}/companies/{{cik}}/periods", response_model=PeriodList)
def periods(cik: CIK, duration: Duration = "quarter", selected=Depends(selection)):
    dataset, context = selected
    with reader(dataset) as connection:
        issuer = company.require_company(connection, cik, context.filed_by)
        return {"context": context, "company": issuer,
                "periods": company.period_rows(connection, cik, duration, context.filed_by)}


def analysis_request(
    cik: CIK,
    fiscal_year: Annotated[int, Query(ge=1900, le=9999)],
    quarter: Annotated[int | None, Query(ge=1, le=4)] = None,
    duration: Duration = "quarter",
    selected=Depends(selection),
):
    if (duration == "annual") != (quarter is None):
        raise HTTPException(422, "Quarter is required for quarterly and trailing periods only")
    dataset, context = selected
    return Analysis(context=context, **company.analysis(dataset, cik, duration, context.filed_by, fiscal_year, quarter))


@app.get(f"{API}/companies/{{cik}}/analysis", response_model=Analysis)
def company_analysis(result: Annotated[Analysis, Depends(analysis_request)]):
    return result


@app.get(
    f"{API}/companies/{{cik}}/export.csv", response_class=Response,
    responses={200: {"content": {"text/csv": {"schema": {"type": "string"}}}}},
)
def export(result: Annotated[Analysis, Depends(analysis_request)]):
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow((
        "section", "cik", "ticker", "duration", "metric", "unit", "value", "status",
        "period_start", "period_end", "reporting_basis", "scope_key", "accessions",
        "dataset_version", "methodology_version", "mode", "filed_by", "filing_cutoff",
    ))
    context = result.context
    for section, rows in (("selected_period", result.metrics), ("free_cash_flow_history", result.series)):
        for row in rows:
            values = row.model_dump()
            number = values["value"]
            writer.writerow(map(csv_cell, (
                section, result.company.cik, result.company.ticker, result.duration,
                values.get("metric", "free_cash_flow"), values.get("unit", "USD"),
                format(number, "f") if number is not None else None, values["status"],
                values["period_start"], values["period_end"], values["reporting_basis"],
                values["scope_key"], "|".join(values["source_accessions"]),
                context.dataset_version, context.methodology_version, context.mode,
                context.filed_by, context.filing_cutoff,
            )))
    return Response(
        output.getvalue(), media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{result.company.cik}-{context.dataset_version}.csv"'},
    )


class OverviewRow(BaseModel):
    company: Company
    period: Period | None
    note: str | None
    metrics: list[Metric]


class Overview(BaseModel):
    context: Context
    rows: list[OverviewRow]


class PeerRow(BaseModel):
    company: Company
    period: Period | None
    window_start: date | None
    reporting_basis: str | None
    metric: Metric | None
    status: str


class PeerComparison(BaseModel):
    context: Context
    period_end: date
    duration: Duration
    metric: str
    rows: list[PeerRow]


class FilingRow(BaseModel):
    accession: str
    form_type: str
    period_end: date
    filed_on: date
    accepted_at: datetime | None
    filing_url: str
    qualified_facts: int


class FilingHistory(BaseModel):
    context: Context
    company: Company
    total: int
    with_qualified_facts: int
    unverified_acceptance: int
    page: int
    page_size: int
    filings: list[FilingRow]


class Curve(BaseModel):
    cutoff_date: date
    observation_date: date | None
    observation_age_days: int | None
    status: str
    vintage_status: str | None
    two_year_percent: Decimal | None
    five_year_percent: Decimal | None
    ten_year_percent: Decimal | None
    ten_minus_two_bps: Decimal | None
    source_url: str | None
    source_retrieved_at: datetime | None
    source_published_at: datetime | None


class MarketRates(BaseModel):
    context: Context
    curve: Curve


Maturity = Literal["two_year", "five_year", "ten_year"]
ScenarioDecimal = Annotated[str, StringConstraints(min_length=1, max_length=128)]


class ScenarioInputs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    principal_usd: ScenarioDecimal
    repricing_share: ScenarioDecimal
    shock_bps: ScenarioDecimal
    horizon_years: ScenarioDecimal
    spread_bps: ScenarioDecimal | None = None
    maturity: Maturity = "five_year"
    curve_date: date | None = None


class Coupon(BaseModel):
    reference_yield_percent: str
    spread_bps: str
    baseline_coupon_percent: str
    shocked_coupon_percent: str
    baseline_interest_usd: str
    shocked_interest_usd: str


class SensitivityPoint(BaseModel):
    shock_bps: str
    incremental_interest_usd: str


class Scenario(BaseModel):
    context: Context
    curve: Curve | None
    reference_maturity: Maturity | None
    methodology_version: str
    currency: str
    inputs: dict[str, str]
    repricing_principal_usd: str
    annual_shock_decimal: str
    incremental_interest_usd: str
    illustrative_coupon: Coupon | None
    formula: str
    assumptions: list[str]
    sensitivity: list[SensitivityPoint]


@app.get(f"{API}/overview", response_model=Overview)
def portfolio_overview(selected=Depends(selection)):
    dataset, context = selected
    with reader(dataset) as connection:
        return {"context": context, "rows": research.overview(connection, dataset, context.filed_by)}


@app.get(f"{API}/peers", response_model=PeerComparison)
def peer_comparison(
    duration: Duration = "quarter",
    metric: Literal["free_cash_flow", "working_capital", "current_ratio"] = "free_cash_flow",
    period_end: date | None = None,
    selected=Depends(selection),
):
    dataset, context = selected
    limit = context.filed_by or context.filing_cutoff
    if period_end and period_end > limit:
        raise HTTPException(422, "The comparison period ends after the selected cutoff")
    with reader(dataset) as connection:
        return {"context": context, "duration": duration, "metric": metric,
                **research.peers(connection, dataset, context.filed_by, duration, period_end, metric)}


@app.get(f"{API}/companies/{{cik}}/filings", response_model=FilingHistory)
def filings(cik: CIK, page: Annotated[int, Query(ge=1, le=10000)] = 1, selected=Depends(selection)):
    dataset, context = selected
    with reader(dataset) as connection:
        issuer = company.require_company(connection, cik, context.filed_by)
        return {"context": context, "company": issuer,
                **research.filing_history(connection, cik, context.filed_by, page)}


@app.get(f"{API}/funding/curve", response_model=MarketRates)
def market_rates(curve_date: date | None = None, selected=Depends(selection)):
    dataset, context = selected
    try:
        cutoff = research.treasury_cutoff(context, curve_date)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    with reader(dataset) as connection:
        return {"context": context, "curve": research.treasury_curve(connection, cutoff)}


@app.post(f"{API}/funding/scenario", response_model=Scenario)
def funding_scenario(inputs: ScenarioInputs, selected=Depends(selection)):
    dataset, context = selected
    curve = None
    try:
        cutoff = research.treasury_cutoff(context, inputs.curve_date)
        if inputs.spread_bps is not None:
            with reader(dataset) as connection:
                curve = research.treasury_curve(connection, cutoff)
            yield_percent = curve[f"{inputs.maturity}_percent"]
            if yield_percent is None:
                raise ValueError("No complete Treasury curve was available on the selected date.")
        else:
            yield_percent = None
        result = calculate_funding_scenario(
            principal_usd=inputs.principal_usd, repricing_share=inputs.repricing_share,
            shock_bps=inputs.shock_bps, horizon_years=inputs.horizon_years,
            reference_yield_percent=yield_percent, spread_bps=inputs.spread_bps,
        )
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    with localcontext(DecimalContext(prec=CALCULATION_PRECISION)):
        sensitivity = [
            {"shock_bps": decimal_string(shock), "incremental_interest_usd": decimal_string(
                result.repricing_principal_usd * shock / 10000 * result.horizon_years
            )}
            for shock in (result.shock_bps - 50, result.shock_bps, result.shock_bps + 50)
        ]
    return {"context": context, "curve": curve, "reference_maturity": inputs.maturity if curve else None,
            "sensitivity": sensitivity, **result.to_dict()}
