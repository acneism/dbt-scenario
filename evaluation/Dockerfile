FROM dbt-scenario-evaluation-base
USER root
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates git && rm -rf /var/lib/apt/lists/*
COPY scripts /app/scripts
COPY evaluation /app/evaluation
RUN DBT_SEND_ANONYMOUS_USAGE_STATS=false dbt deps --project-dir /app/evaluation/dependencies
RUN mkdir /results && chown postgres:postgres /results
USER postgres
ENTRYPOINT ["python", "/app/scripts/evaluate.py"]
