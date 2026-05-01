"""Application settings loaded from environment variables."""

from __future__ import annotations

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Agent proxy configuration.

    All values are read from environment variables.
    Defaults are provided for optional settings.
    """

    letta_server_url: str
    litemaas_api_url: str
    jwt_secret: str

    # LLM providers (independent from the monitored platform)
    agent_model: str
    agent_llm_api_base: str
    agent_llm_api_key: str
    guardrails_model: str
    guardrails_llm_api_base: str
    guardrails_llm_api_key: str

    # Monitored LiteLLM instance (queried by tools)
    litellm_api_url: str
    litellm_api_key: str
    litellm_user_api_key: str

    # LiteMaaS admin API key (for admin tools calling LiteMaaS backend endpoints)
    litemaas_admin_api_key: str = ""

    # JWT issuer/audience validation (optional, recommended for production)
    jwt_issuer: str = ""
    jwt_audience: str = ""

    proxy_port: int = 8400
    log_level: str = "info"
    memory_seed_path: str | None = None
    cors_origins: str = ""
    output_rail_chunk_size: int = 200
    output_rail_overlap: int = 50
    guardrails_required: bool = True
    rate_limit_rpm: int = 30
    rate_limit_memory_writes_per_hour: int = 20
    stream_lock_timeout_seconds: float = 30.0
    stream_max_duration_seconds: float = 120.0
