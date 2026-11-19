# Filing-to-Funding — Proposed Full-Stack Architecture v1.1

**Status: Locked historical review draft.** The [v1.2 architecture and audit](filing-to-funding-audit-v1.2.md) documents the current design.

MY RECOMMENDED TECHNOLOGY STACK

**Frontend**

Next.js · React · TypeScript · Tailwind CSS

**Backend**

Python · FastAPI · REST API

**Database**

PostgreSQL · Supabase-managed hosting

**Cloud infrastructure**

Google Cloud Run · Cloud Storage · Cloud Scheduler

**Frontend hosting**

Vercel · HTTPS · Custom domain support

**Development**

GitHub · Docker · CI/CD · Automated tests

This architecture uses well-established technologies without requiring the expense and operational complexity of an enterprise-scale data platform.

## 1. Why I recommend React and Next.js for the frontend

We should replace Streamlit with a proper frontend application.

Streamlit is useful for rapid analytical prototypes. However, a React application gives us substantially more control over navigation, application state, responsiveness, interaction design, reusable components, and the overall user experience.

**Next.js with React and TypeScript**

Next.js supports modern React application patterns, server-side rendering, client-side interactivity and structured routing. Its official setup also supports TypeScript and Tailwind CSS directly.

### Recommended frontend technologies

| Technology | Responsibility |
|--------|--------|
| Next.js | Web application framework and routing |
| React | Interactive interface and reusable components |
| TypeScript | Type safety across frontend code |
| Tailwind CSS | Responsive styling |
| shadcn/ui | Customisable interface components |
| Apache ECharts | Interactive financial charts |
| TanStack Query | API state, caching and data refresh |
| TanStack Table | Sorting, filtering and displaying financial tables |

We would design a consistent visual system across the application: typography, spacing, colours, charts, navigation, loading states and empty states.

### Core application screens

The proposed application has five analytical screens.

**Overview**

Company universe, latest available financial indicators, changes in resilience, warning flags and recent filings.

**Company Explorer**

Financial statements, historical trends, cash flow, debt, liquidity ratios and source filing links.

**Peer Comparison**

Compare companies, periods and financial indicators with consistent definitions.

**Funding &amp; Scenarios**

Treasury yield analysis and transparent borrowing-cost sensitivity models.

**Data Quality &amp; Filing History**

Filing versions, historical as-of dates, metric provenance, missing observations and ingestion status.

I would also add professional features such as CSV export, responsive layouts, URL-based filters and contextual explanations of financial ratios.

The objective is to build an application that looks and behaves like a genuine financial research platform, not merely a collection of charts.

---

## 2. Why FastAPI for the backend?

The frontend and backend should have clearly separated responsibilities.

The React frontend presents information and accepts user inputs.

The Python backend handles business logic, API requests, database access and validation.

I recommend **FastAPI**, a Python framework designed for building APIs using typed request and response models.

This is particularly suitable because our existing financial-data ingestion and analytical workflows will already use Python.

### Example backend endpoints

| Endpoint | Purpose |
|--------|--------|
| `GET /api/v1/companies` | Retrieve supported companies |
| `GET /api/v1/companies/{id}/financials` | Retrieve financial observations |
| `GET /api/v1/companies/{id}/liquidity` | Retrieve liquidity indicators |
| `GET /api/v1/companies/{id}/cashflow` | Retrieve cash-flow metrics |
| `GET /api/v1/comparisons` | Compare selected companies |
| `GET /api/v1/treasury/yields` | Retrieve interest-rate history |
| `POST /api/v1/scenarios/funding` | Calculate a financing sensitivity scenario |
| `GET /api/v1/filings/{id}` | Retrieve filing metadata and source information |
| `GET /api/v1/data-quality` | Retrieve data-quality information |

The API should define strict request and response schemas, return appropriate error codes, validate inputs and paginate larger datasets.

Importantly, financial calculations should not all be performed in Python.

**SQL remains the central analytical engine.**

