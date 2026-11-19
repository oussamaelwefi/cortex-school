# Backend skeleton

FastAPI + Postgres. Copy this repo, rename `PROJECT_NAME` in `.env`, start coding.

## Run

```bash
cp docker/.env.sample docker/.env
make run
docker exec -it api make apply-migrations   # first time only
```

- **Swagger:** http://localhost:9000/api/docs (WorkOS platform operators)
- **Health:** http://localhost:9000/api/healthcheck
- **Example API:** `curl -H "Authorization: Bearer $WORKOS_ACCESS_TOKEN" http://localhost:9000/api/example/`

Protected `/api` routes validate AuthKit access tokens against the WorkOS
application configured in `app/core/auth.py`.

## Platform maintenance access

Set `WORKOS_OPERATOR_USER_IDS` to a JSON array of WorkOS user IDs for staff authorized to maintain data across schools, and `ADMIN_SESSION_SECRET` to a randomly generated secret of at least 32 characters. On Railway, configure these on the backend service; locally, use `docker/.env`.

In the WorkOS application used by Cortex, add `https://YOUR-BACKEND-DOMAIN/admin/auth/callback` to the allowed redirect URIs (locally, `http://localhost:9000/admin/auth/callback`). Open the backend's `/admin/` and choose **Sign in with WorkOS**. Normal AuthKit sign-in returns you to the console; no access token needs to be copied. This uses the same WorkOS application and token validation as Cortex, and checks the operator allowlist independently of school roles.

The callback URL is inferred from the request. If a reverse proxy reports a different scheme or hostname, set `ADMIN_AUTH_REDIRECT_URI` to the exact public callback URL registered in WorkOS. The authorization-code flow uses PKCE, a browser-bound state, and a single-use WorkOS code; no additional API secret is required for console sign-in. A separate signed, HttpOnly cookie with a ten-minute lifetime and SameSite=Lax allows the WorkOS redirect to complete. The operator session keeps SameSite=Strict; both cookies use Secure outside development. Tokens are never stored in either cookie.

After signing in, `/api/docs` is available in the same browser session. The console session expires with the verified WorkOS access token; use the sign-in button again when needed. API documentation also accepts a current operator bearer token.

## New school onboarding

Applicants choose **Register your school** on the Cortex sign-in page, verify their WorkOS email, and submit a school request. Platform operators review requests under **School requests** in the operator console. Approval queues a worker to create the WorkOS organization, link its ID to a Cortex school, and assign the original requester the `school_admin` membership. The requester checks the result and opens the new workspace from their request page. The console offers **Retry provisioning** for failed attempts.

For Railway, apply `alembic upgrade head` on the backend database and deploy the frontend, API, Celery worker, and Celery Beat scheduler from the same revision. Configure `WORKOS_API_KEY` for the API and worker using the Cortex WorkOS environment. In that environment, make sure AuthKit permits applicants to sign up, and that `school_admin` has `school:manage`. The form lists countries configured in the operator console under **Countries**.

## Invitation status webhooks

In the WorkOS Dashboard, open **Webhooks** in the same environment that sends your invitations. Add or update the endpoint to `https://YOUR-BACKEND-DOMAIN/api/webhooks/workos/` and subscribe to `invitation.accepted`. You can also subscribe to `invitation.revoked` and `invitation.resent` to keep revocations and resent invitation expiry dates in sync.

Copy the endpoint's signing secret into the Railway **backend** service variable `WORKOS_WEBHOOK_SECRET` and deploy the backend. Webhooks update acceptance and revocation as events arrive. **Send status** tracks email delivery separately. To confirm webhook delivery, check the event's response in the WorkOS webhook log.

The API also reconciles tracked invitation states with WorkOS when loading the
invitation list or details and before resending. This recovers previously missed
acceptance events without replaying them. Configure `WORKOS_API_KEY` on the API
service using the same WorkOS environment as the sending worker. List reads use
organization-scoped, paginated provider requests rather than one call per row.
Reconciliation checks exact invitation IDs, organization and email; an active
membership alone does not count as acceptance of a particular invitation. A
concurrent acceptance is never replaced by an older pending snapshot.

The administrator page refreshes every 15 seconds while visible and when returning
to the tab. Manual refresh remains available. If WorkOS cannot be checked, the API
returns a retryable error and the frontend retains its last available results.

## Local Docker runtime for this checkout

The local stack uses `docker/docker-compose.local.yml`. It builds the API,
worker, scheduler, and frontend from this repository without bind mounts, and
reuses the existing `docker_db-data`, `docker_redis-data`, and `docker_default`
network. Keep the local credentials in the ignored `docker/.env` file.

