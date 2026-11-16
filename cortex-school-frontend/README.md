# Cortex School frontend

A responsive React + TypeScript school workspace, connected to the adjacent FastAPI backend. Includes WorkOS sign-in and administrator, teacher, and guardian workspaces.

## Run locally

```powershell
cd F:\cortex-school\cortex-school-frontend
npm install
Copy-Item .env.example .env
npm run dev
```

Open http://localhost:5173. The Vite development server forwards `/api` to `http://localhost:9000`. Start the backend separately following its README and sign in through WorkOS.

## Run with Docker

The frontend is part of the existing **docker** project, alongside the API, worker, PostgreSQL, and Redis. From the backend directory, run:

```powershell
cd F:\cortex-school\cortex-school-backend
docker compose -f docker/docker-compose.yml --env-file docker/.env up --build -d
```

Open http://localhost:5173. The multi-stage image builds the app with Node and serves the production output with Nginx, including fallback routing for frontend pages. Nginx forwards `/api/` requests directly to `http://api:9000` over the shared Docker network. The backend's existing database and environment configuration still applies.

Set optional frontend configuration in `cortex-school-backend/docker/.env`. `FRONTEND_PORT` changes the published frontend port. Set `VITE_WORKOS_REDIRECT_URI` to match that browser URL and register it with WorkOS. `VITE_WORKOS_CLIENT_ID` selects the WorkOS application. No local Node installation is required.

The `VITE_*` values are embedded at build time; rebuild the frontend after changing them. `cortex-school-frontend/compose.yaml` also includes the same full stack, so `docker compose up --build -d` from the frontend directory uses the same `docker` project.

```powershell
docker compose -f docker/docker-compose.yml --env-file docker/.env logs -f frontend
docker compose -f docker/docker-compose.yml --env-file docker/.env stop frontend
```

## Authentication configuration

Configure `http://localhost:5173` as both a redirect URI and an allowed origin in your WorkOS application, following the [AuthKit React setup](https://workos.com/docs/sdks/authkit-react). Hosted AuthKit handles credentials, invitations, account creation, recovery, and session refresh. No WorkOS API secret belongs in frontend environment variables.

The frontend defaults to the backend's WorkOS application client ID. When deploying with a different WorkOS application, match `VITE_WORKOS_CLIENT_ID` to `WORKOS_CLIENT_ID` in `app/core/auth.py`. Set `WORKOS_ISSUER` in the same file to the issuer from the application's WorkOS discovery metadata. In an environment with multiple applications, the issuer can reference the default application's client ID.

The workspace uses WorkOS for live school sign-in. OpenRouter and OpenAI credentials are server-side settings for AI features and are optional for the school workspace.

Role navigation follows access-token claims: administrator screens require `school:manage`; teacher and guardian screens require their corresponding `role` or `roles` claim. Backend authorization remains authoritative. Members also need an `org_id` for school data. The app does not grant roles or create school organizations.

## Features

Use the English/Français selector on the login page or in the workspace header
to change the interface language. The choice is saved in this browser. French
localizes navigation, forms, workflow actions, dates, and the assistant interface;
new assistant requests ask for French replies. Names, existing messages, and
school records remain in their original language. WorkOS hosts its own sign-in
pages and controls their language independently.

- Administrator: overview and needs-review queue; students and guardian links; academic-year lifecycle and publish readiness; calendars; classrooms; placements and transfers; teacher assignments; enrollment histories; attendance summaries; update oversight and recipient histories; registration approval using new or existing student resolution; rejection; single and CSV invitation imports, status, and retry; active member directory and member lookup; attendance and AI settings; AI chat.
- Teacher: today dashboard; assigned classes, rosters, and calendars; daily and dated attendance with per-student status and notes; update audience preview and composition; recipient status, feedback, and history; AI drafts and chat.
- Guardian: family overview; child records; family feeds and update details; weekly explanations; attendance history; registration creation, editing, and withdrawal; update read/acknowledgement/reply; notifications and mark-read.
- Shared: responsive navigation, search, query filters, CSV export, nested record details, contextual actions, validation errors, loading/empty/error states, modal keyboard navigation, and destructive-action confirmation.

Open a record to see related actions with its identifiers prefilled. Each feature's **All workflows** panel exposes its remaining backend operations as typed forms. Backend-specific business rules and authorization errors are shown from the API. Date/time values are serialized with timezone offsets; the attendance sheet defaults to the server's current school date.

Invitation import accepts UTF-8 **CSV**, with columns `email,first_name,last_name,role_slug`; valid roles are `school_admin`, `teacher`, and `guardian`.

Administrators can upload a PDF from **School settings → School policies**. Choose a PDF with selectable text, up to 10 MB and 100 pages. The policy library uses the filename as its title and indexes extracted text with page references. Use **Paste text** to add policy text directly.

Guardians can download their school’s uploaded PDFs from **School policies** in the family workspace. Re-upload an older PDF with the same filename to make its original available. When its extracted passages match, the app reuses the indexed policy and its existing citations.

Administrators can download or delete policies in **School settings → School policies**. Deleting a policy removes the original from the family workspace and its passages from future searches. Existing reminder proposals keep the citations recorded when they were drafted.

## API contract maintenance

```powershell
npm run contracts
npm test
npm run build
```

The Python standard-library generator parses backend source without importing the application, connecting to a database, or needing Swagger credentials. It generates forms for business endpoints and excludes infrastructure routes such as webhooks and the skeleton example. Re-run the generator when backend routes or schemas change, then review the resulting contracts. Pydantic cross-field rules remain server validated.

## Production

Set `VITE_API_BASE_URL` to the deployed API URL (including `/api`) or configure a same-origin `/api` reverse proxy. Set `VITE_WORKOS_CLIENT_ID` and `VITE_WORKOS_REDIRECT_URI` for the intended environment. Register the deployed frontend origin and redirect URI in WorkOS. Run `npm run build`, serve `dist/`, and configure your web server to fall back to `index.html` for frontend routes. Vite's API proxy is development-only.

## Verification

Production build and contract tests are available locally. Real API, database, invitations, and authentication require the running backend and configured WorkOS application. Browser visual verification was unavailable during implementation because the browser automation runtime failed to start.

## Invitation acceptance

WorkOS activates an invited parent or teacher when they accept their school invitation.
The administrator’s School members page reads active WorkOS memberships directly:
no separate local registration or approval is required. These members are also selectable
when linking a guardian or assigning a teacher to a classroom. Child enrollment and
class assignment remain separate from the adult’s account activation.