For example, the backend might request a company's trailing-twelve-month cash flow from a tested PostgreSQL analytical view rather than downloading raw rows and recreating every calculation in pandas.

That ensures the project genuinely demonstrates advanced SQL.

---

## 3. Which cloud platform should we use?

Databricks, Firebase, AWS and Azure serve different roles.

AWS and Azure are broad cloud platforms. Firebase provides managed application services, including document databases. Databricks specialises in data engineering, analytics and AI workloads.

We should choose technologies according to the role they need to perform.

| Platform | Suitability | My assessment |
|--------|--------|--------|
| **Google Cloud** | Very high | Cloud Run and scheduled jobs fit a small-to-medium containerised financial-data application well |
| **AWS** | Very high | Excellent alternative using managed compute, PostgreSQL, S3 and scheduled events |
| **Azure** | High | Equally viable, especially for Microsoft-oriented enterprise environments |
| **Supabase** | Very high | Convenient managed PostgreSQL with connections, backups and other application services |
| **Firebase / Firestore** | Lower for our core database | Firestore's document-oriented NoSQL model is less appropriate for our relational financial SQL requirements |
| **Databricks** | Unnecessary initially | Powerful analytical platform, but excessive for 10–12 companies and our proposed data volumes |

Cloud Firestore is officially a NoSQL document database, whereas Supabase provides managed PostgreSQL. That difference is material for a project designed to demonstrate relational SQL.

Likewise, Databricks would become more relevant if we were processing very large financial datasets or building distributed analytics and machine-learning pipelines.

### My preferred hosting combination

**Next.js frontend — Vercel**

Public web application, HTTPS, responsive interface

HTTPS / JSON API

**FastAPI backend — Google Cloud Run**

Application logic, SQL access, validation, financial API

**PostgreSQL — Supabase**

Financial facts, filings, metrics, history, indexes and views

---

**Data pipeline — Cloud Run Jobs + Cloud Scheduler**

SEC/Treasury ingestion · transformations · tests · refreshes

**Cloud Storage + PostgreSQL**

Source payloads and validated analytical records

Google Cloud Run supports both web services and jobs. The latter can be scheduled through Cloud Scheduler, which is especially useful for separating data ingestion from normal API requests.

Vercel provides a straightforward deployment path for Next.js, including Git-linked deployments and previews.

### Why use three different hosting providers?

It is not strictly necessary, and there is a trade-off.

Vercel simplifies Next.js deployment. Supabase simplifies PostgreSQL management. Cloud Run gives us an appropriate environment for Python APIs and background data jobs.

However, the combination introduces cross-provider networking, multiple billing accounts and additional configuration.

A more consolidated alternative would use Google Cloud for the frontend, backend, database and storage. Another option is an AWS-based architecture using App Runner, RDS PostgreSQL and S3. AWS App Runner supports Python web services and access to RDS databases.

For this project's initial scale, I favour the managed multi-provider approach because it reduces infrastructure administration. But I would keep the application's architecture portable through Docker, PostgreSQL and standard HTTP APIs.

---

## 4. An important cost consideration

We should not choose cloud services without considering their recurring costs.

Cloud Run can scale services down when they are idle, which is useful for a portfolio application with intermittent traffic.

Supabase offers a free tier, but free projects may be paused after approximately a week of low activity. Its free database allowance is also limited. That makes the free tier useful during development, but potentially unsuitable for a portfolio demo that must always be accessible.

My proposal is to begin with local development, use managed services selectively during testing, then evaluate the actual monthly hosting cost before publicly deploying the completed application.

We should also configure budget alerts, database backups, secrets management and proper environment separation.

---

## 5. Updated project development structure

With this architectural change, I would reorganise Filing-to-Funding into eight workstreams rather than the previous seven stages.

