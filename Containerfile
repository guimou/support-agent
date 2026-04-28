# Stage 1: Build — install dependencies in a venv
FROM python:3.12-slim AS builder

WORKDIR /build

RUN pip install --no-cache-dir uv

# C++ compiler needed for nemoguardrails -> annoy
RUN apt-get update && \
    apt-get install -y --no-install-recommends build-essential && \
    rm -rf /var/lib/apt/lists/*

COPY pyproject.toml uv.lock* ./
COPY src/ ./src/

RUN uv venv /opt/venv && \
    . /opt/venv/bin/activate && \
    uv pip install --no-cache .

# Stage 2: Runtime — slim image with only what's needed
FROM python:3.12-slim AS runtime

RUN groupadd --gid 1001 agent && \
    useradd --uid 1001 --gid agent --shell /bin/bash --create-home agent

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /build/src/ ./src/

ENV PATH="/opt/venv/bin:$PATH"
ENV PYTHONPATH="/app/src"
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

EXPOSE 8400

USER agent

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8400/v1/health')"]

CMD ["uvicorn", "proxy.server:app", "--host", "0.0.0.0", "--port", "8400"]
