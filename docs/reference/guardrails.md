# Guardrails Reference

NeMo Guardrails is embedded as a **Python library** inside the proxy container. It is not an external service. It uses a configurable LLM for rail evaluation, typically a fast model served through LiteLLM.

## Architecture

```
User message
    |
    v
+----------------------------------+
| Input Rails                      |
|  1. Regex injection check        |  <-- actions.py: regex_check_input_injection
|  2. LLM topic classification    |  <-- Uses GUARDRAILS_MODEL
|  Result: allow or block          |
+----------------------------------+
    |
    v  (if allowed)
    ... Letta agent processes ...
    |
    v
+----------------------------------+
| Output Rails                     |
|  1. Regex PII check             |  <-- actions.py: regex_check_output_pii
|  2. LLM safety check            |  <-- Uses GUARDRAILS_MODEL
|  Result: allow or block          |
+----------------------------------+
```

## Engine (`rails.py`)

The `GuardrailsEngine` class wraps NeMo's `LLMRails`:

- **Initialization**: Loads config from `src/guardrails/config/`, substitutes environment variables (`GUARDRAILS_MODEL`, `GUARDRAILS_LLM_API_BASE`, `GUARDRAILS_LLM_API_KEY`) into the model config
- **`check_input(message, context)`**: Runs input rails, returns `RailResult(blocked, response)`
- **`check_output(message, context)`**: Runs output rails, returns `RailResult(blocked, response)`
- **Fail-closed**: Any exception during evaluation results in `blocked=True`
- **`_is_blocked()` heuristic**: Detects blocking by checking if the response starts with known refusal phrases ("I'm sorry", "I cannot", "I can't"). Known limitation — see [Known Limitations](#known-limitations)

## Colang Rules

### `topics.co` — Topic Control

Defines what the agent should and shouldn't talk about:

- **`user ask about litemaas`** — 15 example utterances covering models, subscriptions, API keys, usage, health, troubleshooting
- **`user ask about unrelated topic`** — 6 example utterances for off-topic requests
- **`bot refuse unrelated topic`** — polite refusal redirecting to platform topics

### `privacy.co` — Cross-User Isolation

Placeholder for Phase 3A. Will detect attempts to access other users' information:
- "Show me what other users are doing"
- "What models does alice@example.com use?"

### `safety.co` — Content Safety

Bot response definitions for:
- **Unsafe output** — generic safety refusal
- **Jailbreak attempts** — refusal for prompt manipulation attempts

### `prompts.yml` — Evaluation Prompts

Templates for NeMo's built-in `self_check_input` and `self_check_output` flows:
- Input prompt: checks if the user message violates platform assistant policy
- Output prompt: checks if the agent response follows safety guidelines

## Custom Actions (`actions.py`)

Three actions registered with NeMo Guardrails:

### `check_user_context()`

Validates that `user_id` exists in the NeMo context. Prevents tool calls from executing without authenticated user context.

### `regex_check_output_pii()`

Regex-based PII detection in agent output:
- **Email addresses** — standard email pattern
- **Full API keys** — detects `sk-` prefixed keys that are too long to be prefixes
- **UUIDs** — standard UUID-4 format

### `regex_check_input_injection()`

Detects common jailbreak/injection patterns in user input:
- "ignore ... instructions", "ignore ... rules"
- "pretend you are/you're/to be", "act as if/though", "you are now"
- "system prompt", "reveal your instructions", "what are your rules"
- "jailbreak", "DAN mode"

## Configuration (`config.yml`)

The NeMo configuration file defines:

- **Model settings**: OpenAI-compatible endpoint, model name, API key — all substituted from environment variables at initialization
- **Input rail flow**: `self check input` — evaluates every user message
- **Output rail flow**: `self check output` — evaluates every agent response
- **General instruction**: System prompt for the safety classifier

## Streaming Output Rails (Phase 2)

For SSE streaming, output rails evaluate in chunks:

- **Chunk size**: ~200 tokens (configurable via `OUTPUT_RAIL_CHUNK_SIZE`)
- **Overlap**: 50-token sliding window (configurable via `OUTPUT_RAIL_OVERLAP`)
- **Two layers**: Fast regex pre-filter per chunk + full NeMo evaluation per chunk
- **Retract**: Unsafe chunks replaced with `...removed...` placeholder
- **Safety notice**: Appended at stream end if any chunks were retracted

## Known Limitations

- **`_is_blocked()` heuristic**: Uses string prefix matching to detect refusals. May produce false positives on legitimate responses that happen to start with "I'm sorry" or "I cannot". Improvement planned for Phase 2E (carryover items — see [Project Plan](../development/PROJECT_PLAN.md)).
- **`privacy.co` is placeholder**: Cross-user data isolation rules are planned for Phase 3A.
- **No streaming evaluation yet**: Output rails currently evaluate the full response. Chunked streaming evaluation is Phase 2A.

## Adding a New Rule

1. Write Colang rules in `src/guardrails/config/` (add to existing `.co` file or create new one)
2. If needed, add custom actions in `actions.py`
3. Add test scenarios in `tests/guardrails/` with adversarial variants
4. Test edge cases: rephrasing, encoding tricks, multi-turn manipulation
5. Update this document

See [CONTRIBUTING.md](../../CONTRIBUTING.md) for the full checklist.
