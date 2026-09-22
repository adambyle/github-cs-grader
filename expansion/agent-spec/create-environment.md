---
author: Claude Opus 5.5 (AI agent), written for Adam Byle, 2026-09-22
---

# Plan: the development environment

How the repository will be set up so that `docker compose up` gives a running
Flask server, a background worker, a TypeScript compiler watching for changes,
and GitHub webhooks forwarded from smee.io. This plan covers only the scaffolding;
features come in later specs.

## Is Docker the only dependency?

**Yes, to run and develop the app.** Python, pip packages, Node/TypeScript and the
smee client all run inside containers. The machine needs:

| Tool | Required? | Why |
|---|---|---|
| Docker Desktop (WSL 2 backend, Compose v2) | **Required** | Runs everything |
| git | Required (already there) | It's a git repository |
| A local Python venv | Optional | Editor autocomplete, type hints and linting in VS Code. The app never runs from it |
| Python, Node, `gh` on the host | Optional | Only for the **existing CLI** and its tests (`python tests/run_tests.py`), which are unchanged by this plan |

`environment.md` asks for a virtual environment and pip. The image installs
packages with pip into a venv at `/opt/venv`, and the same requirements files
build the optional local `.venv`. That satisfies the instruction both inside and
outside Docker.

## Decisions made here

| Decision | Choice | Reason |
|---|---|---|
| Python version | 3.14 (`python:3.14-slim`) | Matches your local Python, so the optional venv and the container agree |
| Where the new code lives | New package `webapp/` next to `coursekit/` | Leaves the CLI working and available for reference. Web code can import its pure logic (e.g. the restore-list and `complete` rules) where that fits |
| Database access | SQLAlchemy 2 via Flask-SQLAlchemy, migrations via Flask-Migrate (Alembic) | The standard Flask stack. Keeps SQLite now and PostgreSQL possible later (see deploy.md) |
| Background jobs | **Huey** with its SQLite storage | Grading must not run inside a web request (webhook 10-second limit, page load times). Huey needs no extra server: a single SQLite file holds the queue. Redis + RQ is the upgrade path if it's ever needed |
| GitHub API | Plain `httpx` + `PyJWT[crypto]` in a small wrapper module | Mirrors the existing `coursekit/ghcli.py` call for call, so porting is easy to read. Signing the App's JWT and exchanging it for an installation token is about 40 lines. It avoids a big SDK whose abstractions hide the REST calls |
| Frontend | TypeScript compiled by `tsc` alone, no bundler | `goals.md`: simple TypeScript and HTML, not a single-page app. One `.ts` file per page, compiled to `webapp/static/js/` |
| Data storage | A **named Docker volume**, not a folder in the repo | SQLite's file locking is unreliable across Docker Desktop's Windows→Linux bind mounts, which leads to "database is locked" errors or corruption. A named volume lives inside the Linux VM, where locking works |

## Files to add

```
.gitattributes          force LF line endings (see "Windows notes")
.dockerignore           keep .git, .venv, .env, node_modules and *.pem out of the image
.env.example            every variable, empty; copied to .env and filled in by you
Dockerfile              one image for web and worker; `dev` and `prod` stages
compose.yaml            the four development services
requirements.txt        runtime packages
requirements-dev.txt    -r requirements.txt, plus test and lint tools
pyproject.toml          ruff and pytest settings only (no packaging)
webapp/
  __init__.py           create_app(): config, database, blueprints
  config.py             reads environment variables; fails loudly if one is missing
  extensions.py         db, migrate
  tasks.py              the Huey instance, and a `ping` task to prove the worker runs
  github/
    app_auth.py         App JWT, installation tokens (cached until shortly before expiry)
    webhooks.py         POST /webhooks/github: verify signature, record, enqueue, return 202
  routes/
    health.py           GET /healthz
    dev.py              GET /dev/github: lists the App's installations (dev only; proves credentials)
  templates/base.html
  static/css/, static/js/ (compiled output, gitignored)
frontend/
  package.json          typescript as the only devDependency; package-lock.json committed
  tsconfig.json         outDir ../webapp/static/js, strict
  src/main.ts
tests_web/              pytest tests for webapp (the CLI's tests/ stays as is)
```

`.gitignore` gains: `.env`, `.venv/`, `*.pem`, `webapp/static/js/`,
`frontend/node_modules/`, `.pytest_cache/`, `.ruff_cache/`.

