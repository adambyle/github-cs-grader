---
author: Claude Opus 5.5 (AI agent), written for Adam Byle, 2026-09-22
---

# Plan: rosters (phase 1, step 7)

Step 7 of `github-integration.md`. At the end of this step:

> An instructor uploads a roster CSV to an offering, sees exactly what will
> change (new, changed, dropped, and rows with problems, including GitHub
> usernames that don't exist), confirms, and can then add, edit, drop or
> restore single students by hand.

**Nothing is sent to students in this step.** Org invitations are step 8.
Keeping them apart means a roster mistake can be seen and fixed before anyone
gets an email.

## Why this is next

- Steps 8 (invitations) and 9 (the student's side of the app) both need a
  roster, and so does every part of phase 2: repos are created per rostered
  student.
- It only reads from GitHub (it looks up whether usernames exist), so it's safe
  to test with made-up rosters.
- The CLI already settled the format and the checks (`coursekit/roster.py`,
  `coursekit/verbs/students.py`). This step ports them rather than inventing new
  ones.

## 1. The CSV format

Exactly the CLI's, so existing rosters work unchanged:

```
username,first_name,last_name,email,section,github_id,role
jsmith,Jane,Smith,jsmith@example.edu,A,jsmith-gh,student
testacct,Test,Account,,A,adambyle-test-student,test
```

| Column | Rule |
|---|---|
| `username` | **Required.** The institution's identifier for the student. It's the stable key: re-uploads match rows by it, and phase 2 names repos after it. Unique within the offering (case-insensitive) |
| `first_name`, `last_name`, `email`, `section` | Optional. `email` matters later for the Moodle export |
| `github_id` | The student's GitHub username. **May be blank** (they haven't provided it yet): the row is kept and flagged. If present, it must be a valid GitHub login and unique within the offering |
| `role` | `student` (default when blank), `test`, `teacher` or `staff`, as in the CLI. `test` accounts are treated like students but left out of class counts. `teacher`/`staff` are listed but never invited or given repos |

**Being forgiving where the CLI learned to be:**
- Header names are matched case-insensitively. Extra columns are ignored, and the
  preview says which.
- A UTF-8 byte-order mark is fine. If the file isn't UTF-8, it's read as
  Windows-1252 (Excel's usual encoding), and the preview says so, so accented
  names can be checked.
- `github_id` values like `https://github.com/jsmith`, `github.com/jsmith/` or
  `@jsmith` are trimmed to `jsmith`. Students paste profile URLs about as often
  as usernames (from the CLI's `students import`).
- Blank lines and surrounding whitespace are ignored.
- Files over 1 MB are refused (about 10,000 rows, far more than any class).

A **Download a blank roster** link gives the header row, and **Download
roster** exports the current roster in the same format, so instructors can
edit it in a spreadsheet and upload it again.

## 2. Uploading: preview, then confirm

### What the instructor does

1. On the offering page, **Roster → Upload CSV**. They choose the file and one of:
   - **This file is the whole roster** (the default). Students in coursekit but
     not in the file are marked dropped.
   - **Only add and update.** Nobody is dropped. For a file of late additions.
2. coursekit shows a **preview**, and changes nothing yet:

| Section | Shows |
|---|---|
| **Problems** (listed first) | Rows that won't be applied, each with the line number and reason: missing username, duplicate username, duplicate GitHub username, invalid GitHub username, unknown role |
| **GitHub usernames not found** | Valid-looking usernames with no GitHub account. These rows *are* applied (the student can fix it later), but flagged, because they're almost always typos |
| **New** | Rows to be added |
| **Changed** | Rows whose fields differ, with the old and new values of each changed field |
| **Dropped** | Students who will be marked dropped (whole-roster mode only) |
| **Returning** | Previously dropped students who are back in the file |
| **Unchanged** | A count only, with the list collapsed |

   Plus any notes: extra columns ignored, the file read as Windows-1252,
   blank GitHub usernames.
3. **Apply these changes** (with a confirmation dialog when anyone is dropped:
   *"Mark 3 students as dropped?"*) or **Cancel**.

If there are problems, the rest can still be applied. The rows with problems
are simply left out, and the preview says so plainly.

### How it works

- **The upload is saved as a `RosterUpload`** (the parsed rows and the preview),
  and the preview page reads it. Confirming applies that saved upload, so what
  was reviewed is exactly what gets applied. The session cookie is far too small
  to hold it.
- **Stale previews are refused.** If the roster changed after the preview was
  made (another instructor, another tab), applying it asks for a fresh upload
  instead of applying an out-of-date comparison. Each upload records the
  roster's revision number when it was made.
- **Kept afterwards as a history** of uploads: who, when, and what changed.
  (Shown later, if wanted.)

### Checking GitHub usernames

`GET /users/{login}` for each username not already known. It's public data,
checked with the **instructor's own GitHub token**, so it works before the org
is connected.

- The response gives the account's permanent numeric ID and the username's exact
  capitalization. Both are stored.
- A 404 means "not found" and flags the row.
- **Only new or changed usernames are looked up.** A re-upload of a 100-student
  roster with two changes makes two requests.
- **Lookups run in parallel** (8 at a time), so a first upload of 150 students
  takes a few seconds, not a minute.
- **If GitHub can't be reached,** the preview says "couldn't check GitHub
  usernames" and applying is still allowed. The rows are marked unchecked and
  checked again later (step 8 checks before inviting anyway).

## 3. Editing by hand

On the roster page, for the add/drop weeks (`goals.md`):

- **Add student:** a small form with the same fields and the same checks,
  including the GitHub lookup.
- **Edit:** the same form, filled in. Changing `github_id` clears the stored
  numeric ID and looks the new one up.
- **Drop / Restore:** marks or unmarks the row as dropped, with a confirmation.
  Nothing is deleted, so a student who drops and re-adds keeps their history
  (grades, later).

`username` can't be edited once saved, because phase 2 names repos after it. To
correct one, drop the row and add a new one.

## 4. The roster page

`/offerings/<id>/roster` (staff only), linked from the offering page's Roster
panel. The panel itself shows counts: *"28 students, 1 test account, 2
dropped; 3 need a GitHub username"*.

| Username | Name | Email | Section | GitHub | Role | |
|---|---|---|---|---|---|---|
| jsmith | Jane Smith | jsmith@… | A | [jsmith-gh](https://github.com/) ✓ | student | Edit · Drop |
| bdoe | Bob Doe | | A | *none yet* | student | Edit · Drop |
| cjones | Cara Jones | | B | cjonez ⚠ not found | student | Edit · Drop |

- Sorted by last name, with accents folded (as in the CLI's
  `sort_key_last_name`), so Émile sorts with Emile.
- A filter: all / needs attention (missing or not-found GitHub username) / dropped.
- Dropped rows are hidden by default.

Membership and invitation status columns arrive in step 8.

## 5. Data model

```
RosterEntry     id, offering_id → Offering,
                username (unique per offering, case-insensitive),
                first_name, last_name, email, section, role,
                github_login (as entered, then GitHub's capitalization),
                github_user_id (nullable),
                github_status ('missing'|'unchecked'|'ok'|'not_found'),
                dropped_at (nullable), created_at, updated_at

RosterUpload    id, offering_id, uploaded_by → User, created_at,
                filename, mode ('replace'|'merge'), base_revision,
                parsed (JSON: rows and problems), preview (JSON: the diff),
                applied_at (nullable)

Offering        + roster_revision (int), incremented on every roster change
```

Step 8 adds the membership columns to `RosterEntry`. Adding them now would only
leave unused columns.

## 6. Code layout

```
webapp/roster.py          pure logic, no Flask or GitHub, fully unit-tested:
                            parse(bytes) -> ParsedRoster (rows, problems, notes)
                            normalize_login("https://github.com/x/") -> "x"
                            diff(existing entries, parsed rows, mode) -> Preview
                            apply(offering, upload) -> summary
webapp/github/api.py      + lookup_user(token, login) -> {id, login} | None
webapp/routes/roster.py   the roster page, upload, preview, apply, add/edit/drop, downloads
templates/                roster.html, roster_preview.html, roster_entry_form.html
```

`GITHUB_ID_RE` and the role names are copied from `coursekit/roster.py`. They
aren't imported from it, because `coursekit/` is the old tool, and the web app
shouldn't depend on it.

## 7. Tests

- **Parsing:** header case, extra columns, BOM, Windows-1252 fallback, blank
  lines, URL and `@` trimming, a missing `username` column, the size limit.
- **Checks:** duplicate usernames and logins (case-insensitive), invalid logins,
  unknown roles, a blank `github_id` allowed.
- **Comparing:** new / changed (per field) / unchanged / dropped / returning, in
  both replace and merge modes.
- **GitHub lookups** (respx): found (numeric ID and capitalization saved), not
  found, unchanged usernames not looked up again, GitHub unreachable.
- **Pages:** upload → preview → apply; cancel changes nothing; a stale preview is
  refused; only staff can see or change the roster; add, edit, drop, restore;
  `username` can't be changed; the export round-trips (download, upload,
  "no changes").

## 8. Your test, when it's built

1. Download the blank roster and fill in 4 rows:
   - yourself as `teacher`
   - your test student account as `test`
   - one made-up student with a **misspelled** GitHub username
   - one student with **no** GitHub username
2. Upload it. The preview should flag the misspelling as not found and the blank
   username as missing, and list 4 new rows. Apply.
3. Edit the misspelled row to a real username. The ⚠ should become ✓.
4. Download the roster, delete one row in a spreadsheet, and upload it again in
   whole-roster mode. The preview should say exactly one student will be dropped.
   Apply, then **Restore** them.
5. Upload a file with a duplicate username. It should be listed under Problems,
   and the other rows should still apply.

## 9. After this step

Step 8 (invitations and membership) and step 9 (the student's home page and Join
button) complete phase 1, then the end-to-end test (step 10). See
`github-integration.md`.
