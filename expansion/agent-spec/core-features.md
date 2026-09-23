---
author: Claude Opus 5.5 (AI agent), written for Adam Byle, 2026-09-22
---

# Plan: the core features round

Adam's brief for this round (2026-09-22):

- create and modify assignments
- upload a roster to an offering, and edit it
- teams for team-enabled assignments, and students cloning their repos
- instructors see the repos: latest commit, commit history, commits after
  the due date flagged, and the repo as it was at the last commit before the
  due date
- **nothing about grading yet**: no uploading solutions for grading, no running
  graders. Placeholders are fine.
- whatever the web app uploads must accept the files in `examples/` as they
  are, and everything must also be doable from the UI alone: adding,
  viewing and removing files, and editing rosters
- keep the file viewer plain: a folder tree you can expand, and each file on its
  own page

At the end of this round:

> An instructor creates an assignment in a course by uploading the CLI's
> assignment folder (or the whole `examples/sample-course`), or builds one in
> the browser file by file. They make it visible in an offering with a due
> date and create the template repo. A rostered student joins the org, opens
> the assignment, gets a repo (alone, or with a team they formed) and clones
> it. The instructor sees every repo's commits, with late ones flagged, and can
> browse any repo as it was at its last commit before the due date.

This covers the rest of phase 1 (steps 7–9), phase 2 without `verify`,
phase 5 (teams), and the commits part of phase 4. Grading (phase 3) and the
rest of phase 4 come later.

## 1. Build order

The same rule as before: **one step at a time; after each one, stop for Adam to
test.** Each step ends with a short test list.

| # | Step | Branch |
|---|---|---|
| 1 | **Rosters**, exactly as planned in `roster.md` | `rosters` |
| 2 | **Invitations and membership**: phase 1 step 8 (`github-integration.md` §6.2–6.4) | `rosters` |
| 3 | **The student's side**: home page, the offering page for students, the Join button (phase 1 step 9, §6.5) | `rosters` |
| 4 | **Assignments in a course**: create from a ZIP or a form, the file tree and file pages, add and remove files, versions | `assignments` |
| 5 | **Importing a course folder** (`examples/sample-course` as a ZIP), editing the settings (`assignment.json`), the checks that don't run code | `assignments` |
| 6 | **Assignments in an offering**: visible/hidden, due date, teams on or off; the template repo | `assignments` |
| 7 | **Student repos**: the student's assignment page, "Get my repository", clone instructions, and "Create for everyone" | `assignments` |
| 8 | **Teams**: create, join with a code, leave; the instructor moves people; one repo per team | `assignments` |
| 9 | **The repo dashboard**: every repo's latest commit, commit count and late commits; each repo's history; browsing a repo at a commit | `assignments` |
| 10 | **Patch**: push changed restore-list files to existing repos, with a preview | `assignments` |
| 11 | End-to-end test with `examples/`; update the README, `roadmap.md` | `assignments` |

### Progress

| # | Status |
|---|---|
| 1 | **Done**, tested by Adam (2026-09-23) |
| 2 | **Done**, tested by Adam |
| 3 | **Done**, tested by Adam. Join works with the student's token (spike S2 confirmed) |
| 4 | **Next.** Start by branching `assignments` from `main` once `rosters` is merged |
| 5–11 | Planned |

### Notes for whoever builds step 4

- **What's needed first:** new requirements `markdown-it-py` and `nh3` (Markdown,
  sanitized) and `tzdata` (for `TIMEZONE` in step 6). New settings
  `FILE_STORAGE` (default `/data/files`) and a Flask `MAX_CONTENT_LENGTH` of
  50 MB. Tests point `FILE_STORAGE` at `tmp_path`.
- **Scope of step 4 alone:** the `Assignment`, `AssignmentVersion` and
  `StoredFile` models; New assignment (upload an assignment-folder ZIP, or start
  empty); the file tree and file pages; upload files into a folder; remove a
  file or folder; the version list; download a version as a ZIP. The
  course-folder import, the settings form and the checks panel are step 5.
