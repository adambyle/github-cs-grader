# coursekit

One command for a GitHub-based programming course: hand out assignments as
private repositories, push fixes, collect and grade work. The command is
named after your course (`cs108` below; yours will be whatever code you
give the installer). Nothing changes GitHub unless you add `--go`.

## Requirements

- `git`, `python3` (3.8+), `node` (18+)
- the GitHub CLI `gh`, logged in as an **owner** of your course organization:
  `gh auth login`, then `gh auth setup-git`
- an ARC runner scale set attached to that organization (ask whoever
  administers the runners; the toolkit can only check it, see `docs/runners.md`)

No packages to install. Everything is Python standard library.

## Install (once)

```bash
git clone <this repository> ~/coursekit
cd ~/coursekit
./install
```

It asks for your course code, GitHub organization, runner name and a few
defaults, checks `gh`, `git`, `python3` and `node`, and creates your course
folder and the `cs108` command. If it says `~/.local/bin` is not on your
PATH, add the line it prints to `~/.zshrc` and open a new terminal.

Then, before the first assignment: `cs108 doctor --smoke --go`. It pushes a
one-job repository and tells you whether the runners actually run.

## Your first assignment

```bash
cs108 new a01              # makes assignments/a01/{starter,answers} and the grader
cs108 verify a01           # starter must score 0, answers full, copies identical
cs108 template a01 --go    # publishes starter/ as a template repository
cs108 assign a01 --go      # one private repo per student in roster/roster.csv
```

Edit `assignments/a01/starter/` (what students get), `answers/` (your
solution) and `autograders/a01/test.js` (the checks, with hints). Keep
`test.js` identical in all three places; `verify` tells you when it is not.
The roster needs each student's GitHub login in `github_id`;
`cs108 students import form.csv --go` merges a form export into it.

## Every week

```bash
cs108                      # what is out of step, and the command that fixes it
cs108 patch a01 --go       # push a corrected provided file to every repo (never a student file)
cs108 patch a01 --missing --go   # add a starter file the repos do not have yet (never overwrites)
cs108 marks a01 --as-of "2026-10-14T23:59:59-04:00"   # grade what existed at the deadline
cs108 sheet a01            # a CSV to type marks into, sorted by last name
cs108 ui                   # the same thing in a browser
cs108 doctor               # when something feels wrong
```

`marks` writes `~/cs108-grading/a01/gradebook.csv`. The `complete` column
(pushed anything beyond the starter) is the one to use; `score` is
diagnostic. Hand-graded assignments (`cs108 new a09 --kind manual`) skip
`marks` and use `collect` + `sheet`.

## Three things to know

1. Nothing changes GitHub without `--go`. Everything else is a preview.
2. Never push a file students have edited. `patch` refuses; let it.
3. The green tick on a commit is not the grade. `marks` and `sheet` are.

## Read more

- `CHEATSHEET.md` and `CHEATSHEET.pdf` in your course folder: one page of commands
- `docs/writing-an-assignment.md`, `docs/score-vs-complete.md`,
  `docs/troubleshooting.md`, `docs/runners.md`
- `docs/overview.md`: the full picture and the reasons behind it
- `examples/sample-course/`: a complete course with a JS-graded, a
  Python-graded and a manual assignment
- `python3 tests/run_tests.py`: the offline test suite (no GitHub needed)

## The web app (in development)

`webapp/` is the start of a web version for many instructors and courses. It
leaves the CLI above untouched. The plans are in `expansion/`. To run it you
need only Docker: copy `.env.example` to `.env`, fill it in, then run
`docker compose up --build`. See `expansion/agent-spec/create-environment.md`.
