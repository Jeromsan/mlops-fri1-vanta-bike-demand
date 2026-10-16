FROM python:3.12.11-slim-bookworm

WORKDIR /app

ARG SOURCE_COMMIT
ENV SOURCE_COMMIT=${SOURCE_COMMIT}
RUN test -n "$SOURCE_COMMIT"

COPY --from=ghcr.io/astral-sh/uv:0.12.23 /uv /uvx /bin/
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --locked --no-install-project

COPY src ./src
COPY configs ./configs
COPY data ./data
COPY tests ./tests
RUN uv sync --locked

CMD ["uv", "run", "--locked", "python", "-m", "bike_demand.train", "--config", "configs/baseline.yaml"]