- **Where the course page lists assignments:** a new Assignments section on
  `course.html`, above Offerings.
- **The CLI rules to copy** (not import) are in `coursekit/assignment.py`:
  `SKIP_NAMES`, `SKIP_SUFFIXES`, `INFORMATIONAL`, `keep()`, `starter_files()`,
  `restore_names()`, `problems()`, and `ASSIGNMENT_ID_RE` for the id.
- **Things already built that later steps reuse:**
  - `membership.py`: `org_token(offering)` for an installation token, and
    `can_invite`/`participates` for who gets repos.
  - `access.offering_member_required`: sets `g.entry` for students.
  - `routes/student.py` and `offering_student.html`: the student offering page,
    whose Assignments section is a placeholder for step 7.
  - The `data-poll-url`/`data-poll-token` reload in `frontend/src/main.ts`,
    for "Creating your repository…" in step 7.
  - The `ORG`, `fake_org` and `org_offering` test fixtures in
    `tests_web/conftest.py`.
- **Grant repo access on `member_added`** (§5.4): the hook for it is
  `membership.from_webhook`, which step 7 should extend.

Steps 1–3 are already specified (`roster.md`, `github-integration.md`), so this
file only adds what they didn't settle (§2). Steps 4–10 are new and specified
below.

## 2. Additions to steps 1–3

- **The example roster works unchanged.** `examples/sample-course/roster/roster.csv`
  uploads as is. Its `your-test-login` row is flagged as a GitHub username that
  doesn't exist, which is correct.
- **Step 3 also adds the student's offering page.** It shows the join banner, and
  from step 7, the visible assignments.
- **Dropped students keep their repos**, and their access, until the instructor
  removes them from the org (§6.4 of `github-integration.md`). Removing someone
  from the org also removes their access to its repos, so no extra step is needed.

## 3. Assignments: the model

### 3.1 An assignment belongs to a course, not to a semester

`goals.md`: a course is reused from semester to semester, "so assignments don't
have to be recreated". So:

- **`Assignment`** belongs to a **course**. It holds the files and the
  `assignment.json` settings. It's written once and reused every semester.
- **`OfferingAssignment`** is that assignment **in one offering**: visible or
  hidden, due date, teams on or off, and its template repo. A new semester
  starts with all of the course's assignments hidden.

The course page lists the assignments (the files). The offering page lists the
same assignments with this semester's settings and repos.

### 3.2 Files and versions

Every change to an assignment's files or settings makes a **new version**. Old
versions are kept and can be viewed, which also covers `adaptation.md`'s worry
about the server losing the instructor's only copy. Later, grades will refer to
a version (`roadmap.md`, phase 3).

Versions are cheap to keep because file contents are stored only once:

- **Each file's contents are stored once, named by their SHA-256**, under
  `/data/files/` (the named volume). The same `test.js` in 5 versions is stored
  once.
- **A version is a list of paths and SHA-256s**, stored as JSON in the database.
  Changing one file makes a new list pointing at one new file.

This is internal. What the instructor sees is a plain folder tree.

### 3.3 The folder layout

The same layout as the CLI's assignment folder, with the grader bundle moved
inside it:

```
a01/
├── README.md          the instructions students see (optional)
├── MAINTENANCE.md     notes to self, never published (optional)
├── starter/           exactly what students receive
├── answers/           the reference solution, never published
└── autograder/        the CLI's autograders/a01/ (absent when kind is manual)
```

`assignment.json` isn't stored as a file. Its settings are fields on the
version (§3.5), edited in a form. **Download as ZIP** writes it back out, so the
ZIP is a CLI assignment folder again.

**Instructions:** `README.md` at the top if there is one, otherwise
`starter/README.md`. In `examples/`, the two are identical. It is rendered as
Markdown on the student's assignment page, and sanitized, because Markdown
allows raw HTML.

### 3.4 Uploading

**New assignment → Upload a ZIP**, which accepts:

