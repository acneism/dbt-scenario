FROM python:3.12-slim-bookworm AS python
FROM postgres:16-bookworm
COPY --from=python /usr/local/ /usr/local/
RUN apt-get update && apt-get install -y --no-install-recommends libbz2-1.0 libcrypt1 libexpat1 libffi8 libgdbm6 liblzma5 libncursesw6 libreadline8 libsqlite3-0 libssl3 libuuid1 zlib1g && rm -rf /var/lib/apt/lists/* && ldconfig
WORKDIR /app
COPY pyproject.toml README.md LICENSE requirements-dev.lock.txt /app/
COPY src /app/src
COPY scripts/offline_acceptance.py /app/scripts/offline_acceptance.py
RUN python -m pip install --no-cache-dir -r requirements-dev.lock.txt && python -m pip install --no-cache-dir --no-deps .
USER postgres
WORKDIR /tmp
ENTRYPOINT ["python", "/app/scripts/offline_acceptance.py"]
