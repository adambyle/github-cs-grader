"""
patch, push a corrected do-not-edit file into every existing repository.
========================================================================

    cs108 patch a04                       # preview: what would change, where
    cs108 patch a04 --go                  # push the whole restore list
    cs108 patch a04 --go --files test.js
    cs108 patch a04 --go --files .github/workflows/autograde.yml   # after a config change
    cs108 patch a04 --go --students jsmith

For when you find a bug in a test after the repositories have gone out.

WHAT IT PUSHES, AND WHY THAT LIST
    By default, exactly the files on the assignment's restore list (from
    assignment.json), plus the workflow. Those files are safe to overwrite
    precisely because grading already ignores the student's copy of them:
    the grader restores its own before running. Pushing here makes the
    student's local tests and their green tick agree with the mark they were
    going to get anyway.

    The source of truth is the bundle for an autograded assignment and the
    starter for a hand-graded one. Fix the file THERE first, then run this.

WHAT IT WILL NOT PUSH
    Anything the student writes. Overwriting that destroys their work, and no
    hurry justifies it. Naming such a file with --files is refused, and the
    restore list is printed instead. --i-know-what-im-doing overrides once,
    so the refusal is a speed bump rather than a wall.

HOW IT WRITES
    Through the GitHub Contents API: no clones, no working copies. Files
    whose content already matches are skipped, so re-running costs nothing
    and adds no commits. The template repository is updated too, so students
    distributed later start correct (--skip-template to leave it alone).

THE MEASURE
    With --go, every repository's tree is read before and after, and the
    hash of every file NOT on the restore list is compared. The run ends with
    `0 deliverables changed`. That number is printed on every run precisely
    because the one day it is not zero is the day it must be seen at once.

Tell the students afterwards. A file changing under them with no
explanation is worse than the bug was.
"""

from __future__ import annotations

import argparse
from typing import Dict, List

from .. import assignment as asg
from .. import config as cfg
from .. import ghcli, out, roster as rostermod, scaffold


