"""Security invariant tests — must ALL pass for any release.

These tests verify the non-negotiable security invariants:
1. Tools are read-only (GET only, one documented POST exception)
2. user_id from JWT, never from LLM (no user_id function parameter)
3. Admin tools role-gated (check LETTA_USER_ROLE)
4. Scoped tokens (standard=LITELLM_USER_API_KEY, admin=LITEMAAS_ADMIN_API_KEY)
5. Memory writes PII-audited (pre-commit enforcement via custom wrappers)
6. Guardrails fail closed (errors -> refuse)
"""

from __future__ import annotations

import inspect

import pytest

from tools.admin import get_global_usage_stats, lookup_user_subscriptions
from tools.litellm import check_model_health, check_rate_limits, get_model_info
from tools.litemaas import (
    check_subscription,
    get_usage_stats,
    get_user_api_keys,
    list_models,
)
from tools.memory import archival_memory_insert, core_memory_append, core_memory_replace

STANDARD_TOOLS = [
    list_models,
    check_subscription,
    get_user_api_keys,
    get_usage_stats,
    check_model_health,
    get_model_info,
    check_rate_limits,
]
ADMIN_TOOLS = [get_global_usage_stats, lookup_user_subscriptions]
ALL_TOOLS = STANDARD_TOOLS + ADMIN_TOOLS
MEMORY_TOOLS = [core_memory_append, core_memory_replace, archival_memory_insert]


class TestInvariant1ReadOnly:
    """Invariant 1: Tools are read-only (GET only)."""

    @pytest.mark.parametrize("func", ALL_TOOLS, ids=lambda f: f.__name__)
    def test_no_mutation_methods(self, func: object) -> None:
        source = inspect.getsource(func)  # type: ignore[arg-type]
        for method in ["httpx.put", "httpx.patch", "httpx.delete"]:
            assert method not in source, f"{func.__name__} uses {method}"  # type: ignore[union-attr]
        if func.__name__ != "get_global_usage_stats":  # type: ignore[union-attr]
            assert "httpx.post" not in source, f"{func.__name__} uses httpx.post"  # type: ignore[union-attr]

    @pytest.mark.parametrize("func", MEMORY_TOOLS, ids=lambda f: f.__name__)
    def test_memory_tools_use_post_with_pii_gate(self, func: object) -> None:
        """Memory wrappers may POST (invariant #5 enforcement) but must PII-gate."""
        source = inspect.getsource(func)  # type: ignore[arg-type]
        assert "httpx.post" in source
        assert "_PII_PATTERNS" in source
        assert "BLOCKED" in source
        for method in ["httpx.put", "httpx.patch", "httpx.delete"]:
            assert method not in source, f"{func.__name__} uses {method}"  # type: ignore[union-attr]


class TestInvariant2UserIdFromJwt:
    """Invariant 2: user_id comes from JWT via env var, never from function args."""

    @pytest.mark.parametrize("func", ALL_TOOLS, ids=lambda f: f.__name__)
    def test_no_user_id_parameter(self, func: object) -> None:
        sig = inspect.signature(func)  # type: ignore[arg-type]
        param_names = [p.lower() for p in sig.parameters]
        assert "user_id" not in param_names
        assert "userid" not in param_names

    @pytest.mark.parametrize(
        "func",
        [check_subscription, get_user_api_keys, get_usage_stats, check_rate_limits],
        ids=lambda f: f.__name__,
    )
    def test_reads_user_id_from_env(self, func: object) -> None:
        source = inspect.getsource(func)  # type: ignore[arg-type]
        assert "LETTA_USER_ID" in source


class TestInvariant3AdminRoleGated:
    """Invariant 3: Admin tools validate role before executing."""

    @pytest.mark.parametrize("func", ADMIN_TOOLS, ids=lambda f: f.__name__)
    def test_admin_tool_checks_role(self, func: object) -> None:
        source = inspect.getsource(func)  # type: ignore[arg-type]
        assert "LETTA_USER_ROLE" in source
        assert "admin" in source.lower()


class TestInvariant4ScopedTokens:
    """Invariant 4: Standard tools use scoped key, admin tools use master key."""

    @pytest.mark.parametrize(
        "func",
        [check_subscription, get_user_api_keys, get_usage_stats, check_rate_limits],
        ids=lambda f: f.__name__,
    )
    def test_standard_tool_uses_scoped_key(self, func: object) -> None:
        source = inspect.getsource(func)  # type: ignore[arg-type]
        assert "LITELLM_USER_API_KEY" in source

    @pytest.mark.parametrize("func", ADMIN_TOOLS, ids=lambda f: f.__name__)
    def test_admin_tool_uses_admin_key(self, func: object) -> None:
        source = inspect.getsource(func)  # type: ignore[arg-type]
        assert 'os.getenv("LITEMAAS_ADMIN_API_KEY")' in source


class TestInvariant6GuardrailsFailClosed:
    """Invariant 6: Guardrails fail closed — errors result in refusal.

    Uses source inspection to avoid NeMo import dependency.
    """

    def _read_rails_source(self) -> str:
        source_path = inspect.getfile(inspect.getmodule(type(self)) or type(self))
        import pathlib

        rails_path = (
            pathlib.Path(source_path).parent.parent.parent / "src" / "guardrails" / "rails.py"
        )
        return rails_path.read_text()

    def test_check_input_fails_closed(self) -> None:
        source = self._read_rails_source()
        assert "except Exception" in source
        assert "blocked=True" in source

    def test_check_output_fails_closed(self) -> None:
        source = self._read_rails_source()
        assert "_OUTPUT_REFUSAL" in source
        assert "blocked=True" in source

    def test_pii_action_fails_closed_on_none_context(self) -> None:
        from guardrails.actions import _regex_check_output_pii_impl

        assert _regex_check_output_pii_impl(None) is False

    def test_topic_classifier_fails_open_in_source(self) -> None:
        source = self._read_rails_source()
        assert "failing open" in source
        assert 'status="on_topic"' in source


class TestInvariant5MemoryWritePiiAudited:
    """Invariant 5: Memory writes are PII-audited before commit."""

    def test_memory_tools_contain_pii_check(self) -> None:
        for func in MEMORY_TOOLS:
            source = inspect.getsource(func)
            assert "_PII_PATTERNS" in source, f"{func.__name__} missing _PII_PATTERNS"
            assert "BLOCKED" in source, f"{func.__name__} missing BLOCKED response"
            assert "from guardrails" not in source, (
                f"{func.__name__} imports from guardrails (must be self-contained)"
            )
