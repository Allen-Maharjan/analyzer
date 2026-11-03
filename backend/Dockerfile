FROM node:22-bookworm-slim AS dukascopy
WORKDIR /dukascopy
COPY dukascopy/package.json dukascopy/package-lock.json ./
RUN npm ci --omit=dev --ignore-scripts && npm cache clean --force
COPY dukascopy/fetch.mjs ./

FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    GA_DUKASCOPY_SCRIPT=/app/dukascopy/fetch.mjs \
    GA_NODE_BINARY=/usr/local/bin/node
RUN apt-get update \
    && apt-get install -y --no-install-recommends libstdc++6 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=dukascopy /usr/local/bin/node /usr/local/bin/node
WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install .
COPY alembic.ini ./
COPY migrations ./migrations
COPY --from=dukascopy /dukascopy ./dukascopy
RUN useradd --system --uid 10001 --home-dir /app advisor && chown -R advisor /app
USER advisor
EXPOSE 8000
CMD ["uvicorn", "gold_advisor.api:app", "--host", "0.0.0.0", "--port", "8000"]
