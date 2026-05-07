"""Read-only tools for querying the LiteMaaS API.

These functions execute inside Letta's process, not the proxy.
They must be self-contained — no imports from src/ modules.
Functions that access user-scoped data inline their own user_id check
(see Implementation Notes: Tool Source Extraction Constraint).
list_models is an exception — it queries a public, unauthenticated endpoint.
"""


def list_models(search: str = "") -> str:
    """List available models on the platform, optionally filtered by search term.

    Args:
        search: Optional search term to filter models by name, provider, or description.

    Returns:
        A formatted summary of available models.
    """
    import os

    import httpx

    base_url = os.getenv("LITEMAAS_API_URL")
    if not base_url:
        raise RuntimeError("LITEMAAS_API_URL not set")
    params: dict[str, str | int] = {"limit": 50}
    if search:
        params["search"] = search

    # Public endpoint — no auth header required.
    response = httpx.get(f"{base_url}/api/v1/models", params=params, timeout=10.0)
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise RuntimeError(f"Models endpoint returned HTTP {exc.response.status_code}") from None
    data = response.json()

    models = data.get("data", [])
    if not models:
        return "No models found." + (f" (search: '{search}')" if search else "")

    lines = [f"Found {data.get('pagination', {}).get('total', len(models))} models:"]
    for m in models[:20]:  # Cap display at 20
        status = "active" if m.get("isActive") else "inactive"
        restricted = " [restricted]" if m.get("restrictedAccess") else ""
        name = m.get("name", "unnamed")
        provider = m.get("provider", "unknown")
        lines.append(f"- {name} ({provider}) — {status}{restricted}")
    if len(models) > 20:
        lines.append(f"... and {len(models) - 20} more")
    return "\n".join(lines)


def check_subscription(model_name: str) -> str:
    """Check the current user's subscription status for a specific model.

    Args:
        model_name: The name of the model to check (e.g., 'gpt-4o').

    Returns:
        Subscription details including status, quota usage, and reset date.
    """
    import os

    import httpx

    user_id = os.getenv("LETTA_USER_ID")
    if not user_id:
        raise RuntimeError("LETTA_USER_ID not set")
    base_url = os.getenv("LITEMAAS_API_URL")
    if not base_url:
        raise RuntimeError("LITEMAAS_API_URL not set")
    token = os.getenv("LITEMAAS_USER_TOKEN")
    if not token:
        raise RuntimeError("LITEMAAS_USER_TOKEN not set")

    response = httpx.get(
        f"{base_url}/api/v1/subscriptions",
        headers={"Authorization": f"Bearer {token}"},
        timeout=10.0,
    )
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise RuntimeError(
            f"Subscriptions endpoint returned HTTP {exc.response.status_code}"
        ) from None
    data = response.json()

    subs = data.get("data", [])
    # Filter by model name (case-insensitive partial match)
    matching = [s for s in subs if model_name.lower() in s.get("modelName", "").lower()]

    if not matching:
        return (
            f"No subscription found for model '{model_name}'. "
            "The user may need to subscribe to this model first."
        )

    lines = []
    for sub in matching:
        utilization = sub.get("utilizationPercent", {})
        lines.append(
            f"Model: {sub.get('modelName', 'unknown')} ({sub.get('provider', '')})\n"
            f"  Status: {sub.get('status', 'unknown')}\n"
            f"  Requests: {sub.get('usedRequests', 0)}/{sub.get('quotaRequests', 'unlimited')} "
            f"({utilization.get('requests', 0)}% used)\n"
            f"  Tokens: {sub.get('usedTokens', 0)}/{sub.get('quotaTokens', 'unlimited')} "
            f"({utilization.get('tokens', 0)}% used)\n"
            f"  Resets at: {sub.get('resetAt', 'never')}"
        )
    return "\n\n".join(lines)


def get_user_api_keys() -> str:
    """List the current user's API keys with status and budget info.

    Returns key names, prefixes, status, and budget usage — never full key values.

    Returns:
        Summary of the user's API keys.
    """
    import os

    import httpx

    user_id = os.getenv("LETTA_USER_ID")
    if not user_id:
        raise RuntimeError("LETTA_USER_ID not set")
    base_url = os.getenv("LITEMAAS_API_URL")
    if not base_url:
        raise RuntimeError("LITEMAAS_API_URL not set")
    token = os.getenv("LITEMAAS_USER_TOKEN")
    if not token:
        raise RuntimeError("LITEMAAS_USER_TOKEN not set")

    response = httpx.get(
        f"{base_url}/api/v1/api-keys",
        headers={"Authorization": f"Bearer {token}"},
        timeout=10.0,
    )
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise RuntimeError(f"API keys endpoint returned HTTP {exc.response.status_code}") from None
    data = response.json()

    keys = data.get("data", [])
    if not keys:
        return "No API keys found for this user."

    lines = [f"Found {len(keys)} API key(s):"]
    for k in keys:
        status = "active" if k.get("isActive") else "inactive"
        if k.get("revokedAt"):
            status = "revoked"
        budget = k.get("maxBudget")
        spend = k.get("currentSpend", 0)
        budget_part = f"${budget:.2f}" if budget is not None else "unlimited"
        budget_str = f"${spend:.2f}/{budget_part}"
        sync = k.get("syncStatus", "unknown")

        lines.append(
            f"- {k.get('name', 'unnamed')} ({k.get('prefix', k.get('keyPrefix', '???'))})\n"
            f"    Status: {status} | Budget: {budget_str} | Sync: {sync}\n"
            f"    Models: {', '.join(k.get('models', [])) or 'all'}\n"
            f"    Expires: {k.get('expiresAt', 'never')}"
        )
    return "\n".join(lines)


def get_usage_stats() -> str:
    """Get the current user's usage statistics for the last 30 days.

    Returns:
        Usage summary including request counts, tokens, cost, and per-model breakdown.
    """
    import os
    from datetime import UTC, datetime, timedelta

    import httpx

    user_id = os.getenv("LETTA_USER_ID")
    if not user_id:
        raise RuntimeError("LETTA_USER_ID not set")
    base_url = os.getenv("LITEMAAS_API_URL")
    if not base_url:
        raise RuntimeError("LITEMAAS_API_URL not set")
    token = os.getenv("LITEMAAS_USER_TOKEN")
    if not token:
        raise RuntimeError("LITEMAAS_USER_TOKEN not set")

    end_date = datetime.now(UTC).strftime("%Y-%m-%d")
    start_date = (datetime.now(UTC) - timedelta(days=30)).strftime("%Y-%m-%d")

    response = httpx.get(
        f"{base_url}/api/v1/usage/summary",
        params={"startDate": start_date, "endDate": end_date},
        headers={"Authorization": f"Bearer {token}"},
        timeout=10.0,
    )
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise RuntimeError(
            f"Usage summary endpoint returned HTTP {exc.response.status_code}"
        ) from None
    usage = response.json()

    totals = usage.get("totals", {})
    lines = [
        "Last 30 days usage:",
        f"  Requests: {totals.get('requests', 0):,}",
        f"  Tokens: {totals.get('tokens', 0):,}",
        f"  Cost: ${totals.get('cost', 0):.2f}",
        f"  Success rate: {totals.get('successRate', 0)}%",
    ]

    by_model = usage.get("byModel", [])
    if by_model:
        lines.append("\nPer-model breakdown:")
        for m in by_model[:10]:
            lines.append(
                f"  - {m.get('modelName', 'unknown')}: "
                f"{m.get('requests', 0):,} requests, ${m.get('cost', 0):.2f}"
            )

    return "\n".join(lines)
