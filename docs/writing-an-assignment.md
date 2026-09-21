# Writing an assignment

Everything below is what `cs108 new` already does for you. Read it once so
you know what the pieces are for, then change the scaffold rather than
starting from nothing. Substitute your own command name for `cs108`.

## The folder

```
assignments/a04/
├── assignment.json      the contract: kind, grader, restore list
├── README.md            instructions that ship with the starter
├── MAINTENANCE.md       notes to self, never published
├── starter/             EXACTLY what the student receives
│   ├── README.md
│   ├── app.js           the deliverable
│   ├── test.js          the visible suite (provided, on the restore list)
│   └── package.json     "test": "node test.js" (provided, on the restore list)
└── answers/             your reference solution, same layout, never published
autograders/a04/         the bundle. ONLY for autograded assignments.
├── autograder.js        the grader (or autograder.py)
├── test.js              authoritative copy, byte-identical to the starter's
└── package.json         authoritative copy
```

No assignment folder is a git repository. `starter/` is ordinary files you
edit freely; publishing is an explicit act (`template --go`), not a side
effect of committing.

## assignment.json

```json
{
  "title":   "Working with files",
  "kind":    "auto",
  "grader":  "autograder.js",
  "restore": ["test.js", "package.json", "fixtures/"]
}
```

- `kind` is `auto` or `manual`. `grader` is omitted when manual.
- `restore` names every file the student does **not** own. A trailing slash
  means every file under that folder.
- `ignore` (optional) lists starter files that must never be published.

For a project-shaped assignment (an Expo or Vite scaffold, say), most files
are scaffolding the student never touches: configs, assets, a lock file.
List those in `restore` too, with folders as `"assets/"`. Only the files the
student writes stay off it. Two things depend on this: `patch` can only
push what is on the list, and `verify` stops treating scaffolding as work.

## The restore list is the safety model

One list, three jobs:

- **At grading time**, the bundle's copies are written over the student's
  before any test runs. A student who edited `test.js` is graded against
  yours. So fixing a bug in a test fixes it for everyone, retroactively,
  with no student-repository maintenance.
- **`patch` will only push files on this list.** Name anything else and it
  refuses and prints the list. If the changed file is a deliverable,
  announce the change and let students apply it.
- **`verify` checks** that every listed file is present where it should be,
  byte-identical in `starter/`, `answers/` and the bundle, and that no
  deliverable is in the bundle.

The rule that protects students: never push a file students have edited.
`patch` is structurally incapable of doing it, and that is the point.

## Three copies

Every provided file exists in `starter/`, `answers/` and (autograded) the
bundle, byte for byte. The reference solution is tested with the same
`test.js` the students get; the grader uses the same one again. When you
edit a test, copy it to all three, then run `verify`. Three copies that have
drifted apart is the single most common way an assignment grades
differently from what a student saw.

## Autograded or manual

| | auto | manual |
|---|---|---|
| bundle `autograders/a04/` | required | must be absent |
| `new` scaffolds a test stub | yes | no |
| workflow in the template | build and test | none, unless `tick_on_manual` |
| `verify` runs the suites | yes | load-checks the starter |
| `marks` | runs the grader | refuses, points at `collect` and `sheet` |
| `collect`, `sheet`, `patch`, `template`, `assign` | same | same |
| `complete` column | computed | computed |

A manual assignment is not a degraded case. Everything that hands work out,
patches it, pulls it back and records whether it was done works the same.
Only scoring differs.

## The visible suite: test.js

Zero dependencies. `node:assert` for assertions, a forty-line runner at the
top of the file, and your checks below it:

```js
check("Step 3: empty input", () => {
  assert.deepEqual(app.parse(""), [],
    "an empty file should produce an empty array, not throw");
});
```

The third argument is the **hint**, printed when the check fails:

```
  FAIL  Step 3: empty input
        Hint: an empty file should produce an empty array, not throw
Results: 24 / 29 passed
```

The hint is the part that teaches. Write it as the thing you would say
leaning over the student's shoulder. Treat writing good hints as writing the
assignment, not as decoration.

The `Results: N / M passed` line and the two-line `FAIL` / `Hint:` shape are
parsed by the workflow into the run summary. Do not change them.

