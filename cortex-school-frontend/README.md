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

The interface defaults to French. Use the Français/English selector on the login
page or in the workspace header to change the language. The choice is saved in
this browser and takes precedence on later visits. French
localizes navigation, forms, workflow actions, dates, and the assistant interface;
new assistant requests ask for French replies. Names, existing messages, and
school records remain in their original language. WorkOS hosts its own sign-in
pages and controls their language independently.

- Administrator: overview and needs-review queue; students and guardian links; academic-year lifecycle and publish readiness; calendars; classrooms; placements and transfers; teacher assignments; enrollment histories; attendance summaries; update oversight and recipient histories; registration approval using new or existing student resolution; rejection; single and CSV invitation imports, status, and retry; active member directory and member lookup; attendance and AI settings; AI chat.
- Teacher: today dashboard; assigned classes, rosters, and calendars; daily and dated attendance with per-student status and notes; update audience preview and composition; recipient status, feedback, and history; AI drafts and chat.
- Guardian: family overview; child records; family feeds and update details; weekly explanations; attendance history; registration creation, editing, and withdrawal; update read/acknowledgement/reply; notifications and mark-read.
- Shared: responsive navigation, search, query filters, CSV export, nested record details, contextual actions, validation errors, loading/empty/error states, modal keyboard navigation, and destructive-action confirmation.

The administrator’s **Academic years** page groups years by status and keeps the
selected year's dates, calendar, and main actions together. Create and edit years,
add teaching periods or other calendar events, check readiness, publish, and close
directly from the page. Drafts explain missing publication requirements; at least
one `term` is required, while missing classes, teacher assignments, and placements
are non-blocking warnings. Publication and closure require confirmation. Closed
years keep their calendar available in read-only mode. Class links preserve the
selected year, and year/calendar changes refresh the shared workspace data.

The teacher’s **My classrooms** page uses class cards with assignment roles,
current/upcoming status, available daily student counts, and direct attendance
and family-update actions. Open a class to browse/search its current students or
read the school calendar. A student-specific update prefills only that student as
its audience. Upcoming assignments keep attendance and composition unavailable
while allowing preparation through the calendar. Class links preserve context;
rosters load when opened and calendars load on first selection, without fetching
every class roster for the overview. The page reuses the shared class list and
the teacher-only API routes.

The administrator’s **Needs review** page has a dedicated queue with school-wide
open, urgent, and follow-up counts; category filters; priority and date filters;
and pagination. Each issue keeps its context, deadline, and next action together.
**Search this page** searches the currently displayed items. Registration,
invitation, and attendance details open directly from their queue items;
acknowledgements link to the reminder review.

Guardians have one **My children** workspace at `/family`; the former `/students`
page redirects there. Each child’s card shows their current class and academic
year, today’s attendance, the last 30 days of attendance, school updates, and an
enrollment-history dialog. The attendance rate is `(present + late) / recorded
school days`; unsubmitted days are excluded and an empty history shows no rate.
The guardian overview uses the same child cards. Attendance is available inside
**My children**; the former `/attendance` page redirects there. Registration
requests remain in their own workspace.

On generic resource pages, open a record to see related actions with its identifiers prefilled. Their **All workflows** panels expose remaining backend operations as typed forms. Dedicated workspaces such as **Academic years** present their actions directly. Backend-specific business rules and authorization errors are shown from the API. Date/time values are serialized with timezone offsets; the attendance sheet defaults to the server's current school date.

Administrators can use **Invitations → Import CSV** and choose one of four import
types: administrators, teachers, guardians, or mixed roles. The first three apply
the selected role to everyone, overriding any `role_slug` values in the file.
These files require `email`; `first_name` and `last_name` are optional. Mixed files
also require `role_slug` on every row: `school_admin`, `teacher`, or `guardian`.
Save files as UTF-8 **CSV**. The server validates the complete file before saving
and queues invitations automatically for the Celery worker. The result shows
queued, skipped, and failed counts. Existing queued or sent invitations are
skipped when the role matches; conflicting roles reject the import.

