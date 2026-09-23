---
author: Claude Opus 5.5 (AI agent), written for Adam Byle, 2026-09-22
---

# Roadmap and working notes

The overall plan for turning coursekit from a single-instructor CLI into a web
app, plus notes for whichever agent (probably me) picks this up next.
**Human-written files in `expansion/` outrank this one.** If they disagree,
they win, and this file should be updated.

## Phases

| # | Phase | Branch | Status | Spec |
|---|---|---|---|---|
| 0 | Development environment | `environment` | **Done** (merged) | `create-environment.md` |
| 1 | GitHub integration: sign-in, roles, orgs, roster, invitations | `github-integration`, then `rosters` | **In progress**: steps 1–6 done, rosters built (awaiting test) | `github-integration.md`, `roster.md` |
| 2 | Assignments: upload, versions, verify, template, repos, patch | — | Planned | to write |
| 3 | Grading: sandbox, queue, per-commit grades, deadlines | — | Planned | to write, with `sandboxing.md` |
| 4 | Dashboards and export: instructor stats, student feedback, Moodle | — | Planned | to write |
| 5 | Teams | — | Planned | to write |
| 6 | Production hardening and deployment | — | Planned | `deploy.md` |
| 7 | CLI client for the server (`cli.md`) | — | Later | — |

**The current round** (`core-features.md`) finishes phase 1, builds phase 2
without `verify`, builds phase 5 (teams), and the commits part of phase 4.
Grading is left out on purpose.

### Phase 2: assignments

- **Upload format:** a ZIP laid out like the CLI's assignment folder:
  `assignment.json` + `starter/` + `answers/` + `autograder/` (the CLI's
  `autograders/<id>/` bundle). Also the instructions markdown. The same ZIP
  should work for the future CLI.
- **Every upload is a new version.** Old versions are kept, which also covers the
  "keep your own copy" worry in `adaptation.md`. Grades refer to a version.
- **Instructors can view uploaded files but not edit them**, only replace them
  with a new upload (`adaptation.md`).
- **`verify` runs automatically on upload**, in the sandbox, so it needs phase 3's
  sandbox. The results go on the assignment dashboard: SHAPE, SYNC, BUNDLE, SCORE,
  STARTER. The three-copies check becomes a check *within one upload*.
- **Template repo:** a "Create/Update template" button. The dashboard says when the
  template is behind the latest upload.
- **Student repos:** a "Generate for everyone" button, or created lazily when a
  student first opens the assignment (required for teams). The same code path
  either way.
- **Patch button:** pushes only restore-list files, with a confirmation dialog that
  lists the plan and "0 deliverables affected". Also `--missing` (create-only),
  and a clear explanation when a changed file is a deliverable.
- **Open/visible switch** per assignment.
- **Hand-graded (`kind: manual`)** assignments are fully supported: no grader;
  `complete` is still computed.

**Sequencing note:** `verify` needs phase 3's sandbox, because it runs the
starter and answers. So either build the sandbox first (at the start of phase 2),
or ship phase 2 with verify as "pending" and turn it on with phase 3. The
sandbox is also the part IT is most likely to have opinions about
(`deploy.md` §4), so starting it early is the safer choice.

### Phase 3: grading

- **Sandbox:** one throwaway container per grading run, no network, CPU, memory and
  time limits, files copied in and out (`put_archive`/`get_archive`, not bind mounts:
  paths inside the worker container aren't host paths). Only the worker gets the
  Docker socket. Production may need rootless Podman or gVisor (see `deploy.md`).
- **Triggers:** a push webhook (every push, so per-commit statistics exist), a new
  upload (marks grades stale), a manual regrade, or a specific commit the instructor
  picks.
- **A grade is keyed by (commit SHA, assignment version)**, and is stale when the
  version changes.
- **Deadlines:** the default is the latest commit before the deadline. Late grace is
  a per-student extension, not a manual regrade.
- **Keep the CLI's grader contract unchanged** (`result.json`, `feedback.md`, exit
  codes, `RESTORE_FILES`) so existing graders work as they are.