Why not a test framework? The runners that give the green tick have **no
network**; `npm install` there fails. A suite built on `node:assert` needs
nothing installed, so the constraint disappears rather than needing to be
managed. If you must have a framework, either vendor `node_modules/` into
the starter and add it to `restore` (bloats every repository) or bake it
into a custom container image (someone must maintain it). The
zero-dependency suite is the one that keeps working by itself.

**Never write an assignment that needs the network at test time.**

## The grader: autograder.js or autograder.py

Pick the language you would rather read at eleven at night. Both scaffolds
implement the same contract, and the harness dispatches by the extension
named in `assignment.json`:

```
cwd                     the student's checkout
the bundle directory    resolvable from the script's own path
reads (environment)     COURSE, ASSIGNMENT, USERNAME, SUBMISSION_TAG,
                        COMMIT_URL, RELEASE_URL, REVIEW_URL, RESTORE_FILES
must write              ./result.json
may write               ./feedback.md
exit 0                  graded, whether the student passed or failed
exit non-zero           infrastructure error, not a student failure
```

A student whose code does not load scores zero and exits 0. A missing
bundle file exits non-zero, and `marks` reports a tooling problem instead of
recording a zero.

The config block at the top is the only part you normally touch:

```js
const EXPECTED_VISIBLE = 29;   // how many checks the visible suite runs
const EXPECTED_HIDDEN  = 0;    // and the hidden one
const POINTS = {};             // label prefix -> points, default 1
const HIDDEN_SUITE = null;     // "hidden_test.js" to enable one
const SUITE = ["node", "test.js"];
```

`EXPECTED_VISIBLE` keeps the denominator stable: a student whose code fails
to load still scores out of the full total, not out of zero. `verify`
checks that the number of checks that **actually ran** equals it, because a
real assignment once generated checks in a loop, the hand-written constant
did not match, and every student's denominator was wrong until it was
caught.

`examples/sample-course/` holds one assignment graded by `autograder.js`
and one by `autograder.py`, exactly as `new` produces them.

## The hidden suite

Optional, autograded only. `hidden_test.js` lives in the bundle and never
lands in a student repository. Same logic, different inputs, so a student
who hardcoded the visible cases does not pass.

It is **obscure, not secret**. Grading runs the student's code with the
grader's privileges, and that code can read files and print them. The
grader deletes the hidden suite from disk before any student code runs,
which raises the cost of extraction. It is not a boundary. Never write a
hidden test whose content is itself the answer, and never put anything in a
bundle that would be damaging to leak.

## Run verify after every change, however small

```bash
cs108 verify a04
```

| check | proves |
|---|---|
| SHAPE | starter and answers exist and differ, README present, no answers file leaked into the starter |
| SYNC | every restore file is byte-identical in all copies |
| BUNDLE | every restore file is in the bundle, no deliverable is |
| SCORE | answers score exactly EXPECTED_VISIBLE, and that many checks ran |
| STARTER | the untouched starter loads and scores strictly less than answers |
| TOOLCHAIN | if both halves fail at the same point, blame the machine, not the assignment |

A starter that fails to load is a broken assignment. A starter that scores
full marks is a broken suite. The check that has saved the most
embarrassment is SHAPE: noticing that the solution was copied into the
starter folder.

## Before it goes out

1. `cs108 verify a04` is clean.
2. `cs108 template a04 --go`, then `cs108 assign a04 --go --students <test account>`.
3. Push something as the test account. Confirm the tick. Run
   `cs108 marks a04 --students <test account>` and read the row.
4. Only then `cs108 assign a04 --go` for everyone.

## After a bug turns up in a provided file

In this order:

1. Fix the bundle copy (`autograders/a04/test.js`). Grading uses it, so every
   mark is corrected immediately and retroactively.
2. Copy it to `starter/` and `answers/`. `cs108 verify a04`.
3. `cs108 template a04 --go` so students distributed later start right.
4. `cs108 patch a04` to preview, `cs108 patch a04 --go` to push.
5. Tell the students. A file changing under them with no explanation is
   worse than the bug was.

If the bug is in a file students write, do steps 1 to 3 only and announce
the change. `patch` will refuse the file. Let it.