The administrator’s **School members** directory separates administrators,
teachers, and guardians with role selectors and school-wide counts. Choose a
group, search by name or email, sort by name, and export the current results to
CSV. People with several roles appear in each relevant group. The directory uses
active school memberships; pending invitations remain in **Invitations**. It
reuses the workspace’s member list, and its refresh updates that list without
reloading unrelated school data.

Administrators have dedicated **Classrooms** and **Students** directories with
an academic-year selector. Classroom cards show the teaching team and roster
count; **View class** opens teachers and students together. Student rows show
their class, an attendance rate, and a direct class link. Student details retain
editing, guardian linking, enrollment, and enrollment history. Existing class
and student operations remain available in **All workflows**.

Rates cover submitted records from the selected year’s start through today
(or the year’s end for historical years). Present and late days count as attended;
all recorded statuses count in the denominator, and missing records are excluded.
Transfers count each student/date once, using its latest record. No history shows
an unset rate. Roster membership uses exclusive placement/assignment end dates,
as of today clamped to the selected year’s dates; the date is shown on screen.
The year directory is one organization-scoped API request for all classes and
students, rather than separate attendance or roster requests per child.

Admin student lists, classroom rosters, and student details show linked guardian
names. The workspace reuses its school-member directory to resolve identities;
missing profiles and failed lookups are distinguished from students with no
linked guardian. School-member teacher rows link to current classes in active
academic years, and guardian rows link to their children. Search also matches
these class and child names, and member CSV exports include both relationships.

**School settings** displays every weekday by name, with instructional and
non-instructional days clearly marked. The editor uses named weekday checkboxes
while retaining the API’s Monday=0 through Sunday=6 values. **View AI settings**
fetches and displays feature status and default language immediately, including
when opened through a workflow dialog; it does not require a second Run action.

Administrators can upload a PDF from **School settings → School policies**. Choose a PDF with selectable text, up to 10 MB and 100 pages. The policy library uses the filename as its title and indexes extracted text with page references. Use **Paste text** to add policy text directly.

Guardians can read their school’s uploaded PDFs online from **School policies** in the family workspace and from policy sources in reminders. **View document** opens an authenticated preview inside the page; opening a new tab or saving a copy is optional. Re-upload an older PDF with the same filename to make its original available. When its extracted passages match, the app reuses the indexed policy and its existing citations.

Administrators can preview, download, or delete policies in **School settings → School policies**. Deleting a policy removes the original from the family workspace and its passages from future searches. Existing reminder proposals keep the citations recorded when they were drafted.

## Workspace identity

Each signed-in space has a persistent role label, school name and distinct accent:
green for school administration, teal for teachers and purple for families. Home pages
prioritize each role’s daily tasks. Accounts with multiple authorized roles can use
**Switch workspace** to return to the selected role’s home page. The accent also
applies to dialogs and is cleared on sign-out.

Cards, tables, forms, attendance pages, chat and study-tutor components use the
role palette for their surfaces, text, controls and hover states. Green is reserved
for positive statuses such as present, submitted or a correct quiz answer; neutral
badges use the workspace accent.

School names come from the authenticated `GET /school/context` endpoint. Approved
onboarding requests supply the name locally; older schools use a bounded WorkOS
lookup. If no name is available, the interface displays **Your school**. Deploy the
backend and frontend changes together; no database migration is needed.

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

Production build and contract tests are available locally. Workspace identities were
also checked in headless Chrome with a mocked API on desktop and mobile, including
role switching, dialogs, school-name fallback and responsive headers. Real API,
database, invitations, and authentication require the running backend and configured
WorkOS application.

Component tests use an explicit English browser preference for their existing
English-language assertions.

## Invitation acceptance

WorkOS activates an invited parent or teacher when they accept their school invitation.
The administrator’s School members page reads active WorkOS memberships directly:
no separate local registration or approval is required. These members are also selectable
when linking a guardian or assigning a teacher to a classroom. Child enrollment and
class assignment remain separate from the adult’s account activation.
