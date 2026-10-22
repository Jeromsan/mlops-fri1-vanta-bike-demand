FROM python:3.12.11-slim-bookworm

WORKDIR /app

ARG SOURCE_COMMIT
ENV SOURCE_COMMIT=${SOURCE_COMMIT}
RUN test -n "$SOURCE_COMMIT"

COPY --from=ghcr.io/astral-sh/uv:0.12.23 /uv /uvx /bin/
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --locked --no-install-project

COPY .python-version ./
COPY src ./src
COPY configs ./configs
COPY data ./data
COPY .github/workflows/ci.yml ./.github/workflows/ci.yml
# Preflight checks this path; keep team names and historical evidence out of the image.
RUN mkdir -p reports && touch reports/week-01-team.md
COPY tests ./tests
COPY scripts ./scripts
RUN uv sync --locked

EXPOSE 8000
CMD ["uv", "run", "--locked", "--no-sync", "uvicorn", "bike_demand.api:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
