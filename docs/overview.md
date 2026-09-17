# coursekit: a portable GitHub classroom toolkit

One instructor. One course folder. One command, named after the course.

```
cs108 new a04            make the assignment folders, auto or manual
cs108 verify a04         check it before anyone sees it
cs108 template a04 --go  starter folder -> GitHub template repository
cs108 assign a04 --go    one private repo per student, from that template
cs108 patch a04 --go     push a corrected do-not-edit file into existing repos
cs108 marks a04          clone, autograde, write gradebook.csv
cs108 collect a04        clone and stop, for reading by hand
cs108 sheet a04          a CSV to type manual marks into
cs108 students import f.csv --go   merge GitHub usernames into the roster
cs108 doctor             check everything is still healthy
cs108 config             show or change any setting
cs108 ui                 a small local page
cs108                    what is out of step, and what to run
```

`cs108` is whatever course code you give the installer. Nothing in this
repository names a course, an organization, a runner or a language: those
are settings in `course.json`, asked for at install time and changeable
afterwards with `config`.

This is a port of the system that has run CS 112 at Calvin University since
2026-08-14 (26 students, 16 assignments, self-hosted runners), made
installable by a different instructor, for a JavaScript course, in a
different GitHub organization. The build brief is in `docs/`; the full
specification, with the reasons and the scars, is in the Vic-System project.

## Install

Needs `git`, `python3` (3.8 or newer), `node` (18 or newer) and the GitHub CLI
`gh`, logged in as an owner of the organization (`gh auth login`). No sudo,
no packages, no dependencies: the harness is Python standard library only.

```bash
git clone <this repository> ~/coursekit
cd ~/coursekit
./install
```

The installer asks for the course code (which becomes the command name),
title, organization, course folder, runner scale-set name, container
image, build command, whether hand-graded assignments should get a check
on push, and the grading folder. It validates each answer, checks `gh`,
organization access, `git`, `python3` and `node`, names the fix when one is
missing, and creates:

```
~/Courses/26FA-CS108/          the course folder (README.md explains the layout)
~/Courses/26FA-CS108/CHEATSHEET.md and .pdf    one page, with your command name
~/.local/bin/cs108             the command (or a shell alias, your choice)
```

Run it again any time: it offers to update the answers and never destroys a
course folder with content in it. Every setting can also be changed later:

```bash
cs108 config                     # every setting and where it came from
cs108 config runner runners-2026 # change one, validated against GitHub
cs108 config --check             # re-run the precondition checks
```

## The four-command semester

```bash
# once per assignment
cs108 new a04
cs108 verify a04
cs108 template a04 --go
cs108 assign a04 --go

# when a bug turns up in a test after repos have gone out
cs108 patch a04
cs108 patch a04 --go

# whenever marks are wanted
cs108 marks a04 --as-of "2026-10-14T23:59:59-04:00"
cs108 sheet a04
```

Before any of that, once: the ARC runner scale set must exist for your
organization. That is an infrastructure task for whoever administers the
runners; the toolkit can only verify it. Read `docs/runners.md` first, and
run `cs108 doctor --smoke --go` before the first assignment goes out.

## The shape of a course

```
26FA-CS108/
├── course.json          the only file tying the tools to this course
├── course-history.log   one line per setting change, with the date
├── roster/roster.csv    username,first_name,last_name,email,section,github_id,role
├── assignments/a04/
│   ├── assignment.json  kind (auto or manual), grader, restore list
│   ├── starter/         EXACTLY what the student receives
│   └── answers/         reference solution, never published
├── autograders/a04/     OPTIONAL. Absent means graded by hand.
└── templates/           autograde.yml and check.yml, rendered at publish time
```

## Ten things that are not obvious

1. **Preview by default.** Every verb that changes GitHub or the roster
   shows the plan and stops. `--go` performs it. The UI honors this too.
2. **`restore` is the whole safety model.** One list per assignment, in
   `assignment.json`, naming the files the student does not own. Grading
   overwrites them with the instructor's copies, `patch` refuses to push
   anything outside it, and `verify` checks the copies have not drifted.