- **`complete` is computed before the grader runs**, from a clean checkout compared
  against the starter of the graded version.
- **Missed pushes:** a periodic reconciliation compares each repo's HEAD with the
  last commit seen, because GitHub doesn't retry failed webhooks.

### Phase 4: dashboards

- **Instructor view** per assignment: repo exists / has commits / missing; score and
  `complete`; commit count; first and last commit and the time between them; commits
  after the deadline; errors per commit; restore-list files modified (blob SHA
  compared with the version's copy).
- **Student view:** the latest result, with failing checks and hints, per commit.
- **Moodle export:** a CSV keyed by email or institution username. The instructor
  chooses whether it exports `complete` or `score`. It only exports; nothing is
  imported.

### Phase 5: teams

Students form teams themselves. A repo is created when a team exists, and every
member gets push access. Repos are named after the team. `result.json`'s
`usernames` array already allows several authors.

### Phase 6: production

Everything in `deploy.md`, plus replacing self-selected roles (see
`github-integration.md` §3, which isolates the check in one function for this
reason).

## Decisions already made

| Decision | Why | Where |
|---|---|---|
| Flask, SQLite (SQLAlchemy + Alembic), Huey on SQLite, plain TS via `tsc` | `goals.md`/`environment.md`; no extra servers | `create-environment.md` |
| Docker is the only dev dependency | `environment.md` | done |
| One GitHub App: both sign-in (user tokens) and acting in orgs (installation tokens) | One registration, one set of credentials | `github-integration.md` |
| Separate dev and production Apps | Only one webhook URL and one setup URL per App | `deploy.md` |
| One org per course offering, created by hand by the instructor | Adam's call. GitHub has no API to create orgs | `goals.md` |
| Roles self-selected for now | Adam's call, for development simplicity. **Must change before production** | `goals.md` |
| No `--go`, but a preview + confirm dialog for bulk GitHub changes | Adam accepted this pushback | `adaptation.md` + this file |
| Grading in background jobs, never in a request | Webhook 10-second limit, page speed | phase 3 |
| Grades keyed by (commit, version); extensions for lateness | Accepted pushbacks | phase 3 |
| Roster CSV keeps the CLI format (`username,first_name,last_name,email,section,github_id,role`) | Existing rosters work as they are; `username` stays the stable key | `github-integration.md` |
| Store GitHub's numeric user ID once known | Logins can be renamed; IDs can't | `github-integration.md` |
| TypeScript 6.0, not 7 | 7.0's watcher misses edits on Windows bind mounts | `create-environment.md` |
| Ruff formats the Python | Consistency for a team | `pyproject.toml` |
| Assignments belong to a course; per-semester settings (visible, due, teams, template) on `OfferingAssignment` | `goals.md`: assignments are reused between semesters | `core-features.md` §3.1 |
| File contents stored once by SHA-256; a version is a list of paths | Every change is a version, cheaply | `core-features.md` §3.2 |
| `assignment.json` is edited as a form, not stored as a file; the ZIP download writes it | One source of truth for the settings | `core-features.md` §3.3 |
| Repo names `<a01>-starter`, `<a01>-<username>`, `<a01>-team-<slug>`, no course prefix | The org already names the course | `core-features.md` §5.1 |
| No Actions workflow in templates for now | Grading will be server-side; decide in phase 3 | `core-features.md` §4.2 |
| Teams are joined with a code, not picked from a list | A list lets anyone join any team's repo | `core-features.md` §6.1 |
| "Late" means pushed after the due date (push webhook time), falling back to the commit date | Commit dates are set by the student's machine | `core-features.md` §7.2 |
| Keep `coursekit/` until the end of phase 3, then remove it | Phase 3 ports its grader harness | `core-features.md` §10 |

## What the CLI got right (keep it in the web app)

These come from `docs/` and the CLI's docstrings. Each one was learned the hard
way.

- **The restore list is the safety model.** One list, three jobs: grading overwrites
  those files, patch may push only those, verify checks them.
- **Never push a file students have edited.** Patch is structurally unable to.
- **`complete` is the grade column; `score` is diagnostic.** Compute `complete`
  before grading, from one definition of "the starter" (`starter_files()`), and it
  must never regress for the same commit.
- **Export only.** Two files that both look authoritative is how grades get lost.
- **The test account ritual:** a `role=test` roster row that gets every assignment
  first.
- **Hidden tests are obscure, not secret.** Student code runs with the grader's
  privileges.
- **No network during grading**, and so zero-dependency test suites (`node:assert`).
- **Graders in Python or Node**, dispatched by file extension. The harness contract
  is language-neutral.
- **If every submission fails at the same point, blame the machine.** Don't write
  zeros.
- **Grant push access only to active org members.** Otherwise GitHub sends a second,
  repo-level invitation. (With lazily created repos this mostly takes care of itself.)

## Gotchas already hit

- **Git Bash rewrites container paths** in `docker run -v/-w`. Prefix with
  `MSYS_NO_PATHCONV=1`.
- **`core.autocrlf=true`** had corrupted `CHEATSHEET.pdf` in the working copy. Fixed
  by `.gitattributes` (LF everywhere; PDFs binary).
- **PyJWT requires a string `iss`.** Use the App ID as a string. A made-up client ID
  gets "'iss' must be an Integer" from GitHub, which is misleading.
- **SQLite goes in the named volume**, never a Windows bind mount (unreliable locking).
- **huey's consumer logs twice** unless the `huey` logger stops propagating once the
  app configures root logging (handled in `tasks.app_context`).
- **smee.io forwarding keeps signatures valid** for compact JSON (verified with a real
  channel).
- **Browsers restore pages from the back/forward cache**, showing stale lists.
  Pages are sent `no-store`, and `main.ts` reloads any restored page.
- **GitHub's app Configure page keeps Save disabled until something changes**, so
  reconfiguring an already-installed org never reaches the Setup URL. The offering
  page's "choose an existing org" list covers that case.
- **The CLI's own test suite fails on Windows** (4 failures, 29 errors) *before and
  after* this work. It was written for macOS/Linux. Not a regression. Run it on
  Linux if needed.
- **Testing without Adam's secrets:** a scratch `.env` with dummy values, a throwaway
  key in `%TEMP%`, and `docker compose -p ckscratch ...` so the real volume stays
  clean. Tear it all down afterwards.

## How Adam works

- A student, building this for university deployment. Most comfortable with
  Python. New to GitHub Apps and OAuth, so explain GitHub mechanics rather than
  assuming them.
- Writes the direction in `expansion/*.md`. Agents write specs in `agent-spec/`
  with an `author:` front-matter line.
- Wants a plan to review before building, then **one build step at a time**,
  stopping for Adam to test after each. When asked for fixes, make only those.
- Uses one branch per phase and merges through PRs.
- No taglines or marketing copy in the UI; keep text functional.
- Has told me to go with my recommendation wherever I'm leaning a certain way, and
  to use my own judgment otherwise. Record such decisions in this file.
- Keeps secrets out of chat. Never read `.env` or `.pem` files. Check only that
  they exist.

## Open questions

- **IT answers** (`deploy.md` §4): public vs. campus-only, inbound webhooks
  (`webhooks.md`: GitHub needs HTTPS access), Docker socket policy, a separate
  grading VM, FERPA.
- **Whether the App can accept an org invitation on a student's behalf** with their
  user token. GitHub's docs say yes; confirm in phase 1, step 9.
- **Whether the Actions tick stays.** Server-side grading makes it optional.
  Decide in phase 3.
