# Architecture Diagrams

Visual representations of the system architecture. All diagrams use Mermaid format for easy maintenance and render natively on GitHub.

## 1. System Context

How the agent fits into the LiteMaaS ecosystem. The agent stack is a standalone deployment that connects to existing LiteMaaS services.

```mermaid
graph TB
    User([User / Browser])

    subgraph LiteMaaS["LiteMaaS Stack"]
        Frontend[Frontend<br/>React + PatternFly]
        Backend[Backend<br/>Fastify API]
    end

    subgraph Agent["Agent Stack"]
        Proxy[Proxy<br/>FastAPI :8400]
        Letta[Letta Runtime<br/>:8283]
    end

    LiteLLM[LiteLLM Proxy<br/>Model Gateway]
    LLMs([LLM Providers<br/>OpenAI, Anthropic, ...])

    User -->|Browser| Frontend
    Frontend -->|SSE| Backend
    Backend -->|JWT pass-through| Proxy
    Proxy -->|REST| Letta
    Letta -->|Tool calls| Backend
    Letta -->|Tool calls| LiteLLM
    Proxy -->|Guardrails eval| LiteLLM
    Letta -->|Agent reasoning| LiteLLM
    LiteLLM --> LLMs
```

## 2. Container Diagram

The two containers, their responsibilities, ports, and communication.

```mermaid
graph LR
    subgraph Proxy["Container 1: Proxy (port 8400)"]
        FastAPI[FastAPI Server]
        Auth[JWT Auth]
        GuardrailsEngine[NeMo Guardrails<br/>embedded library]
        Routes[/v1/chat<br/>/v1/health]
    end

    subgraph LettaContainer["Container 2: Letta (port 8283)"]
        AgentLoop[Agent Loop<br/>inner monologue]
        Memory[Memory<br/>Core + Recall + Archival]
        Tools[Registered Tools<br/>10 read-only functions]
        PG[(PostgreSQL<br/>+ pgvector)]
    end

    Volume[(letta-data<br/>volume)]

    FastAPI --> Auth
    FastAPI --> GuardrailsEngine
    FastAPI --> Routes
    Routes -->|REST API| AgentLoop
    AgentLoop --> Memory
    AgentLoop --> Tools
    Memory --> PG
    PG --> Volume
```

## 3. Request Flow

The full lifecycle of a chat message, from user to response.

```mermaid
sequenceDiagram
    participant User
    participant LiteMaaS as LiteMaaS Backend
    participant Proxy as Agent Proxy
    participant NeMo as NeMo Guardrails
    participant Letta as Letta Runtime
    participant API as External APIs

    User->>LiteMaaS: POST /api/v1/assistant/chat
    LiteMaaS->>Proxy: POST /v1/chat (JWT forwarded)

    Proxy->>Proxy: Validate JWT, extract user context

    Proxy->>NeMo: Input rails check
    NeMo-->>Proxy: allow / block

    alt Blocked by input rails
        Proxy-->>LiteMaaS: {blocked: true, message: "..."}
    else Allowed
        Proxy->>Letta: Inject secrets (user_id, role, keys)
        Proxy->>Letta: Send message to conversation

        Letta->>Letta: Inner monologue (reasoning)

        opt Tool call needed
            Letta->>API: GET (read-only, scoped token)
            API-->>Letta: Response data
        end

        opt Memory update
            Letta->>Letta: core_memory_append / archival_memory_insert
        end

        Letta-->>Proxy: Agent response

        Proxy->>NeMo: Output rails check
        NeMo-->>Proxy: allow / block / sanitize

        Proxy-->>LiteMaaS: {message: "...", conversation_id: "..."}
    end

    LiteMaaS-->>User: Response
```

## 4. Agent Bootstrap Sequence

What happens when the proxy container starts up.

```mermaid
sequenceDiagram
    participant Proxy as Proxy Server
    participant Letta as Letta Runtime
    participant NeMo as NeMo Guardrails

    Note over Proxy: Container starts

    Proxy->>Letta: Wait for health check
    Letta-->>Proxy: Healthy

    Proxy->>Letta: List agents (find by name)

    alt Agent exists
        Proxy->>Letta: Reuse existing agent
    else Agent not found
        Proxy->>Letta: Create agent with persona blocks
    end

    Proxy->>Letta: Upsert all 10 tools (idempotent)
    Proxy->>Letta: Check archival seed version

    opt Seeds not yet inserted
        Proxy->>Letta: Insert archival memory seeds
    end

    Proxy->>NeMo: Initialize guardrails engine
    NeMo-->>Proxy: Ready (or fail-closed)

    Note over Proxy: Ready to accept requests
```

## 5. Security Trust Boundaries

How security invariants are enforced across system zones.

