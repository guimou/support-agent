# Deployment Guide

How to deploy and operate the LiteMaaS Agent Assistant.

## Local Development (Compose)

The quickest way to run the agent. Uses `compose.yaml` with `compose.override.yaml` for dev features.

```bash
podman-compose up     # or docker-compose up
```

The override file (applied automatically) provides:
- **Volume mount**: `src/` mounted into the container for live-reload
- **Uvicorn reload**: Auto-restarts on code changes
- **Log capture**: Writes to `logs/agent.log` and `logs/letta.log`

### Services

| Service | Image | Port | Health Check |
|---|---|---|---|
| `agent` | Built from `Containerfile` | 8400 | `GET /v1/health` |
| `letta` | `letta/letta:latest` | 8283 | Built-in Letta health check |

### Startup Order

The `agent` service depends on `letta` with a health check condition. The proxy waits for Letta to be healthy before bootstrapping the agent.

### Volumes

- **`letta-data`**: Persists Letta's PostgreSQL database (agent state, memory, conversations)

### Skip Overrides

To test production-like behavior:

```bash
podman-compose -f compose.yaml up    # ignores compose.override.yaml
```

## Production Compose

For production, use only `compose.yaml` (no override):

```bash
podman-compose -f compose.yaml up -d
```

Key differences from development:
- No volume mount (uses baked-in code from the image)
- No `--reload` flag
- No log file capture (use container logging)

### Environment Configuration

Set all required variables in `.env` or pass via `environment` in compose:

```bash
cp .env.example .env
# Fill in all required values
```

See [Configuration Reference](../reference/configuration.md) for the full list.

## Container Image

### Building

```bash
podman build -f Containerfile -t litemaas-agent:latest .
```

### Multi-Stage Build

The `Containerfile` uses two stages:

1. **Builder**: Installs dependencies via `uv` into a virtual environment
2. **Runtime**: Slim Python image, copies only the venv and source code

### Runtime Properties

- **Non-root user**: Runs as `agent` (UID 1001)
- **Health check**: Built-in urllib-based check against `/v1/health`
- **Exposed port**: 8400
- **PYTHONPATH**: `/app/src`

## Kubernetes / OpenShift (Helm)

> **Status**: Helm chart planned for Phase 3D. The design below documents the target architecture.

### Helm Chart Structure

```
deployment/helm/litemaas-agent/
├── Chart.yaml
├── values.yaml
└── templates/
    ├── deployment-proxy.yaml
    ├── deployment-letta.yaml
    ├── service-proxy.yaml
    ├── service-letta.yaml
    ├── pvc-letta.yaml
    └── configmap.yaml
```

### Target `values.yaml`

```yaml
replicaCount: 1

proxy:
  image:
    repository: quay.io/litemaas/agent-proxy
    tag: latest
  port: 8400
  resources:
    requests: { cpu: 200m, memory: 512Mi }
    limits: { cpu: 1000m, memory: 1Gi }

letta:
  image:
    repository: letta/letta
    tag: latest
  port: 8283
  persistence:
    enabled: true
    size: 10Gi
  resources:
    requests: { cpu: 500m, memory: 1Gi }
    limits: { cpu: 2000m, memory: 4Gi }

config:
  litemaasApiUrl: "http://litemaas-backend:8081"
  litellmApiUrl: "http://litellm:4000"
  agentModel: ""
  guardrailsModel: ""
  rateLimitRpm: 30

secrets:
  litellmApiKey: ""
  litellmUserApiKey: ""
  jwtSecret: ""
```

### Integration as LiteMaaS Subchart

The agent chart can be deployed standalone or as a subchart:

```yaml
# In LiteMaaS values.yaml
agent:
  enabled: true
  chart: litemaas-agent
  values:
    config:
      litemaasApiUrl: "http://{{ .Release.Name }}-backend:8081"
      litellmApiUrl: "http://{{ .Release.Name }}-litellm:4000"
```

### Resource Requirements

| Component | CPU Request | Memory Request | CPU Limit | Memory Limit |
|---|---|---|---|---|
| Proxy | 200m | 512Mi | 1000m | 1Gi |
| Letta | 500m | 1Gi | 2000m | 4Gi |

Letta requires more resources due to embedded PostgreSQL and vector operations.

### Persistent Volume

Letta needs persistent storage for its PostgreSQL database:
- **Size**: 10Gi recommended for production
- **Access mode**: ReadWriteOnce
- **Mount path**: `/data` inside the Letta container

Alternatively, Letta can connect to an external PostgreSQL instance via `LETTA_PG_URI` (the external DB must have `pgvector` installed).

## Monitoring

### Health Endpoint

`GET /v1/health` returns:

```json
{
  "status": "healthy",
  "agent": "connected",
  "agent_id": "uuid",
  "guardrails": "active"
}
```

Use for Kubernetes liveness/readiness probes.

### Logs

- **Development**: `logs/agent.log` and `logs/letta.log` (truncated on restart)
- **Production**: Use container stdout/stderr logging (standard Kubernetes log collection)

Log content:
- **Proxy**: Request/response metadata, guardrail results (allowed/blocked), latency
- **Letta**: Tool calls, memory operations, model interactions

### Planned Metrics (Phase 4)

| Metric | Type | Description |
|---|---|---|
| `agent_requests_total` | Counter | Total chat requests |
| `agent_requests_blocked` | Counter | Requests blocked by guardrails |
| `agent_response_latency_seconds` | Histogram | End-to-end response time |
| `agent_tool_calls_total` | Counter | Tool calls by tool name |
| `agent_memory_writes_total` | Counter | Memory operations (core, archival) |
| `guardrails_decisions_total` | Counter | Guardrail decisions by rail and result |
| `guardrails_latency_seconds` | Histogram | Guardrails evaluation time |

## Backup and Recovery

### What to back up

- **Letta data volume**: Contains PostgreSQL with all agent state, memory, and conversation history
- **`.env` file**: Contains secrets and configuration

### Recovery

The agent bootstrap is **idempotent**:
- If the agent exists in Letta, it is reused
- Tool registration uses upsert (safe to re-run)
- Archival seeds are version-tracked (not re-inserted if already present)

A fresh Letta volume means the agent starts from scratch — it re-creates the agent, re-registers tools, and re-seeds archival memory. Conversation history and learned patterns are lost.

### External PostgreSQL

For production, consider pointing Letta to an external PostgreSQL instance with standard backup procedures:

```
LETTA_PG_URI=postgresql://user:pass@host:5432/letta
```

The external DB must have the `pgvector` extension installed.
