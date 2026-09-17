"""
template, starter folder -> GitHub template repository.
=======================================================

    cs108 template a04          # show what would be published
    cs108 template a04 --go     # publish it
    cs108 template               # list assignments and their state

Turns assignments/a04/starter/ into <org>/<course>-a04-starter: creates the
repository if absent, adds the rendered workflow as
.github/workflows/autograde.yml (or check.yml for a hand-graded assignment
when tick_on_manual is on; nothing at all otherwise), pushes the files, and
SETS THE TEMPLATE FLAG. That last step is easy to forget, and its absence
surfaces weeks later as a confusing error inside `assign`.

It force-pushes a single commit each time. The template's history is
disposable by design, and student repositories are GENERATED from it, not
forked, so they have no link back and are never affected by a re-push.

WHAT IT PUBLISHES
    Exactly `Assignment.starter_files()`: every file under starter/ except
    build output, node_modules, .DS_Store and the assignment's own ignore
    list. The same function decides what `complete` compares against, so the
    two cannot drift.

AFTER PUBLISHING
    Students who already have repositories do NOT get these changes; they
    hold independent copies. Use `patch` for that, and only for files on the
    restore list.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import tempfile
from pathlib import Path

from .. import assignment as asg
from .. import config as cfg
from .. import ghcli, out, scaffold


def _git(argv, cwd):
    return subprocess.run(["git", *argv], cwd=str(cwd), capture_output=True, text=True)


def workflow_text(course: cfg.Course, a: asg.Assignment) -> str:
    """The rendered workflow for this assignment, or '' when none ships."""
    if not a.ships_workflow():
        return ""
    path = a.workflow_template()
    if not path.is_file():
        raise FileNotFoundError(
            f"missing {path}\n  The course folder should hold templates/autograde.yml and "
            f"templates/check.yml.\n  Re-run ./install, or copy them from the toolkit's "
            f"coursekit/templates/ folder.")
    return scaffold.render_workflow(path, course)


def list_state(course: cfg.Course) -> int:
    """`template` with no argument: what exists, what has a starter, what is published."""
    ids = asg.list_ids(course)
    if not ids:
        out.say(f"No assignments found under {course.assignments}.")
        out.say(f"  An assignment is a folder there holding starter/ (what the student gets),")
        out.say(f"  answers/ and assignment.json. Create one with:  {course.course} new a00")
        return 1
    repos = {}
    try:
        repos = ghcli.Gh(course.org).repos()
        have_gh = True
    except ghcli.GhUnavailable as exc:
        have_gh = False
        out.note(f"GitHub not reachable ({exc}); the published column is unknown")
    out.say(f"  {'assignment':<12} {'kind':<8} {'starter':<10} published")
    for aid in ids:
        try:
            a = asg.load(course, aid)
            kind = a.kind
        except asg.AssignmentError:
            kind = "?"
        has_starter = course.starter(aid).is_dir() and bool(asg.collect(course.starter(aid)))
        if have_gh:
            t = repos.get(course.template_repo(aid).lower())
            pub = "yes" + ("" if t and t["is_template"] else " (flag not set)") if t else "no"
        else:
            pub = "unknown"
        out.say(f"  {aid:<12} {kind:<8} {'yes' if has_starter else 'no':<10} {pub}")
    out.say(f"\n  Publish one with:  {course.course} template <assignment> --go")
    return 0


def run(course: cfg.Course, argv) -> int:
    ap = argparse.ArgumentParser(prog=f"{course.course} template",
                                 description="Publish a starter folder as a template repository.")
    ap.add_argument("assignment", nargs="?")
    ap.add_argument("--go", action="store_true", help="perform it (default is a preview)")
    ap.add_argument("--message", help="commit message")
    args = ap.parse_args(argv)

    if not args.assignment:
        return list_state(course)

    try:
        a = asg.load(course, args.assignment)
    except asg.AssignmentError as exc:
        out.say(f"error: {exc}")
        return 1

    if not a.starter.is_dir():
        out.say(f"error: there is no starter folder at\n    {a.starter}")
        out.say(f"  That is where the student-facing files go: put EXACTLY what a student")
        out.say(f"  should receive there, or scaffold it with:  {course.course} new {a.id} --force")
        return 1

    files = a.starter_files()
    if not files:
        out.say(f"error: {a.starter} has no publishable files")
        return 1

    try:
        workflow = workflow_text(course, a)
    except FileNotFoundError as exc:
        out.say(f"error: {exc}")
        return 1

    if workflow and not course.runner:
        out.say(f"error: course.json has no runner scale-set name, so the workflow would queue")
        out.say(f"  forever. Set it with:  {course.course} config runner <scale-set-name>")
        return 1

    try:
        ghcli.require_auth()
    except ghcli.GhUnavailable as exc:
        out.say(f"error: {exc}")
        return 1

    template = course.template_repo(a.id)
    full = course.full(template)
    exists = ghcli.repo_exists(full)
    wf_name = asg.WORKFLOW_PATH if a.is_auto else ".github/workflows/check.yml"

    out.say(f"{'PREVIEW: ' if not args.go else ''}Publishing {a.id} ({a.kind})")
    out.say(f"  from   : {a.starter}")
    out.say(f"  to     : {full} ({'exists, will be replaced' if exists else 'will be created'})")
    if workflow:
        out.say(f"  files  : {len(files)} + {wf_name}  (runner {course.runner}, image {course.image})")
    else:
        out.say(f"  files  : {len(files)}, no workflow (hand-graded, tick_on_manual is off)")
    for f in files:
        out.say(f"           {f}")
    out.say()

    if not args.go:
        out.preview_footer(f"{course.course} template {a.id}")
        return 0

    message = args.message or f"{a.id} starter code"
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / template
        work.mkdir(parents=True)
        for rel in files:
            dest = work / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(a.starter / rel, dest)
        if workflow:
            wf = work / wf_name
            wf.parent.mkdir(parents=True, exist_ok=True)
            wf.write_text(workflow, encoding="utf-8")

        for argv_ in (["init", "-q", "-b", "main"],
                      ["add", "-A"],
                      ["-c", "user.name=course-tools", "-c", "user.email=course-tools@local",
                       "commit", "-q", "-m", message]):
            proc = _git(argv_, work)
            if proc.returncode != 0:
                out.say(f"error: git {' '.join(argv_[:2])} failed: {proc.stderr.strip()[:200]}")
                return 1

        if not exists:
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
        out.say(f"pushed {len(files) + (1 if workflow else 0)} file(s) to {full}")

    err = ghcli.set_template_flag(full)
    if err:
        out.say(f"warning: could not mark {full} as a template ({err}); do it by hand at "
                f"https://github.com/{full}/settings")
    else:
        out.say(f"{full} is marked as a template repository")

    cfg.append_history(course.root, f"template {a.id} published to {full}")
    out.say(f"\nStudents who already have repositories are unaffected. "
            f"Use `{course.course} patch {a.id}` to push corrected provided files to them.")
    if a.is_auto:
        out.say(f"The template's own Actions run should be RED: it holds unfinished starter code.")
    return 0
