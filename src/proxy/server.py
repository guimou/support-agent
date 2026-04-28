"""FastAPI proxy server for the LiteMaaS Agent Assistant."""

from __future__ import annotations

from fastapi import FastAPI

app = FastAPI(
    title="LiteMaaS Agent Proxy",
    description="Proxy server for the LiteMaaS AI Agent Assistant",
    version="0.1.0",
)


@app.get("/v1/health")
async def health() -> dict[str, str]:
    """Health check endpoint for container probes."""
    return {"status": "healthy"}
