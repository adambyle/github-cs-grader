# coursekit

A web app for running programming courses on GitHub. Instructors create
courses and semester offerings, connect each offering to a GitHub
organization, and hand out assignments as private repositories. Students
sign in with GitHub and get feedback on their work.

**Status: early development.** What works today:

- Signing in with GitHub, as a student or an instructor
- Creating courses and semester offerings
- Connecting an offering to its GitHub organization
- Receiving GitHub webhooks

Rosters, assignments, grading and dashboards are next. The plan is in
[`expansion/`](expansion/) (the project's direction, written by the
maintainers) and [`expansion/agent-spec/`](expansion/agent-spec/) (specs and
the roadmap).

This repository also holds the original command-line tool this app grew
from, in `coursekit/`. It is documented in [`docs/overview.md`](docs/overview.md).

---

## Running it locally

You need **Docker Desktop** (on Windows, with the WSL 2 backend) and
**git**. Nothing else is installed on your machine: Python, Node and the rest
run in containers.

Setup takes about half an hour the first time. Most of that is on GitHub:
coursekit acts through a **GitHub App** that you register yourself, and it
needs a GitHub organization to practise on.

### 1. A second GitHub account, for testing as a student

Sign-in and org invitations can't be tested properly with only your own
account. Create a second GitHub account for a pretend student. With Gmail,
`you+coursekit-student@gmail.com` delivers to your normal inbox. Keep it
signed in in a separate browser profile or a private window, so you can use
both accounts at once.

### 2. A development organization

Signed in as yourself: **your avatar → Your organizations → New
organization → Free**. Name it something like `coursekit-dev-<you>`. It
plays the part of one course's semester. Don't invite anyone to it; the
app will.

### 3. A webhook forwarding channel

GitHub can't reach `localhost`, so in development its webhooks go through
a relay. Open [smee.io](https://smee.io), click **Start a new channel**, and
keep the URL (`https://smee.io/AbC123...`). No account is needed.

### 4. A webhook secret

GitHub signs every webhook with this, so the app can reject forged ones:

```
docker run --rm python:3.14-slim python -c "import secrets; print(secrets.token_hex(32))"
```

Save the output. GitHub won't show it to you again once it's saved in the
App.

### 5. Register the GitHub App

Signed in as yourself: **Settings → Developer settings → GitHub Apps → New
GitHub App**.

| Field | Value |
|---|---|
| GitHub App name | Unique across GitHub, e.g. `coursekit-dev-<you>` |
| Homepage URL | Any real URL, e.g. this repository's. GitHub rejects `localhost` here |
| Callback URL | `http://localhost:5000/auth/github/callback` |
| Expire user authorization tokens | ✅ checked |
| Request user authorization (OAuth) during installation | ☐ **unchecked** (checking it disables the Setup URL) |
| Enable Device Flow | ☐ unchecked |
| Setup URL | `http://localhost:5000/github/installed` |
| Redirect on update | ✅ checked |
| Webhook → Active | ✅ checked |
| Webhook URL | your smee.io URL |
| Webhook secret | the value from step 4 |

**Repository permissions**

| Permission | Access |
|---|---|
| Administration | Read and write |
| Contents | Read and write |
| Workflows | Read and write |
| Checks | Read and write |
| Actions | Read-only |
| Metadata | Read-only (selected automatically) |

**Organization permissions**

| Permission | Access |
|---|---|
| Members | Read and write |

**Account permissions**

| Permission | Access |
|---|---|
| Email addresses | Read-only |

**Subscribe to events:** **Push**, **Organization** and **Member**. The last
two appear only after Organization → Members is set above.

**Where can this GitHub App be installed?** **Any account**. That doesn't
list it anywhere public; it lets organizations other than yours install
it.

Click **Create GitHub App**. Then, on its settings page:

- Note the **App ID** and the **Client ID**, and the App's URL name (the
  `<slug>` in `github.com/apps/<slug>`).
- **Generate a new client secret** and copy it right away.
- **Generate a private key**. A `.pem` file downloads. Move it somewhere
  **outside** this repository, e.g. `C:\Users\you\.secrets\coursekit-dev.pem`
  or `~/.secrets/coursekit-dev.pem`.

Never commit these or paste them anywhere public.

### 6. Install the App on the development organization

On the App's settings page: **Install App → your dev organization →
Install**, choosing **All repositories**. GitHub then tries to send you to
`localhost:5000`. Nothing is running there yet, so the browser error is
expected and harmless.

