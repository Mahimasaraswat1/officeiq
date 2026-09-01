# OfficeIQ

**An HR onboarding platform with a retrieval-augmented assistant that answers company
policy questions from your own handbook — and says "I don't know" when the handbook
doesn't cover it.**

A full-stack application: React frontend, FastAPI backend, PostgreSQL with pgvector for
semantic search, and a RAG pipeline over the company knowledge base. Built as an
implementation of a two-part PRD (business/functional and development/production).

### What it does

New hires are invited by HR, upload their documents, have them OCR-extracted and
verified, get a checklist assigned by rules HR controls in-app, and can ask the
assistant questions about policy. HR sees an analytics dashboard, an approvals queue,
and an audit trail of everything that happened.

### What is worth looking at

- **The assistant refuses to guess.** Answers are grounded in retrieved passages with
  citations, gated on a similarity floor and a confidence threshold. When nothing
  relevant is retrieved it escalates to HR rather than inventing a policy — and it
  distinguishes "not in the handbook" from "the model call failed", because telling an
  employee to go looking for a documentation gap that does not exist wastes their time.
  See [Anti-hallucination guarantees](#anti-hallucination-guarantees).
- **Providers are pluggable and degrade honestly.** Chat generation runs on Claude or
  Groq, embeddings on Voyage. A missing key is refused at startup rather than silently
  swapped for a fallback embedder — documents and queries in different vector spaces
  return zero results while every health check still reads green.
- **Assignment rules live in the database**, editable by HR in-app. Changing onboarding
  policy does not require a deploy.
- **Roughly 570 tests**, including adversarial ones: a migration suite that runs
  `alembic upgrade head` against a throwaway database because the main suite builds its
  schema from the models and would never catch a missing `ALTER TYPE`, and a static
  check that no module reads the local calendar date, because the timezone bug it
  guards against passes for nineteen hours a day.

### Current state

All eight PRD phases complete, plus three employee self-service modules: a company
**Holiday Calendar**, a generic **Request & Approval Engine**, and **Leave Application**
built on top of it. See the [roadmap](#roadmap) for the breakdown.

---

## Stack

| Layer | Choice |
|---|---|
| Frontend | React 18 + Vite + Tailwind CSS v4 |
| Backend | Python 3.13 + FastAPI |
| Database | PostgreSQL 16 + pgvector (via Docker Compose) |
| Migrations | Alembic |
| Auth | JWT access + refresh tokens, bcrypt hashing, RBAC middleware |
| Email | Pluggable — `file`/`console` in dev, SMTP or Brevo's HTTP API in production |
| Object storage | Pluggable — `local` filesystem or `s3` (MinIO locally, AWS S3 in prod) |
| OCR | Self-hosted Tesseract via a pluggable engine interface |
| PDF | PyMuPDF — uses an embedded text layer when present, rasterises + OCRs when not |
| Face matching | OpenCV DNN (YuNet detector + SFace recogniser), behind a pluggable interface |
| ID verification | Mock UIDAI/NSDL simulator — no government API is contacted in v1 |
| Assignment rules | Stored in PostgreSQL and editable by HR in-app — no deploy to change policy |
| Chatbot generation | Claude (`claude-opus-5`) or Groq (`openai/gpt-oss-120b`), behind one interface |
| Embeddings | Voyage AI (`voyage-3`) — the Claude API has no embeddings endpoint |
| Vector store | pgvector, in the same Postgres database as everything else |
| Notifications | In-app inbox, written in the same transaction as the event; optional email |
| Charts | Hand-drawn inline SVG — no charting dependency |
| Reports | openpyxl (Excel) + ReportLab (PDF) over one shared dataset layer |
| Deployment | Multi-stage Docker images, nginx-served frontend, GitHub Actions CI |

---

## Project layout

```
.
├── docker-compose.yml        # PostgreSQL + Adminer + MinIO
├── backend/
│   ├── alembic/versions/     # 0001_initial … 0007_session_metadata
│   ├── Dockerfile            # multi-stage; runs as a non-root user
│   ├── models/               # face ONNX models (gitignored, fetched by script)
│   ├── scripts/              # download_face_models.py
│   ├── app/
│   │   ├── api/v1/           # auth, onboarding, employees, documents, verification,
│   │   │                     #   tasks, knowledge, chat, dashboard, search,
│   │   │                     #   notifications, reports, users, audit
│   │   ├── core/             # config, database, security, deps (RBAC), errors,
│   │   │                     #   types, middleware, ratelimit
│   │   ├── models/           # SQLAlchemy models + enums
│   │   ├── schemas/          # Pydantic request/response contracts
│   │   ├── services/
│   │   │   ├── ocr/          # OCR engine interface + Tesseract + stub
│   │   │   ├── extraction/   # field extractors, resume parser, pipeline
│   │   │   ├── face/         # face matcher interface + OpenCV DNN + stub
│   │   │   ├── verification.py   # mock Aadhaar/PAN registry
│   │   │   ├── assignment.py # DB-driven rule engine + checklist sync
│   │   │   ├── review.py     # status transitions + verification orchestration
│   │   │   ├── notifications.py  # event fan-out + scheduled task reminders
│   │   │   ├── reports/      # shared datasets + excel/pdf/csv renderers
│   │   │   └── storage.py, email.py, audit.py, invitation.py
│   │   ├── seed.py           # bootstrap admin + optional demo data
│   │   ├── seed_tasks.py     # starter task catalogue + rules
│   │   └── main.py
│   └── tests/                # 483 tests (pytest)
├── frontend/
│   └── src/
│       ├── pages/            # Login, AcceptInvite, Dashboard, Employees,
│       │                     #   MyTasks, OnboardingRules, Notifications,
│       │                     #   Reports, Users, Audit…
│       ├── components/       # Layout, RequireAuth, Document*, ExtractionReview,
│       │                     #   VerificationPanel, DocumentReviewActions,
│       │                     #   TaskList, EmployeeTasksPanel, GlobalSearch,
│       │                     #   NotificationBell, charts, shared UI
│       ├── context/          # AuthContext
│       └── lib/api.js        # API client with automatic token refresh
├── docker-compose.prod.yml   # production-shaped stack (API + web + Postgres)
├── .github/workflows/ci.yml  # tests on SQLite *and* Postgres, builds, images
└── docs/
```

---

## Getting started

### 0. Install Tesseract (OCR) and fetch the face models

```bash
brew install tesseract          # macOS
sudo apt install tesseract-ocr  # Debian/Ubuntu
```

Optional — set `OCR_ENGINE=stub` to run without it (uploads still work; no text is extracted).

```bash
cd backend && python scripts/download_face_models.py
```

Downloads two Apache-2.0 ONNX models (~37 MB total) from the OpenCV Zoo, with pinned
checksums. Without them face matching reports "not configured" rather than a fake result;
set `FACE_MATCHER=stub` to make that explicit.

### 1. Start the services

Requires **Docker Desktop**.

```bash
docker compose up -d
```

| Service | Address | Purpose |
|---|---|---|
| PostgreSQL | `localhost:5433` | Application database + pgvector (5433 leaves a local 5432 undisturbed) |
| Adminer | <http://localhost:8081> | Database web UI |
| MinIO | `localhost:9000` | S3-compatible document storage |
| MinIO console | <http://localhost:9001> | Bucket browser (`officeiq` / `officeiq123`) |

The `minio-init` one-shot container creates the `officeiq-documents` bucket on first start.

### 2. Backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env          # then set a real SECRET_KEY
alembic upgrade head          # create the schema
python -m app.seed --demo     # bootstrap admin + HR user + sample employees
python -m app.seed_tasks      # starter task/training catalogue + assignment rules
python -m app.seed_knowledge  # starter HR policy knowledge base (chunked + embedded)

uvicorn app.main:app --reload
```

API: <http://localhost:8000> · Interactive docs: <http://localhost:8000/docs>

### 3. Frontend

```bash
cd frontend
npm install
npm run dev
```

App: <http://localhost:5173> (Vite proxies `/api` to the backend, so no CORS setup is needed in dev.)

### Default credentials (from `python -m app.seed --demo`)

| Role | Email | Password |
|---|---|---|
| Admin | `admin@officeiq.dev` | `Admin@12345` |
| HR | `hr@officeiq.dev` | `Hr@123456` |
| Employee | `employee@officeiq.dev` | `Employee@12345` |

Sign in as the employee to see the other half of the product — onboarding, the
checklist, the assistant, the holiday calendar and leave requests all look different
from that side. HR is linked to an employee record too, which is what makes the
self-approval guard visible: HR can submit a leave request, see it in the queue they
work, and be unable to decide it.

The seed is idempotent, so running it twice adds nothing.

Change these before any shared or deployed environment — `production_problems()` refuses
to start a production process that is still using the default admin password.

---

## Reading invitation emails in development

`EMAIL_BACKEND=file` writes every outgoing message to `backend/outbox/` as a plain-text file.
Open the newest file and follow the `accept-invite?token=…` link to complete registration as
the invited employee — no mail server or API key required.

Switch to real delivery with either backend, no code changes:

- `EMAIL_BACKEND=smtp` plus the `SMTP_*` variables.
- `EMAIL_BACKEND=brevo` plus `BREVO_API_KEY`. Delivery goes over HTTPS rather than SMTP,
  which matters because many hosting platforms block outbound SMTP ports. Note this is
  Brevo's API key (`xkeysib-`), not its separate SMTP key — the relay rejects the API
  key. `EMAIL_FROM` must be a sender verified in the Brevo dashboard.

---

## How document extraction works

1. **Upload** — the file's true type is determined from its magic bytes, not the client's
   `Content-Type` or filename. Size and type are enforced server-side; the original filename
   is kept for display only and never used as a path.
2. **Store** — saved under `employees/{id}/{type}/{uuid}{ext}` in object storage.
3. **Extract** — runs in a background task. A PDF with an embedded text layer is read directly
   (exact, confidence `1.0`); anything else is rasterised and passed to Tesseract.
4. **Score** — each field gets a confidence combining OCR character confidence with format
   validation: Aadhaar numbers are checked with the **Verhoeff checksum** and PAN against its
   character grammar, so a single misread digit scores far below the review threshold.
5. **Review** — HR sees every field with its confidence; anything under
   `OCR_LOW_CONFIDENCE_THRESHOLD` (default 0.70) is flagged. Corrections are stored alongside
   the original OCR value rather than overwriting it.
6. **Apply** — chosen fields are copied onto the employee profile. Aadhaar and PAN numbers are
   deliberately **never** written to profile columns; they are verification inputs for Phase 3.

### Swapping the OCR engine

Nothing outside `app/services/ocr/` depends on Tesseract. To move to a cloud OCR provider,
add a class implementing `OcrEngine` (`is_available`, `image_to_result`), register it in
`get_ocr_engine()`, and change `OCR_ENGINE` in the environment.

---

## How verification and review work

### Mock ID verification

> **No government API is contacted.** Aadhaar/PAN checks run against a simulated registry
> (PRD A.4.2). Every result records `provider: mock-uidai-nsdl` and `is_mock: true`, so a mock
> pass can never be mistaken for a real identity verification.

Outcomes are deterministic, derived from the number itself:

| Condition | Result |
|---|---|
| Fails Verhoeff (Aadhaar) or PAN grammar | `failed` · `checksum_failed` / `invalid_format` |
| In the reserved test range | `failed` · `not_found_in_registry` |
| Valid, but the name on the ID differs from the profile | `failed` · `name_mismatch` |
| Otherwise | `passed` · `verified` |

Only a **masked** number is ever persisted (`XXXX XXXX 2346`); the full value never reaches
`verification_checks` or `audit_logs`.

### Face matching

YuNet detects faces, SFace embeds them, and cosine similarity is compared against
`FACE_MATCH_THRESHOLD` (0.363). "No face found" is reported separately from "faces differ" —
the first is a re-upload the employee can fix, the second is a decision for HR. The threshold
is stored with each result so a later config change cannot silently reinterpret history.

To swap the matcher, add a class implementing `FaceMatcher` in `app/services/face/` and change
`FACE_MATCHER`.

### Review workflow and status transitions

Stages are derived from document state rather than set by hand, and never move backwards:

```
registered → documents_pending → documents_submitted → under_review
           → tasks_assigned → complete
```

Rejection **requires** a reason of at least 10 characters (PRD A.7.4), which is shown to the
employee so they know what to fix. `POST /employees/{id}/complete-onboarding` refuses while any
blocking issue remains and lists every one of them.

---

## Tasks, training and the checklist

### Rules live in the database, not in code

HR edits the catalogue and the rules in-app (**Rules** in the nav); changes take effect on the
next assignment run with no deploy. Seed a starter set with:

```bash
python -m app.seed_tasks
```

**Templates** are the catalogue: a title, a category (task / training / document checklist /
policy acknowledgement), a default due offset in days, and whether the item is mandatory.

**Rules** map employee attributes to templates. A blank condition means *any*:

| Rule | Department | Designation | Effect |
|---|---|---|---|
| All new joiners | *(any)* | *(any)* | baseline for everyone |
| Engineering | Engineering | *(any)* | adds secure-coding training |
| Finance | Finance | *(any)* | adds compliance training |

Evaluation is a **union** — every matching rule contributes, so an Engineering hire gets the
baseline *plus* the engineering extras. Union rather than first-match-wins means a department
rule and a designation rule compose the way HR expects instead of one silently suppressing the
other. When two rules select the same template, the **stricter** setting wins: the earlier due
date, and mandatory over optional.

`POST /assignment-rules/preview` (the **Preview** panel) shows exactly what a given
department/designation would receive, without creating anything.

### Assignment behaviour

- Triggered automatically when all required documents are approved (PRD A.6 step 7), and
  runnable on demand by HR.
- **Idempotent** — re-running never duplicates a task, so it is safe on every review pass.
- Task title/description are **snapshotted** at assignment, so editing a template later never
  rewrites an employee's history.
- Due dates are computed from `date_of_joining` where known, otherwise from the assignment date.

### Digital checklist

A `document_checklist` template names a `required_document_type`. The item **completes itself**
when a document of that type is approved — including one approved before the task existed. It
stays open while the document is merely uploaded, because uploading is not approval.

### Completion gating

Outstanding **mandatory** tasks block `complete-onboarding` and are listed in
`blocking_issues`. Optional tasks never block. Waiving requires a reason of at least 10
characters, and a waived task counts as closed.

---

## The AI assistant (RAG)

### Why embeddings come from Voyage, not Claude

**The Claude API has no embeddings endpoint** — it is Messages-only. Anthropic's documented
recommendation is Voyage AI, so generation and embeddings come from two different providers:

| Role | Provider | Config |
|---|---|---|
| Generation | Claude `claude-opus-5` | `CHAT_PROVIDER`, `ANTHROPIC_API_KEY` |
| Embeddings | Voyage `voyage-3` | `EMBEDDING_PROVIDER`, `VOYAGE_API_KEY` |
| Vector store | pgvector, same database | `EMBEDDING_DIMENSIONS` (must match both) |

Both sit behind interfaces (`app/services/chat.py`, `app/services/embeddings.py`) — swapping
either provider is one class plus an env var.

> ⚠️ **`EMBEDDING_PROVIDER=local` is not a production setting.** It is a deterministic hashing
> embedder that exists so the pipeline is testable with no API key. It matches *lexical
> overlap*, not meaning: "when are salaries **paid**" fails to retrieve a policy that says
> salaries are "**credited** on the last working day". Set `VOYAGE_API_KEY` for real use.

### Pipeline

1. **Ingest** — HR adds a document; it is split on headings (ALL-CAPS, `1.2`, or Markdown),
   each chunk is prefixed with its heading so the embedder gets topical context, embedded,
   and stored in a `vector(1024)` pgvector column.
2. **Retrieve** — the question is embedded and ranked by cosine distance (`<=>`) in SQL.
   Chunks below `RETRIEVAL_MIN_SIMILARITY` are dropped. Only **published, fully-ingested**
   documents are searchable.
3. **Generate** — Claude receives the numbered passages and a system prompt that forbids
   answering from anything else, and is told to emit `INSUFFICIENT_CONTEXT` when the passages
   don't cover the question.
4. **Gate** — confidence blends retrieval strength with whether the model could actually
   answer. Below `CHAT_ESCALATION_THRESHOLD`, or on the insufficient-context marker, the
   employee gets an escalate-to-HR message instead of the model's text.

### Anti-hallucination guarantees

The PRD's top chatbot risk is inventing policy (A.11). Four independent defences:

- The system prompt restricts the model to the supplied passages and names the failure mode
  explicitly ("a plausible answer that isn't this company's policy is worse than no answer").
- An `INSUFFICIENT_CONTEXT` marker is never shown to the employee — it becomes an escalation.
- The **confidence gate** escalates even when the model produced fluent text, if retrieval was
  too weak to support it.
- A safety `stop_reason: "refusal"` escalates rather than surfacing the refusal.

Every answer carries **citations** (document, heading, source reference, similarity), so an
employee can check the claim against the handbook.

### Privacy

Chat conversations are private to the employee who had them — **HR and Admin cannot read them
through the API**. HR sees aggregate `/chat/analytics` (resolution rate, escalation reasons),
which is what the PRD A.10 KPI needs, without reading individual transcripts.

### Diagnosing a bad answer

`POST /knowledge/search` (the **Test retrieval** panel on the Knowledge page) shows exactly
which passages a question retrieves and at what similarity — usually the fastest way to tell a
retrieval problem from a generation problem.

---

## The HR dashboard, search and notifications

### Dashboard

`GET /dashboard/summary` is the headline row: headcount by state, mean days from
profile creation to completion, documents waiting on a decision, overdue tasks, task
completion rate, and the assistant's resolution rate. Where a metric already exists
elsewhere it runs **the same aggregation** rather than a lookalike — the resolution
rate here and on `/chat/analytics` are computed identically, so the two screens can
never disagree.

Three more endpoints back the rest of the page:

| Endpoint | Answers |
|---|---|
| `/dashboard/funnel` | how many people sit at each onboarding stage |
| `/dashboard/departments` | headcount and progress per department |
| `/dashboard/trends?days=` | daily profiles created, registrations, completions, uploads, questions |
| `/dashboard/attention?limit=` | the four work queues below |

**The attention queue** is the part HR actually works from: documents whose extraction
finished and now need a decision (oldest first), failed ID checks, overdue tasks
(worst first), and onboardings that have not moved in `ONBOARDING_STALLED_DAYS`.
Each group reports its **true `total` alongside a capped `items` list**, so a backlog
longer than the cap is stated rather than silently truncated.

Trends are day-bucketed in Python rather than SQL: date truncation is spelled
differently in Postgres and SQLite, the window is bounded, and the portable version
costs nothing measurable.

> **Charts.** The funnel and the three activity sparklines are hand-written inline
> SVG — no charting dependency. Each plots a **single series**, so no legend is
> needed and no colour has to stand for identity; the three activity measures are
> **small multiples** rather than one plot, because three unrelated scales sharing
> one y-axis would invent a relationship the data does not contain. Every value the
> hover tooltip shows is also reachable without hovering, through the funnel's inline
> labels and each sparkline's table view.

### Global search

`GET /search?q=` is **navigational** — a fast jump to a record you already know
exists. It matches literal substrings, case-insensitively, across employees,
documents, tasks and knowledge documents, and returns them grouped with a link and a
status badge. `/` focuses the box; arrow keys and Enter work the list.

It deliberately does *not* use embeddings. `POST /knowledge/search` is the semantic
path; quietly returning conceptually-similar-but-differently-named records in a
jump-to box would make it unpredictable.

**Scoping happens in the query, not after it.** An employee's search never loads rows
they are not allowed to see: the Employees group is not offered to them at all, their
document and task groups are restricted to their own records, and unpublished
knowledge documents are excluded.

### Notifications

One row per recipient per event, written **in the same transaction as the event
itself** — a notification saying "your document was approved" cannot survive a
transaction that failed to approve it.

| Event | Reaches |
|---|---|
| Document uploaded | HR/Admin (never the person who uploaded it) |
| Document approved / rejected | the employee — the rejection reason *is* the body |
| Tasks assigned | the employee, once; re-running the idempotent engine adds nothing |
| ID verification failed | HR/Admin |
| Invitation accepted | HR/Admin |
| Onboarding complete | the employee and HR/Admin |
| Assistant could not answer | HR/Admin — **the question only**, never the transcript |
| Task due soon / overdue | the employee, via the reminder sweep |

The actor is excluded from their own operational event, and an employee who has not
registered yet has no account to notify, so nothing is queued for them.

**Inboxes are private.** Every route is scoped to the signed-in user's own rows;
there is no path for any role, Admin included, to read someone else's. Fetching by id
matches on owner too, so a wrong guess returns 404 rather than confirming the row
exists.

**Reminders** are a sweep, not a background thread: `POST /notifications/run-reminders`
is the hook a scheduler calls. It is idempotent — a recipient who already has an
unread reminder for a task does not get a second one — so it is safe to run as often
as you like. HR can also trigger it by hand from the Notifications page.

Set `NOTIFICATION_EMAIL_ENABLED=true` to additionally email employee-facing events
through the same pluggable backend invitations use. HR-facing events stay in-app on
purpose: HR lives in the product, and a mailbox full of "a document was uploaded" is
noise.

---

## Reports, the audit trail and your account

### Reports

`GET /reports` lists what the signed-in role may export; `GET /reports/{key}?format=`
returns the file. Six reports, three formats each:

| Report | Contains | Access |
|---|---|---|
| `employee_roster` | every profile with employment details and stage | HR, Admin |
| `onboarding_status` | stage, elapsed days, missing approvals, open mandatory tasks | HR, Admin |
| `document_compliance` | a column per required document type, plus failed ID checks | HR, Admin |
| `task_completion` | per-employee task progress, least complete first | HR, Admin |
| `audit_trail` | filtered export of the audit log | **Admin** |
| `user_accounts` | staff accounts, roles and last sign-in, for access review | **Admin** |

**One dataset, three renderers.** `services/reports/datasets.py` decides *what* a
report contains; `excel.py`, `pdf.py` and the CSV writer decide only how it looks. The
three formats of a report therefore cannot disagree about a number — there is one query
behind all of them, and a test asserts the Excel and CSV renderings match row for row.

Each format has a job: **Excel** ships a frozen, auto-filtered header row for sorting
and pivoting; **PDF** is landscape A4 with a title block, repeating headers and page
numbers, for attaching to a compliance pack; **CSV** is the bare table with a UTF-8 BOM
so Excel opens accented names correctly.

Caps are stated, never silent. The audit export stops at the 5,000 most recent matching
entries and the PDF at 1,200 rows — in both cases the file says so on its own face and
tells the reader how to get the rest.

**Every export is audited**, with its format, row count and the filters that were
actually applied. A report is company data leaving the system, which is exactly what an
audit trail is for.

### Audit trail

Still append-only — no update or delete path exists anywhere in the codebase. Phase 7
adds the surface for reading it: filter by action, actor (substring), entity type,
entity id and date range, click any row for the full entry including its user agent and
pretty-printed detail, and export the current filter as CSV.

`GET /audit-logs/facets` returns the actions, entity types and actors **actually
present**, so the filter dropdowns never offer a dead option and never miss an action
written by an older build. The list and the export share one `build_audit_filters`
function, so "what this filter means" is defined once.

A date range is inclusive of its end day: "to 5 March" includes everything that
happened on 5 March, which is what anyone typing that date means.

### Your account

The profile page answers three questions: who am I, who else is signed in as me, and
what have I been doing.

**Signed-in devices** lists active refresh tokens with the browser, platform, IP and
last-used time recorded at sign-in — enough to recognise your own sessions and revoke
one you don't. Revoked and expired sessions are omitted rather than greyed out, because
the question is "who can get in right now?". Sessions are matched on owner *and* id, so
a wrong id returns 404 rather than confirming somebody else's session exists.

> Revoking a session revokes its **refresh** token. Access tokens are stateless and keep
> working until they expire, which is `ACCESS_TOKEN_EXPIRE_MINUTES` (30 by default) —
> the UI says so rather than implying an instant kill.

**Recent account activity** shows audit entries where *you* are the actor. It is not a
window into the organisation-wide trail; that stays on the Admin-only audit log.

---

## Hardening and deployment

### The API refuses to start misconfigured

Every development convenience in this project is *silent* when it is wrong. A stub OCR
engine still returns 200s. A `file` email backend still "sends" invitations. The default
`SECRET_KEY` still issues tokens that look valid. The failure mode is a system that
looks healthy while doing nothing real.

So when `ENVIRONMENT=production`, the process checks itself at import and **refuses to
boot** if any of these is true, listing every problem at once:

| Category | Refused |
|---|---|
| Secrets | default or short `SECRET_KEY`, default `FIRST_ADMIN_PASSWORD`, `DEBUG=true` |
| Infrastructure | SQLite `DATABASE_URL`, `console`/`file` email, `local` storage |
| AI/OCR shims | `OCR_ENGINE=stub`, `FACE_MATCHER=stub`, `CHAT_PROVIDER=stub`, `EMBEDDING_PROVIDER=local` |
| Missing keys | Claude without `ANTHROPIC_API_KEY`, Voyage without `VOYAGE_API_KEY`, S3 without credentials |
| Network | `*` in `CORS_ORIGINS`, empty `CORS_ORIGINS`, any plain-http origin or frontend URL |

A container that will not start is a far cheaper failure than one that quietly drops
every invitation email. Each message names the *consequence*, not just the variable —
`EMBEDDING_PROVIDER=local` reports that retrieval will return the wrong policies.

### Security headers, correlation IDs and logging

Every response carries `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`,
`Referrer-Policy: no-referrer`, a `Permissions-Policy` denying camera/mic/geolocation,
and `Content-Security-Policy: default-src 'none'; frame-ancestors 'none'` — this is a
JSON API, so nothing legitimately loads anything. `/docs` is exempt, since a CSP that
blocks Swagger's CDN breaks the documentation rather than protecting anyone. HSTS is
sent only in production **and** only over https; pinning `localhost` to https for a year
would be a hostile thing to do to a developer's browser.

Every request gets an id — a sanitised, length-capped client-supplied
`X-Request-ID` if there is one, so a trace can span the frontend and a proxy, otherwise
a fresh one. It is echoed in the response and printed in every log line for that
request, including logs from third-party libraries. Requests slower than
`SLOW_REQUEST_MS` are logged at WARNING against the **route pattern**, not the resolved
path, so per-endpoint timings aggregate instead of scattering across every UUID.

### Rate limiting

Four routes are limited, chosen because abuse there is cheap for the attacker and
expensive for us:

| Route | Default | Keyed by | Why |
|---|---|---|---|
| `POST /auth/login` | 10/minute | IP | The account lockout stops one account being brute forced; it says nothing about one IP trying a thousand *different* accounts |
| `POST /auth/forgot-password`, `/reset-password` | 5/hour | IP | Unauthenticated and sends email — a loop is a way to spam someone else's inbox from our domain |
| `POST /chat/ask` | 20/minute | user | Every question costs a model call, in money |
| `GET /reports/{key}` | 30/hour | user | Every export scans and renders the whole table |

Authenticated routes key by **account, not IP**, so a whole office behind one NAT
address does not share a single allowance. A 429 always carries `Retry-After`.

> ⚠️ **The default backend is in-memory, and that means something.** Counters live in
> one process: exact with a single worker, and with N workers a client effectively gets
> N times the limit. A restart forgets everything. That is a deliberate trade to avoid a
> Redis dependency in v1, and it buys protection from scripted abuse, not from a
> distributed attacker. `RateLimitBackend` is the seam — a Redis implementation is one
> class and no call-site changes. This is also why the Docker image defaults to one
> worker per container and scales with replicas.

### Health probes

Two endpoints, because they answer different questions:

- **`GET /health`** — liveness. Touches nothing external. A liveness probe that queries
  the database restarts a healthy container every time the database blips, turning a
  recoverable outage into a crash loop.
- **`GET /health/ready`** — readiness. Checks the database, object storage, *and* the
  production configuration, returning **503** when any fails so a load balancer stops
  routing here instead of serving errors. Failure detail names the exception type and
  the dependency — never a connection string or a credential.

### Performance

Connection-pool size, overflow, timeout and recycle are configurable; recycle sits below
typical proxy idle timeouts so a stale socket is replaced before a query finds it dead.
Set `SLOW_QUERY_MS` above zero to log slow statements — with parameters omitted, since
they routinely carry personal data and a log line is the last place it should surface.
The timing hooks are only registered when the setting is on, so the fast path is not
taxed to measure nothing. Responses above `GZIP_MIN_SIZE_BYTES` are compressed.

**A production bug this phase caught.** The Postgres test run failed with
`cached plan must not change result type`, which SQLite could never have shown. psycopg3
caches a server-side plan after a statement runs a few times; if the table's shape then
changes under a pooled connection, the next execution fails. That is not just a test
artefact — it is what happens during a rolling migration that adds a column while older
connections are still checked out, and it is why prepared statements are incompatible
with PgBouncer in transaction-pooling mode. `prepare_threshold=None` is now set for
psycopg connections. The cost is re-planning each statement; the benefit is that a
deploy cannot half-break the API until every worker restarts.

### Running it in production

```bash
cp backend/.env.example .env.production   # then fill in real values
docker compose -f docker-compose.prod.yml --env-file .env.production up -d --build
```

The stack builds the API and the frontend as images and runs them in front of Postgres.
Notable choices:

- **Migrations run in their own one-shot container** that the API waits on, so N
  replicas cannot race each other to migrate.
- **Every value comes from the environment with no default.** A compose file with a
  working default password is a compose file that ships with a working default password.
- **The API image runs as a non-root user**, installs no compiler toolchain in the
  runtime layer (wheels are built in a discarded stage), and its `HEALTHCHECK` uses
  liveness — restarts are for a dead process, not a dependency outage.
- **Postgres publishes no port.** Only the API reaches it, over the compose network.
- **nginx serves the frontend and proxies `/api`**, so the browser stays on one origin
  and production needs no CORS preflight at all. Hashed assets are cached for a year;
  `index.html` is never cached, because a stale copy pins the whole app to a previous
  deploy.

The web image is ~76 MB. The API image is ~1.5 GB, and honestly so: OpenCV, PyMuPDF,
NumPy and the Tesseract system package are most of it. Trimming it means giving
something up — dropping face matching or OCR to a separate worker image — which is a
scaling decision, not a packaging one.

Two things this deliberately does **not** do, because they belong to whatever runs it:
terminate TLS (put a load balancer or Caddy in front — the app sets HSTS once it sees
https) and back up the database volume.

### CI

Building the image is also how a genuine packaging bug surfaced: `requirements.txt`
pinned `voyageai==0.3.2`, which declares `Requires-Python <3.13` and therefore could
never install on this project's own Python version. It only ever worked because the
development venv predated the pin. Nothing but a from-scratch build could have caught
it — the tests all pass, because they run against the installed environment rather than
the file that claims to describe it. Both stale pins are corrected, and the CI job below
now builds the images on every push so the file cannot drift again.

`.github/workflows/ci.yml` runs four jobs on every push and pull request: the test suite
on SQLite (the fast signal), the same suite against **real Postgres with pgvector**,
plus `alembic check` and a full `downgrade base` → `upgrade head` round-trip, the
frontend build, and both Docker images. The Postgres job exists precisely because of the
prepared-statement bug above: the things that only a real database shows — enum types,
cascades, pgvector, and plans surviving a schema change — are worth a slower job.

---

## Tests

```bash
cd backend
source .venv/bin/activate
pytest
```

483 tests run against a throwaway SQLite file, so no database service is needed for CI.
Coverage spans login and token lifecycle, account lockout, password reset, RBAC boundaries,
employee CRUD, the full invitation journey, audit-log completeness, upload validation
(including magic-byte sniffing and path-traversal filenames), signed download tokens,
Aadhaar/PAN validators, field extraction, resume parsing, the extraction pipeline,
rule matching and union semantics, idempotent assignment, checklist auto-completion,
heading-aware chunking, vector retrieval ranking, the anti-hallucination escalation
gate, chat privacy boundaries, every dashboard aggregate (including the empty-workspace
case and the capped-queue totals), search role-scoping and literal wildcard handling,
notification fan-out, inbox privacy and reminder idempotency, report content and
access control in all three formats (including that Excel and CSV agree), audit
filtering and facets, session revocation boundaries, and the Phase 8 hardening: every production guardrail
individually, security headers on success *and* error paths, request-id sanitisation,
rate limiting per IP and per account, and readiness returning 503 without leaking a
connection string.

`tests/test_ocr_real.py` (live Tesseract), `tests/test_face_match_real.py` (real OpenCV
DNN models), and `tests/test_chat_real.py` (live Claude + Voyage APIs) all **skip
automatically** when their dependency or API key is absent, so CI stays green either way.

To run the same suite against real PostgreSQL (recommended before a release):

```bash
docker exec officeiq-postgres psql -U officeiq -d postgres -c "CREATE DATABASE officeiq_test OWNER officeiq;"
TEST_DATABASE_URL=postgresql+psycopg://officeiq:officeiq@localhost:5433/officeiq_test pytest
```

Both paths are verified green. You can also confirm the migration matches the ORM models with
`alembic check`.

---

## API surface (v1)

All routes are under `/api/v1`. Every error uses one envelope:

```json
{ "status": 403, "error": { "code": "forbidden", "message": "…", "details": null } }
```

| Method | Path | Access |
|---|---|---|
| POST | `/auth/login` · `/auth/refresh` · `/auth/logout` | public / signed in |
| GET | `/auth/me` | signed in |
| POST | `/auth/forgot-password` · `/auth/reset-password` | public |
| GET | `/onboarding/invitation?token=` | public (token) |
| POST | `/onboarding/accept` | public (token) |
| GET/POST | `/employees` | HR, Admin |
| GET/PATCH | `/employees/me` | Employee |
| GET/PATCH | `/employees/{id}` | HR, Admin (own record for Employee on GET) |
| DELETE | `/employees/{id}` | Admin |
| GET | `/employees/{id}/invitations` | HR, Admin |
| POST | `/employees/{id}/invite` · `/invite/revoke` | HR, Admin |
| GET/POST | `/employees/{id}/documents` | HR, Admin, own Employee |
| GET/DELETE | `/documents/{id}` | HR, Admin, own Employee |
| POST | `/documents/{id}/reprocess` | HR, Admin |
| GET | `/documents/{id}/download-url` | HR, Admin, own Employee |
| GET | `/documents/{id}/download?token=` | signed token only |
| PATCH | `/documents/{id}/fields/{field_id}` | HR, Admin, own Employee |
| POST | `/documents/{id}/apply-to-profile` | HR, Admin, own Employee |
| POST | `/documents/{id}/verify` | HR, Admin |
| POST | `/documents/{id}/approve` · `/reject` | HR, Admin |
| POST | `/employees/{id}/face-match` | HR, Admin |
| GET | `/employees/{id}/verifications` · `/face-matches` | HR, Admin, own Employee |
| GET | `/employees/{id}/verification-summary` | HR, Admin, own Employee |
| POST | `/employees/{id}/complete-onboarding` | HR, Admin |
| GET/POST | `/task-templates`, PATCH/DELETE `/task-templates/{id}` | HR, Admin (delete: Admin) |
| GET/POST | `/assignment-rules`, PATCH/DELETE `/assignment-rules/{id}` | HR, Admin |
| POST | `/assignment-rules/preview` | HR, Admin |
| POST | `/employees/{id}/assign-tasks` | HR, Admin |
| GET/POST | `/employees/{id}/tasks` | HR, Admin (GET: own Employee) |
| GET | `/employees/{id}/task-progress` | HR, Admin, own Employee |
| PATCH/DELETE | `/tasks/{id}` | HR, Admin, own Employee (delete: HR) |
| POST | `/tasks/{id}/waive` | HR, Admin |
| GET | `/my-tasks` · `/my-task-progress` | Employee |
| GET | `/knowledge/stats` | HR, Admin |
| GET/POST | `/knowledge/documents`, PATCH/DELETE `/knowledge/documents/{id}` | HR, Admin |
| POST | `/knowledge/documents/{id}/reingest` · `/knowledge/search` | HR, Admin |
| POST | `/chat/ask` | any signed-in user |
| GET | `/chat/conversations`, GET/DELETE `/chat/conversations/{id}` | owner only |
| GET | `/chat/analytics` | HR, Admin |
| GET | `/dashboard/summary` · `/funnel` · `/departments` · `/trends` · `/attention` | HR, Admin |
| GET | `/search?q=` | signed in (results scoped to role) |
| GET | `/notifications` · `/notifications/unread-count` | owner only |
| POST | `/notifications/{id}/read` · `/notifications/read-all` | owner only |
| DELETE | `/notifications/{id}` | owner only |
| POST | `/notifications/run-reminders` | HR, Admin |
| GET | `/reports` | HR, Admin |
| GET | `/reports/{key}?format=xlsx\|pdf\|csv` | HR, Admin (two are Admin-only) |
| GET | `/profile/sessions` · `/profile/activity` | owner only |
| DELETE | `/profile/sessions/{id}` | owner only |
| POST | `/profile/sessions/revoke-all` | owner only |
| GET | `/audit-logs/facets` · `/audit-logs/{id}` | Admin |
| GET | `/health` · `/health/ready` | public (no credentials to offer) |
| GET/PATCH | `/profile`, POST `/profile/password` | signed in |
| GET/POST | `/users`, PATCH `/users/{id}` | Admin |
| GET | `/audit-logs` | Admin |

---

## Roadmap

| Phase | Scope | Status |
|---|---|---|
| 1 | Auth, roles, employee profile CRUD, invitation flow | ✅ Complete |
| 2 | Document upload + OCR extraction + resume parsing | ✅ Complete |
| 3 | Mock verification + face matching + HR review/approval | ✅ Complete |
| 4 | Task/training assignment engine + digital checklist | ✅ Complete |
| 5 | AI chatbot (RAG) on company knowledge base | ✅ Complete |
| 6 | HR dashboard, analytics, search, notifications | ✅ Complete |
| 7 | Reports (Excel/PDF), audit logs, profile polish | ✅ Complete |
| 8 | Hardening: security review, performance, integration readiness | ✅ Complete |

### Employee self-service modules

Built after the PRD phases, on the same foundations.

| Module | Scope | Status |
|---|---|---|
| Holiday Calendar | Company holiday list, HR-managed, upcoming highlighted | ✅ Complete |
| Request & Approval Engine | Generic submit → route → decide, pluggable request types | ✅ Complete |
| Leave Application | Balances, accrual and deduction, built on the request engine | ✅ Complete |
| Rewards & Recognition | — | Not started |
| Goals & Achievements | — | Not started |
| Payslip (read-only) | — | Not started |

#### Leave entitlements come from the handbook

The Annual Leave Policy and Sick Leave documents in the knowledge base define 21 days
annual (accruing at 1.75 a month, pro-rated for mid-year joiners, up to 10 carried
forward) and 12 days sick (no carry-forward). Those are the numbers the leave module
enforces, because they are the numbers the assistant quotes — an employee told "21 days"
who then sees a different figure has been given two answers by one system.

Casual leave is deliberately absent for the same reason: the handbook does not mention
it, so the assistant could not answer questions about a type the app enforced. Unpaid
leave carries no balance and is always available, which is what the "you have only N
days left" refusal points at.

Balances are stored counters, written in the same transaction as the approval that
causes them, so displaying a balance is one row read rather than a scan over requests.
The risk of a cached figure is drift, so `recompute_used_days()` rebuilds it from the
requests themselves and a test asserts the two agree after a mixed sequence of
approvals, rejections and withdrawals.

#### How a new request type is added

The engine never branches on request type. Adding one — WFH, equipment, expenses — is:

1. a value on `RequestType`
2. a payload model registered with `@payload_for(RequestType.X)`
3. a form component

`submit`, `approve`, `reject` and `cancel` are untouched. The alternative considered was
a database-driven form builder, which buys a new type without a migration at the cost of
a dynamic form renderer and the loss of typed validation — not worth it for a small,
known set of types.

Requests carry an `assigned_to_id` that is currently always null, meaning the HR/Admin
pool. There is no manager role and `Employee.reporting_manager` is free text, so there
is nobody specific to route to; when a hierarchy exists, one function changes and
nothing downstream has to know.
