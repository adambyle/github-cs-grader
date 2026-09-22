---
author: Claude Opus 5.5 (AI agent), written for Adam Byle, 2026-09-22
---

# Production deployment: what changes, and what to ask IT

This is a checklist for a person, not a build spec. It lists everything that
will be different when coursekit moves from a laptop to a university server,
and what needs a decision or permission from university IT (or the CS
department) before that can happen. Most items have long lead times, so start
the conversations early, even though launch is a long way off.

## 1. What changes between development and production

| | Development (now) | Production |
|---|---|---|
| Where it runs | Your laptop, Docker Desktop | A university server at a subdomain (e.g. `coursekit.cs.<university>.edu`) |
| GitHub App | `coursekit-dev-adambyle`, owned by your personal account | A **separate** App, owned by a department GitHub organization (section 2) |
| Webhooks | GitHub → smee.io → your laptop | GitHub → the server's HTTPS address directly (section 3) |
| URLs | `http://localhost:5000/...` | `https://<subdomain>/...` with a real TLS certificate |
| Web server | Flask's development server with auto-reload | `gunicorn` behind a reverse proxy (nginx or IT's equivalent) that handles HTTPS |
| Frontend | TypeScript recompiled on save | Compiled once, built into the image |
| Secrets | `.env` file on your laptop | Stored on the server with restricted file permissions, or in IT's secret store |
| Database | SQLite in a Docker volume, disposable | SQLite on the server's **local** disk, backed up nightly (section 4) |
| Choosing a role | Self-selected at sign-in | **Must be replaced before real students use it** (section 5) |
| Grading sandbox | Containers on your laptop | Containers on the server or on a separate grading machine. Needs IT sign-off (section 4) |
| GitHub orgs | `coursekit-dev-26fa`, fake students | One org per course offering, created by each instructor |
| Owner | You | Someone who will still be at the university after you graduate (section 6) |

## 2. The production GitHub App

**It is a different App from your dev App.** Reasons:

- A GitHub App has exactly **one** webhook URL and **one** setup URL. The dev
  App's point to smee.io and localhost; production's must point to the server.
  (Callback URLs can have up to 10 entries, but that doesn't help with the other two.)
- Separate credentials: a leaked or misused dev key can't touch real courses.
- You can break, reconfigure and reinstall the dev App freely.

**Who owns it.** A **department GitHub organization** (e.g. `calvin-cs`), not a
personal account. Ask the department whether one exists and who owns it. That org
should have **at least two owners who are faculty or staff**. An org owner can make
you a **GitHub App manager**, which lets you configure the App without being an
owner of the org. (GitHub can also transfer an existing App to another owner, but
creating a fresh one is cleaner.)

**How to register it.** Follow the same steps as for the dev App, from the
department org: **Org settings → Developer settings → GitHub Apps → New GitHub
App**. Only the following differ:

| Field | Production value |
|---|---|
| Name | e.g. `calvin-coursekit` (students see this name on commits and invitations) |
| Homepage URL | `https://<subdomain>` |
| Callback URL | `https://<subdomain>/auth/github/callback` |
| Setup URL | `https://<subdomain>/github/installed` |
| Webhook URL | `https://<subdomain>/webhooks/github` |
| Webhook secret | **New** value, never the dev one |
| Permissions and events | **Identical to the dev App**. The implementation will keep the list in the repo so the two can be compared |
| Where can it be installed | Any account |

Then generate a **new private key and client secret** and hand them to whoever
manages the server's secrets. Don't email them or commit them.

**Settle permissions before the first real course.** Once orgs have installed the
App, any change to its permissions has to be approved again by an owner of **each**
installed org. Until they approve, the App keeps working with the old permissions,
and any feature that needs the new one fails. Test permission changes on the dev
App first.

**Never install the production App on dev orgs, or the dev App on course orgs.**

## 3. Webhooks in production

- **GitHub must be able to reach the server from the internet.** Webhooks come
  from GitHub's published IP ranges (the `hooks` list at
  `https://api.github.com/meta`). Only one path, `/webhooks/github`, has to be
  reachable from outside. The rest of the site can be campus-only if IT prefers
  (see the question in section 4).
