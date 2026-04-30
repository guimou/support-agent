"""Initial knowledge seeds for archival memory."""

from __future__ import annotations

ARCHIVAL_SEEDS: list[str] = [
    # Model access troubleshooting
    """FAQ: Why can't I access a model?
Common causes:
1. Model requires restricted access approval — check subscription status for 'pending' or 'denied'
2. Model is inactive — admin has disabled it
3. Budget exhausted — check spend vs maxBudget on your API key
4. API key expired — check expiresAt field
5. API key revoked — check revokedAt field
6. Rate limit exceeded — check RPM/TPM limits
Diagnostic order: subscription status → API key status → budget → rate limits""",
    # API key troubleshooting
    """FAQ: My API key stopped working
Diagnostic steps:
1. Check if key is active (isActive=true, revokedAt=null)
2. Check budget: currentSpend vs maxBudget — budget exhaustion is the #1 cause
3. Check expiration: expiresAt field
4. Check sync status: syncStatus should be 'synced', not 'error'
5. Check model access: the key's 'models' array must include the model you're using
6. Budget duration matters: 'monthly' budgets reset on the 1st""",
    # Subscription management
    """FAQ: How do subscriptions work?
- Users subscribe to models to get access
- Non-restricted models: subscription is immediate (status=active)
- Restricted models: subscription goes to 'pending', admin must approve
- Quotas: requests and tokens have separate limits
- Utilization: check utilizationPercent for quick read (0-100)
- Reset: quota resets at the time specified in resetAt field
- Null quotas mean unlimited""",
    # Platform overview
    """Platform Overview: LiteMaaS
LiteMaaS is an AI model management platform that provides:
- Model catalog with multiple providers (OpenAI, Anthropic, etc.)
- Subscription-based access control with per-model quotas
- API key management with budget controls
- Usage tracking and analytics
- Admin tools for user and subscription management
The platform uses LiteLLM as a proxy for model routing.""",
]
