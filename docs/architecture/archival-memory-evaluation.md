# Archival Memory Isolation Evaluation

## Summary

This document evaluates the current shared archival memory model against a split architecture (shared read-only + per-user writable tiers) and records the decision to defer the split (Phase 3, decision 22 / plan D29).

**Decision**: Defer split architecture. Strengthen PII audit on the current shared model instead.

---

## Context

LiteMaaS Agent uses Letta's three-tier memory hierarchy. The relevant tier for this evaluation is **archival memory** — an unlimited vector-indexed store used for documentation chunks, resolution summaries, and accumulated platform knowledge. See [Memory and Learning](memory-and-learning.md) for the full memory architecture.

**Current state**: All users share a single archival memory store associated with the single shared Letta agent. The agent reads from and writes to this store autonomously based on what it learns during conversations.

**Isolation concern**: Agent-written patterns derived from user A's conversation (e.g., resolution summaries, FAQ entries) are visible to user B via `archival_memory_search`. If those patterns retain residual user-identifying information, cross-user PII leakage is possible.

---

## Evaluation Criteria

| Criterion | Current (shared) | Split (shared-RO + per-user-RW) |
|---|---|---|
| **Isolation** | Weak — agent-written patterns from user A are visible to user B via archival search | Strong — per-user writes only visible to that user; shared tier contains only admin-curated content |
| **Learning** | Shared learning benefits all users immediately | Per-user learning is isolated; shared learning requires explicit admin promotion workflow |
| **Letta API support** | Works with current `letta-client` 1.10.x API | Requires per-user agent instances (expensive) or custom passage metadata filtering (not yet in Letta SDK 1.10.x) |
| **Complexity** | Simple — single agent, single store | Significant — separate bootstrapping, query routing, promotion workflow, per-user agent lifecycle |
| **PII risk** | Higher — shared store can accumulate PII fragments from multiple user conversations | Lower — per-user PII stays in per-user stores; cross-user contamination requires admin promotion |
| **Operational cost** | Single agent, minimal resource overhead | Per-user agent instances: linear resource scaling with user count; large deployments become expensive |
| **Bootstrap** | Single bootstrap at startup | Per-user bootstrap on first conversation; requires lazy initialization or pre-provisioning |

---

## Investigation Findings

### 1. Letta SDK Passage-Level Metadata Filtering

Letta's `letta-client` 1.10.x does not expose a `metadata` parameter on `archival_memory_search` or the passages list endpoint. There is no supported way to filter archival search results by a `user_id` metadata tag at query time.

**Conclusion**: Implementing per-user isolation within a single shared agent's archival store — via query-time filtering — is not feasible with the current Letta SDK. A filter parameter would require either a custom Letta fork or waiting for upstream support.

### 2. Per-User Agent Instance Cost

The alternative is to provision a separate Letta agent per user. Each agent gets its own archival memory store, providing true isolation.

**Resource implications**:
- Each agent consumes: a PostgreSQL schema, pgvector index, agent configuration row, core memory blocks, and model context overhead at inference time.
- For the LiteMaaS use case (potentially thousands of users), this creates linear resource scaling that is cost-prohibitive for Phase 3.
- Agent provisioning latency (create + bootstrap + memory seed) adds 5–30 seconds to a new user's first conversation — unacceptable without pre-provisioning infrastructure.

**Conclusion**: Per-user agent instances are technically correct but operationally expensive at scale for Phase 3.

### 3. `archival_memory_search` Filtering Capability

The agent's `archival_memory_search` tool (Letta built-in) accepts a query string and returns semantically similar passages from the shared store. There is no caller-controlled filter to restrict results to passages written in a specific conversation or by a specific user.

