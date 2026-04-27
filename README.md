# LiteMaaS Agent Assistant

An AI-powered platform support assistant for [LiteMaaS](https://github.com/your-org/litemaas). Helps users with model subscriptions, API keys, usage questions, and troubleshooting.

> **Status:** Design phase — see [Architecture docs](#documentation) for the full design.

## What Is This?

A standalone AI agent that sits alongside LiteMaaS and provides intelligent platform support. It answers user questions, diagnoses issues, and learns from interactions over time.

This is **not** the model playground — LiteMaaS already has a `/chatbot` page for direct model interaction. This assistant focuses on helping users navigate the platform itself.

## How It Works

```
User → LiteMaaS Frontend → LiteMaaS Backend → Agent Proxy → Letta Runtime
                                                  ↑               ↑
                                           JWT auth        Reasoning +
                                           Guardrails      Tool calls +
                                           SSE streaming   Memory
```

The agent runs as **two containers**:

- **Proxy** — FastAPI server handling auth, guardrails (NeMo Guardrails), and streaming (port 8400)
- **Letta** — Off-the-shelf agent runtime managing reasoning, memory, and tool execution (port 8283)

The agent has **read-only access** to LiteMaaS and LiteLLM APIs. It uses multiple LLMs: a reasoning model for the agent loop and a fast model for guardrail evaluation, both served through LiteLLM.

## Key Features

- **Continuous learning** — builds institutional knowledge from interactions via self-editing memory
- **Privacy-first** — per-user conversation isolation, PII auditing on memory writes, cross-user data blocking
- **Multi-model routing** — different LLMs for reasoning vs. guardrails, configurable via environment variables
- **Safety rails** — NeMo Guardrails for topic control, prompt injection defense, and output filtering
- **Reusable** — designed as a standalone project adaptable to other platforms

## Prerequisites

- Python 3.11+
- [Podman](https://podman.io/) or [Docker](https://www.docker.com/)
- A running LiteMaaS instance
- A running LiteLLM proxy with at least two models configured (reasoning + guardrails)

## Quick Start

1. **Clone the repository**

   ```bash
   git clone https://github.com/your-org/litemaas-agent.git
   cd litemaas-agent
   ```

2. **Configure environment**

   ```bash
   cp .env.example .env
   # Edit .env with your LiteMaaS, LiteLLM, and JWT settings
   ```

3. **Start the stack**

   ```bash
   podman-compose up       # or docker-compose up
   ```

4. **Verify**

   ```bash
   curl http://localhost:8400/v1/health
   ```

## Configuration

| Variable | Required | Description |
|---|---|---|
| `LETTA_SERVER_URL` | Yes | Letta runtime URL |
| `LITEMAAS_API_URL` | Yes | LiteMaaS backend API base URL |
| `LITELLM_API_URL` | Yes | LiteLLM proxy base URL |
| `LITELLM_API_KEY` | Yes | LiteLLM master key (admin tools only) |
| `LITELLM_USER_API_KEY` | Yes | Scoped read-only LiteLLM key (standard tools) |
| `AGENT_MODEL` | Yes | Reasoning model name (as configured in LiteLLM) |
| `GUARDRAILS_MODEL` | Yes | Fast model for guardrail evaluation |
| `JWT_SECRET` | Yes | Shared JWT signing secret (must match LiteMaaS) |
| `RATE_LIMIT_RPM` | No | Per-user chat requests/min (default: 30) |
| `RATE_LIMIT_MEMORY_WRITES_PER_HOUR` | No | Per-user memory writes/hr (default: 20) |

See the [architecture doc](docs/architecture/ai-agent-assistant.md#10-configuration--environment-variables) for the full list.

## Project Structure

```
src/
├── agent/              # Agent configuration, bootstrap, persona
├── tools/              # Read-only platform tools (LiteMaaS, LiteLLM, admin)
├── guardrails/         # NeMo Guardrails config and custom actions
├── proxy/              # FastAPI server, JWT auth, SSE routes
└── adapters/           # Platform-specific adapters
tests/
├── unit/
├── integration/
└── guardrails/         # Safety and privacy test scenarios
deployment/
├── helm/               # Kubernetes/OpenShift Helm chart
└── kustomize/          # OpenShift Kustomize overlay
scripts/                # Knowledge seeding and export utilities
```

## Documentation

| Document | Description |
|---|---|
| [Architecture & Scenarios](docs/architecture/ai-agent-assistant.md) | Full system design, security model, memory architecture, deployment |
| [Integration Reference](docs/architecture/ai-agent-assistant-integration-reference.md) | LiteMaaS/LiteLLM API schemas, JWT structure, frontend patterns |

## Adapting to Another Platform

The project is designed to be reusable. To adapt it for a different platform:

1. Create a new adapter in `src/adapters/`
2. Write platform-specific tools in `src/tools/`
3. Update the agent persona in `src/agent/persona.py`
4. Customize guardrail rules in `src/guardrails/config/`

Everything else (Letta runtime, proxy, auth, memory) stays the same.

## License

[MIT](LICENSE)
