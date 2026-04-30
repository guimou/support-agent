# LiteMaaS Agent Assistant

[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

An AI-powered platform support assistant for LiteMaaS. Helps users with model subscriptions, API keys, usage questions, and troubleshooting.

> **Status:** Phase 1 (Foundation) complete — proxy, guardrails, tools, and agent bootstrap implemented. See [CHANGELOG.md](CHANGELOG.md) for details.

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

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) (Python package manager)
- [Podman](https://podman.io/) or [Docker](https://www.docker.com/)
- A running LiteMaaS instance
- A running LiteLLM proxy with at least two models configured (reasoning + guardrails)

## Quick Start

1. **Clone the repository**

   ```bash
   git clone <repository-url>
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

See the [Developer Guide](docs/guides/developer-guide.md) for the full setup walkthrough.

## Configuration

| Variable | Required | Description |
|---|---|---|
| `LETTA_SERVER_URL` | Yes | Letta runtime URL |
| `LITEMAAS_API_URL` | Yes | LiteMaaS backend API base URL |
| `JWT_SECRET` | Yes | Shared JWT signing secret (must match LiteMaaS) |
| **LLM Providers** | | |
| `AGENT_MODEL` | Yes | Reasoning model name |
| `AGENT_LLM_API_BASE` | Yes | Agent model provider URL |
| `AGENT_LLM_API_KEY` | Yes | Agent model provider API key |
| `GUARDRAILS_MODEL` | Yes | Fast model for guardrail evaluation |
| `GUARDRAILS_LLM_API_BASE` | Yes | Guardrails model provider URL |
| `GUARDRAILS_LLM_API_KEY` | Yes | Guardrails model provider API key |
| **Monitored Platform** | | |
| `LITELLM_API_URL` | Yes | Monitored LiteLLM instance URL (queried by tools) |
| `LITELLM_API_KEY` | Yes | Monitored LiteLLM master key (admin tools only) |
| `LITELLM_USER_API_KEY` | Yes | Monitored LiteLLM scoped key (standard tools) |
| **Optional** | | |
| `RATE_LIMIT_RPM` | No | Per-user chat requests/min (default: 30) |
| `RATE_LIMIT_MEMORY_WRITES_PER_HOUR` | No | Per-user memory writes/hr (default: 20) |

See [Configuration Reference](docs/reference/configuration.md) for the full list with defaults and groupings.

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

Full documentation is in [`docs/`](docs/index.md):

| Section | Description |
|---|---|
| [Architecture Overview](docs/architecture/overview.md) | System design, two-container model, multi-model routing |
| [Security Architecture](docs/architecture/security.md) | Trust boundaries, 6 security invariants, memory safety |
| [Memory & Learning](docs/architecture/memory-and-learning.md) | Three-tier memory, agent learning scenarios |
| [Architecture Diagrams](docs/architecture/diagrams.md) | 8 Mermaid diagrams covering all system aspects |
| [Developer Guide](docs/guides/developer-guide.md) | Setup, daily workflow, testing, debugging |
| [Deployment Guide](docs/guides/deployment-guide.md) | Compose, containers, Kubernetes, monitoring |
| [Tool Catalog](docs/reference/tools.md) | All 10 registered tools with security properties |
| [Guardrails Reference](docs/reference/guardrails.md) | NeMo Guardrails config, Colang rules, custom actions |
| [Module Reference](docs/reference/modules.md) | Code-level module documentation |

See [docs/index.md](docs/index.md) for the complete navigation hub.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines on branching, code standards, testing, and the PR process.

## Adapting to Another Platform

The project is designed to be reusable. See the [Platform Adaptation Guide](docs/guides/adapting-to-another-platform.md) for a step-by-step walkthrough of what to change and what stays the same.

## Security

See [SECURITY.md](SECURITY.md) for the security model, invariants, and vulnerability reporting.

## License

[MIT](LICENSE)
