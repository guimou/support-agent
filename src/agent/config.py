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
    litellm_api_url: str
    litellm_api_key: str
    litellm_user_api_key: str
    agent_model: str
    guardrails_model: str
    jwt_secret: str

    proxy_port: int = 8400
    log_level: str = "info"
    memory_seed_path: str | None = None
    cors_origins: str = "*"
    output_rail_chunk_size: int = 200
    output_rail_overlap: int = 50
    rate_limit_rpm: int = 30
    rate_limit_memory_writes_per_hour: int = 20
