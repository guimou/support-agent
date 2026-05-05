# Phase 3 Plan Review

## Verdict

This revision is materially better. The earlier concerns about pre-commit memory auditing, HPA, missing chart values files, benchmark/token wording, indirect-probe assertions, the tool self-containment model, bootstrap registration style, and Phase 2E carryover wording have mostly been addressed.

The plan is now very close, but I still see three issues worth fixing before coding begins.

## Remaining Findings

### 1. Critical — Step 3A.3 now conflicts with the project's non-negotiable read-only tool invariant

- Step `3A.3` introduces `src/tools/memory.py` as a new custom tool module whose functions call `httpx.post(...)` to mutate Letta memory.
- That conflicts with the project's existing invariant in `SECURITY.md` and `docs/architecture/security.md`: tools are read-only, with the one documented exception of `get_global_usage_stats()`.
- The plan partially acknowledges this by adding updates to `docs/reference/tools.md` and `docs/architecture/security.md` to describe memory wrappers as the only other non-GET tools, but that is effectively redefining invariant #1 rather than implementing within it.
- The current `tests/unit/test_security_invariants.py` also assumes only the existing standard/admin tool sets are subject to the read-only invariant, so the plan would need a deeper security-model decision here, not just doc edits.
- Recommendation: either keep memory mutation outside the custom tool layer, or explicitly revisit the project's security invariants before proceeding. As written, this is still a core architectural conflict.

### 2. High — The new `check_user_is_admin` action is still not fully wired in the implementation snippets

- Step `3A.1` now correctly adds admin-aware logic to the semantic flow:
  - `define flow cross user access from intent`
  - `user ask about other users`
  - `$is_admin = execute check_user_is_admin`
  - `if not $is_admin ...`
- But the plan only shows `_check_user_is_admin_impl(...)`; it does not show the NeMo action wrapper function that Colang would actually execute.
- The `rails.py` registration snippet also still imports and registers only `regex_check_input_cross_user`, not `check_user_is_admin`.
- Recommendation: add the full `check_user_is_admin` action wrapper pattern in `src/guardrails/actions.py` and include its import/registration explicitly in the `src/guardrails/rails.py` snippet.

### 3. Medium — One implementation note still contradicts the now-correct admin-aware flow

- In `## Implementation Notes`, the section `Cross-User Regex vs LLM Classification` still says the intent-based flow "blocks immediately" when matched.
- That no longer matches the corrected Step `3A.1`, where the intent flow first checks `check_user_is_admin` and only blocks non-admin users.
- Recommendation: update that note so it describes the same role-aware behavior as the main implementation steps.

## Minor Inconsistencies

- The admin test example in `tests/guardrails/test_cross_user_probing.py` still constructs `AuthenticatedUser(..., ["admin"], False)`. The role tuple is admin, but the final `is_admin` flag should probably be `True` to stay semantically aligned with the real auth model.

## Overall Assessment

- The updated plan is much stronger than the previous version.
- I would consider it one short revision away from implementation-ready.
- The only remaining major question is whether custom memory-write wrappers are actually acceptable under the project's security invariants. If that point is resolved, the rest looks close.