3. **Three copies of every provided file**, in `starter/`, `answers/` and
   the bundle, byte-identical. `verify` checks this because drifted copies
   are the most common way for grading to disagree with what students saw.
4. **`runs-on` must be the ARC scale-set name.** ARC registers runners with
   no labels. A job asking for `[self-hosted, Linux, X64]` queues forever
   with no error. A `container:` is mandatory and its image must run as root.
5. **The runners have no network.** `npm install` at test time fails. Test
   suites use `node:assert` and nothing else, and no assignment may need the
   network.
6. **`score` is not the grade. `complete` is.** `complete` is `yes` when the
   student pushed anything beyond the untouched starter. See
   `docs/score-vs-complete.md`.
7. **Autograding is optional.** `kind: "manual"` is a first-class case.
   Handing out, patching, collecting and `complete` work identically.
   Manual assignments ship no workflow unless `tick_on_manual` is on.
8. **Graders may be Python or Node**, per assignment, dispatched by
   extension. The harness itself is Python 3, stdlib only. Two levels; do
   not confuse them.
9. **The tick is disposable.** If the runners break, students lose a green
   tick and nothing else. Nothing about the course depends on GitHub
   Actions staying up.
10. **`sheet` exports and nothing imports.** No merge back, ever. Two files
    that both look authoritative is how grades get lost.

## Three measures, printed on every relevant run

- `patch --go` compares every non-restore file in every repository before and
  after, and prints `0 deliverables changed`.
- `marks --verify-reproducible` grades twice and confirms the gradebooks are
  byte-identical.
- `marks` keeps the previous gradebook and prints loudly if any student's
  `complete` went from yes to no for the same commit.

And one ritual: keep a roster row with `role=test`. Every assignment goes to
that account, gets pushed to, and gets graded before any student sees it.
`doctor` warns when it did not.

## The UI

`cs108 ui` serves three screens on localhost: Status, Assignment, Settings.
Every button maps to exactly one command, shows that command as text, and
runs the same command line you would type. No charts, no per-student page,
no in-browser editing, no accounts, no framework. If a screen needs a
capability, add the verb first and surface it second.

## Documentation

| Page | Read it when |
|---|---|
| `docs/writing-an-assignment.md` | writing your first assignment, or your tenth |
| `docs/score-vs-complete.md` | someone asks why a low score is marked complete |
| `docs/troubleshooting.md` | something is wrong and you do not know which layer |
| `docs/runners.md` | before the first assignment goes out, and when the tick stops |
| `docs/course-tooling-brief.md` | the build brief this toolkit was made from |
| `README.md` | the short version, for installing and the first assignment |
| `course-tooling-spec.md` (in the Vic-System Claude project) | the full specification, with the reasons and the scars; copy it into `docs/` to keep it with the code |
| `CHEATSHEET.md` in your course folder | standing at a terminal with a class waiting |

## Tests

```bash
python3 tests/run_tests.py
```

Runs the acceptance tests of section 12.1 of the specification offline, in a
throwaway home with a fake `gh` (`tests/fake_gh.py`) and local bare
repositories standing in for the organization. Needs `git` and `node`. The
one thing it cannot test is a job running on the real runners; that is
`cs108 doctor --smoke --go`, against the real organization, by design.

## Layout of this repository

```
install                 the installer
coursekit/              the harness (Python 3, stdlib only)
  cli.py                verb dispatch; the bare command
  config.py             course.json, discovery, history
  assignment.py         the assignment contract, restore, the one collect()
  verbs/                one module per verb
  templates/            autograde.yml, check.yml (placeholders filled at publish)
  scaffold/             what `new` creates: test.js, autograder.js, autograder.py, ...
  ui.html               the three screens, one file
docs/                   the pages above
examples/               a scaffolded course with one JS-graded, one Python-graded
                        and one manual assignment, as `new` produces them
tests/                  the offline acceptance tests and the fake gh
```
