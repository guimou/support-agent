# Memory and Learning

This document describes how the agent thinks, remembers, and improves over time using Letta's memory architecture.

## Letta Agent Runtime

The agent is powered by [Letta](https://github.com/letta-ai/letta) (formerly MemGPT), a stateful agent runtime that provides:

- A **reasoning loop** with inner/outer monologue (the agent thinks before responding)
- **Self-editing memory** across three tiers
- **Tool calling** — the agent decides which tools to call and when
- Built-in **PostgreSQL + pgvector** for persistence and vector search

## Memory Architecture

Letta provides a three-tier memory hierarchy inspired by operating system memory management:

### Core Memory (Always In-Context — SHARED)

The agent's "working knowledge" — always present in the LLM context window. The agent reads and writes this directly during conversations. **Core memory is shared across all conversations**, so it must never contain user-specific information.

Organized into blocks:

| Block | Purpose | Example Content |
|---|---|---|
| `persona` | Who the agent is, how it behaves | "I am the LiteMaaS assistant. I help users manage model subscriptions, diagnose access issues, and understand platform features." |
| `knowledge` | Accumulated domain knowledge | "Common issue: users confuse 'restricted' models with 'unavailable' models. Restricted means approval needed; unavailable means the provider is down." |
| `patterns` | Learned resolution patterns | "When users report 403 on a model, first check subscription status, then check if model was recently marked restricted." |

> **Important**: There is no `human` block in core memory. Per-user context lives in **recall memory**, scoped per conversation. This ensures strict user isolation — Alice's context is never visible to Bob.

The agent **autonomously updates** these blocks based on what it learns:

```python
core_memory_append("patterns",
  "Budget exhaustion is the #1 cause of sudden API key failures.
   Always check spend vs. max_budget before investigating other causes.")
```

### Recall Memory (Searchable History — PER-USER)

Full-text search over past conversations, **scoped by conversation** (per user). The agent can query: "Have I helped this user before? What was the issue?" This enables continuity across sessions while maintaining strict user isolation.

### Archival Memory (Long-Term Vector Store — SHARED)

Unlimited vector-indexed storage for:
- Documentation chunks (seeded at bootstrap)
- Past resolution summaries (written by the agent after successful interactions)
- FAQ entries (accumulated over time)
- Platform-specific knowledge (release notes, known issues)

The agent explicitly writes to archival memory when it learns something worth retaining:

```python
archival_memory_insert(
  "Resolution: Model 'gpt-4o' showing 'unhealthy' status was caused by
   LiteLLM cache staleness after provider endpoint rotation.")
```

## Agent Loop

```
User message
    |
    v
+----------------------------------+
|  1. Proxy: Input Guardrails      |  <-- NeMo Guardrails (embedded)
|     Block injection, validate    |      Uses GUARDRAILS_MODEL
|     topic                        |
+-----------------+----------------+
                  | (if allowed)
                  v
+----------------------------------+
|  2. Letta receives message       |
|  3. Agent reasons (inner         |  <-- Uses AGENT_MODEL
|     monologue):                  |
|     - What does the user need?   |
|     - Should I call a tool?      |
|     - Should I update memory?    |
|  4. Tool calls (if needed)       |
|  5. Memory updates (if needed)   |
|  6. Generate response            |
+-----------------+----------------+
                  |
                  v
+----------------------------------+
|  7. Proxy: Output Guardrails     |  <-- Chunked rail evaluation
|     Redact PII, check safety     |      (~200 tokens, 50 overlap)
+-----------------+----------------+
                  |
                  v
         Response to user
```

## Conversations API (Multi-User)

Letta's Conversations API enables per-user memory scoping:

```python
# Each user gets their own conversation with the agent
conversation = client.create_conversation(
    agent_id=agent.id,
    metadata={"user_id": "alice@example.com", "user_role": "user"}
)

# Inject user identity into conversation environment (trusted source for tools)
client.update_conversation_secrets(
    conversation_id=conversation.id,
    secrets={"LETTA_USER_ID": "alice@example.com", "LETTA_USER_ROLE": "user"},
)
```

The agent maintains:
- **Shared knowledge** — learned patterns, FAQ, documentation (core + archival memory). Must never contain user-identifying information.
- **Per-user context** — conversation history, user-specific preferences (recall memory, scoped by conversation). Strictly isolated.

## Learning Scenarios

### Scenario 1: Learning From a Resolution

```
Day 1:
  User: "My API key stopped working suddenly"
  Agent: (checks subscription -- active, checks key -- valid, checks spend -- 98%)
  Agent: "Your API key has nearly exhausted its budget."
  Agent: core_memory_append("patterns",
    "Budget exhaustion is a frequent cause of sudden key failures.")

Day 15:
  Different user: "My API key just stopped working"
  Agent: (reads patterns block -> sees budget exhaustion pattern)
  Agent: (checks spend immediately -- 100%)
  Agent: "Your API key has reached its budget limit."
  # Faster resolution -- the agent learned the pattern
```

### Scenario 2: Accumulating FAQ Knowledge

```
After 50 interactions about "restricted models":
  Agent: archival_memory_insert(
    "FAQ: Restricted vs Unavailable models.
     Restricted = requires admin approval. User must request subscription.
     Unavailable = provider is down or model removed.
     Diagnostic: if model appears in list -> restricted. If not -> unavailable.")

Future interaction:
  User: "I can see the model but can't use it"
  Agent: (searches archival memory -> finds FAQ entry)
  Agent: "That model is marked as restricted -- it requires admin approval."
```

### Scenario 3: Per-User Context Retention

```
Session 1 (Alice):
  Alice: "I'm working on the embeddings pipeline project"
  Agent: (stores in Alice's conversation recall memory -- invisible to others)

Session 2 (Alice, next week):
  Alice: "Which models should I use?"
  Agent: (searches recall memory -> finds embeddings pipeline context)
  Agent: "Since you're working on the embeddings pipeline, I'd recommend
          these embedding models..."
  # Agent remembered Alice's context via per-user recall memory
```