## Packages

Versions are pinned with `~=` when the files are created, taking the current
releases at that time. Checked against Python 3.14.

**requirements.txt (now)**

| Package | Purpose |
|---|---|
| Flask | The web framework |
| Flask-SQLAlchemy | SQLAlchemy 2 integration |
| Flask-Migrate | Alembic database migrations |
| httpx | Calls to the GitHub REST API and OAuth |
| PyJWT[crypto] | Signs the GitHub App JWT (RS256, which needs `cryptography`) |
| huey | Background job queue on SQLite |
| python-dotenv | Loads `.env` when running Flask outside Docker (optional venv) |
| gunicorn | Production server. Installed now so dev and prod images match |

**Added when the feature arrives (not now)**

| Package | Feature |
|---|---|
| docker | Starting sandboxed grading containers (sandboxing spec) |
| Flask-WTF | CSRF protection, with the first form |
| markdown-it-py, nh3 | Rendering instructor-uploaded instructions, **sanitized**, because the HTML is shown to students |

**requirements-dev.txt**

| Package | Purpose |
|---|---|
| pytest | Tests |
| respx | Fakes GitHub's API in tests (for `httpx`), like the CLI's `tests/fake_gh.py` |
| ruff | Linting and formatting |

**frontend/package.json:** `typescript` only.

## Dockerfile

```dockerfile
FROM python:3.14-slim AS base
RUN apt-get update \
 && apt-get install -y --no-install-recommends git sqlite3 \
 && rm -rf /var/lib/apt/lists/*
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

FROM base AS dev
COPY requirements-dev.txt .
RUN pip install --no-cache-dir -r requirements-dev.txt
# Source is bind-mounted by compose, not copied.

FROM base AS prod
# Filled in at deployment: copy source and compiled JS, run as a non-root
# user, start gunicorn.
```

`git` is in the image because the server clones submissions. `sqlite3` is there so
you can inspect the database (`docker compose exec web sqlite3 /data/coursekit.db`).

## compose.yaml

Four services, one image:

| Service | Command | Notes |
|---|---|---|
| `web` | `flask --app webapp run --host 0.0.0.0 --port 5000 --debug` | Port `5000:5000`. Source bind-mounted at `/app`. Auto-reloads on save |
| `worker` | `huey_consumer webapp.tasks.huey` | Same mounts. Restarted with `docker compose restart worker` after changing task code. Later gets the Docker socket for sandboxing; `web` never does |
| `frontend` | `npx tsc --watch --preserveWatchOutput` in `node:22-slim` | Writes to `webapp/static/js/` through the bind mount |
| `smee` | `npx --yes smee-client --url $SMEE_URL --target http://web:5000/webhooks/github` in `node:22-slim` | Forwards GitHub webhooks to Flask. Downloads the client on first start |

Shared by `web` and `worker`:

- `env_file: .env`
- Named volume `coursekit-data` at `/data`, holding the database, the Huey queue
  file and repo checkouts
- The private key, mounted read-only:
  `${GITHUB_APP_PRIVATE_KEY_FILE}:/run/secrets/github-app.pem:ro`. The app reads
  it from the fixed container path, so your Windows path appears only in `.env`.

## .env.example

```
# From the GitHub App settings page
GITHUB_APP_ID=
GITHUB_APP_SLUG=            # the app's URL name, e.g. coursekit-dev-adambyle (used for the install link)
GITHUB_APP_CLIENT_ID=
GITHUB_APP_CLIENT_SECRET=
GITHUB_WEBHOOK_SECRET=
# Path ON YOUR MACHINE to the downloaded .pem; forward slashes work on Windows
GITHUB_APP_PRIVATE_KEY_FILE=C:/Users/adamb/.secrets/coursekit-dev.pem

SMEE_URL=

BASE_URL=http://localhost:5000
FLASK_SECRET_KEY=           # python -c "import secrets; print(secrets.token_hex(32))"
DATABASE_URL=sqlite:////data/coursekit.db
```

## Windows notes

- **Line endings.** This repo has `core.autocrlf=true`, so git checks files out
  with CRLF. Linux containers choke on CRLF in shell scripts and some configs
  (`/bin/sh^M: not found`). `.gitattributes` gets `* text=auto eol=lf`, then a
  one-time `git add --renormalize .` commit. This also fixes the existing `install`
  script if it is ever run from WSL.
