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

The administrator page receives live invitation updates through `/api/invitations/ws`.
The API and worker publish school-scoped refresh events over Redis. On Railway,
deploy the API, worker, and frontend together and point the API and worker at the
same Redis broker with `CELERY_BROKER_URL` and the same `ENVIRONMENT` value. The
frontend proxy forwards WebSocket upgrades on the app's public domain.

The visible page reconciles every 60 seconds while connected and polls every 15
seconds while disconnected. It also refreshes when returning to the tab. Manual
refresh remains available. If WorkOS cannot be checked, the API returns a retryable
error and the frontend retains its last available results.

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

### Import one historical publication

`scripts/import_historical_publication.py` inserts a school-trip authorization notice directly
into the configured database, dated 18 November 2026 at 09:00 (Tunis). It targets
the current family accounts and teachers of `6e A`, verifies WorkOS membership,
and inserts the publication and receipts atomically. This is a new historical
entry; the original historical recipient list and read state are not inferred.
Existing messages are not modified and repeated execution does not create copies.

The notice concerns a trip on 25 November 2026 with a signed-authorization deadline
of 18 November at 18:00. Its referenced document is supplied as fictional PFE demo
content in `docs/demo-publication-sortie-scolaire.md`; add that text to the school's
policy library before using the notice. General publications do not invoke policy
retrieval. To demonstrate automatic citations, use the documented student-update
acknowledgement/reminder workflow described in that file.

After deploying this script, run it from `/app` in the Railway backend:

```bash
python -m scripts.import_historical_publication
python -m scripts.import_historical_publication --apply
```

The first command previews the content and recipient counts without writing.
`--apply` writes to the database configured for that backend process. With multiple
schools, add `--organization-id org_...`; another class can be selected with
`--classroom-name "6e B"`. `--author-id user_...` selects a verified active school
administrator; otherwise the first active administrator by ID is used.

For the overdue acknowledgement/RAG demonstration, import a student update with
the additional mode below. Its default deadline is 18 November 2026 at 18:00 Tunis:

```bash
python -m scripts.import_historical_publication --organization-id org_... --classroom-name "1A · Jasmin" --require-acknowledgement --due-at "2026-11-18T18:00:00+01:00" --apply
```

This mode writes to the existing student-update workflow, with mandatory
acknowledgement, per-student recipients, family states, assignment events and
in-app notifications. An active teacher assigned to the class is selected as the
responsible teacher; `--teacher-id user_...` can select another eligible teacher.
The assignment event records the importing administrator as its actor. The update
appears in **Student updates** and the overdue acknowledgement queue; it is ready
for manual reminder preparation and approval. It does not create a general
`schoolpublication`, call the LLM or send a reminder automatically. If a general
publication was previously imported, that row is not converted or removed.

The imported deadline must follow the publication date and already be past. The
normal application continues to reject past deadlines when creating new updates.
Repeating this import preserves any subsequent family reads and acknowledgements.

## School-data chat

`POST /api/ai/chat/` accepts `message`, an optional authenticated workspace `role`
(`admin`, `teacher`, `guardian`), and `language` (`fr` by default, or `en`).
The response includes `reply` and a `sources` array with verified source IDs,
internal page links, and exact excerpts for cited school-policy passages.

The model can call `QuerySchoolData` and `SearchSchoolPolicies` before finishing
with `ChatAnswer`. Queries cover students, classrooms, enrollments, attendance,
academic years/calendars, student updates, family acknowledgements, publications,
registration requests, invitations and school members. Access is determined by
the signed-in user's claims and verified active WorkOS school membership:

| Workspace | Accessible data |
| --- | --- |
| Administrator | Records and members of their own school |
| Teacher | Assigned classes and students, permitted attendance history, their own student updates and family acknowledgements, their publication inbox |
| Guardian | Linked children, their attendance, personal updates/receipts, registration requests and publication inbox |

All three roles can search their school's policy passages and active academic
calendars. Teachers cannot access registration requests, invitations or the member
directory; invitations and the directory are administrator-only. A client-supplied
role must already be authorized for the session. Organization/user IDs are never
model tool parameters. The database transaction is read-only, with a four-second
statement timeout. The tools do not mark records as read, publish, acknowledge or
execute arbitrary SQL. Only bounded query results and policy passages are sent
to the configured AI provider; credentials and invitation error payloads are excluded.

