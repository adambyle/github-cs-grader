# The runners

Students get a green tick on each push from a GitHub Actions workflow that
runs on **self-hosted runners** managed by Actions Runner Controller (ARC)
in Kubernetes. Understanding four facts about them prevents most of the
failures this system has ever had.

## 1. The scale set must exist for your organization

ARC runner scale sets are registered against one organization (or one
repository). A scale set that serves `26fa-cs112` does not serve
`26fa-cs108`. Before anything can be tested end to end, whoever administers
the runners must either install a scale set for the new organization or
grant an existing one access to it.

**This is an infrastructure task the toolkit cannot do.** It can only
verify. The lead time may be weeks, so ask first, before writing the first
assignment.

What to ask for, in one sentence: "a runner scale set attached to the
GitHub organization `<org>`, and its name". That name goes into
`course.json` as `runner`, either at install or with `cs108 config runner
<name>`.

## 2. Three lines in the workflow are not negotiable

```yaml
jobs:
  test:
    runs-on: runners-26fa-cs108    # 1
    container:
      image: node:22               # 2, 3
```

1. **`runs-on` must be the scale-set name.** ARC registers runners with no
   labels, so the name is the only thing that routes a job. A job asking
   for `[self-hosted, Linux, X64]` matches nothing and queues forever with
   no error message.
2. **A `container:` is mandatory.** ARC in Kubernetes mode rejects any job
   without one.
3. **The image must default to root.** The Kubernetes hook ignores the
   container `user` and `options` settings. An image that defaults to a
   non-root user fails with `EACCES` the moment `actions/checkout` writes
   to `/__w/_temp`. The official `node`, `python` and `gcc` images run as
   root and are fine. `config` warns when it cannot confirm the image you
   name is one of those.

All three were learned by failing, on 2026-08-14. The workflow templates
carry them, `template` renders the current values in at publish time, and
`doctor` checks that every published workflow still matches.

## 3. The runner pods have no network

Confirmed 2026-08-22. A submission that tries to reach the network cannot.
That is the property that makes it safe to run student code at all, not a
limitation to work around.

Consequences:

- `npm install` at test time fails. Test suites use `node:assert` and
  nothing else; the starter ships everything the tests need.
- No assignment may require network access at test time. For a
  web-programming course this is the constraint that will bite: test the
  functions, not the fetch.
- If a third-party framework is truly needed, either vendor `node_modules/`
  into the starter (and put it on the restore list) or bake it into a
  custom image published somewhere the runners can pull from. Both carry
  ongoing maintenance. The zero-dependency suite does not.

## 4. The workflow does one thing

Checkout, run the tests, write a summary. It produces exactly one output: a
green tick or a red X on the commit. It never calls `gh`, never publishes a
release, never posts a commit status. The job's own success or failure is
the tick. Doing more than that is precisely what broke the platform
autograder this system replaced.

## What the tick is, and is not

The tick is formative feedback: "what you pushed passes the visible tests".
It is **advisory, not authoritative**. Students can edit the suite or the
workflow in their own repository. The mark of record is `cs108 marks`,
which runs the instructor's restored copies on the instructor's machine.

The tick is also **disposable**. If the runners break in October, students
lose a tick and nothing else: `npm test` still works locally, `marks` still
works, marks still happen. Nothing about the course may come to depend on
GitHub Actions staying up. Any feature that makes it depend on the runners
is a regression, whatever else it does.

## Verifying, rather than assuming

```bash
cs108 config --check        # gh, org access, git, python3, node, runner, image, grading folder
cs108 doctor                # the above plus every published workflow and template flag
cs108 doctor --smoke --go   # push one job and watch it: RAN, QUEUED or FAILED
```

The runner check can only list runners that exist at that moment; a scale
set at minimum zero shows nothing while idle. The smoke test is the certain
answer, and it costs one small private repository named
`<course>-smoke-test` that you can delete afterwards.