- **File watching.** Change notifications don't always get through Windows→Linux
  bind mounts. Flask's reloader falls back to polling, which works. `tsc` is told
  to poll with `TSC_WATCHFILE=DynamicPriorityPolling` in the `frontend` service.
- **Performance.** Bind mounts from `C:\` are slower than the WSL filesystem. It's
  fine at this project's size. If it ever feels sluggish, clone the repo inside WSL
  (`\\wsl$\...`) and open it from there.

## Your steps once it's built

1. `copy .env.example .env` and fill it in from the App settings page. Get
   `GITHUB_APP_SLUG` from the App's public URL, `github.com/apps/<slug>`.
2. `docker compose up --build`
3. First time only: `docker compose exec web flask --app webapp db upgrade`
4. Optional, for your editor: `python -m venv .venv`, then
   `.venv\Scripts\pip install -r requirements-dev.txt`, then choose `.venv` as the
   interpreter in VS Code.

## How we'll know it works

| Check | Proves |
|---|---|
| `http://localhost:5000/healthz` returns `ok` | Flask is running and the database opens |
| `http://localhost:5000/dev/github` lists `coursekit-dev-26fa` | App ID and private key are correct, and the App is installed on the dev org |
| App settings → Advanced → Recent Deliveries → **Redeliver** the original `ping` (it failed when you created the App) → the `web` log shows it with signature **valid** | smee forwarding and the webhook secret work |
| A push to any repo in the dev org appears in the `web` log and then the `worker` log | The whole path works: webhook → queue → worker |
| `docker compose run --rm web pytest` and `docker compose run --rm web ruff check` pass | The test and lint setup works |

## Implementation order

1. `.gitattributes` and renormalize (a commit of its own, so the line-ending
   changes don't bury real changes)
2. `.gitignore`, `.dockerignore`, `.env.example`, requirements files, `pyproject.toml`
3. `Dockerfile` and `compose.yaml` with a hello-world `webapp`
4. Config loading, database, first migration, `/healthz`
5. Huey and the `ping` task in the worker
6. GitHub App auth and `/dev/github`
7. The webhook endpoint with signature checking, and the `smee` service
8. The `frontend` service with one compiled `main.ts` loaded by `base.html`
9. `tests_web/` covering config, signature checking and token caching

## Out of scope for this plan

Sign-in (GitHub OAuth), data models, grading, the sandbox, and production
configuration each get their own spec. This plan only creates places for them.

## Implementation notes (2026-09-22)

Built as planned, with these departures, each found while testing:

- **TypeScript is pinned to 6.0, not 7.** TypeScript 7 (the Go rewrite) never
  noticed edits made through the Windows bind mount: it ignores
  `TSC_WATCHFILE`, and `watchOptions` polling didn't help. 6.0 recompiles
  within a few seconds. Moving to 7 is just a version bump once its watcher
  supports polling. `tsconfig.json` also sets `moduleDetection: "force"`, because
  pages load the scripts as ES modules.
- **The App JWT's `iss` is the App ID** (`GITHUB_APP_ID`), not the client ID.
  The client ID is kept for GitHub sign-in (OAuth) later.
- **`/dev/worker`** was added beside `/dev/github`. It enqueues a ping task and
  waits for the worker's answer. Dev routes are on only when
  `COURSEKIT_DEV_ROUTES=1`, which compose.yaml sets for `web`.
- **`HUEY_DB`** (the queue file, `/data/huey.db`) was added to `.env.example`.
- **The first table is `webhook_deliveries`**, one row per verified webhook,
  unique on GitHub's delivery ID so redeliveries are ignored.
- **The `frontend` service keeps `node_modules` in an anonymous volume.** The
  Linux packages stay inside the container, and an empty `frontend/node_modules`
  folder appears on the host as the mount point.
- **Ruff formats the code**, and `migrations/` is excluded because Alembic
  generates it.

Verified with dummy credentials in a separate compose project, since torn down:
`/healthz`, `/dev/worker`, the Alembic migration, WAL mode, the `tsc` watcher, a
signed webhook through a real smee.io channel reaching the worker, a redelivery
ignored, a forged signature rejected, and `pytest` (15 tests) plus `ruff check`
passing. What dummy credentials can't show is `/dev/github` succeeding: with the
fake App ID GitHub answers "Integration not found", as it should.
