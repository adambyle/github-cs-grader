"""
doctor, check the whole system in one command.
==============================================

    cs108 doctor                    # every check, by name, exit non-zero on any failure
    cs108 doctor --smoke            # preview the smoke test
    cs108 doctor --smoke --go       # push a one-job repository and watch it RUN, QUEUE or FAIL
    cs108 doctor --json

Meant to be typed, not scheduled: when something feels wrong, and by habit
before each assignment goes out. There is no daemon, no scheduler, no
background check, and there must not be one.

| check                                  | catches                                        |
|----------------------------------------|------------------------------------------------|
| gh authenticated, still an org admin   | the failure that looks like every other failure |
| runner scale set has runners           | the silently queued job, before it costs a week |
| every published template has the flag  | a confusing error inside assign, weeks later    |
| every published workflow is current    | a setting changed and never re-pushed           |
| three copies of each restore file agree| grading disagreeing with what students saw      |
| roster: missing ids, bad ids, duplicates| the student who never got a repository         |
| roster rows vs repositories, both ways | both directions of the same gap                 |
| test account has every distributed repo| an assignment nobody tried before students did  |
| grading folder exists and is writable  | discovering this the moment marks are due       |

THE SMOKE TEST
    The only certain answer to "will a job run on this organization's
    runners" is a job that ran. --smoke --go creates (or reuses) a private
    repository <course>-smoke-test, pushes a one-step workflow rendered with
    the course's runner and image, and polls it. It reports RAN, QUEUED (the
    runs-on scar) or FAILED (the container or image scar), and prints the
    run URL either way. Nothing else in the toolkit can tell those apart.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import tempfile
import time
from pathlib import Path
from typing import List

from .. import assignment as asg
from .. import checks
from .. import config as cfg
from .. import ghcli, out, roster as rostermod, scaffold
from ..checks import FAIL, OK, WARN, Result

SMOKE_WORKFLOW = """name: Smoke test
# Pushed by `{course} doctor --smoke --go`. One job, one step. If this queues
# forever the runs-on name is wrong; if it fails in checkout the image does
# not run as root; if it runs, the runners are fine and any other problem is
# in the assignment, not the infrastructure.
on:
  push:
    branches: ["main"]
  workflow_dispatch:
jobs:
  smoke:
    runs-on: {runner}
    container:
      image: {image}
    timeout-minutes: 5
    steps:
      - uses: actions/checkout@v4
      - run: echo "the runners for {org} can run a job" && ls