Counts use SQL aggregates over the authorized scope, with separately paginated
items. Missing attendance does not count as absence. Acknowledgements are counted
per guardian/student pair, and a read receipt does not count as acknowledgement.
Lookups are fresh for each HTTP request; previous conversational citations must be
retrieved again. The entire model/tool loop has a 50-second deadline and eight-step
limit. Source IDs are checked against actual results; model wording still needs
the user's usual review.

Deploy the backend and frontend together and run `python -m alembic upgrade head`
from `/app` before using chat privacy controls (migration `b4c6d8e0f2a3`). No new
worker task is needed. The backend needs `WORKOS_API_KEY` and the existing LLM configuration
(`OPENROUTER_API_KEY` + `OPENROUTER_MODEL`, or `OPENAI_API_KEY`). Use a model with
function/tool calling; the project's configured `openai/gpt-4.1-mini` can use this
request format. Generic writing help needs no database lookup. Membership or
provider failures return a safe error rather than an unverified data answer.

### Saved conversations

The Assistant saves completed turns in PostgreSQL. Send a `client_message_id` on
the first `POST /api/ai/chat/` request to start a conversation, then include the
returned `conversation_id` and a new `client_message_id` on each follow-up. Reuse
the same message ID when retrying a send. Requests without either ID use the
stateless chat endpoint behavior.

`GET /api/ai/chat/conversations/` lists saved conversations. Read or delete an
individual conversation at `/api/ai/chat/conversations/{conversation_id}/`. The
API scopes each operation to the signed-in user's current school and workspace
role. It sends recent user questions to the model for context. When opening
history, it verifies the school data used by a saved answer before returning the
answer or its sources. Unavailable answers display a placeholder. Deletion also
removes the stored messages.

Apply migration `08b5d2a9c4e1` with `python -m alembic upgrade head` before
deploying the backend and frontend that use saved conversations.

### Chat data privacy controls

Administrators can switch school-data access on/off under **School settings →
AI settings**. Their chat panel shows read-only access status. Guardians have a
personal switch in the chat panel. The persisted default preserves existing access until explicitly turned
off. The school switch blocks both record and policy tools for every role;
general writing help remains available. Each guardian's preference belongs to
their user ID and school, and survives school-wide disable/re-enable operations.

`GET /api/ai/chat/access/?role=guardian` reads effective access. Guardians save
their own preference with `PUT /api/ai/chat/access/` and `{ "enabled": false }`.
Administrators save the school switch with
`PUT /api/school/chat-data-settings` and the same body. Caller-controlled guardian
or organization IDs are not accepted. Updates require a verified active WorkOS
membership, with `school:manage` required for the school-wide setting. Responses
use `Cache-Control: no-store`.

A guardian opt-out excludes their member profile, owned registration requests,
linked children, enrollments, attendance, student updates, acknowledgements and
related publications from **every role's chat tools**, including administrators.
One opt-out protects a shared child even if another guardian opts in. Shared
updates/publications that include a protected recipient are withheld as a whole
so their free text cannot expose that family's details. Invitation records are
withheld from chat when any school guardian opts out: email-only invitations
cannot reliably be matched to a stable guardian identity. The normal invitation
screen is unaffected. General school policies, academic years, classes and
calendars remain institutional data for otherwise authorized users.

Filtering occurs in SQL before pagination and aggregates, or before member
directory filtering/counting. The model receives no excluded rows or excluded-row
counts. Its tool arguments cannot override these guards. Each lookup rechecks
effective access and the school's privacy revision; a concurrent preference
change discards the result. The model loop checks again before/after provider
calls and rejects stale answers. There is no saved server-side chat transcript.
The client sends prior user questions, never prior AI answers, and clears the
visible conversation when it observes a new privacy revision (including on window
focus). Already returned information cannot be recalled from a recipient or
provider; changes govern subsequent lookups and stop stale in-flight responses.
These controls apply to this chat feature, independently of the other AI features.

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