- **HTTPS with a certificate GitHub trusts.** GitHub checks the certificate by
  default. A self-signed or campus-internal certificate fails unless verification
  is turned off, and we should not turn it off.
- **GitHub waits 10 seconds for a response.** The server only records the event,
  queues the grading and replies right away. It doesn't grade inside the request.
  (The code is designed this way from the start, so nothing extra to do at deploy.)
- **GitHub does not automatically retry failed deliveries.** If the server is down
  during a deadline rush, those pushes are missed. The server will periodically
  check each repo's latest commit to catch anything it missed. For planned
  maintenance, check the App's "Recent Deliveries" page afterwards. Failed
  deliveries can be resent from there.
- **If IT won't allow inbound traffic from GitHub at all,** the app can check every
  few minutes for new commits instead. Everything still works, but "immediate
  feedback" becomes "feedback within a few minutes". Knowing this early lets us
  design for it.

## 4. The IT conversation

A short description you can open with:

> coursekit is a web app for CS courses that replaces GitHub Classroom. Instructors
> upload assignments. The app creates a private GitHub repository for each student,
> and when a student pushes code, the app runs the instructor's tests against it in
> an isolated container and shows the result to the student and the instructor. It is
> a Python (Flask) app packaged with Docker, using a SQLite database. It stores
> student names, GitHub usernames and scores. Students and instructors sign in with
> their GitHub accounts.

### Questions, with why they matter

**Hosting**

| Ask | Why it matters | If the answer is no |
|---|---|---|
| Can we have a Linux VM (or container host) with Docker (or Podman) installed? | The whole app and the grading sandbox are packaged as containers | Ask what container runtime they do support. Podman is nearly a drop-in replacement |
| Will we have admin (sudo) access, or does IT operate it? | Determines who deploys updates and who restarts things | We write a deployment runbook for IT to follow |
| Who applies OS security patches? | Running student code raises the stakes | — |
| Starting size: about **4 vCPU, 8 GB RAM, 100 GB disk** | Grading runs several containers at once around deadlines. Disk holds container images, repo checkouts and logs. These are estimates, adjustable after a pilot | Grading slows down around deadlines, but nothing breaks |
| Is the disk local? | SQLite on a network filesystem (NFS/SMB) can corrupt the database | We switch to PostgreSQL, which IT may already run |

**Network**