From this repository's `cortex-school-backend/docker` directory, rebuild and
replace the application containers after changing code:

```powershell
docker compose --env-file .env -f docker-compose.local.yml up -d --build --no-deps api worker scheduler frontend
```

Open http://localhost:5173. This setup runs the code copied into each image;
source edits take effect after rebuilding. PostgreSQL and Redis retain their
existing containers and data during the command above. The local Compose file
requires the existing data volumes and network; use the standard configuration
for a fresh installation.

## AI assistant configuration

Configure the provider in `docker/.env`:

```env
# OpenRouter key (sk-or-...), routed to https://openrouter.ai/api/v1
OPENROUTER_API_KEY=your_openrouter_key
OPENROUTER_MODEL=openai/gpt-4.1-mini
```

Alternatively, use a direct OpenAI key in `OPENAI_API_KEY` with `OPENAI_MODEL`.
The assistant uses OpenRouter when `OPENROUTER_API_KEY` is set, otherwise OpenAI.
Do not put an OpenRouter key in `OPENAI_API_KEY`. Teacher drafts and guardian
weekly explanations also use the OpenRouter settings.

Teacher drafts and guardian weekly explanations use `ChatOpenAI` with OpenRouter's
compatible endpoint, the same adapter as the chat. Its Pydantic serializer makes
all properties required for strict JSON output, keeps nullable fields, and removes
unsupported null defaults. Responses still pass the Pydantic business validators;
provider parameter requirements and the data-collection restriction stay enabled.

`OPENROUTER_TIMEOUT_SECONDS` is expressed in seconds, as expected by this adapter.
Teacher draft model calls have an overall 45-second deadline (`AI_TEACHER_DRAFT_TIMEOUT_SECONDS`, maximum
50), below the frontend proxy timeout. AI requests have a separate 65-second browser
budget, and timeouts are reported separately from connection failures.

The AI rate limiter uses `AI_TEACHER_DRAFT_REDIS_URL` when provided, otherwise
`CELERY_BROKER_URL`. On Railway, these must point to the reachable Redis service;
the API needs this connection as well as `OPENROUTER_API_KEY`. Redis connection and
command waits are bounded, and unavailable rate limiting blocks generation rather
than bypassing the limits. Authentication/model configuration errors and provider
timeouts return safe, actionable errors. The entered observations stay in the form.

After changing environment variables, recreate the API container:

```bash
docker compose -f docker/docker-compose.yml --env-file docker/.env up -d --no-deps --force-recreate api
```

## School publications

School administrators can publish an announcement to selected active classes,
family accounts, teachers, or students. A class resolves to its currently enrolled
students' active family accounts plus its currently assigned active teachers.
Selecting students delivers to their linked active family accounts, never to a
student login. Direct account targeting checks the requested role in the same
WorkOS organization. One account receives one copy, even across multiple classes
or children. The preview lists actual accounts and warns about students without
an active linked family account.

The seven `/api/publications/` endpoints provide admin audience options, preview,
confirmed publication, sent-history and receipt details, plus an authenticated
teacher/guardian inbox and read action. Admin routes require `school:manage`.
Publishing rechecks membership and audience, refuses a changed preview, and uses
an author-scoped idempotency key so a repeated request does not deliver twice.
Recipient inboxes recheck active membership; student-related messages disappear
from a guardian's inbox if that guardian is no longer linked to any relevant child.
Read timestamps are per account and only the administration sees readership lists.
Delivery is in the application; no email or SMS is sent by this feature.

Before using publications on Railway, apply the additive database migration in the
backend service's `/app` directory: `python -m alembic upgrade head`. The revision
`a3b5c7d9e1f2` creates `schoolpublication` and `publicationrecipient`. Deploy the
backend and frontend together. The API needs `WORKOS_API_KEY`; no new secret or
Celery task is needed for these durable inbox deliveries.

## Folders

| Path | What |
|------|------|
| `app/main.py` | App entry |
| `app/core/` | Config, DB, auth |
| `app/modules/` | **Put your features here** (`router.py` per folder) |
| `app/migrations/` | DB schema (Alembic) |
| `app/ai/` + `app/prompts/` | Optional LLM helpers |
| `app/modules/*/tasks.py` | Celery background jobs |
| `docker/` | Postgres + API |

## Add a feature

```
app/modules/orders/router.py
```

```python
from core.router import APIRouter
router = APIRouter(prefix="/orders", tags=["Orders"])

@router.get("/")
async def list_orders():
    return []
```

Auto-loaded. No wiring needed.
