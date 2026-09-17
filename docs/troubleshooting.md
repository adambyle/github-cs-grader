# Troubleshooting

## First: isolate the layer before debugging

A silent failure inside a real assignment could equally be the roster, the
distribution, the workflow, the runners, the image, or the assignment
itself. Testing through a real assignment tells you that *something* is
wrong and nothing else. So do not start there.

```bash
cs108 doctor                 # every check by name, in one command
cs108 doctor --smoke --go    # one throwaway repository, one job: RAN, QUEUED or FAILED
```

The smoke test is a repository with a single workflow and a single `echo`.
If it **runs**, the runners, the organization, the image and the workflow
are all fine and the problem is in the assignment. If it **queues**, the
`runs-on` name is wrong or the scale set is not attached to this
organization. If it **fails** inside `actions/checkout`, the image does not
run as root. None of those three shows up as a distinct error anywhere in
GitHub's interface; each looks like "the tick is not appearing". This
discipline is what found the container requirement, the ignored `user`
setting and the missing labels in the first place, none of which appear in
any documentation.

Then work down the layers in order:

| layer | how to test it alone |
|---|---|
| gh | `gh auth status`; `cs108 config --check` |
| organization | `cs108 config --check` (owner access, org exists) |
| runners | `cs108 doctor --smoke --go` |
| the workflow file | `cs108 doctor` (published workflows match the current settings) |
| the assignment | `cs108 verify a04` |
| the roster | `cs108 doctor` (missing ids, duplicates, rows without repos) |
| a student's repository | `cs108 marks a04 --students jsmith`, then read `logs/jsmith.log` |

## Symptoms

**A job sits at "Queued" forever.**
The `runs-on` scar. ARC registers runners with no labels; only the scale-set
name routes a job. Check `cs108 config runner`, then `cs108 doctor --smoke
--go`. If the name is right and it still queues, the scale set is not
installed for this organization: that is an infrastructure task for whoever
administers the runners (see `docs/runners.md`).

**The job fails at "Check out your code" with EACCES.**
The image does not run as root, and the Kubernetes hook ignores the
container `user` setting. Use an official image (`node:22`) or one that
defaults to root. `cs108 config image node:22`, then re-push the workflow.

**The job fails before any step, or ARC rejects it.**
There is no `container:` block. Every template the toolkit publishes has
one; this happens when someone edited the workflow by hand inside a
repository. `cs108 patch a04 --files .github/workflows/autograde.yml --go`
restores it.

**`npm install` fails in the workflow.**
The runners have no network. This is the property that makes running
student code safe. Build suites on `node:assert` with no dependencies, and
never write an assignment that needs the network at test time.

**I changed the runner (or image) and nothing happened.**
A setting only reaches templates published from then on. `config` printed
the commands: `cs108 patch a04 --files .github/workflows/autograde.yml
--go` for each published assignment. `cs108 doctor` lists the ones that
are out of date.

**`assign` says the template repository is not marked as a template.**
`cs108 template a04 --go` sets the flag. It is the last step of publishing
and the one that is easy to forget by hand.

**A student says they have no repository.**
Three different things look identical from their side. `cs108` (the bare
command) tells them apart: not on the roster with a `github_id`
(`students import`), invited but not accepted (they must accept the
organization email; it expires in seven days), or accepted after the last
`assign` run (re-run `cs108 assign a04 --go`; it is idempotent).

**Every student scored zero.**
`marks` stops before writing the gradebook when every submission failed to
load at the same point, because that is a fact about the grading machine,
not the class. Read the runtime line it prints (`node : /path v22.x`) and
compare with a fresh terminal. If the grading process inherited a different
PATH, restart it from a shell where `which node` is the one you want.

**`verify` says both starter and answers fail to load at the same point.**
Same cause: the toolchain on this machine. Not the assignment.

**`verify` says EXPECTED_VISIBLE does not match the checks that ran.**
The constant in the grader's config block is wrong, usually because checks
are generated in a loop and one was added. Fix the number. Until it is
fixed, every student's denominator is wrong.

**The gradebook shows a score, but the student pushed since.**
The status screen flags it as stale. The number is a true record of an
older commit. Run `marks` again; it costs nothing.

**A mark is disputed.**
`changed` in the gradebook names the file that made `complete` say yes.
`checkouts/<user>/` under the grading folder holds exactly what was graded.
`results/<user>.json` holds every check. `logs/<user>.log` holds the grader's
output. Nothing needs re-running to answer the question.

**`marks --verify-reproducible` says the two gradebooks differ.**
Something in a grader is non-deterministic: a clock, an unordered
iteration, randomness, an attempted network call. Fix it before the marks
mean anything. Compare `gradebook.csv` and `gradebook.second.csv`.

**`patch` refuses a file.**
It is not on the restore list, so students may have edited it. If it truly
is a provided file, add it to `restore` in `assignment.json` (that is the
list grading uses too) and run `verify`. If it is a deliverable, announce
the change and let students apply it. `--i-know-what-im-doing` overrides
once; it exists so the refusal is a speed bump, not a wall.

**`sheet` wrote `marks-a04-2.csv` instead of overwriting.**
Correct. `marks-a04.csv` had marks typed in it. Nothing ever overwrites a
sheet with marks in it.

**The UI shows nothing about GitHub.**
It says "unknown" rather than guessing. `gh auth status` in a terminal;
almost always the token expired or gh was never logged in on this machine.

**The command is not found after install.**
`~/.local/bin` is not on PATH, which is the default on macOS with zsh. The
installer printed the line to add to `~/.zshrc`. Open a new terminal.

## When something changed in week 9

```bash
cat ~/Courses/26FA-CS108/course-history.log
```

One line per change to a setting, dated, plus every publish, assign, patch
and marks run. The first useful question when something breaks is what
changed, and this is the answer.
