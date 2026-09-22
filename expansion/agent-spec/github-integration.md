---
author: Claude Opus 5.5 (AI agent), written for Adam Byle, 2026-09-22
---

# Plan: phase 1, GitHub integration

Branch `github-integration`. At the end of this phase:

> An instructor signs in with GitHub, creates a course and a semester offering,
> connects the offering's GitHub org, and uploads a roster. Every student gets an
> org invitation. A student signs in, sees the offering, and joins the org from
> inside coursekit.

Assignments, repos and grading are later phases (`roadmap.md`). This phase builds
the identity and access layer they all depend on.

## 1. Background: the two kinds of GitHub access

Both come from the one GitHub App registered during setup.

| | User access token | Installation token |
|---|---|---|
| Acts as | The person who signed in | The App, inside one org that installed it |
| Obtained by | That person signing in (OAuth web flow) | The server, from its private key (already built: `app_auth.py`) |
| Limited to | The App's permissions **and** what that person may do | The App's permissions in that org |
| Lifetime | 8 hours, renewed with a 6-month refresh token | 1 hour, minted again as needed |
| Used for | Who is this? Which orgs can they install into? Accepting their own org invitation | Everything else: invitations, membership checks, later repos and files |

Signing in doesn't ask for "scopes" as a classic OAuth App would. With a GitHub
App, what a user token can do is set by the App's permissions, so the consent
screen only says the App can act on the user's behalf.

## 2. Start with spikes

Each is a throwaway script or route, run against the dev App and dev org, and each
answers one question before any design depends on it. Record the results at the
bottom of this file.

| Spike | Question | If the answer is no |
|---|---|---|
| S1 | Does the full sign-in round trip work: redirect, callback, code exchange, `GET /user`, refresh? | Nothing else works; fix before continuing |
| S2 | Can `PATCH /user/memberships/orgs/{org}` with a **student's user token** accept a pending invitation? (Needs the org Members permission, which the App has) | The Join button links to `https://github.com/orgs/{org}/invitation` instead |
| S3 | What happens when invitations exceed GitHub's daily cap? (It is reported as 50 per 24 hours for new or free-plan orgs.) What error or status comes back? | Determines how the invitation queue backs off and what the roster page says |
| S4 | With an installation set to "Only select repositories", can the App see repos it creates itself? | If not, "All repositories" becomes a requirement at connect time, not just a warning |

S3 needs about 55 invitations in a throwaway org. Invite fake users, or read
GitHub's docs and error bodies first. Don't spam real accounts. If the cap is
confirmed, the plan below already handles it (§6.3).

## 3. Sign-in and the student/instructor choice

### What users see

1. **Signed out, on `/`:** a short description and two buttons,
   **Sign in as a student** and **Sign in as an instructor**.
2. The button goes to `/login?as=student` (or `instructor`), which sends them to
   GitHub's consent screen. The first time, GitHub asks them to authorize the App.
   After that it bounces straight back.
3. They land on their home page, which depends on the mode:
   - **Instructor:** their courses and a **New course** button.
   - **Student:** the offerings whose roster includes them, and any pending
     "Join the GitHub organization" prompts.
4. **The header** shows their avatar and login, the current mode, a
   **Switch to instructor/student** link, a light/dark toggle (system default;
   `appearance.md`), and **Sign out**.

"They can switch if they make a mistake" (`goals.md`) is the switch link. It's
always available and changes the stored choice.

### Mode is not permission

The student/instructor choice is a **view mode**, not permission to see anything.
Every page also checks the person's relationship to the specific course:

- **Course staff** (the creator, plus co-instructors they add) can manage that
  course and its offerings.
- **Roster members** of an offering can see that offering's student pages.

Instructor mode only unlocks **creating a course** and the instructor home page. So
a student who switches to instructor mode sees an empty course list, not anyone
else's grades. This also covers real cases such as a TA who is on one course's
staff and a student in another.

All the "may this person be an instructor at all" logic is in one function:

