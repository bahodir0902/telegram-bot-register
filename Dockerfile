FROM ghcr.io/astral-sh/uv:0.11.33@sha256:77280f2f771df71f90786c314fe1bbc1e023feac652969bbf139c280babf2eb7 AS uv

FROM python:3.13.15-slim-bookworm@sha256:00faa2debb87529f9f0764e9491d8ba400a3678976616c3bd7cb193745ac20d1 AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_SYSTEM_CERTS=1

WORKDIR /app

COPY --from=uv /uv /usr/local/bin/uv
COPY pyproject.toml uv.lock ./
RUN --mount=type=secret,id=build_ca,required=false \
    set -eu; \
    if [ -f /run/secrets/build_ca ]; then \
        cp /etc/ssl/certs/ca-certificates.crt /tmp/build-ca-bundle.pem; \
        cat /run/secrets/build_ca >> /tmp/build-ca-bundle.pem; \
        SSL_CERT_FILE=/tmp/build-ca-bundle.pem \
            uv sync --locked --no-dev --no-install-project; \
        rm /tmp/build-ca-bundle.pem; \
    else \
        uv sync --locked --no-dev --no-install-project; \
    fi

COPY app ./app
RUN python -m compileall -q app

FROM python:3.13.15-slim-bookworm@sha256:00faa2debb87529f9f0764e9491d8ba400a3678976616c3bd7cb193745ac20d1 AS runtime

ARG SOURCE_URL="unknown"
ARG VCS_REVISION="unknown"

LABEL org.opencontainers.image.title="Telegram Registration Bot" \
      org.opencontainers.image.description="Telegram-native registration and media delivery bot" \
      org.opencontainers.image.source="${SOURCE_URL}" \
      org.opencontainers.image.revision="${VCS_REVISION}"

ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid 10001 --no-create-home --home-dir /app \
        --shell /usr/sbin/nologin app \
    && mkdir -p /app/data /app/media \
    && chown -R 10001:10001 /app

WORKDIR /app

COPY --from=builder --chown=10001:10001 /app/.venv /app/.venv
COPY --from=builder --chown=10001:10001 /app/app /app/app

USER 10001:10001

STOPSIGNAL SIGTERM

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD ["python", "-m", "app", "--healthcheck"]

CMD ["python", "-m", "app"]