**Implication**: Any content the agent writes to archival memory during conversation A is discoverable if conversation B triggers a related search. The defense relies entirely on:
1. PII pre-commit audit (invariant #5) blocking any PII from reaching archival memory.
2. The agent's persona instructions to anonymize before writing.
3. Output rails scanning any archival search results returned to the user.

### 4. Residual PII Risk of Current Model

Even with PII audit mitigations in place, residual risks exist:

| Risk | Likelihood | Mitigation |
|---|---|---|
| PII in archival memory due to regex gap | Low | Output rails provide second layer; proxy post-commit audit logs for alerting |
| Cross-user inference from aggregated patterns | Low | Patterns are intended to be anonymized and general; persona instructions enforce this |
| Memory poisoning via repeated interactions | Low–Medium | Memory write rate limiting (`RATE_LIMIT_MEMORY_WRITES_PER_HOUR`); admin review |
| Search revealing structural facts about other users' issues | Very Low | Patterns describe problem types, not user identities |

---

## Decision: Defer Split Architecture

**Decision recorded as architectural decision 22** (plan reference: D29).

**Rationale**:

1. **Letta SDK does not support per-passage metadata filtering** — the split would require per-user agent instances, which are operationally expensive.
2. **Phase 3 PII audit mitigations address the primary risk** — custom memory tool wrappers block PII before any write reaches archival memory (invariant #5 enforcement). This eliminates the main cross-user leakage vector.
3. **Shared learning is a feature, not a bug** — the agent learns general platform patterns (e.g., "budget exhaustion causes key failures") that benefit all users. Isolating this learning per-user would require an admin promotion workflow and would slow the agent's improvement cycle.
4. **The threat is probabilistic, not structural** — unlike recall memory (where cross-user isolation is structural via per-conversation scoping), archival cross-user risk depends on whether PII reaches the store. With pre-commit PII gating, this risk is low.

---

## Residual Risks (Accepted for Phase 3)

The following risks are accepted with the current shared model:

1. **PII regex coverage is not exhaustive** — novel PII formats not in `_PII_PATTERNS` could bypass the pre-commit check and reach archival storage. Mitigated by post-commit proxy audit (defense-in-depth logging).

2. **Custom memory wrapper dependency** — isolation enforcement depends on `upsert_from_function()` correctly overwriting Letta's built-in memory tools. If Letta changes tool upsert semantics, built-in (unaudited) tools could re-register and bypass the PII gate. Mitigated by an integration test that verifies the registered tool source contains the PII check.

3. **Aggregated pattern inference** — a sophisticated attacker could infer details about other users' issues by probing archival memory search. Patterns are intended to be fully anonymized, but subtle correlations may persist. Mitigated by persona instructions and output rails.

4. **Admin review dependency** — the "periodic memory audit" mitigation requires active admin participation. Without regular pruning, stale or borderline entries accumulate. This is an operational risk, not a code risk.

---

## Conditions for Reconsideration

The split architecture should be reconsidered if any of the following conditions arise:

1. **Multi-tenant production deployment with regulated data** — if users include entities subject to GDPR, HIPAA, or similar frameworks, the shared archival model may not satisfy data isolation requirements even with PII audit in place.

2. **Letta SDK adds passage metadata filtering** — if upstream Letta adds `metadata`-filtered search, per-user isolation within a single agent becomes feasible without per-user agent instances.

3. **PII audit bypass discovered in production** — if a real-world incident reveals that PII reached the shared archival store, the residual risk is no longer theoretical and the split must be implemented urgently.

4. **User count warrants per-user agent cost** — if the deployment reaches a scale where per-user agents are economically viable (e.g., dedicated enterprise deployments with predictable user counts), the operational cost argument weakens.

5. **Admin promotion workflow becomes available** — if the platform adds an admin UI for reviewing and promoting agent-learned patterns from per-user stores to the shared tier, the learning benefit can be preserved while improving isolation.

---

## References

- [Memory and Learning Architecture](memory-and-learning.md)
- [Security Architecture](security.md)
- [Security Policy — Invariant #5](../../SECURITY.md)
- Plan decision D29: Defer split architecture; strengthen PII audit instead
- Plan decision D32: Custom memory tool wrappers with pre-commit PII scan
