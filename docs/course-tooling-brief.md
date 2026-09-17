# Portable GitHub classroom toolkit: build brief

**Short version. The full specification is `course-tooling-spec.md` and is
authoritative wherever the two differ. Read this to know what you are building.
Read that before writing any part of it.**

Prepared for Eric Araújo, Calvin University, 2026-09-17.

---

## The job

Port a working system. CS 112 at Calvin has run on it since 2026-08-14: 26
students, 16 assignments, one command, self-hosted runners. You are making it
installable by a different professor, for a **JavaScript** course, in a
**different GitHub organization**, with a command named after **his** course.

Nothing may be hardcoded to CS 112, its organization, its runner, or C++.

## The shape

One instructor. One course folder. One command, named at install time.

```
cs108 new a04            make the assignment folders, auto or manual
cs108 verify a04         check it before anyone sees it
cs108 template a04 --go  starter folder -> GitHub template repository
cs108 assign a04 --go    one private repo per student, from that template
cs108 patch a04 --go     push a corrected do-not-edit file into existing repos
cs108 marks a04          clone, autograde, write gradebook.csv
cs108 collect a04        clone and stop, for reading by hand
cs108 sheet a04          a CSV to type manual marks into
cs108 students import f.csv   merge GitHub usernames into the roster
cs108 doctor             check everything is still healthy
cs108 config             show or change any setting
cs108 ui                 a small local page
cs108                    what is out of step, and what to run
```

```
26FA-CS108/
├── course.json          the only file tying the tools to this course
├── roster/roster.csv    username,first_name,last_name,email,section,github_id,role
├── assignments/a04/
│   ├── assignment.json  kind, grader, restore list
│   ├── starter/         EXACTLY what the student receives
│   └── answers/         reference solution, never published
├── autograders/a04/     OPTIONAL. Absent means graded by hand.
└── templates/autograde.yml
```

## Ten things that are not obvious

**1. Preview by default.** Every verb that changes GitHub or the roster shows
the plan and stops. `--go` performs it. The UI honors this too.

**2. `restore` is the whole safety model.** One list per assignment, in
`assignment.json`, naming the files the student does not own. It drives three
things: grading overwrites them with the instructor's copies (so fixing a test
fixes it retroactively for everyone, with no student-repo maintenance),
`patch` refuses to push anything outside it (so a student's work can never be
destroyed by a fix), and `verify` checks the copies have not drifted.

**3. Three copies of every provided file**, in `starter/`, `answers/` and the
bundle, byte-identical. Three copies of a test file that have drifted apart is
the most common way for grading to disagree with what students saw.

**4. `runs-on` must be the ARC scale-set name.** ARC registers runners with
**no labels**. A job asking for `[self-hosted, Linux, X64]` matches nothing and
**queues forever with no error**. A `container:` is mandatory, and its image
must default to root, or `actions/checkout` dies with `EACCES`.

**5. The runners have no network.** `npm install` at test time will fail. That
is the property that makes running student code safe. Build test suites on
`node --test` and `node:assert` with zero dependencies, and never write an
assignment that needs the network.

**6. `score` is not the grade. `complete` is.** `complete` is `yes` when the
student pushed anything at all beyond the untouched starter. Not the score, not
whether it builds, not how much they wrote. Generous on purpose. Compute it
against a clean checkout **before** the grader runs, and compute the starter's
file set with the same code `template` uses to publish it.

**7. Autograding is optional.** `kind: "manual"` is a first-class case, not a
degraded one. Handing out, patching, collecting and `complete` all work
identically. Only scoring differs. Manual assignments ship **no workflow** by
default.

**8. Graders may be Python or Node**, per assignment, declared in
`assignment.json` and dispatched by extension. The harness itself is Python 3,
stdlib only, one language, no dependencies. Do not confuse the two levels.

**9. The tick is disposable.** If the runners break in October, students lose a
green tick and nothing else. Local tests still work, `marks` still works.
Nothing about the course may come to depend on GitHub Actions staying up.

**10. `sheet` exports and nothing imports.** No merge back, ever. Two files
that both look authoritative is how grades get lost.

## The UI, kept small on purpose

The original has one and it is too full. One rule governs the port: **every
button maps to exactly one command, shows that command as text, and does
nothing the command line cannot do.**

Three screens. **Status**: one row per assignment, state first, then what is
wrong with the command that fixes it. **Assignment**: one row per student.
**Settings**: `course.json` as a form, with a check button.

No charts, no per-student page, no in-browser editing, no accounts, no build
step, no framework. Plain HTML served by the harness.

## Install, and changing settings later

An interactive installer asks for the course code (which becomes the command
name), title, organization, course folder, runner scale set, container image,
build command, grading folder, and whether hand-graded assignments should get a
check on push. It verifies `gh`, org access, `git`, `python3` and `node`, and
names the fix when one is missing.

**Every one of those is changeable afterwards**, via `config` or the Settings
screen, with validation against GitHub where possible. A changed runner or
image only reaches templates published afterwards, so the tool must say so and
offer to re-push the workflow.

## Required deliverables beyond the code

A **one-page cheatsheet**, generated with his real command name, organized by
task rather than by verb, delivered as Markdown and as a printable PDF. A
README covering the four-command semester. A page on writing an assignment. An
explanation of `score` versus `complete`. A troubleshooting page whose first
instruction is to isolate the layer before debugging.

## Before you start, ask

1. Test framework: zero-dependency `node --test`, vendored `node_modules`, or a
   custom image? Recommend the first.
2. Does the ARC scale set exist for the new organization yet? Ask this first.
   The lead time may be weeks and nothing tests end to end without it.
3. Course code, organization name, scale-set name.

## Done means

**It works once:** an untouched starter reads `complete: no` and a
one-character edit reads `yes`. `patch` refuses a deliverable and adds no
commits on a second run. A smoke-test job **runs** rather than queues against
the real organization. A manual assignment goes out, comes back and gets a
sheet, with no workflow anywhere. A Python grader and a Node grader both work
without being told which is which. Every button's command, run by hand, gives
the same result.

**It keeps working:** `doctor` checks the whole system in one command and exits
non-zero on any failure. Three properties are measured on every relevant run
and printed rather than hidden: no deliverable is ever changed by `patch`,
grading is reproducible, and `complete` never goes from yes back to no. One
test account in the roster receives and is graded on every assignment **before**
any student sees it.

Full lists in section 12 of the specification. Build 12.2 as well as 12.1. The
acceptance tests prove it works in August; the measures are what tell you it is
still working in October.