def run(course: cfg.Course, argv) -> int:
    ap = argparse.ArgumentParser(prog=f"{course.course} patch",
                                 description="Push corrected provided files into existing repositories.")
    ap.add_argument("assignment")
    ap.add_argument("--go", action="store_true", help="perform it (default is a preview)")
    ap.add_argument("--files", help="comma-separated paths (default: the restore list + workflow)")
    ap.add_argument("--students", help="comma-separated usernames; default all")
    ap.add_argument("--message", help="commit message")
    ap.add_argument("--skip-template", action="store_true", help="leave the template repository alone")
    ap.add_argument("--i-know-what-im-doing", dest="override", action="store_true",
                    help="allow --files to name a file outside the restore list, once")
    args = ap.parse_args(argv)

    try:
        a = asg.load(course, args.assignment)
    except asg.AssignmentError as exc:
        out.say(f"error: {exc}")
        return 1

    workflow_path = asg.WORKFLOW_PATH if a.is_auto else ".github/workflows/check.yml"
    source_dir = a.source_dir()
    # Expanded over starter, answers and bundle together, so a file that
    # exists in one copy and not the source is reported below as missing
    # rather than silently skipped.
    restore_names = a.restore_names()
    protected = list(restore_names) + ([workflow_path] if a.ships_workflow() else [])

    if args.files:
        names = [f.strip() for f in args.files.split(",") if f.strip()]
        outside = [n for n in names if n not in protected and not a.is_restored(n)]
        if outside and not args.override:
            out.say("error: refusing to push file(s) students may own: " + ", ".join(outside))
            out.say(f"  The restore list for {a.id} is: {', '.join(restore_names) or '(empty)'}")
            if a.ships_workflow():
                out.say(f"  plus the workflow {workflow_path}.")
            out.say(f"  If one of these really is a do-not-edit file, add it to \"restore\" in")
            out.say(f"  {a.dir / asg.ASSIGNMENT_JSON}; that is the list grading uses too.")
            out.say(f"  If the changed file is a deliverable, announce the change and let")
            out.say(f"  students apply it. To override once: --i-know-what-im-doing")
            return 1
    else:
        names = protected

    if not names:
        out.say(f"Nothing to patch: {a.id} has an empty restore list and ships no workflow.")
        out.say(f"  The list is \"restore\" in {a.dir / asg.ASSIGNMENT_JSON}")
        out.say(f"  Name the provided files there (folders as \"assets/\"), run "
                f"{course.course} verify {a.id}, then patch again.")
        return 0

    def source_bytes(name: str) -> bytes:
        if name == workflow_path:
            return scaffold.render_workflow(a.workflow_template(), course).encode("utf-8")
        return (source_dir / name).read_bytes()

    missing = []
    for n in names:
        if n == workflow_path:
            if not a.workflow_template().is_file():
                missing.append(str(a.workflow_template()))
        elif not (source_dir / n).is_file():
            missing.append(str(source_dir / n))
    if missing:
        out.say("error: not found: " + ", ".join(missing))
        out.say(f"  patch pushes the copy in {source_dir}; that is what grading uses.")
        out.say(f"  Put the file there (byte-identical to the starter's), then:  {course.course} verify {a.id}")
        return 1

    payload = {n: source_bytes(n) for n in names}
    message = args.message or f"Update {', '.join(names)} for {a.id} (instructor)"

    try:
        ghcli.require_auth()
        roster = rostermod.select(rostermod.participants(course.roster), args.students)
    except (ghcli.GhUnavailable, rostermod.RosterError) as exc:
        out.say(f"error: {exc}")
        return 1

    gh = ghcli.Gh(course.org)
    try:
        have = gh.repos()
    except ghcli.GhUnavailable:
        have = {}

    targets: List[tuple] = []
    if not args.skip_template:
        targets.append(("template", course.full(course.template_repo(a.id))))
    # Repositories that exist first (the ones a patch touches), newest first.
    indexed = list(enumerate(roster))
    indexed.sort(key=lambda pair: (0 if course.student_repo(a.id, pair[1]["username"]) in have else 1,
                                   -pair[0]))
    for _, student in indexed:
        targets.append((student["username"], course.full(course.student_repo(a.id, student["username"]))))

    out.say(f"{'PREVIEW: ' if not args.go else ''}Patching {', '.join(names)} for {a.id}")
    out.say(f"  source  : {source_dir}" + (f" (workflow from {a.workflow_template()})" if workflow_path in names else ""))
    out.say(f"  targets : {len(targets)}\n")

    changed = skipped = failed = missing_repos = 0
    deliverables_changed: List[str] = []
    for label, full_repo in targets:
        if full_repo.split("/", 1)[1].lower() not in have and not ghcli.repo_exists(full_repo):
            missing_repos += 1
            out.bad_line(label, f"no such repository: {full_repo}")
            continue
        before: Dict[str, str] = gh.tree(full_repo) if args.go else {}
        outcomes = []
        for name, data in payload.items():
            try:
                outcome = ghcli.put_file(full_repo, name, data, message, dry_run=not args.go)
            except RuntimeError as exc:
                outcomes.append(f"{name}: FAILED ({exc})")
                failed += 1
                continue
            if outcome != "same":
                changed += 1
            outcomes.append(f"{name}: {outcome}")
        if args.go:
            gh.invalidate()
            after = gh.tree(full_repo)
            for path_, sha in before.items():
                if path_ in payload:
                    continue
                if after.get(path_) != sha:
                    deliverables_changed.append(f"{full_repo}:{path_}")
        if all(o.endswith(": same") for o in outcomes):
            skipped += 1
            out.skip_line(label, "already current")
        elif any("FAILED" in o for o in outcomes):
            out.bad_line(label, "; ".join(outcomes))
        else:
            out.ok_line(label, "; ".join(outcomes))

    out.say()
    out.say(f"{changed} file write(s), {skipped} repo(s) already current, "
            f"{missing_repos} repo(s) missing, {failed} failure(s)")
    if args.go:
        n = len(deliverables_changed)
        line = f"{n} deliverables changed"
        out.say(out.green(line) if n == 0 else out.red(line.upper() + "  <-- this must be zero"))
        for item in deliverables_changed:
            out.say(f"    {item}")
        cfg.append_history(course.root, f"patch {a.id}: {', '.join(names)}; {changed} write(s); {n} deliverables changed")
        if changed:
            out.say("\nTell the students what changed and why. A file moving under them with")
            out.say("no explanation is worse than the bug.")
    else:
        out.say("0 deliverables would be changed (patch only ever writes the files listed above)")
        out.preview_footer(f"{course.course} patch {a.id}"
                           + (f" --files {args.files}" if args.files else "")
                           + (f" --students {args.students}" if args.students else ""))
    return 1 if failed or deliverables_changed else 0