| ZIP contents | Result |
|---|---|
| An assignment folder: `assignment.json` at the top, or inside one top-level folder (zipping `a01/` in Explorer or Finder gives the second) | One assignment. Its id is the folder's name, or the name typed in the form |
| The same, plus `autograder/` inside it | The grader bundle comes too |
| A whole course folder: `course.json` and `assignments/` (`examples/sample-course`) | Step 5. A preview lists every assignment found, each paired with `autograders/<id>/` when there is one. Import all or some. The roster and `course.json` are ignored; the preview says so |

**New assignment → Start empty** asks for an id, a title and the kind, and
creates an assignment with no files.

**On an existing assignment:**

- **Upload files** into any folder: one or more files, or a ZIP that is unpacked
  there. A file with the same path is replaced, and the confirmation says which
  ones.
- **Remove** a file or a whole folder, with a confirmation.
- **Replace everything** with a new ZIP of the whole assignment.
- **Download as ZIP**, of this or any older version.

Each of these makes one new version.

**Safety limits on uploads:** 50 MB per request; at most 5,000 files and
200 MB unpacked per ZIP; paths with `..`, absolute paths and symlinks are
refused. `__MACOSX/`, `.DS_Store`, `.git/`, `node_modules/` and
`__pycache__/` are dropped (the CLI's `SKIP_NAMES` and `SKIP_SUFFIXES`), and the
result page lists what was dropped.

### 3.5 Settings (`assignment.json`)

Edited in a form on the assignment page, with the same fields and meanings as the
CLI (`coursekit/assignment.py`):

| Field | Form control |
|---|---|
| `title` | text |
| `kind` | auto / manual |
| `grader` | a dropdown of the `.js` and `.py` files in `autograder/` (auto only) |
| `restore` | one path per line. A trailing `/` means a whole folder |
| `ignore` | one path per line. Never published |

The id (`a01`) can't be changed after creation: repos are named after it.

### 3.6 Checks that don't run anything

The CLI's `verify` has five checks. Two of them only read files, so they can
work now. The other three run code in the sandbox, and wait for phase 3:

| Check | Now | What it checks |
|---|---|---|
| SHAPE | yes | `problems()` from the CLI: kind, grader named and present, `starter/` and `answers/` present, restore paths relative |
| SYNC | yes | Every restore-list file is byte-identical in `starter/`, `answers/` and `autograder/` (compare the SHA-256s) |
| BUNDLE, SCORE, STARTER | "Available when grading is built" | They run the grader against the starter and the answers |

They appear as a panel on the assignment page and are recomputed for each version.

### 3.7 Pages

```
/courses/<c>/assignments/new                      upload a ZIP or start empty
/courses/<c>/assignments/<a>                      settings, checks, versions,
                                                  and the file tree of the latest version
/courses/<c>/assignments/<a>/v/<n>                the same page for an older version
/courses/<c>/assignments/<a>/v/<n>/files/<path>   one file: text shown with line numbers,
                                                  Markdown also rendered, binaries offered
                                                  as a download
/courses/<c>/assignments/<a>/v/<n>/zip            download
```

**The file tree** is nested `<details>` elements (folders, closed by default
except the top level), with file names as links. No JavaScript is needed. Next
to each file and folder there's a small **Remove** button, and next to each
folder **Upload here**. These only appear on the latest version.

**Versions:** a list of *"v4 · 22 Sep 14:03 · adambyle · uploaded 2 files to
autograder/"*, each linking to that version's page. The description is
generated from what changed.

**Deleting an assignment:** only when no offering has made it visible or created
repos for it. Otherwise it's hidden from every offering.

### 3.8 Data model

```
Assignment          id, course_id, slug ('a01'; unique per course),
                    created_by, created_at, deleted_at
AssignmentVersion   id, assignment_id, number (1, 2, …), created_by, created_at,
                    summary ('uploaded 2 files to autograder/'),
                    title, kind, grader, restore (JSON), ignore (JSON),
                    files (JSON: {path: {sha256, size}})
StoredFile          sha256 (primary key), size, created_at
                    (the contents live on disk at /data/files/ab/cdef…)
```

New setting: `FILE_STORAGE` (default `/data/files`). Tests use a temporary
folder.

## 4. Assignments in an offering

### 4.1 Settings per semester

On the offering page, an **Assignments** panel lists every assignment in the
course. Each one links to the **offering assignment page**
(`/offerings/<o>/assignments/<a>`), which holds:

| Setting | Notes |
|---|---|
| **Visible to students** | Off by default. When it's off, students can't see the assignment or get a repo |
| **Due** | A date and time, shown and entered in the app's time zone (new setting `TIMEZONE`, default `America/New_York`), stored in UTC. Optional |
| **Teams** | Off, or on with a maximum team size (2–10). Can only be changed before any repos exist |

### 4.2 The template repo

`adaptation.md`: a button creates the template repo, and the page links to it.

- **Create template repo** makes `<org>/<a01>-starter` (private), pushes the
  latest version's `starter_files()` (the CLI's definition: `starter/` without
  `ignore` and the build-output names) as one commit, and marks the repo as a
  template. This is the CLI's `template`, ported.
