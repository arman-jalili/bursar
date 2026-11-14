# Bursar Python services — one image, two entrypoints (console-api, authority-service).
# The settlement broadcaster (`payments.broadcast`) is installed here too, because Rigorix's
# governed run_command step executes it from the host image that also carries this package.
# solc-js compiles the contracts on any host architecture (native solc lacks arm64 Linux).
FROM node:22-alpine AS contracts-build
WORKDIR /compile
COPY contracts/src /contracts/src
COPY scripts/compile_contracts.mjs .
RUN npm init -y >/dev/null \
    && npm install --no-audit --no-fund solc@0.8.24 \
    && node compile_contracts.mjs

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
COPY src ./src
COPY migrations ./migrations
COPY alembic.ini ./
COPY contracts ./contracts
COPY scripts ./scripts
COPY --from=contracts-build /out/contracts.json ./contracts/build/contracts.json

RUN pip install --no-cache-dir uv \
    && uv pip install --system .

RUN mkdir -p /app/data

EXPOSE 8000 8001
CMD ["uvicorn", "src.apps.console_api.app:app", "--host", "0.0.0.0", "--port", "8000"]