### 7. Configure `.env`

```
cp .env.example .env          # Windows cmd: copy .env.example .env
```

Fill in every value. The comments in the file say where each one comes from,
and give the commands for the two random keys.

### 8. Start it

```
docker compose up --build
```

The first time only, in a second terminal, create the database:

```
docker compose exec web flask --app webapp db upgrade
```

Run the same command again whenever you pull new changes. It applies any new
migrations and does nothing if there are none.

Four services start:

| Service | What it does |
|---|---|
| `web` | The Flask server at http://localhost:5000. Reloads when you save Python files |
| `worker` | Background jobs (webhook processing, nightly sync). Restart it after changing `webapp/tasks.py` or the handlers: `docker compose restart worker` |
| `frontend` | Recompiles `frontend/src/*.ts` into `webapp/static/js/` when you save |
| `smee` | Forwards webhooks from your smee.io channel to `web` |

### 9. Check that everything is connected

| Check | Expect |
|---|---|
| http://localhost:5000/healthz | `ok` |
| http://localhost:5000/dev/worker | `worker answered: pong` |
| http://localhost:5000/dev/github | Your dev organization, with its token marked **ok**. This proves the App ID and private key |
| On GitHub: the App's settings → **Advanced → Recent Deliveries** → the original `ping` → **Redeliver** | `docker compose logs web` shows the webhook `received ... signature valid`. This proves smee and the webhook secret. (A ping sent before you changed the secret fails with 401; any new event works) |

The `/dev/...` pages exist only in development.

### 10. Try it

1. At http://localhost:5000, click **Sign in as an instructor** and approve the
   App on GitHub.
2. Click **New course** and create a course, then add an offering (e.g.
   `Fall 2026`).
3. On the offering page, choose your dev organization from the list of
   organizations where coursekit is installed, or click **Connect
   organization** to go through GitHub's install page.
4. In the other browser profile, sign in as the test student with **Sign in as
   a student**.

---

## Tests and linting

```
docker compose run --rm web pytest
docker compose run --rm web ruff check webapp tests_web
docker compose run --rm web ruff format webapp tests_web
```

The tests fake GitHub completely: they need no `.env` values beyond what
Compose requires to start, and any request that reaches the network fails.
They create their own throwaway database, so your development data is never
touched.

To use your editor's autocomplete, create an optional local environment:
`python -m venv .venv`, then `.venv/bin/pip install -r requirements-dev.txt`
(on Windows: `.venv\Scripts\pip install -r requirements-dev.txt`). The app
itself always runs in Docker.

## Troubleshooting

| Symptom | Cause |
|---|---|
| `/dev/github` shows **Integration not found** | `GITHUB_APP_ID` is wrong |
| `/dev/github` shows **A JSON web token could not be decoded** | The private key file isn't this App's, or is damaged |
| Webhooks rejected with 401: `signature missing or invalid` | `GITHUB_WEBHOOK_SECRET` doesn't match the App's webhook secret. It can be overwritten on GitHub but never read back, so set a new one in both places |
| Sign-in fails with `redirect_uri` errors | The App's Callback URL isn't exactly `http://localhost:5000/auth/github/callback`, or `BASE_URL` differs |
| No **Organization** event to subscribe to | Set Organization permissions → Members first |
| After adding or changing a Python package, imports fail | Rebuild: `docker compose up --build` |
| On Windows Git Bash, `docker run -v`/`-w` paths come out as `C:/Program Files/Git/...` | Prefix the command with `MSYS_NO_PATHCONV=1` |
| Compose says `env file ... .env not found`, or `set GITHUB_APP_PRIVATE_KEY_FILE in .env` | `.env` is missing, or that line is empty (step 7) |
| Starting over with an empty database | `docker compose down -v` deletes the data volume. Then `up`, then `db upgrade` again |

## Repository layout

```
webapp/          the Flask app
  github/        everything that talks to GitHub: App and user auth, API calls,
                 webhooks and their handlers
  routes/        pages
  templates/     Jinja templates
  models.py      database tables (migrations in migrations/)
  tasks.py       background jobs (Huey)
frontend/        TypeScript, compiled to webapp/static/js/
tests_web/       tests for the web app
expansion/       the plan: direction (top level) and specs (agent-spec/)
coursekit/       the original command-line tool; docs/ and tests/ belong to it
compose.yaml, Dockerfile, requirements*.txt, .env.example
```
