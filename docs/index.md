# LiteMaaS Agent Assistant — Documentation

An AI-powered platform support assistant for LiteMaaS. This index organizes all documentation by what you need.

## Getting Started

- [Developer Guide](guides/developer-guide.md) — Environment setup, daily workflow, testing, debugging
- [Contributing](../CONTRIBUTING.md) — How to submit changes, code standards, PR process

## Understanding the System

- [Architecture Overview](architecture/overview.md) — What the agent is, two-container model, design goals
- [Architecture Diagrams](architecture/diagrams.md) — Visual system overview (Mermaid)
- [Memory and Learning](architecture/memory-and-learning.md) — How the agent thinks, remembers, and improves
- [Security Architecture](architecture/security.md) — Trust boundaries, invariants, threat mitigations
- [Decisions](architecture/decisions.md) — Architecture decision log and open questions

## Reference

- [Module Reference](reference/modules.md) — How the code is organized (understand the codebase without opening files)
- [Configuration](reference/configuration.md) — All environment variables and config files
- [Proxy API](reference/api.md) — Endpoints, request/response schemas, error codes
- [Tool Catalog](reference/tools.md) — All registered tools, what they do, how to add new ones
- [Guardrails](reference/guardrails.md) — NeMo Guardrails engine, Colang rules, custom actions

## External API References

- [Authentication](reference/authentication.md) — JWT validation, token claims, role system
- [LiteMaaS API](reference/litemaas-api.md) — Endpoints the agent's tools call
- [LiteLLM API](reference/litellm-api.md) — Health, model info, rate limits, API quirks

## Operations

- [Deployment Guide](guides/deployment-guide.md) — Compose, containers, Kubernetes, monitoring, backup

## Extending the System

- [Adapting to Another Platform](guides/adapting-to-another-platform.md) — What to change, step-by-step
- [Frontend Integration](guides/frontend-integration.md) — PatternFly chatbot widget, SSE streaming, LiteMaaS backend routes

## Security

- [Security Policy](../SECURITY.md) — Invariants, vulnerability reporting, responsible disclosure

## Project History

- [Project Plan](development/PROJECT_PLAN.md) — Four-phase roadmap
- [Phase 0 — Scaffolding](development/phase-0-scaffolding/PLAN.md)
- [Phase 1 — Foundation](development/phase-1-foundation/PLAN.md)
