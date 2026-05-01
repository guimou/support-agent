# Phase 2 Plan Review Findings

Reviewed file: `docs/development/phase-2-integration/PLAN.md`

## Findings

### High

1. **Unsafe content is emitted before retraction**
   - The proposed stream flow sends a `chunk` event before `retract_chunk` when output rails block a chunk.
   - This leaks unsafe text to the client/UI before removal and conflicts with the output-rails security goal.
   - Reference in plan:
     - `if result.blocked: yield chunk ... yield retract_chunk ...`

2. **Overlap context sequencing is inconsistent**
   - `TokenBuffer` updates `overlap_context` during flush, and then that same value is passed to evaluate the emitted chunk.
   - This uses current-chunk tail as overlap instead of previous-chunk tail, weakening intended continuity semantics.
   - Reference in plan:
     - `TokenBuffer._flush()` updates `_overlap_context`
     - `check_output_chunk(chunk_text, ..., buffer.overlap_context)`

### Medium

3. **Spike error-handling outcomes are not fully carried into route design**
   - The spike section calls out handling `LettaErrorMessage`, but route pseudo-code only processes `assistant_message` and generic exceptions.
   - Risk: silent stream failures or incorrect `done` semantics.

4. **Documentation update scope is incomplete for new SSE payload contract**
   - Plan introduces `done` payload including `conversation_id`, but the file manifest does not include updates to canonical docs that currently describe a different shape.
   - At minimum, update:
     - `docs/reference/api.md`
     - `docs/guides/frontend-integration.md`
   - Otherwise backend/frontend teams may implement against stale contract details.

5. **Blocked-input behavior for `/v1/chat/stream` is underspecified**
   - The plan says blocked input should return a blocked response and not stream, but it does not define exact status code/content type/body contract.
   - Clients need deterministic behavior (JSON response vs SSE response with immediate terminal event).

## Open Questions

1. Should security take precedence over retract transparency (i.e., never emit blocked chunk content)?
2. For blocked input on stream route, should behavior mirror `/v1/chat` JSON or still use SSE format?
3. On `error_message` or error stop reasons from Letta, should the proxy emit `done`, `error`, both, or terminate without `done`?

## Recommended Plan Updates

1. Revise stream algorithm so blocked chunks are **not** emitted as normal text before retraction.
2. Adjust buffer/evaluator API so overlap passed for chunk N is derived from chunk N-1.
3. Define explicit SSE error event and terminal semantics (`error`, `done`, retryability).
4. Add explicit blocked-input response contract for `/v1/chat/stream`.
5. Add `docs/reference/api.md` and `docs/guides/frontend-integration.md` to the file manifest updates.
