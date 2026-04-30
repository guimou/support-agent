# Architecture Overview

> **Status**: Phase 1 (Foundation) complete
> **Scope**: Standalone AI assistant agent for LiteMaaS (reusable for similar platforms)

## Executive Summary

The LiteMaaS Agent Assistant is a standalone AI agent that acts as an intelligent **platform support assistant** for LiteMaaS users. It helps with platform questions, troubleshooting, and guidance — it is **not** the model playground (the existing `/chatbot` page handles direct model interaction).

The agent:

- Runs as an **independent container** with its own lifecycle
- Has **read-only API access** to LiteMaaS and LiteLLM backends
- **Learns from interactions** — improves over time via self-editing memory
- **Respects user boundaries** — per-user data isolation and privacy via embedded NeMo Guardrails
- Is **reusable** — designed as a separate project adaptable to other platforms

The agent is powered by [Letta](https://github.com/letta-ai/letta) (formerly MemGPT), a stateful agent runtime with self-editing memory, and protected by [NVIDIA NeMo Guardrails](https://github.com/NVIDIA/NeMo-Guardrails) (embedded as a Python library) for dialog safety, topic control, and privacy enforcement.

## Design Goals

| Goal | Description |
|---|---|
| **Autonomous intelligence** | Answers questions, diagnoses issues, and guides users without human intervention |
| **Continuous learning** | Builds institutional knowledge from interactions and gets better over time |
| **Privacy-first** | Users never see each other's data, subscriptions, or conversations |
| **Multi-model routing** | Different LLMs handle different tasks (reasoning, tool calling, guardrails) |
| **Standalone deployment** | Ships as containers with no hard dependency on LiteMaaS internals |
| **Reusability** | Generic enough to serve as an assistant for similar platforms |

## Two-Container Model

The agent stack runs as **two separate containers** that communicate via REST API:

| Container | Image | Role | Port |
|---|---|---|---|
| **Proxy** (`agent`) | Custom (built from this project) | FastAPI server: JWT auth, NeMo Guardrails (embedded Python library), SSE streaming, request routing | 8400 |
| **Letta** (`letta`) | `letta/letta:latest` (off-the-shelf) | Agent runtime: reasoning loop, memory management, tool execution, embedded PostgreSQL + pgvector | 8283 |

**Why two containers?** Letta is an off-the-shelf agent server with its own API — we don't modify it. Our custom logic (auth, guardrails, streaming) lives in the proxy, which sits in front of Letta and communicates with it via HTTP.

**Request flow:**

```
LiteMaaS Backend ──> Proxy (auth + input rails) ──> Letta (reasoning + tools) ──> Proxy (output rails) ──> LiteMaaS Backend
```

## Tool Execution Model

Tools (the plain Python functions in `src/tools/`) are **registered with Letta via `client.tools.upsert_from_function()`** at bootstrap time. When the agent decides to call a tool, **Letta executes the function inside its own process** — not in the proxy. This means:

- Tool functions must be **self-contained** — they use `os.getenv()` for configuration and make HTTP calls to external APIs
- Tool **dependencies** (e.g., `httpx`) must be available in Letta's Python environment
- Tool **secrets** (API URLs, keys) are passed via Letta's secrets mechanism, which makes them available as environment variables inside the tool sandbox
- The **proxy does not execute tools** — it only handles auth, guardrails, and routing

## Architecture Diagram

```
                         +-------------------------------------+
                         |           LiteMaaS Stack            |
                         |                                     |
  User ---- Browser ---+ |  +----------+     +-------------+  |
                         |  | Frontend |---->|  Backend    |  |
                         |  | Assistant| SSE |  /api/v1/   |  |
                         |  | Widget   |     |  assistant/ |  |
                         |  +----------+     +------+------+  |
                         |                          |         |
                         +--------------------------+---------+
                                                    |
                              User JWT + message    |
                                                    v
+ - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - +
  Agent Stack (two containers, one project)
|                                                               |
| +------------------------------------------------------------+|
  |  CONTAINER 1: Proxy (custom image, port 8400)               |
| |  FastAPI server                                             ||
  |  + NeMo Guardrails (embedded Python library)                |
| |  + JWT validation & user context extraction                 ||
  |  + SSE streaming with chunked output rails                  |
| +----------------------------+--------------------------------+|
                               | REST API (HTTP)
| +----------------------------v--------------------------------+|
  |  CONTAINER 2: Letta (off-the-shelf, port 8283)              |
| |                                                             ||
  |  Agent Instance: Core Memory + Recall Memory + Archival     |
| |  Read-Only Tools (executed by Letta, registered at bootstrap)||
  |  PostgreSQL + pgvector (bundled inside Letta container)     |
| +------------------------------------------------------------+|
                               |                  |
+ - - - - - - - - - - - - - - | - - - - - - - - -|- - - - - - +
                               |                  |
                        +------v--------+ +-------v--------------+
                        | LiteLLM Proxy | |   LiteMaaS API       |
                        | <reasoning>   | |   (read-only)        |
                        | <guardrails>  | |  /api/v1/models      |
                        +---------------+ |  /api/v1/subscriptions|
                                          |  /api/v1/api-keys    |
                                          +----------------------+
```

> **Note**: The Letta container bundles PostgreSQL (with pgvector) internally — no separate database container is needed. Data is persisted via a volume mount. Alternatively, Letta can connect to an external PostgreSQL instance via `LETTA_PG_URI`.

## Multi-Model Routing Strategy

The agent leverages multiple LLMs, each optimized for its task. All models are served through LiteLLM:

| Stage | Env Variable | Characteristics |
|---|---|---|
| Letta agent reasoning + memory decisions | `AGENT_MODEL` | Strong reasoning, good at complex diagnosis and memory management |
| Guardrails rail evaluation | `GUARDRAILS_MODEL` | Fast, cheap, good at classification tasks |

**Naming convention**: Letta requires a provider prefix (`openai-proxy/MyModel`), but guardrails call the LLM provider directly and use the plain model name (`MyModel`).

NeMo Guardrails is configured in `src/guardrails/config/config.yml` to use `GUARDRAILS_MODEL` via the LiteLLM endpoint. This keeps guardrails evaluation fast and cost-effective, independent of the heavier reasoning model.

## Development Roadmap

| Phase | Status | Focus |
|---|---|---|
| **Phase 0**: Scaffolding | Complete | Project structure, CI/CD, dev environment |
| **Phase 1**: Foundation | Complete | Agent setup, tools, auth, guardrails |
| **Phase 2**: Integration | Planned | SSE streaming, LiteMaaS backend routes, frontend widget |
| **Phase 3**: Hardening | Planned | Privacy rails, red-team testing, Helm chart |
| **Phase 4**: Observability | Planned | Metrics, admin dashboard, knowledge pipeline |

See [Project Plan](../development/PROJECT_PLAN.md) for details.
