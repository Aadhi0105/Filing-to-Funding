"""Versioned read-only company explorer API."""

import csv
import io
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated

import psycopg
from fastapi import Depends, FastAPI, HTTPException, Path, Query, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from apps.api import company_data as company
from apps.api.dataset_access import Duration, Mode, catalog_datasets, reader

app = FastAPI(title="Filing-to-Funding API", version="1.0.0")
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


class DatasetList(BaseModel):
    active_version: str
    versions: list[DatasetRecord]


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
    if active is None or not versions:
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
        raise HTTPException(409, "The selected dataset changed. Reload the Explorer to refresh its values.")
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


@app.get(f"{API}/datasets", response_model=DatasetList)
def datasets():
    active, versions = current_catalog()
    return {"active_version": active, "versions": versions}


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
            writer.writerow((
                section, result.company.cik, result.company.ticker, result.duration,
                values.get("metric", "free_cash_flow"), values.get("unit", "USD"),
                format(number, "f") if number is not None else None, values["status"],
                values["period_start"], values["period_end"], values["reporting_basis"],
                values["scope_key"], "|".join(values["source_accessions"]),
                context.dataset_version, context.methodology_version, context.mode,
                context.filed_by, context.filing_cutoff,
            ))
    return Response(
        output.getvalue(), media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{result.company.cik}-{context.dataset_version}.csv"'},
    )