| Ask | Why it matters | If the answer is no |
|---|---|---|
| A DNS name, e.g. `coursekit.cs.<university>.edu` | GitHub App URLs are registered against it. Changing it later means updating the App | — |
| A TLS certificate (Let's Encrypt or the campus CA), and who renews it? | GitHub webhooks and GitHub sign-in need HTTPS | — |
| Public, or campus/VPN-only? | Students work off campus. Campus-only means using the VPN for every visit | See the next row |
| If campus-only: can `/webhooks/github` be reachable from GitHub's IP ranges? | This path is how the server learns about pushes | We check for new commits every few minutes instead |
| Outbound access to `github.com`, `api.github.com` and Docker Hub (or an internal registry mirror), plus PyPI/npm while building | The server calls GitHub, clones repos and pulls grading images | Get a list of allowed hosts or a proxy address |
| Is there a reverse proxy we should put the app behind, or do we run our own? | Handles HTTPS, and is where access restrictions live | We run nginx in a container |

**Running untrusted student code (the one IT will care about most)**

| Ask | Why it matters | If the answer is no |
|---|---|---|
| May the app start containers to run student code, with **networking disabled** and CPU, memory and time limits? | This is how grading stays safe. Student code can't reach the network or the rest of the server | Grading has to run somewhere else. Ask what they'd allow |
| Is giving the app access to the Docker socket acceptable, or do they require rootless Docker/Podman or a hardened runtime such as gVisor? | Access to the Docker socket is equivalent to root on that machine, so IT may insist on something stricter | Rootless Podman or gVisor both work. They're a configuration choice, not a rewrite |
| Should grading run on a **separate VM** from the website? | Isolates student code from the database and secrets. This is the safest layout | We run it on the same VM with the sandbox restrictions |
| Is a security review required before launch? | Better to know the timeline now | — |

**Data and privacy**

| Ask | Why it matters |
|---|---|
| This stores student names, emails, GitHub usernames and scores. Is that covered by FERPA, and what does the university require (approval, data classification, a privacy notice)? | Grades are education records. Start this early, because approvals are slow |
| Backups: can the server's backup system include the data volume, or should we run a nightly `sqlite3 .backup` somewhere? How long should backups be kept? | Losing the database means losing every course's roster and grades |
| How long should data be kept after a semester ends, and who may delete it? | Retention policy |
| Who at IT may access the server and its data? | Access policy for student records |

**Sign-in**

| Ask | Why it matters |
|---|---|
| Is signing in with GitHub acceptable, or does IT require campus SSO (SAML/CAS/Shibboleth)? | GitHub sign-in is needed anyway to link GitHub accounts. SSO could be added alongside it, e.g. to prove someone really is an instructor |
| Can IT or the registrar give us a list of who is faculty (or an SSO attribute that says so)? | Needed to replace self-selected roles (section 5) |

**Operations**

| Ask | Why it matters |
|---|---|
| Is there monitoring or uptime alerting we can plug into? Who gets notified if it's down during a deadline? | Missed webhooks and missed feedback happen at the worst times |
| Are there maintenance windows we should avoid scheduling due dates in? | — |
| Where do logs go, and how long are they kept? | Debugging disputed grades |

**Existing infrastructure**

| Ask | Why it matters |
|---|---|
| Who runs the existing ARC GitHub runners (used by the CS 112 setup)? | Server-side grading replaces them for feedback, but it's worth telling whoever runs them, and they may have useful Kubernetes and sandboxing experience |
| Does the department use GitHub Education benefits for course orgs? | Free orgs are enough, but Education benefits give the upgraded plan and more Actions minutes if we keep the GitHub Actions tick |

## 5. Must be done in code before real students use it

- **Replace self-selected roles.** In development anyone can call themselves an
  instructor. In production that would let a student create courses or view other
  students' grades. Options, depending on the IT answers: an admin-maintained
  allowlist of instructors, campus SSO, or an instructor promoting co-instructors.
- **Production settings:** a strong `FLASK_SECRET_KEY`, secure-only cookies, debug
  mode off, and CSRF protection on every form.
- **Checking for missed pushes** (section 3), switched on.
- **Settle the App permissions** (section 2).

## 6. Keeping the service going after you graduate

- **A named faculty or staff owner** for the service, the server and the production
  GitHub App.
- **At least two owners** of the department GitHub org.
- **The repository** lives under the department org, not a personal account.
- **Runbooks** in the repo covering deploying an update, rotating the App's private
  key and webhook secret, restoring from backup, and starting a new semester.

## 7. The start-of-semester routine for instructors (for the user guide)

1. Create a GitHub org for the offering (free plan).
2. In coursekit: create the offering, click **Connect organization** and install the App.
3. Upload the roster CSV and confirm the invitations.
4. Upload or reuse the assignments.

## 8. Launch sequence

1. Deploy to the server with the production App installed on a **staging** org
   that contains only test accounts.
2. Run a full assignment end to end: invite, create repo, push, grade, dashboard,
   Moodle export.
3. Pilot with **one** course, with an instructor who knows it's a pilot and has a
   fallback.
4. Only then open it to other courses.
