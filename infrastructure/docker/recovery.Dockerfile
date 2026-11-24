FROM postgres:17.12@sha256:223efeb196329b55b3b9a13db144956411dbc18e727e59f681c3e0aede6475cf

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /opt/filing-to-funding
RUN apt-get update && apt-get install --no-install-recommends -y python3 ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY pipelines/*.py pipelines/
COPY database/tests/*.sql database/tests/
USER postgres
ENTRYPOINT ["python3", "-m", "pipelines.hosted_recovery"]
