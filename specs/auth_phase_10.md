# Phase 10 — Auth & Privacy

Written 2026-06-03.

## Scope (decisions locked)

- **Single-tenant.** Single user only. No `user_id` columns added. No multi-user UI.
- **Microsoft Entra ID** via Azure SWA's built-in authentication. Portfolio alignment with the Azure-pipelines pivot is part of the brief.
- **Everything behind login.** Whole app gated. Only `/api/health` stays public (for ops).
- **Local dev**: `AUTH_BYPASS=1` in `.env` (backend) / `VITE_AUTH_BYPASS=1` in `frontend/.env` (frontend) returns a stub principal. No live Entra dependency for daily iteration.
- **Allowlist**: `config/auth.yml` (project convention — non-secret policy config).
- **Trust boundary** for production (how `X-MS-CLIENT-PRINCIPAL` reaches the backend safely): deferred to Phase 9. Phase 10's code just reads the header; Phase 9 picks shared-secret vs. ACA-only ingress.

## How Azure SWA auth works

When SWA hosts the frontend with a linked backend (Azure Container Apps):

1. User hits `/.auth/login/aad` → SWA redirects to Entra ID → Entra ID auths the user → SWA writes a cookie
1. SWA's `/.auth/me` returns the current user's claims as JSON (`userId`, `userDetails` (email), `userRoles`, etc.)
1. SWA proxies `/api/*` to the linked backend, injecting `X-MS-CLIENT-PRINCIPAL` header (base64-encoded JSON of the same claims)
1. SWA enforces `allowedRoles` declaratively via `staticwebapp.config.json` — unauthenticated users never reach the backend

This means we don't integrate Entra SDKs in FastAPI directly. The backend trusts the header (within the trust boundary established by Phase 9 deployment).

## Data model

No schema change. There is no user table. There is no `user_id` column anywhere. Single-tenant means the data already implicitly belongs to one person.

## API surface

| Route                          | Public?                                         |
| ------------------------------ | ----------------------------------------------- |
| `GET /api/health`              | ✅ public                                       |
| Everything else under `/api/*` | 🔒 requires authenticated allowlisted principal |

## Backend implementation

### `config/auth.yml`

```yaml
# Allowed identities. Email match against userDetails from Entra ID.
# Single-tenant today; can grow to a small list if needed.
allowed_emails:
  - example@example.com
```

### `src/api/auth.py`

- `load_auth_config()` reads `config/auth.yml` at startup
- `current_principal(request: Request) -> Principal` dependency:
  - If `AUTH_BYPASS` env var is truthy → return stub `Principal(email="dev@localhost", roles=["dev-bypass"])` and log a warning at startup so dev mode can't be silently shipped
  - Else: read `X-MS-CLIENT-PRINCIPAL` header, base64-decode → JSON, extract `userDetails` (email) and `userRoles`
  - Email lookup against `allowed_emails`; reject (401) if missing header, (403) if email not in allowlist
- `Principal` dataclass: `email: str`, `roles: list[str]`, `raw_claims: dict` (preserved for future use)

### `src/api/main.py` wiring

- Add `Principal = Annotated[Principal, Depends(current_principal)]` to every route except `/api/health`
- Routes don't use the principal yet (single-tenant — no row-level filtering by user) but receive it so future multi-tenancy is a search-and-replace
- Lifespan startup logs the active mode: "auth: bypass (dev)" or "auth: enforced (allowlist=N entries)"

### Tests

- `tests/api/test_auth.py`:
  - Bypass mode: requests succeed without any header
  - Enforced mode + valid header (allowlisted email) → 200
  - Enforced mode + valid header (non-allowlisted email) → 403
  - Enforced mode + missing header → 401
  - Enforced mode + malformed base64 → 401
  - `/api/health` stays 200 in both modes regardless of header

## Frontend implementation

### `src/lib/auth.ts`

- `fetchPrincipal()` → `GET /.auth/me`, returns claims or null
- In dev (`import.meta.env.DEV` and `VITE_AUTH_BYPASS=1`): return a stub principal without hitting `/.auth/me`

### `useAuth()` hook

- React Query against `fetchPrincipal()` on app load
- Returns `{ principal, isLoading, isAuthenticated }`
- On unauthenticated principal → redirect to `/.auth/login/aad?post_login_redirect_uri=/`

### `App.tsx` integration

- Top-level gate: if `isLoading` → splash, if `!isAuthenticated` → redirect to login, else render the app
- Header shows the logged-in email as a `/.auth/logout` link

### Tests

- Vitest + React Testing Library
- Test the unauthenticated → redirect path
- Test the authenticated → renders children path

## Out of scope (defer until needed)

- Multi-tenancy / signup flow / user table — gated on "do I actually want anyone else using this?"
- Public read-only landing page — would re-open the "what's gated" question
- Role-based access control beyond the single allowlist — overkill for one user
- Logout button (besides a simple `/.auth/logout` link) — single user rarely logs out
- Auth event audit log — meaningful only with multi-tenancy or compliance pressure
