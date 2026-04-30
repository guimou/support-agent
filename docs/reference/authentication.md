# Authentication

The agent proxy validates JWT tokens issued by LiteMaaS. This document covers the token format, validation logic, and role system.

## Current Implementation (HS256)

**Algorithm**: HS256 (HMAC-SHA256, symmetric)
**Secret**: `JWT_SECRET` environment variable (shared with LiteMaaS)
**Default Expiration**: 24 hours

> **Production hardening**: Migrate LiteMaaS to RS256 (asymmetric) so the agent only needs the public key for validation. This eliminates the risk of token forgery if the agent container is compromised.

## Token Claims

```json
{
  "userId": "550e8400-e29b-41d4-a716-446655440001",
  "username": "alice",
  "email": "alice@example.com",
  "roles": ["user"],
  "iat": 1714200000,
  "exp": 1714286400
}
```

| Claim | Type | Description |
|---|---|---|
| `userId` | `string` (UUID) | User's unique identifier. Injected as `LETTA_USER_ID` for tools |
| `username` | `string` | User's login name (from OAuth provider) |
| `email` | `string` | User's email address |
| `roles` | `string[]` | Array of role values (see [Role System](#role-system)) |
| `iat` | `number` | Issued-at timestamp (seconds since epoch) |
| `exp` | `number` | Expiration timestamp (seconds since epoch) |

## Role System

**Role values** (from most to least privileged):

| Role | Description | Permissions |
|---|---|---|
| `admin` | Full system access | Manage users, models, view all analytics, approve subscriptions |
| `admin-readonly` | Read-only admin access | View all data but cannot modify |
| `user` | Standard user | Manage own API keys and subscriptions |
| `readonly` | Read-only user | View own data only |

**Role hierarchy**: `admin` > `admin-readonly` > `user` > `readonly`

**How roles are determined** (merged from three sources):

1. **OAuth group mapping** — Groups from the identity provider are mapped to roles:
   ```
   litemaas-admins     -> [admin, user]
   administrators      -> [admin, user]
   litemaas-users      -> [user]
   developers          -> [user]
   litemaas-readonly   -> [admin-readonly, user]
   viewers             -> [admin-readonly, user]
   ```

2. **Initial admin users** — Usernames listed in `INITIAL_ADMIN_USERS` env var get `[admin, user]` on first login

3. **Database-stored roles** — Roles persisted in the `users.roles` column, preserved across logins

The `user` role is always present as a base role. All sources are merged (union).

**For the agent proxy**: To determine if a user is admin, check if `roles` array contains `"admin"`.

## Token Extraction

The token is sent in the `Authorization` header:

```
Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```

The LiteMaaS backend forwards this header as-is when proxying to the agent container.

## Python Validation Reference

See `src/proxy/auth.py` for the implementation. The key flow:

1. Extract Bearer token from `Authorization` header
2. Decode with `jwt.decode(token, JWT_SECRET, algorithms=["HS256"])`
3. Validate required claims: `userId`, `username`, `email`, `roles`
4. Create `AuthenticatedUser` dataclass with `is_admin = "admin" in roles`

## Alternative Authentication Methods

LiteMaaS also supports API key authentication. The agent proxy does **not** validate these — it only accepts JWT tokens from the LiteMaaS backend.

| Key Format | Purpose |
|---|---|
| `ltm_admin_*` | Admin API keys (set via `ADMIN_API_KEYS` env var) |
| `sk-litellm-*` | User API keys (from database) |
