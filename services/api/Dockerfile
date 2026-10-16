# floating patch tag = security updates on rebuild; pin a digest (@sha256:...) for fully reproducible builds
FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app/services/api
COPY services/api/pyproject.toml services/api/requirements.lock ./
COPY services/api/stark ./stark
# STARK_UID should match your user on Linux so the bind-mounted ./sandbox is writable (compose passes $UID)
ARG STARK_UID=10001
RUN pip install --require-hashes -r requirements.lock && pip install --no-deps . \
    && useradd --create-home --uid ${STARK_UID} stark
COPY agents /app/agents
RUN mkdir -p /app/data /app/sandbox && chown -R stark:stark /app/data /app/sandbox
USER stark
ENV STARK_HOST=0.0.0.0 STARK_DATA_DIR=/app/data STARK_WORKSPACE_ROOTS=/app/sandbox STARK_AGENTS_DIR=/app/agents
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/api/health')"
CMD ["python", "-m", "stark.main"]