"""


def _git(argv, cwd):
    return subprocess.run(["git", *argv], cwd=str(cwd), capture_output=True, text=True)


def smoke(course: cfg.Course, go: bool, wait: int) -> int:
    name = f"{course.course}-smoke-test"
    full = course.full(name)
    out.say(f"{'PREVIEW: ' if not go else ''}Smoke test against {course.org}")
    out.say(f"  repository : {full}")
    out.say(f"  runs-on    : {course.runner or '(NOT SET)'}")
    out.say(f"  container  : {course.image}")
    out.say(f"  one step   : actions/checkout, then echo\n")
    if not course.runner:
        out.say("error: no runner configured; set it first:  "
                f"{course.course} config runner <scale-set-name>")
        return 1
    if not go:
        out.preview_footer(f"{course.course} doctor --smoke")
        return 0
    try:
        ghcli.require_auth()
    except ghcli.GhUnavailable as exc:
        out.say(f"error: {exc}")
        return 1

    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / name
        (work / ".github" / "workflows").mkdir(parents=True)
        (work / ".github" / "workflows" / "smoke.yml").write_text(
            SMOKE_WORKFLOW.format(course=course.course, runner=course.runner,
                                  image=course.image, org=course.org), encoding="utf-8")
        (work / "README.md").write_text(
            f"# Smoke test\n\nPushed by `{course.course} doctor --smoke --go` at {stamp}.\n"
            f"Safe to delete.\n", encoding="utf-8")
        for argv in (["init", "-q", "-b", "main"], ["add", "-A"],
                     ["-c", "user.name=course-tools", "-c", "user.email=course-tools@local",
                      "commit", "-q", "-m", f"smoke test {stamp}"]):
            proc = _git(argv, work)
            if proc.returncode != 0:
                out.say(f"error: git failed: {proc.stderr.strip()[:200]}")
                return 1
        if not ghcli.repo_exists(full):
            ok, err = ghcli.create_repo(full, private=True, cwd=str(work))
            if not ok:
                out.say(f"error: could not create {full}: {err}")
                return 1
            out.say(f"created {full}")
        _git(["remote", "add", "origin", f"https://github.com/{full}.git"], work)
        proc = _git(["push", "--force", "-q", "origin", "main"], work)
        if proc.returncode != 0:
            out.say(f"error: push failed: {proc.stderr.strip()[:300]}")
            return 1
    out.say(f"pushed; waiting up to {wait}s for the job to start and finish...")
    cfg.append_history(course.root, f"doctor --smoke: pushed to {full}")

    deadline = time.monotonic() + wait
    last = None
    while time.monotonic() < deadline:
        time.sleep(5)
        runs = ghcli.workflow_runs(full, limit=1)
        if not runs:
            continue
        run = runs[0]
        if run.get("created_at", "") < stamp:
            continue
        last = run
        status, conclusion = run.get("status"), run.get("conclusion")
        if status == "completed":
            break
        out.say(f"  ... {status}")
    if last is None:
        out.say(out.red("NO RUN APPEARED. GitHub did not start a workflow run at all."))
        out.say("  Check that Actions are enabled for the organization and the repository:")
        out.say(f"  https://github.com/{full}/actions")
        return 2
    url = last.get("html_url", "")
    if last.get("status") != "completed":
        out.say(out.red(f"QUEUED after {wait}s: the job never started."))
        out.say(f"  That is the runs-on scar. Either the scale set {course.runner!r} does not exist")
        out.say(f"  for {course.org}, has no runners, or the name is spelled differently.")
        out.say(f"  Whoever administers the runners has to install or grant it; the toolkit cannot.")
        out.say(f"  {url}")
        return 2
    if last.get("conclusion") == "success":
        out.say(out.green(f"RAN: the job completed successfully on {course.runner}."))
        out.say(f"  {url}")
        return 0
    out.say(out.red(f"FAILED: the job ran and failed ({last.get('conclusion')})."))
    out.say(f"  If it failed inside actions/checkout with EACCES, the image {course.image!r}")
    out.say(f"  does not run as root. If it failed before any step, ARC rejected the job.")
    out.say(f"  {url}")
    return 2


def run(course: cfg.Course, argv) -> int:
    ap = argparse.ArgumentParser(prog=f"{course.course} doctor",
                                 description="Check everything at once.")
    ap.add_argument("--smoke", action="store_true", help="push a one-job repository and watch it")
    ap.add_argument("--go", action="store_true", help="perform the smoke test")
    ap.add_argument("--wait", type=int, default=300, help="seconds to wait for the smoke job")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    if args.smoke:
        return smoke(course, args.go, args.wait)

    results: List[Result] = []
    results.append(checks.check_gh())
    gh_ok = results[-1].status == OK
    results.append(checks.check_org(course.org) if gh_ok else Result("gh org access", FAIL, "skipped: gh is not usable"))
    results.append(checks.check_git())
    results.append(checks.check_git_credentials())
    results.append(checks.check_python())
    results.append(checks.check_node())
    results.append(checks.check_runner(course.org, course.runner) if gh_ok
                   else Result("runner scale set", WARN, "skipped: gh is not usable"))
    results.append(checks.check_image(course.image))
    results.append(checks.check_grading_folder(course.grading))

    # ── roster ─────────────────────────────────────────────────────────
    try:
        rows = rostermod.read_rows(course.roster)
        probs = rostermod.problems(rows)
        if probs:
            results.append(Result("roster", WARN, f"{len(probs)} problem(s): " + "; ".join(probs[:3])))
        else:
            n = len(rostermod.students_only(rows))
            t = sum(1 for r in rows if r["role"] == "test")
            results.append(Result("roster", OK if t else WARN,
                                  f"{n} student(s), {t} test account(s)" + ("" if t else "; add a row with role=test")))
    except rostermod.RosterError as exc:
        rows = []
        results.append(Result("roster", FAIL, str(exc).splitlines()[0]))
    participants = [r for r in rows if r["role"] in rostermod.PARTICIPANT_ROLES]
    tester = [r for r in participants if r["role"] == "test"]

    # ── assignments on disk ────────────────────────────────────────────
    ids = asg.list_ids(course)
    drift_total, contract_total = [], []
    for aid in ids:
        try:
            a = asg.load(course, aid)
        except asg.AssignmentError as exc:
            contract_total.append(f"{aid}: {str(exc).splitlines()[0]}")
            continue
        for p in a.problems():
            contract_total.append(f"{aid}: {p}")
        src = a.source_dir()
        for name in a.restore_files(src):
            copies = [a.starter / name, a.answers / name] + ([a.bundle / name] if a.is_auto else [])
            blobs = {c.read_bytes() for c in copies if c.is_file()}
            missing = [str(c.parent.name) for c in copies if not c.is_file()]
            if missing or len(blobs) > 1:
                drift_total.append(f"{aid}/{name}")
    results.append(Result("assignment contracts", OK if not contract_total else FAIL,
                          f"{len(ids)} assignment(s) parse and are consistent" if not contract_total
                          else "; ".join(contract_total[:3])))
    results.append(Result("restore copies agree", OK if not drift_total else FAIL,
                          "every copy of every restore file is identical" if not drift_total
                          else "differ or missing: " + ", ".join(drift_total[:5])))

    # ── GitHub side ────────────────────────────────────────────────────
    if gh_ok:
        gh = ghcli.Gh(course.org)
        try:
            repos = gh.repos()
            members = {m.lower() for m in gh.members()}
        except ghcli.GhUnavailable as exc:
            repos, members = {}, set()
            results.append(Result("github inventory", FAIL, str(exc)))
        flag_missing, wf_stale, gaps, test_missing = [], [], [], []
        for aid in ids:
            try:
                a = asg.load(course, aid)
            except asg.AssignmentError:
                continue
            t = repos.get(course.template_repo(aid).lower())
            if not t:
                continue
            if not t["is_template"]:
                flag_missing.append(aid)
            if a.ships_workflow() and a.workflow_template().is_file():
                want = scaffold.render_workflow(a.workflow_template(), course).encode("utf-8")
                wf_path = asg.WORKFLOW_PATH if a.is_auto else ".github/workflows/check.yml"
                tree = gh.tree(course.full(t["name"]))
                if tree and tree.get(wf_path) != ghcli.git_blob_sha(want):
                    wf_stale.append(aid)
            assigned = [p for p in participants if course.student_repo(aid, p["username"]) in repos]
            if assigned:
                no_repo = [p["username"] for p in participants
                           if course.student_repo(aid, p["username"]) not in repos and p["github_id"]]
                if no_repo:
                    gaps.append(f"{aid}: {len(no_repo)} roster row(s) without a repository")
                if tester and not any(course.student_repo(aid, x["username"]) in repos for x in tester):
                    test_missing.append(aid)
        prefix = f"{course.course}-".lower()
        known = {course.student_repo(aid, p["username"]) for aid in ids for p in participants} | \
                {course.template_repo(aid).lower() for aid in ids} | {f"{course.course}-smoke-test"}
        orphans = [n for n in repos if n.startswith(prefix) and n not in known]
        if orphans:
            gaps.append(f"{len(orphans)} repositor{'y' if len(orphans) == 1 else 'ies'} with no roster row: "
                        + ", ".join(orphans[:3]))
        results.append(Result("template flags", OK if not flag_missing else FAIL,
                              "every published template has the template flag" if not flag_missing
                              else "flag not set: " + ", ".join(flag_missing) + f"  (fix: {course.course} template <a> --go)"))
        results.append(Result("published workflows", OK if not wf_stale else WARN,
                              "every published template's workflow matches the current settings" if not wf_stale
                              else "out of date: " + ", ".join(wf_stale)
                              + f"  (fix: {course.course} patch <a> --files .github/workflows/autograde.yml --go)"))
        results.append(Result("roster vs repositories", OK if not gaps else WARN,
                              "every roster row with a github_id has a repository for each assigned assignment, and no repository lacks a row"
                              if not gaps else "; ".join(gaps[:3])))
        results.append(Result("test account pre-flight", OK if not test_missing else WARN,
                              "the test account has a repository for every distributed assignment" if not test_missing
                              else "test account missing from: " + ", ".join(test_missing)))
        uninvited = [p["username"] for p in participants if p["github_id"] and p["github_id"].lower() not in members]
        if uninvited:
            results.append(Result("organization membership", WARN,
                                  f"{len(uninvited)} participant(s) not (yet) members: " + ", ".join(uninvited[:5])))

    if args.json:
        print(json.dumps([r.__dict__ for r in results], indent=1))
    else:
        out.say(f"{out.bold(course.course)} doctor  {out.dim(course.root.as_posix())}\n")
        checks.print_results(results, indent="  ")
        failed = [r for r in results if r.failed]
        warned = [r for r in results if r.status == WARN]
        out.say()
        if failed:
            out.say(out.red(f"{len(failed)} check(s) failed."))
        elif warned:
            out.say(out.yellow(f"nothing failed; {len(warned)} warning(s)."))
        else:
            out.say(out.green("everything is healthy."))
        out.say(out.dim(f"The certain test of the runners is a job that ran:  {course.course} doctor --smoke --go"))
    return 1 if any(r.failed for r in results) else 0
