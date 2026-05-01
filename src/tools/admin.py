"""Admin-only tools (role-gated, defense-in-depth).

All tools (standard + admin) are registered on a single shared agent.
Letta does not support per-conversation tool registration, so admin tools
use runtime role checks as the isolation mechanism.

SECURITY: Every admin tool MUST check LETTA_USER_ROLE == "admin" before
executing. The proxy injects this secret from the validated JWT before
each request. Even if the LLM attempts to call an admin tool for a
non-admin user, the tool will refuse to run.

Admin tools calling LiteMaaS endpoints use LITEMAAS_ADMIN_API_KEY.
Admin tools calling LiteLLM endpoints use LITELLM_API_KEY (master key).
Both keys are only injected into agent secrets when the request comes
from an admin user (see proxy/routes.py chat() — empty string for non-admin).
"""

def get_global_usage_stats() -> str:
    """Get system-wide usage statistics (admin only).

    Returns:
        Global usage summary including total spend, active users, and top models.
    """
    import os

    import httpx

    # Defense-in-depth: validate admin role
    role = os.getenv("LETTA_USER_ROLE")
    if role != "admin":
        raise PermissionError("This tool requires admin privileges.")

    base_url = os.getenv("LITEMAAS_API_URL")
    if not base_url:
        raise RuntimeError("LITEMAAS_API_URL not set")
    token = os.getenv("LITEMAAS_ADMIN_API_KEY")
    if not token:
        raise RuntimeError("LITEMAAS_ADMIN_API_KEY not set")

    # NOTE: This is a POST endpoint — an exception to the read-only rule.
    # The POST is required because the admin analytics endpoint accepts
    # complex filter arrays in the request body. No data is mutated.
    response = httpx.post(
        f"{base_url}/api/v1/admin/usage/analytics",
        headers={"Authorization": f"Bearer {token}"},
        json={},  # No filters — get global stats
        timeout=15.0,
    )
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise RuntimeError(
            f"Admin analytics endpoint returned HTTP {exc.response.status_code}"
        ) from None
    data = response.json()

    totals = data.get("totals", {})
    lines = [
        "Global Usage Statistics:",
        f"  Total requests: {totals.get('requests', 0):,}",
        f"  Total tokens: {totals.get('tokens', 0):,}",
        f"  Total cost: ${totals.get('cost', 0):.2f}",
        f"  Success rate: {totals.get('successRate', 0)}%",
    ]

    models = data.get("modelBreakdown", [])
    if models:
        lines.append("\nTop models:")
        for m in models[:5]:
            lines.append(
                f"  - {m.get('modelName', 'unknown')}: "
                f"{m.get('requests', 0):,} requests, "
                f"${m.get('cost', 0):.2f}, "
                f"{m.get('uniqueUsers', 0)} users"
            )

    return "\n".join(lines)


def lookup_user_subscriptions(target_user_id: str) -> str:
    """Look up any user's subscriptions (admin only).

    Args:
        target_user_id: The user ID to look up subscriptions for.

    Returns:
        All subscriptions for the specified user.
    """
    import os
    import re

    import httpx

    # Defense-in-depth: validate admin role
    role = os.getenv("LETTA_USER_ROLE")
    if role != "admin":
        raise PermissionError("This tool requires admin privileges.")

    if not re.fullmatch(
        r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}",
        target_user_id,
    ):
        raise ValueError(f"Invalid user ID format: {target_user_id!r}")

    base_url = os.getenv("LITEMAAS_API_URL")
    if not base_url:
        raise RuntimeError("LITEMAAS_API_URL not set")
    token = os.getenv("LITEMAAS_ADMIN_API_KEY")
    if not token:
        raise RuntimeError("LITEMAAS_ADMIN_API_KEY not set")

    response = httpx.get(
        f"{base_url}/api/v1/admin/users/{target_user_id}/subscriptions",
        headers={"Authorization": f"Bearer {token}"},
        timeout=10.0,
    )
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise RuntimeError(
            f"Admin subscriptions endpoint returned HTTP {exc.response.status_code}"
        ) from None
    data = response.json()

    subs = data.get("data", [])
    if not subs:
        return f"No subscriptions found for user '{target_user_id}'."

    lines = [f"Subscriptions for user '{target_user_id}':"]
    for sub in subs:
        lines.append(
            f"- {sub.get('modelName', 'unknown')} ({sub.get('provider', '')}): "
            f"{sub.get('status', 'unknown')}"
        )
    return "\n".join(lines)
