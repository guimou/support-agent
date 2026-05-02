"""PII-audited memory write wrappers.

These replace Letta's built-in memory tools. Each wrapper runs PII
regex against the content before calling the Letta memory API.
If PII is detected, the write is rejected (returns error to agent).

IMPORTANT: These functions must be fully self-contained — no imports
from src/ modules. Letta extracts function source and executes it in
its own process where src/ packages are not available. PII patterns
are inlined for this reason.
"""

# Shared PII pattern list — inlined in each function because Letta
# extracts functions individually. Kept in module scope for tests only;
# each function re-defines _PII_PATTERNS locally to be self-contained
# when extracted.

_PII_PATTERNS_SOURCE = [
    r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
    r"sk-[a-zA-Z0-9]{20,}",
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    r"(?<!\d)(?:\+?1[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?)?\d{3}[-.\s]?\d{4}(?!\d)",
    r"(?<!\d)\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}(?!\d)",
    r"(?<!\d)(?:4\d{3}|5[1-5]\d{2}|6011|3[47]\d{2})[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}(?!\d)",
]


def core_memory_append(label: str, content: str) -> str:
    """Append to a core memory block, with PII pre-check."""
    import os
    import re

    _PII_PATTERNS = [  # noqa: N806
        r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
        r"sk-[a-zA-Z0-9]{20,}",
        r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
        r"(?<!\d)(?:\+?1[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?)?\d{3}[-.\s]?\d{4}(?!\d)",
        r"(?<!\d)\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}(?!\d)",
        r"(?<!\d)(?:4\d{3}|5[1-5]\d{2}|6011|3[47]\d{2})[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}(?!\d)",
    ]
    for pattern in _PII_PATTERNS:
        if re.search(pattern, content):
            return (
                "BLOCKED: Cannot write to memory — the content contains "
                "personally identifiable information (PII). Please rephrase "
                "without including email addresses, IDs, phone numbers, "
                "IP addresses, or API keys."
            )

    import httpx

    agent_id = os.getenv("LETTA_AGENT_ID", "")
    base_url = os.getenv("LETTA_SERVER_URL", "http://localhost:8283")
    resp = httpx.post(
        f"{base_url}/v1/agents/{agent_id}/memory/core/{label}",
        json={"content": content, "append": True},
        timeout=10,
    )
    if resp.status_code == 200:
        return f"Successfully appended to {label} memory block."
    return f"Error appending to memory: {resp.status_code}"


def core_memory_replace(label: str, old_content: str, new_content: str) -> str:
    """Replace content in a core memory block, with PII pre-check on new content."""
    import os
    import re

    _PII_PATTERNS = [  # noqa: N806
        r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
        r"sk-[a-zA-Z0-9]{20,}",
        r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
        r"(?<!\d)(?:\+?1[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?)?\d{3}[-.\s]?\d{4}(?!\d)",
        r"(?<!\d)\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}(?!\d)",
        r"(?<!\d)(?:4\d{3}|5[1-5]\d{2}|6011|3[47]\d{2})[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}(?!\d)",
    ]
    for pattern in _PII_PATTERNS:
        if re.search(pattern, new_content):
            return (
                "BLOCKED: Cannot write to memory — the new content contains "
                "personally identifiable information (PII)."
            )

    import httpx

    agent_id = os.getenv("LETTA_AGENT_ID", "")
    base_url = os.getenv("LETTA_SERVER_URL", "http://localhost:8283")
    resp = httpx.post(
        f"{base_url}/v1/agents/{agent_id}/memory/core/{label}",
        json={"content": new_content, "old_content": old_content, "replace": True},
        timeout=10,
    )
    if resp.status_code == 200:
        return f"Successfully replaced content in {label} memory block."
    return f"Error replacing memory: {resp.status_code}"


def archival_memory_insert(content: str) -> str:
    """Insert into archival memory, with PII pre-check."""
    import os
    import re

    _PII_PATTERNS = [  # noqa: N806
        r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
        r"sk-[a-zA-Z0-9]{20,}",
        r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
        r"(?<!\d)(?:\+?1[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?)?\d{3}[-.\s]?\d{4}(?!\d)",
        r"(?<!\d)\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}(?!\d)",
        r"(?<!\d)(?:4\d{3}|5[1-5]\d{2}|6011|3[47]\d{2})[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}(?!\d)",
    ]
    for pattern in _PII_PATTERNS:
        if re.search(pattern, content):
            return (
                "BLOCKED: Cannot write to archival memory — the content "
                "contains personally identifiable information (PII)."
            )

    import httpx

    agent_id = os.getenv("LETTA_AGENT_ID", "")
    base_url = os.getenv("LETTA_SERVER_URL", "http://localhost:8283")
    resp = httpx.post(
        f"{base_url}/v1/agents/{agent_id}/archival",
        json={"content": content},
        timeout=10,
    )
    if resp.status_code == 200:
        return "Successfully inserted into archival memory."
    return f"Error inserting into archival memory: {resp.status_code}"
