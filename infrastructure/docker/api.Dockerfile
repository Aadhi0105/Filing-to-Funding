FROM python:3.11-slim-bookworm@sha256:a83ba18aef0f865b1a4a611c2cf460fe446f2795673bbb9fe43be570439e3b39

ENV FILING_RUNTIME=hosted \
    FILING_API_PUBLIC=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /opt/filing-to-funding
COPY apps/api/requirements.lock.txt /tmp/requirements.lock.txt
RUN pip install --no-cache-dir --only-binary=:all: -r /tmp/requirements.lock.txt \
    && rm /tmp/requirements.lock.txt \
    && python -c 'from zoneinfo import ZoneInfo; ZoneInfo("America/New_York")'

COPY apps/api/*.py apps/api/
COPY pipelines/*.py pipelines/

USER 65532:65532
EXPOSE 8080
CMD ["sh", "-c", "exec uvicorn apps.api.main:app --host 0.0.0.0 --port \"${PORT:-8080}\" --workers 1 --no-access-log --no-proxy-headers"]
