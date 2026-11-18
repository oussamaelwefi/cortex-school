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

After changing environment variables, recreate the API container:

```bash
docker compose -f docker/docker-compose.yml --env-file docker/.env up -d --no-deps --force-recreate api
```

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
