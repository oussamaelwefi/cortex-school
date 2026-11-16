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

Set `WORKOS_OPERATOR_USER_IDS` in `docker/.env` to a JSON array of WorkOS user IDs for staff authorized to maintain data across schools. API documentation accepts a current WorkOS bearer token from an operator. To enable the browser console at `/admin/`, also set `ADMIN_SESSION_SECRET` to a randomly generated secret of at least 32 characters. Use the console’s WorkOS access-token form, then open `/api/docs` in the same browser session. The console session expires with that token.

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
