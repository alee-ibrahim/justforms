# syntax=docker/dockerfile:1
FROM python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:0.13 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY . .

# Local file storage (JUSTFORMS_STORAGE_BACKEND=local, the default). Mount a volume here;
# a fresh named volume inherits this directory's ownership.
ENV JUSTFORMS_STORAGE_LOCAL_PATH=/data/storage
RUN groupadd --system --gid 10001 justforms \
    && useradd --system --uid 10001 --gid justforms justforms \
    && mkdir -p /data/storage \
    && chown -R justforms:justforms /data
USER justforms

EXPOSE 8000
# Same image runs the worker with: arq app.worker.WorkerSettings
# --proxy-headers trusts only FORWARDED_ALLOW_IPS (default 127.0.0.1,::1): set it to the web
# container's addresses, the same as JUSTFORMS_TRUSTED_PROXIES. Never "*".
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
