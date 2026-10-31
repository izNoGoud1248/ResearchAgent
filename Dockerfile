# One image for every Python service. Compose picks the service with the command, e.g. services.api.
FROM ghcr.io/astral-sh/uv:0.12.9-python3.12-trixie-slim

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_NO_SYNC=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
RUN useradd --create-home --uid 10001 app

# Dependencies first, so code changes do not reinstall them.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev --no-install-project

COPY libs ./libs
COPY services ./services
RUN mkdir -p /app/logs && chown app:app /app/logs

USER app
ENTRYPOINT ["uv", "run", "--no-sync", "python", "-m"]
CMD ["services.api"]
