FROM python:3.11-slim-bookworm@sha256:a83ba18aef0f865b1a4a611c2cf460fe446f2795673bbb9fe43be570439e3b39

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    FILING_SEC_REQUEST_BUDGET=/tmp/filing-sec-request-budget.lock

WORKDIR /opt/filing-to-funding
RUN apt-get update && apt-get install --no-install-recommends -y curl \
    && rm -rf /var/lib/apt/lists/*
COPY apps/api/requirements.lock.txt /tmp/requirements.lock.txt
RUN pip install --no-cache-dir --only-binary=:all: -r /tmp/requirements.lock.txt && rm /tmp/requirements.lock.txt
COPY pipelines/*.py pipelines/
USER 65532:65532
ENTRYPOINT ["python", "-m", "pipelines.hosted_source_check"]
