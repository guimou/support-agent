# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/), and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.1.0] - 2026-04-30

### Added

- **Phase 1 — Foundation**
  - FastAPI proxy server with JWT authentication (HS256)
  - Letta agent bootstrap with idempotent tool registration and archival memory seeding
  - 10 read-only platform tools: 7 standard (LiteMaaS + LiteLLM) + 2 admin (role-gated) + 1 placeholder
  - NeMo Guardrails integration with topic control, safety, and injection detection
  - Custom guardrail actions for PII detection and jailbreak pattern matching
  - Agent persona with core memory blocks (persona, knowledge, patterns)
  - Conversation ownership validation and per-user isolation
  - Security invariant test suite (`test_security_invariants.py`)
  - Unit tests for all modules (~2,200 lines of test coverage)

- **Phase 0 — Scaffolding**
  - Two-container architecture (FastAPI proxy + Letta runtime)
  - Container build with multi-stage Containerfile
  - Compose setup with health checks and live-reload for development
  - Python project configuration (pyproject.toml, ruff, mypy)
  - CI pipeline (lint, type check, unit tests)
  - Architecture documentation (system design + integration reference)

[Unreleased]: https://github.com/your-org/litemaas-agent/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/your-org/litemaas-agent/releases/tag/v0.1.0