- **Update template repo** replaces its contents with a newer version, again as a
  single commit (force-pushed, as in the CLI: the template's history doesn't
  matter, because student repos are generated from it, not forked).
- The page says which version the template holds, and warns when the assignment
  has a newer one: *"The template has v3; the latest is v5."* Existing student
  repos aren't affected (step 10 is for that).

**No workflow file is added** (the CLI's `.github/workflows/autograde.yml`).
Grading will run on the server, and whether the Actions tick stays is an open
question for phase 3 (`roadmap.md`).

**How:** GitHub's Git Data API only works on a non-empty repo, so the repo is
created with `auto_init`, then one commit is made with no parent from a tree of
blobs, and `main` is force-updated to it. Then `PATCH /repos/…
{"is_template": true}`. All of this uses the installation token, and needs
Administration and Contents (read and write), which the App already has.

### 4.3 Data model

```
OfferingAssignment  id, offering_id, assignment_id (unique together),
                    visible, due_at (nullable), team_max (nullable = no teams),
                    template_repo (name), template_version_id (nullable),
                    template_updated_at
```

## 5. Student repos

### 5.1 Names

| Repo | Name |
|---|---|
| Template | `<a01>-starter` |
| One student | `<a01>-<username>`, e.g. `a01-jsmith` |
| A team | `<a01>-team-<slug>`, e.g. `a01-team-rocket` |

Lowercase, because GitHub lowercases the names of generated repos (a lesson from
the CLI's `student_repo`). The org already names the course and semester, so the
CLI's course prefix is dropped.

### 5.2 The student's side

The student's offering page lists the visible assignments with their due dates.
The assignment page shows:

1. The instructions (rendered Markdown).
2. **If they haven't joined the org yet:** the Join banner from step 3, and
   nothing else.
3. **If there's no repo yet:** **Get my repository**. (Teams: §6.)
4. **Once the repo exists:** its link, and a clone box:

   ```
   git clone https://github.com/coursekit-dev-26fa/a01-jsmith.git
   ```

   with a Copy button, plus the time of their latest push when there is one.

**"Get my repository"** is a Huey task, because generating a repo from a template
takes a few seconds on GitHub's side. The page shows *"Creating your repository…"*
and refreshes itself until the repo is ready.

### 5.3 The instructor's side

**Create for everyone** on the offering assignment page creates the repos of
every rostered student (`student` and `test` rows, not dropped) who has a GitHub
username and doesn't have a repo yet. A confirmation gives the count first:
*"Create 27 repositories? 3 students have no GitHub username and will be
skipped."* Not available for team assignments.

### 5.4 How a repo is made (one code path for both)

`adaptation.md`: "the same code path either way". One task,
`create_repo(offering_assignment, owner)`, where the owner is one roster row or
one team:

1. If the repo already exists, record it and continue (safe to run again).
2. `POST /repos/<org>/<template>/generate` with `private: true`.
3. Wait until it has contents (the CLI's `wait_for_content`).
4. For each person who owns it: if they're an **active org member**, add them as a
   collaborator with push access. If not, leave it: they get access as soon as
   `organization.member_added` arrives (the step 2 handler), or at the nightly
   recheck. This is the CLI's rule: granting access to a non-member makes GitHub
   send a second, repository-level invitation.

### 5.5 Data model

```
Repo    id, offering_assignment_id, roster_entry_id (nullable), team_id (nullable),
        name, github_id, state ('creating'|'ready'|'failed'), error,
        created_at, template_version_id,
        head_sha, commit_count, last_push_at, synced_at     (step 9)
RepoAccess  repo_id, roster_entry_id, granted_at (nullable)
```

## 6. Teams

`goals.md`: students form their own teams, and a team's repo is created once
the team exists, with access for everyone on it.

### 6.1 The student's side

On a team assignment, a student not yet on a team sees:

- **Create a team:** a team name. They're its first member, and the page shows a
  **join code** (6 letters, e.g. `KXQ-TRP`) to give their teammates.
- **Join a team:** enter a code.

On a team, they see the members, the join code, **Leave team**, and **Create our
repository**. Any member can press it. After that:

- the team is **locked**: nobody can join or leave by themselves any more (the
  instructor still can, §6.2), and
- every member gets access (§5.4).

A team can't have more than the offering's maximum size. A student can be on only
one team per assignment.

**Why a join code rather than a list of teams to pick from:** with a list, anyone
could join any team with a free place and get access to its repo. A code has to be
given out by someone on the team.

### 6.2 The instructor's side

The offering assignment page lists teams with their members, plus the students
not on any team. The instructor can:

- **move a student** into another team, or out of one (a dropdown for each
  student),
- **rename** or **delete** a team (deleting only before it has a repo),
- **unlock** a team.

When a locked team's members change, repo access is changed to match: new
members are added, removed ones lose access (`DELETE
/repos/<org>/<repo>/collaborators/<login>`). Both are listed in the confirmation.

### 6.3 Data model

```
Team        id, offering_assignment_id, name, slug, join_code, locked_at,
            created_by → RosterEntry, created_at
TeamMember  team_id, roster_entry_id, joined_at
            (unique (offering_assignment, roster_entry), enforced in the code)
```

## 7. The repo dashboard

### 7.1 What the instructor sees

On the offering assignment page, a table with one row per student (or team):

| Student | Repo | Commits | Latest commit | Late |
|---|---|---|---|---|
| Jane Smith | [a01-jsmith](https://github.com) | 7 | `3f2a1c9` "fix loop" · 12 Oct 21:04 | — |
| Bob Doe | [a01-bdoe](https://github.com) | 4 | `9b0e77d` "done" · 15 Oct 00:31 | **2** |
| Cara Jones | *no repo yet* | | | |
| Dan Wu | [a01-dwu](https://github.com) | 0 | *no commits since the template* | |

Plus a count at the top (*"24 repos, 21 with commits, 3 without; 5 students without
a repo"*), and a **Refresh from GitHub** button. There's also a **Grade** column
that shows "—" until phase 3.

Clicking a row opens the **repo page**
(`/offerings/<o>/assignments/<a>/repos/<r>`):

- **The commit history** of `main`: short SHA, message, author, commit time, push
  time (when known), with **late** commits flagged.
- The **last commit before the due date** highlighted, with **Browse files at this
  commit** (and the same link on any commit).
- A **Grade this commit** placeholder, disabled until phase 3.

**Browsing a repo at a commit** uses the same folder tree and file pages as
assignment files (§3.7), reading from GitHub through the installation token
(`GET /repos/…/git/trees/<sha>?recursive=1`, and the blob when a file is opened).
There's also a link to GitHub's own view of that commit.

### 7.2 When is a commit late?

A commit's date is set by the student's computer, so it can be wrong, or faked.
The time GitHub **received the push** can't be. So:

- **Push times come from `push` webhooks.** The handler stores the time the push
  arrived for each commit in it. (The `push` event is already subscribed.)
- **Late** means *pushed* after the due date. When coursekit never got the push
  (it was made before coursekit knew the repo, or a webhook was lost), it uses the
  commit date, and the page marks it *"time from the commit, not the push"*.
- **The last commit before the due date** is the newest commit on `main` that
  isn't late.

Per-student extensions come with grading (phase 3), which already plans them
(`roadmap.md`).

### 7.3 Keeping it current

- A **`push` webhook** records the push and refreshes that repo in the background.
- **Refresh from GitHub** (and the nightly job) re-reads every repo of the
  assignment: `GET /repos/…/commits?sha=main`, following pages.
- Commits are stored, so the pages read from the database and don't call GitHub
  while loading.

### 7.4 Data model

```
Commit      id, repo_id, sha, message, author_name, author_login,
            committed_at, pushed_at (nullable), parents (JSON)
            unique (repo, sha)
```

## 8. Patch (step 10)

The CLI's `patch`, as a button, in `adaptation.md`'s words: "Any changes to
the assignment files must be manually deployed to student repos in the same way
as the patch command."

- **Patch repos** on the offering assignment page, when the template's version is
  older than the latest one.
- **The preview** lists, per file, the restore-list files that differ between the
  version the repos were made from and the latest version. Anything that changed
  but isn't on the restore list is listed as **not pushed** (it's the student's
  file), with the reason. It ends *"0 of your students' own files will be
  changed."*
- **Patch** pushes those files to every repo as one commit per repo (the Contents
  API), in a Huey task, and records the new version on each repo.
- **Only restore-list files are ever pushed.** This is the CLI's safety model
  (`roadmap.md`, "What the CLI got right").
- **Add missing files** (the CLI's `--missing`): create restore-list files a repo
  lacks, and never overwrite.

## 9. Placeholders for grading

Only where the page would otherwise look like something's missing:

- the assignment page's checks panel: BUNDLE, SCORE and STARTER marked
  "available when grading is built"
- a **Grade** column on the repo dashboard, showing "—"
- **Grade this commit**, disabled, on the repo page

No models or routes for grading are added.

## 10. The old CLI (`coursekit/`)

**Keep it for now.** Phase 3 ports its grading harness (`grading.py`,
`verbs/marks.py`), the rest of `verify`, and `sheet`. Those files are the best
record of the grader contract and the lessons behind it. What this round needs
from it is small and gets copied, not imported (as `roster.md` already does):
`SKIP_NAMES`, `SKIP_SUFFIXES`, `INFORMATIONAL`, `starter_files()`,
`restore_names()`, `problems()`.

**Remove it at the end of phase 3**, together with `tests/`, `install`, the CLI
parts of `docs/`, and `coursekit/ui.html` (the old dashboard, which `goals.md`
says to scrap). `examples/` stays, as test data for the web app.

## 11. Tests

In addition to `roster.md` §7:

- **Uploads:** each of the `examples/` assignments zipped both ways (folder at the
  top, and contents at the top); `sample-course` as a course folder; zip-slip,
  absolute paths, symlinks, too many files and too many bytes refused; skipped
  names dropped and reported.
- **Versions:** adding, replacing and removing files each make one version with the
  right summary; unchanged contents are stored once; the ZIP download round-trips
  (upload it again and nothing changes).
- **Checks:** SHAPE and SYNC for the three examples (all clean), plus broken
  copies (a restore file that differs, a missing grader).
- **GitHub** (respx): template creation from an empty repo; template update;
  generating a repo that already exists; access granted only to active members;
  access granted on `member_added`; team repo access after a member is moved;
  commit sync with pagination; push times from a `push` webhook; late flags;
  browsing a tree at a SHA.
- **Access:** students see only visible assignments in their own offerings, and
  only their own repo; team codes don't work across assignments; nobody but staff
  sees the dashboard.