```mermaid
graph TB
    subgraph Untrusted_In["UNTRUSTED: User Input"]
        UserMsg[User Message<br/>potential injection / probing]
    end

    subgraph InputRails["INPUT RAILS"]
        RegexIn[Regex Injection Check]
        LLMClassify[LLM Topic Classification]
    end

    subgraph LLMZone["LLM-CONTROLLED ZONE (not a security boundary)"]
        Reasoning[Agent Reasoning<br/>inner monologue]
        ToolSelect[Tool Selection]
        MemoryOps[Memory Operations]
    end

    subgraph HardEnforce["HARD ENFORCEMENT (deterministic code)"]
        UserIdEnv["user_id from os.getenv()<br/>NOT from LLM args"]
        RoleCheck["LETTA_USER_ROLE == admin<br/>runtime validation"]
        GetOnly["httpx.get() only<br/>no mutation methods"]
        ScopedTokens["User token != Admin token"]
        RateLimit["Per-user rate limiting"]
    end

    subgraph OutputRails["OUTPUT RAILS"]
        RegexPII[Regex PII Detection]
        LLMSafety[LLM Safety Check]
    end

    subgraph Untrusted_Out["UNTRUSTED: Agent Output"]
        Response[Agent Response<br/>potential PII / hallucination]
    end

    UserMsg --> RegexIn --> LLMClassify
    LLMClassify --> Reasoning
    Reasoning --> ToolSelect --> HardEnforce
    ToolSelect --> MemoryOps
    HardEnforce --> RegexPII --> LLMSafety
    LLMSafety --> Response
```

## 6. Memory Architecture

Three-tier memory with scope and access patterns.

```mermaid
graph TB
    subgraph Core["Core Memory (in-context, SHARED)"]
        Persona[persona block<br/>agent identity + rules]
        Knowledge[knowledge block<br/>domain knowledge]
        Patterns[patterns block<br/>learned resolutions]
    end

    subgraph Recall["Recall Memory (searchable, PER-USER)"]
        Conv1[Alice's conversations]
        Conv2[Bob's conversations]
        Conv3[Carol's conversations]
    end

    subgraph Archival["Archival Memory (vector store, SHARED)"]
        Seeds[Seeded FAQ entries]
        Learned[Agent-learned patterns]
        Docs[Documentation chunks]
    end

    Agent((Agent)) -->|reads always| Core
    Agent -->|writes autonomously| Core
    Agent -->|searches per-conversation| Recall
    Agent -->|vector search| Archival
    Agent -->|writes when learning| Archival

    style Core fill:#e8f5e9
    style Recall fill:#e3f2fd
    style Archival fill:#fff3e0
```

> **Isolation**: Core and Archival memory are shared — they must never contain user-identifying information. Recall memory is strictly per-conversation (per-user).

## 7. Guardrails Pipeline

Input and output rail evaluation flows.

```mermaid
flowchart TD
    subgraph Input["Input Rails"]
        A[User Message] --> B{Regex: Injection<br/>patterns?}
        B -->|Match| C[BLOCK: Jailbreak refusal]
        B -->|No match| D{LLM: On-topic?}
        D -->|Off-topic| E[BLOCK: Topic refusal]
        D -->|On-topic| F[ALLOW: Forward to agent]
        D -->|Uncertain| G[BLOCK: Fail closed]
    end

    subgraph Output["Output Rails"]
        H[Agent Response] --> I{Regex: PII<br/>detected?}
        I -->|Email/Key/UUID| J[BLOCK: PII refusal]
        I -->|Clean| K{LLM: Safe<br/>content?}
        K -->|Unsafe| L[BLOCK: Safety refusal]
        K -->|Safe| M[ALLOW: Return to user]
        K -->|Uncertain| N[BLOCK: Fail closed]
    end
```

## 8. Tool Execution Model

How tool secrets are injected and tools execute inside Letta.

```mermaid
sequenceDiagram
    participant Proxy
    participant Letta
    participant Tool as Tool Function<br/>(inside Letta)
    participant ExtAPI as External API

    Note over Proxy: User request arrives

    Proxy->>Letta: Update conversation secrets<br/>LETTA_USER_ID, LETTA_USER_ROLE,<br/>LITELLM_USER_API_KEY, ...

    Proxy->>Letta: Send message

    Letta->>Letta: Agent reasons:<br/>"I should check the subscription"

    Letta->>Tool: Execute check_subscription("gpt-4o")

    Note over Tool: Tool reads from environment:<br/>user_id = os.getenv("LETTA_USER_ID")<br/>token = os.getenv("LITELLM_USER_API_KEY")<br/>url = os.getenv("LITEMAAS_API_URL")

    Tool->>ExtAPI: GET /api/v1/subscriptions<br/>Authorization: Bearer {token}
    ExtAPI-->>Tool: Subscription data

    Tool-->>Letta: Formatted result string

    Letta->>Letta: Agent incorporates result,<br/>generates response

    Letta-->>Proxy: Response with tool results
```
