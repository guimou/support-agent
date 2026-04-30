"""Read-only tools for querying the LiteLLM API.

These functions execute inside Letta's process, not the proxy.
They must be self-contained — no imports from src/ modules.
LiteLLM quirks: auth via x-litellm-api-key header, sentinel 2147483647 = unlimited.
"""

_UNLIMITED_SENTINEL = 2147483647


def check_model_health() -> str:
    """Check the overall health of the LiteLLM proxy.

    Returns:
        Health status of the LiteLLM service.
    """
    import os

    import httpx

    base_url = os.getenv("LITELLM_API_URL")
    if not base_url:
        raise RuntimeError("LITELLM_API_URL not set")
    api_key = os.getenv("LITELLM_USER_API_KEY")
    if not api_key:
        raise RuntimeError("LITELLM_USER_API_KEY not set")

    response = httpx.get(
        f"{base_url}/health/liveness",
        headers={"x-litellm-api-key": api_key},
        timeout=10.0,
    )
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise RuntimeError(
            f"LiteLLM health check returned HTTP {exc.response.status_code}"
        ) from None

    # Handle both JSON and plain text responses
    content_type = response.headers.get("content-type", "")
    if "application/json" in content_type:
        data = response.json()
        status = data.get("status", "unknown")
        version = data.get("litellm_version", "unknown")
        return f"LiteLLM status: {status} (version: {version})"
    else:
        text = response.text.strip()
        if "alive" in text.lower():
            return "LiteLLM status: healthy (alive)"
        return f"LiteLLM response: {text}"


def get_model_info(model_name: str = "") -> str:
    """Get model configuration details from LiteLLM.

    Args:
        model_name: Optional model name to filter results. If empty, returns all models.

    Returns:
        Model configuration including provider, limits, and capabilities.
    """
    import os

    import httpx

    base_url = os.getenv("LITELLM_API_URL")
    if not base_url:
        raise RuntimeError("LITELLM_API_URL not set")
    api_key = os.getenv("LITELLM_USER_API_KEY")
    if not api_key:
        raise RuntimeError("LITELLM_USER_API_KEY not set")

    response = httpx.get(
        f"{base_url}/model/info",
        headers={"x-litellm-api-key": api_key},
        timeout=10.0,
    )
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise RuntimeError(
            f"LiteLLM model info endpoint returned HTTP {exc.response.status_code}"
        ) from None
    data = response.json()

    models = data.get("data", [])
    if model_name:
        models = [m for m in models if model_name.lower() in m.get("model_name", "").lower()]

    if not models:
        return "No model info found" + (f" for '{model_name}'" if model_name else "") + "."

    fmt = {_UNLIMITED_SENTINEL: "unlimited"}
    lines = []
    for m in models[:10]:
        params = m.get("litellm_params", {})
        info = m.get("model_info", {})
        max_t = info.get("max_tokens")
        tpm = params.get("tpm")
        rpm = params.get("rpm")
        lines.append(
            f"Model: {m.get('model_name', 'unknown')}\n"
            f"  Provider: {params.get('custom_llm_provider', 'unknown')}\n"
            f"  Backend: {params.get('model', 'unknown')}\n"
            f"  Max tokens: {fmt.get(max_t) or ('not set' if max_t is None else f'{max_t:,}')}\n"
            f"  TPM: {fmt.get(tpm) or ('not set' if tpm is None else f'{tpm:,}')} | "
            f"RPM: {fmt.get(rpm) or ('not set' if rpm is None else f'{rpm:,}')}\n"
            f"  Vision: {info.get('supports_vision', False)} | "
            f"Function calling: {info.get('supports_function_calling', False)}"
        )
    return "\n\n".join(lines)


def check_rate_limits() -> str:
    """Check rate limit and budget status for the current user's API key.

    Returns:
        Rate limit status including TPM, RPM, spend, and budget.
    """
    import os

    import httpx

    user_id = os.getenv("LETTA_USER_ID")
    if not user_id:
        raise RuntimeError("LETTA_USER_ID not set — tool called outside authenticated context")

    base_url = os.getenv("LITELLM_API_URL")
    if not base_url:
        raise RuntimeError("LITELLM_API_URL not set")
    api_key = os.getenv("LITELLM_USER_API_KEY")
    if not api_key:
        raise RuntimeError("LITELLM_USER_API_KEY not set")

    response = httpx.get(
        f"{base_url}/key/info",
        headers={"x-litellm-api-key": api_key},
        timeout=10.0,
    )
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise RuntimeError(
            f"LiteLLM key info endpoint returned HTTP {exc.response.status_code}"
        ) from None
    data = response.json()

    # Handle both nested and flat response formats
    key_info = data.get("info", data)

    fmt = {_UNLIMITED_SENTINEL: "unlimited"}
    tpm = key_info.get("tpm_limit")
    rpm = key_info.get("rpm_limit")

    spend = key_info.get("spend", 0)
    max_budget = key_info.get("max_budget")
    budget_part = f"${max_budget:.2f}" if max_budget is not None else "unlimited"
    budget_str = f"${spend:.2f} / {budget_part}"

    lines = [
        f"API Key: {key_info.get('key_name', 'unknown')}",
        f"Budget: {budget_str}",
        f"Budget resets: {key_info.get('budget_reset_at', 'never')}",
        f"TPM limit: {fmt.get(tpm) or ('not set' if tpm is None else f'{tpm:,}')}",
        f"RPM limit: {fmt.get(rpm) or ('not set' if rpm is None else f'{rpm:,}')}",
        f"Blocked: {key_info.get('blocked', False)}",
    ]

    model_spend = key_info.get("model_spend", {})
    if model_spend:
        lines.append("\nPer-model spend:")
        for model, amount in model_spend.items():
            lines.append(f"  - {model}: ${amount:.2f}")

    return "\n".join(lines)
