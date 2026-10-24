FROM python:3.12-slim-bookworm
COPY --from=ghcr.io/astral-sh/uv:0.10.4 /uv /usr/local/bin/uv
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8080 \
    UV_PROJECT_ENVIRONMENT=/opt/venv UV_LINK_MODE=copy PATH=/opt/venv/bin:$PATH
ARG APP_REVISION=development
ENV APP_REVISION=$APP_REVISION
LABEL org.opencontainers.image.source="https://github.com/wjdecorte/electric-dashboard"
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project
COPY app/ ./
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health',timeout=3)" || exit 1
CMD ["python", "server.py"]