| Workstream | Deliverable |
|--------|--------|
| 1. Product and UI/UX design | User journeys, wireframes, design system, responsive page designs |
| 2. Database architecture | PostgreSQL schema, constraints, migrations and source provenance |
| 3. Data ingestion | SEC and Treasury API clients, historical backfill and incremental refreshes |
| 4. Financial analytics | SQL-based ratios, temporal calculations, comparisons and warning indicators |
| 5. Backend API | FastAPI routes, request validation, query services and error handling |
| 6. Frontend application | Next.js pages, charts, tables, filters, exports and API integration |
| 7. Cloud and automation | Hosting, scheduled jobs, CI/CD, security, monitoring and backups |
| 8. Quality assurance and release | Financial reconciliation, automated tests, performance profiling and GitHub documentation |

Some workstreams will overlap during implementation.

### What I would require from the finished application

The final version should have:

- A publicly accessible HTTPS website.
- A genuine React/TypeScript frontend, not an embedded notebook or Streamlit app.
- A separately implemented, documented Python API backend.
- A managed PostgreSQL database with meaningful financial-data modelling.
- Automated ingestion and refresh of real-world data.
- SQL-based financial calculations and point-in-time analysis.
- A professional financial dashboard with source traceability.
- Automated tests covering financial correctness, frontend behaviour and backend functionality.
- A working deployment pipeline and reproducible GitHub repository.

For security, the frontend must never expose PostgreSQL credentials or ingestion secrets. Administrative refresh operations should remain private; public users should access validated data through appropriately restricted read-only interfaces.

---

## 6. The resulting GitHub repository

I would use a monorepo structure:

```text

filing-to-funding/
│
├── apps/
│   ├── web/                 # Next.js + TypeScript
│   └── api/                 # FastAPI backend
│
├── pipelines/
│   ├── sec_ingestion/
│   ├── treasury_ingestion/
│   └── refresh/
│
├── database/
│   ├── migrations/
│   ├── models/
│   ├── analytics/
│   └── tests/
│
├── packages/
│   └── shared-types/
│
├── infrastructure/
│   ├── docker/
│   └── cloud/
│
├── docs/
│   ├── architecture.md
│   ├── financial_methodology.md
│   ├── data_dictionary.md
│   └── deployment.md
│
├── .github/
│   └── workflows/
│
└── README.md
```

This makes the frontend, backend, SQL logic, ingestion jobs and infrastructure clearly distinguishable while keeping the entire product in a single portfolio repository.

---

## 7. What this changes about the ambition of the project

This is no longer merely a medium-sized SQL project with a visual reporting layer.

It becomes a **medium-to-large, end-to-end financial technology engineering project**.

That's a meaningful increase in complexity, and we should acknowledge it.

The project would demonstrate four complementary competencies:

**Financial analytics**

Liquidity, cash flow, leverage, financial statement interpretation and funding sensitivity.

**Advanced SQL and data engineering**

Relational modelling, temporal queries, historical revisions, financial reconciliation and automated data ingestion.

**Full-stack software engineering**

React, TypeScript, API design, application architecture, testing and frontend/backend integration.

**Cloud and deployment engineering**

Containerisation, scheduled jobs, managed databases, deployment workflows and operational reliability.

That breadth could help make the project distinctive for financial technology, financial analytics, portfolio analytics and technically demanding finance roles.

But breadth alone will not make it impressive. We must still prioritise the accuracy of the financial analysis, the quality of the SQL, and the reliability of the application.

## My recommended decision

I recommend adopting the following architecture as **Filing-to-Funding Project Specification v1.1**:

**Frontend:** Next.js + React + TypeScript + Tailwind + shadcn/ui + ECharts.

**Backend:** FastAPI + Python + carefully structured SQL services.

**Database:** PostgreSQL, locally during development and hosted on Supabase for deployment.

**Cloud:** Vercel for the frontend; Google Cloud Run for backend services and ingestion jobs; Cloud Storage for preserved source data; Cloud Scheduler for refreshes.

**Engineering:** Docker, GitHub Actions, automated testing, database migrations, logs and appropriate security controls.

**AI:** Optional filing-research assistant after the complete core web application works.

I would also revise our success criterion: **Filing-to-Funding should be a deployable financial research product, not simply a completed analytics dashboard.**
