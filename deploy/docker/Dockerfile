FROM python:3.11-slim AS builder

WORKDIR /app
ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --prefix=/install .

FROM python:3.11-slim AS runtime

RUN useradd --create-home --uid 10001 appuser
WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH=/home/appuser/.local/bin:$PATH

COPY --from=builder /install /usr/local
USER appuser

# A worker stage is supplied by Docker Compose or the Helm chart.
ENTRYPOINT ["python", "-m", "rag_ingestion.workers"]