```python
def may_use_instructor_mode(user) -> bool:
    return True   # self-selected for now (goals.md); replace before production (deploy.md §5)
```

### The OAuth flow in detail

`GET /login?as=<mode>`
- Store the chosen mode, a random `state`, and a PKCE `code_verifier` in the session.
- Redirect to `https://github.com/login/oauth/authorize` with `client_id`,
  `redirect_uri` (`BASE_URL/auth/github/callback`), `state`, and `code_challenge`
  (S256).
- Also carry an optional `next` path, accepted only if it's a local path starting
  with `/` (so the sign-in can't be used to redirect somewhere else).

`GET /auth/github/callback?code=...&state=...`
- Reject if `state` doesn't match the session (a forged callback).
- `POST https://github.com/login/oauth/access_token` with the code, client ID,
  client secret and `code_verifier`. The response has an access token, a refresh
  token and their expiry times.
- `GET /user` for `id`, `login`, `name` and `avatar_url`. `GET /user/emails` for the
  primary verified email (the App has Email addresses: read).
- Create or update the `User` by **GitHub numeric id**, since logins can be renamed.
  Refresh the stored login and name.
- Store the tokens **encrypted** (§5). Set `session["user_id"]`, clear the OAuth
  keys, and set the mode (if `may_use_instructor_mode` allows).
- **Match roster rows** that have this `github_id` login but no numeric ID yet, then
  redirect to `next` or `/`.
- If the user clicked **Cancel** on GitHub, it returns `error=access_denied`. Show
  "Sign-in was cancelled" on `/`.

`POST /logout`: clear the session. It's a POST (not a link) with CSRF protection,
so another site can't sign people out.

**Refreshing tokens:** a helper `user_token(user)` returns a valid access token,
refreshing it with the refresh token when there's less than 5 minutes left. If the
refresh fails (revoked, or older than 6 months), the user is sent through sign-in
again.

**The session** is Flask's signed cookie and holds only `user_id`, `mode` and a CSRF
token, never GitHub tokens. Settings: `SESSION_COOKIE_HTTPONLY`,
`SESSION_COOKIE_SAMESITE=Lax`, and `SESSION_COOKIE_SECURE` when `BASE_URL` is
https. Sessions last 14 days.

## 4. Connecting an offering to its GitHub org

### What the instructor sees

The offering page (e.g. *CS 108 · Fall 2026*) has a **GitHub organization** panel
with one of these states:

| State | Shown |
|---|---|
| Not connected | Two steps: **1. Create an org on GitHub** (a link to `https://github.com/account/organizations/new`, noting that the free plan is fine), then **2. Connect it**. Below: *"Already installed coursekit on an org? Choose it:"* followed by a dropdown |
| Connected | The org name with a link, "coursekit installed ✓", and a warning if the installation covers selected repos only (see S4) |
| Waiting for approval | "An owner of `<org>` must approve the installation." This happens when the instructor isn't an org owner |
| Disconnected | "The coursekit App was removed from `<org>`," with a **Reconnect** button |
| Suspended | "An owner of `<org>` suspended coursekit," and nothing that writes to GitHub works until it's unsuspended |

### How it works

- **Connect** sends the instructor to
  `https://github.com/apps/<GITHUB_APP_SLUG>/installations/new?state=<token>`, where
  `<token>` is a signed, short-lived value naming the offering and the user. GitHub
  passes `state` back to the setup URL.
- **The setup URL** `GET /github/installed?installation_id=...&setup_action=...&state=...`:
  - `setup_action=request`: show the waiting-for-approval state. Link the offering
    when the `installation.created` webhook arrives, recognized by org login.
  - `install` / `update`: **don't trust `installation_id` from the address bar.**
    Anyone could type any number. Confirm it with the instructor's own token:
    `GET /user/installations` must list it (GitHub's recommended check). Then load
    the details with the App JWT (`GET /app/installations/{id}`), require
    `account.type == "Organization"`, record it, and link it to the offering named
    in `state`.
- **The "Choose it" dropdown** lists the orgs from `GET /user/installations`
  (installations this instructor can access) that are organizations. Picking one
  links it directly, with the same check.
- **Reuse is allowed but flagged.** `goals.md` gives each offering its own org, so
  linking an org already used by another offering shows a warning, not an error.
  (The roadmap keeps the org as a per-offering setting.)

### Keeping installations in sync (webhooks)

Extend `process_webhook` into a dispatcher keyed by event name:

| Event.action | Effect |
|---|---|
| `installation.created` | Record or refresh the `Installation`. Link any offering waiting for approval on that org |
| `installation.deleted` | Mark it removed; its offerings show Disconnected. Drop cached tokens |
| `installation.suspend` / `unsuspend` | Set or clear `suspended_at` |
| `installation.new_permissions_accepted` | Refresh the stored permissions |
| `installation_repositories.*` | Refresh `repository_selection` |
| `organization.member_invited` / `member_added` / `member_removed` | Update the matching roster row's membership state (§6) |
| `organization.renamed` | Update the stored org login |
| `push` | Log only (grading comes in phase 3) |

Events that come from GitHub's own `installation` field are routed by that
installation's ID. Anything the handler doesn't know is logged and ignored.

## 5. Data model added in this phase

```
User               id, github_id (unique, int), login, name, email, avatar_url,
                   mode ('student'|'instructor'), created_at, last_login_at
UserToken          user_id (unique), access_token_enc, access_expires_at,
                   refresh_token_enc, refresh_expires_at
Installation       id (GitHub's installation id, primary key), account_id, account_login,
                   account_type, repository_selection, permissions (JSON),
                   suspended_at, removed_at, updated_at
Course             id, code ('CS 108'), title, created_by → User, created_at
CourseStaff        course_id, user_id, role ('owner'|'instructor'); unique (course, user)
Offering           id, course_id, term ('2026FA'), label ('Fall 2026'),
                   installation_id → Installation (nullable), org_login (cached),
                   pending_org_login (while waiting for approval), created_at
RosterEntry        id, offering_id, username (institution id; unique per offering),
                   first_name, last_name, email, section,
                   github_login, github_user_id (nullable until resolved),
                   role ('student'|'test'|'teacher'|'staff'),
                   membership ('unknown'|'none'|'invited'|'active'|'failed'),
                   membership_error, invited_at, checked_at, dropped_at
```

- **Tokens are encrypted** with Fernet (`cryptography`, already installed), using a
  new `.env` variable `TOKEN_ENCRYPTION_KEY`. Generate it with
  `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`.
  Anyone who gets a copy of the database still can't act as users on GitHub.
- **A dropped student is marked (`dropped_at`), not deleted**, so their history
  survives. Their row reappears if they re-add.
- **Roles on the roster** mean what they mean in the CLI (`coursekit/roster.py`).
  `test` rows are treated like students but left out of class counts;
  `teacher`/`staff` rows are listed but never invited as students.

## 6. Roster and invitations

### 6.1 Uploading a roster (preview, then confirm)

- **Format:** the CLI's CSV, unchanged: `username,first_name,last_name,email,section,github_id,role`.
  UTF-8 with or without a BOM. Port the CLI's validation from
  `coursekit/roster.py`: GitHub's login rule, duplicate usernames, and duplicate
  logins.
- **Upload shows a preview, not a change.** Rows are listed as *new*, *changed*
  (with which fields), *unchanged*, *dropped* (in coursekit but not in the file),
  and *invalid* (with the reason). Each login is looked up with
  `GET /users/{login}` (installation token) so typos show up now, not at invitation
  time. The numeric ID is saved when found.
- **Confirm** applies it and shows the next step, in the same preview-then-confirm
  style as the `--go` replacement: *"Send org invitations to 27 students?"* Dropped
  rows are only marked dropped; removing people from the org is a separate,
  explicit action (§6.4).
- **Editing one row** (a late add, or a fixed login) uses a small form with the same
  validation, for the add/drop case in `goals.md`.

### 6.2 Membership state

For each roster row the server knows one of: `none`, `invited` (pending), `active`,
or `failed` (with a reason). It comes from:

1. `GET /orgs/{org}/memberships/{login}`, checked before inviting and when the
   roster page is loaded (at most once every 10 minutes per row; results cached in
   `checked_at`),
2. `organization.*` webhooks (§4), and
3. a nightly Huey periodic task that rechecks everyone, because webhooks can be
   missed.

### 6.3 Sending invitations

- **A Huey task per offering** works through the rows that need an invitation:
  `POST /orgs/{org}/invitations` with `invitee_id` (the numeric ID) and
  `role: "direct_member"`. This is the CLI's `ghcli.invite`, ported. It skips anyone
  already `invited` or `active`, so running it again is always safe.
- **Rate limits and the daily cap** (S3): when GitHub says to slow down or that the
  cap is reached, leave the remaining rows as `none`, reschedule the task for when
  GitHub says (or 24 hours), and show it on the roster page: *"GitHub limits new
  organizations to 50 invitations a day; 12 more will be sent automatically
  tomorrow."*
- **The roster page** shows counts (active / invited / not yet invited / failed), the
  per-row status, a **Resend** action for failed rows, and the warning above when it
  applies.

### 6.4 Leaving the course

**Remove from organization** (per row or for all dropped rows) calls
`DELETE /orgs/{org}/memberships/{login}` after a confirmation dialog. It is never
automatic. What happens to their repos is decided in phase 2.

### 6.5 The student's side

- **Home page:** offerings where a roster row matches the user's numeric ID
  (matched at sign-in, or by login if the ID isn't known yet).
- **When their invitation is pending:** a banner saying *"Join the `<org>` GitHub
  organization to get your assignment repositories,"* with a **Join** button.
  - If S2 works: the button calls `PATCH /user/memberships/orgs/{org}`
    `{"state":"active"}` with the student's token. They never have to find the
    email.
  - If S2 fails: the button opens `https://github.com/orgs/{org}/invitation`, and the
    page rechecks membership when they come back.
- **Not on any roster:** *"You're signed in as `<login>`, but no course lists that
  GitHub account. Ask your instructor to add it."* This makes a typo'd login easy to
  diagnose.

## 7. The GitHub client layer

Grow `webapp/github/` in the shape of the CLI's `coursekit/ghcli.py`, so ports stay
readable:

```
github/
  app_auth.py     (exists) App JWT, installation tokens. Add: a request() for any
                  method, pagination (Link header), and retry after a rate-limit reset
  user_auth.py    authorize URL, code exchange, refresh, user_token(user)
  api.py          named operations, one function per GitHub call, each taking a token source:
                    get_user, get_user_emails, user_installations,
                    get_installation, lookup_user(login),
                    membership_state(org, login), invite(org, user_id),
                    accept_membership(org) [user token], remove_member(org, login)
                  (phase 2 adds create_repo_from_template, grant_push, put_file, tree, ...)
  webhooks.py     (exists) verification. Add: the dispatcher table
  handlers.py     one function per webhook event (§4)
```

All GitHub HTTP goes through these modules. Tests fake GitHub at the HTTP level
with `respx`, as `tests_web/test_app_auth.py` already does.

## 8. Pages and routes

| Route | Who | Purpose |
|---|---|---|
| `GET /` | anyone | Signed out: the two sign-in buttons. Signed in: the home page for their mode |
| `GET /login`, `GET /auth/github/callback`, `POST /logout` | anyone | §3 |
| `POST /account/mode` | signed in | Switch mode |
| `GET /courses/new`, `POST /courses` | instructor mode | Create a course; the creator becomes its owner |
| `GET /courses/<id>` | course staff | Offerings list, **New offering**, staff list |
| `POST /courses/<id>/staff` | course owner | Add a co-instructor by GitHub login (they must have signed in once) |
| `GET /offerings/<id>` | staff or roster member | Staff: org panel and roster summary. Student: the join banner (and assignments, later) |
| `GET /offerings/<id>/connect`, `POST /offerings/<id>/installation` | course staff | Start the install flow; choose an existing installation |
| `GET /github/installed` | signed in | The App's setup URL (§4) |
| `GET/POST /offerings/<id>/roster[...]` | course staff | Upload, preview, confirm, edit a row, invite, resend, remove |
| `POST /offerings/<id>/join` | roster member | Accept their invitation (§6.5) |

Access checks are decorators (`@login_required`, `@instructor_mode`,
`@course_staff(param)`, `@on_roster(param)`), each backed by one query function
that tests use directly.

**Every form gets CSRF protection** from Flask-WTF. `/webhooks/github` is exempt,
because its signature check protects it (already noted in `webhooks.py`).

**Frontend:** server-rendered Jinja pages. TypeScript only where it helps: the theme
toggle, confirmation dialogs, and live invitation counts that refresh themselves.
Page styling follows `appearance.md` (black and white, GitLab-like, functional).
This phase sets up the base layout and header that every later page reuses.

## 9. Configuration and settings changes

- `.env.example` gains `TOKEN_ENCRYPTION_KEY`.
- `requirements.txt` gains `Flask-WTF`.
- **Nothing changes in the GitHub App's settings**: the callback URL, setup URL,
  permissions and events set during setup already cover this phase. If S2 or S4
  show a permission is missing, change it on the dev App and record it in
  `deploy.md` for the production App.

## 10. Testing

- **Unit and route tests** with `respx`:
  - sign-in: the state check, PKCE, the code exchange, and matching an existing user
    by numeric ID after a login rename
  - token refresh and its failure
  - the setup URL rejecting an installation ID the user can't access
  - each webhook handler
  - roster parsing and the preview categories
  - the invitation task's skip, resume and daily-cap behavior
  - access checks: a student in instructor mode can't see another course
- **A test helper** signs a user in by writing the session directly. There is no
  dev-only impersonation route (too easy to leave on).
- **Manual end-to-end test**, the definition of done:
  1. As yourself (instructor mode), create *CS 108 · Fall 2026* and connect
     `coursekit-dev-26fa`.
  2. Upload a roster containing your test student account plus one bad login. The
     preview flags the bad one.
  3. Confirm and invite. The test student's row shows `invited`.
  4. In the other browser profile, the test student signs in (student mode), sees
     the offering, clicks **Join**, and the instructor's roster shows `active`
     (through the webhook, without a reload beyond the auto-refresh).
  5. Uninstall the App from the org on GitHub. The offering shows Disconnected.
     Reinstall and it reconnects.

## 11. Build order

Each step is a commit or two, and each leaves the app working.

1. Spikes S1–S4. Record the results below.
2. Flask-WTF, the base layout and header, the theme toggle.
3. `User`/`UserToken` models, token encryption, sign-in and sign-out, the mode choice
   and switch, the access decorators.
4. `Installation` model, the webhook dispatcher and installation handlers, the
   `/dev/github` page reading from the database.
5. `Course`/`CourseStaff`/`Offering` models and pages.
6. The connect flow: install redirect, setup URL verification, choosing an
   existing installation, and the org panel states.
7. `RosterEntry`, CSV parsing ported from the CLI, preview and confirm, editing one
   row.
8. Membership checks, the invitation task with backoff, `organization.*` handlers,
   the nightly recheck.
9. The student home page, the join banner, and the Join action.
10. The manual end-to-end test; update `roadmap.md`, and `deploy.md` if a permission
    changed.

## Spike results

*(To be filled in during step 1.)*

| Spike | Result | Consequence |
|---|---|---|
| S1 | | |
| S2 | | |
| S3 | | |
| S4 | | |
