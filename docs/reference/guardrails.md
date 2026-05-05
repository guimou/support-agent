# Guardrails Reference

NeMo Guardrails is embedded as a **Python library** inside the proxy container. It is not an external service. It uses a configurable LLM for rail evaluation, typically a fast model served through LiteLLM.

## Architecture

```
User message
    |
    v
+----------------------------------+
| Input Rails                      |
|  1. Llama Guard safety check     |  <-- NeMo native integration
|  2. Cross-user isolation (intent)|  <-- privacy.co: semantic matching
|  3. Cross-user isolation (regex) |  <-- actions.py: regex_check_input_cross_user
|  4. LLM topic classification    |  <-- Uses AGENT_MODEL (parallel)
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
|  2. Llama Guard safety check     |  <-- NeMo native integration
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

Detects and blocks attempts to access other users' information using two complementary flows:

- **Intent-based flow** (`cross user access from intent`): NeMo's dialog model matches the user message against 16 `user ask about other users` examples semantically. If matched, calls `check_user_is_admin` — admin users are allowed through, non-admin users are blocked. Catches rephrased probing attempts.
- **Regex-based flow** (`check cross user access`): The `regex_check_input_cross_user` action runs deterministic pattern matching against 13 cross-user patterns (email addresses, "other user", "all users", user IDs, etc.). Admin bypass when `user_role == "admin"`.

Both flows are registered as input flows and run in sequence. The bot refusal is: "I can only access your own account information."

### `safety.co` — Content Safety

Bot response definitions for:
- **Unsafe output** — generic safety refusal
- **Jailbreak attempts** — refusal for prompt manipulation attempts

### `prompts.yml` — Evaluation Prompts

Templates for NeMo's built-in `self_check_input` and `self_check_output` flows:
- Input prompt: checks if the user message violates platform assistant policy
- Output prompt: checks if the agent response follows safety guidelines

## Custom Actions (`actions.py`)

Five actions registered with NeMo Guardrails:

### `check_user_context()`

Validates that `user_id` exists in the NeMo context. Prevents tool calls from executing without authenticated user context.

### `regex_check_output_pii()`

Regex-based PII detection in agent output:
- **Email addresses** — standard email pattern
- **Full API keys** — detects `sk-` prefixed keys (20+ chars)
- **UUIDs** — standard UUID-4 format (prevents leaking user/conversation IDs)
- **Phone numbers** — US format with optional country code
- **IPv4 addresses** — dotted decimal notation
- **Credit card numbers** — Visa, Mastercard, Discover, Amex patterns

### `regex_check_input_cross_user()`

Detects cross-user probing patterns in user input (13 regex patterns):
- "other/another user", "all users", "someone else"
- Email addresses in lookup context, user IDs
- "who else", "how many users", "all subscriptions"
- Colleague/manager references with sensitive data keywords

Admin bypass: returns safe when `user_role == "admin"`.

### `check_user_is_admin()`

Returns `True` if the user has admin role (from NeMo context `user_role`). Used by the intent-based cross-user isolation flow.

### `regex_check_input_injection()`

Detects common jailbreak/injection patterns in user input:
- "ignore ... instructions", "ignore ... rules"
- "pretend you are/you're/to be", "act as if/though", "you are now"
- "system prompt", "reveal your instructions", "what are your rules"
- "jailbreak", "DAN mode"

## Configuration (`config.yml`)

The NeMo configuration file defines:

- **Model settings**: OpenAI-compatible endpoint, model name, API key — all substituted from environment variables at initialization
- **Input rail flows**: `llama guard check input`, `cross user access from intent`, `check cross user access`
- **Output rail flows**: `check output safety` (regex PII pre-filter), `llama guard check output`
- **General instruction**: System prompt for the safety classifier

## Streaming Output Rails (Phase 2)

For SSE streaming, output rails evaluate in chunks:

- **Chunk size**: ~200 tokens (configurable via `OUTPUT_RAIL_CHUNK_SIZE`)
- **Overlap**: 50-token sliding window (configurable via `OUTPUT_RAIL_OVERLAP`)
- **Two layers**: Fast regex pre-filter per chunk + full NeMo evaluation per chunk
- **Retract**: Unsafe chunks replaced with `...removed...` placeholder
- **Safety notice**: Appended at stream end if any chunks were retracted

## Adversarial Test Suite

Phase 3 added a comprehensive adversarial test suite under `tests/guardrails/`:

| File | Category | Scenarios |
|---|---|---|
| `test_injection_attacks.py` | Prompt injection | 17 attacks (direct override, role-play, extraction, delimiter, indirect, encoded) |
| `test_jailbreak_attempts.py` | Jailbreaks | 10 attacks (DAN, hypothetical framing, authority impersonation, emotional) |
| `test_encoding_tricks.py` | Encoding tricks | 10 attacks (leetspeak, unicode, whitespace, markdown, multi-language) |
| `test_cross_user_probing.py` | Cross-user access | 16 probes + 6 legitimate queries + 5 admin bypass queries |
| `test_multi_turn_manipulation.py` | Multi-turn | 3 scenarios (trust building, context poisoning, output PII) |
| `test_indirect_probing.py` | Indirect probing | 7 must-block + 4 ambiguous probes with output fallback |

Run with: `uv run pytest tests/guardrails/ -v -m adversarial`

## Known Limitations

- **`_is_blocked()` heuristic**: Uses string prefix matching to detect refusals. May produce false positives on legitimate responses that happen to start with "I'm sorry" or "I cannot". Improvement planned for Phase 2E (carryover items — see [Project Plan](../development/PROJECT_PLAN.md)).
- **Encoding trick coverage**: Some encoding tricks (homoglyphs, zero-width characters) may not be caught by regex-based detection alone. The Llama Guard model provides a second layer for semantic intent.
- **Stateless multi-turn evaluation**: NeMo evaluates each message independently. Multi-turn attacks relying on context accumulation across messages are not caught by per-message input rails. Output rails provide a second line of defense.

## Adding a New Rule

1. Write Colang rules in `src/guardrails/config/` (add to existing `.co` file or create new one)
2. If needed, add custom actions in `actions.py`
3. Add test scenarios in `tests/guardrails/` with adversarial variants
4. Test edge cases: rephrasing, encoding tricks, multi-turn manipulation
5. Update this document

See [CONTRIBUTING.md](../../CONTRIBUTING.md) for the full checklist.
