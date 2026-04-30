"""Documentation search tools.

For Phase 1, documentation search leverages the agent's built-in
archival_memory_search tool. This module provides a supplementary
search function that can be extended in Phase 4 with external search.
"""

from __future__ import annotations


def search_docs(query: str) -> str:
    """Search the platform documentation and knowledge base for information.

    Use this tool to find answers about LiteMaaS features, common issues,
    troubleshooting steps, and platform capabilities.

    Args:
        query: The search query describing what information you need.

    Returns:
        Relevant documentation excerpts if found, or a message indicating
        no results.
    """
    # Phase 1: This tool is a placeholder. The agent should use its built-in
    # archival_memory_search tool for documentation lookups. This function
    # will be enhanced in Phase 4 with external search capabilities.
    return (
        f"Searched for: '{query}'. "
        "Use the archival_memory_search tool to find documentation in your knowledge base."
    )
