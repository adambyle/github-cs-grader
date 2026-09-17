"""
config, show or change any setting, after install.
==================================================

    cs108 config                        # every setting, its value, where it came from
    cs108 config runner                 # one setting
    cs108 config runner runners-2026    # set one, after validating it
    cs108 config tick_on_manual true
    cs108 config --check                # re-run every precondition check
    cs108 config --edit                 # open course.json in $EDITOR, validate on save

Settings change mid-semester. A scale set gets renamed, an image needs
bumping, an organization turns out to be wrong. None of that should mean
opening a JSON file and hoping. Three routes edit the same course.json: this
verb, the Settings screen in the UI, and, in a pinch, a text editor followed
by `config --check`.

WHAT A CHANGE AFFECTS
    runner, image, build and tick_on_manual only reach templates published
    from that point on. Changing one prints the commands that push the new
    workflow into existing template and student repositories, because
    without that a setting change silently applies to next semester only.

    course cannot be changed here. It is the command name and every
    repository name; renaming it would rename the command and none of the
    repositories. Refusing and explaining beats half-doing it.

HISTORY
    Every change is one dated line in course-history.log.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess

from .. import assignment as asg
from .. import checks
from .. import config as cfg
from .. import ghcli, out


def show(course: cfg.Course, key=None) -> int:
    raw = json.loads((course.root / cfg.CONFIG_NAME).read_text(encoding="utf-8"))
    keys = [key] if key else list(cfg.DESCRIPTIONS)
    if key and key not in cfg.DESCRIPTIONS:
        out.say(f"error: unknown setting {key!r}. Settings: {', '.join(cfg.DESCRIPTIONS)}")
        return 1
    out.say(f"{out.bold(course.course)}  {course.root / cfg.CONFIG_NAME}\n")
    for k in keys:
        if k in raw:
            value, origin = raw[k], "course.json"
        else:
            value, origin = cfg.DEFAULTS.get(k, ""), "default"
            if k == "grading" and not value:
                value = f"~/{course.course}-grading"
        shown = json.dumps(value) if isinstance(value, bool) else str(value)
        out.say(f"  {k:<15} {shown:<32} {out.dim(origin)}")
        if key:
            out.say(f"                  {out.dim(cfg.DESCRIPTIONS[k])}")
    if not key:
        out.say(f"\n  {out.dim('Change one:  ' + course.course + ' config <setting> <value>')}")
        out.say(f"  {out.dim('History:     ' + str(course.root / cfg.HISTORY_NAME))}")
    return 0


def published_assignments(course: cfg.Course):
    """Assignment ids whose template repository exists (empty if GitHub is unreachable)."""
    try:
        repos = ghcli.Gh(course.org).repos()
    except ghcli.GhUnavailable:
        return []
    return [aid for aid in asg.list_ids(course) if course.template_repo(aid).lower() in repos]


def explain_workflow_change(course: cfg.Course, key: str) -> None:
    out.say(f"\n  {out.yellow('This only reaches templates published from now on.')}")
    out.say("  Repositories that already exist keep the old workflow until it is re-pushed:")
    live = published_assignments(course)
    if live:
        for aid in live:
            out.say(f"    {course.course} patch {aid} --files .github/workflows/autograde.yml --go")
        out.say("  (each of those updates the template repository and every student repository)")
    else:
        out.say(f"    {course.course} patch <assignment> --files .github/workflows/autograde.yml --go")
    if key in ("tick_on_manual",):
        out.say("  Hand-graded assignments use .github/workflows/check.yml instead; re-publish")
        out.say(f"  them with `{course.course} template <assignment> --go` to add or remove it.")


def set_value(course: cfg.Course, key: str, raw: str) -> int:
    if key == "course":
        out.say("error: the course code cannot be changed after install.")
        out.say("  It is the command name and part of every repository name. Changing it here")
        out.say("  would rename the command and none of the repositories. To start a new course,")
        out.say("  run ./install again with the new code and a new course folder.")
        return 1
    if key not in cfg.DESCRIPTIONS:
        out.say(f"error: unknown setting {key!r}. Settings: {', '.join(cfg.DESCRIPTIONS)}")
        return 1
    value = cfg.coerce(key, raw)
    why = cfg.validate_value(key, value)
    if why:
        out.say(f"error: {why}")
        return 1

    # Where a value can be checked against GitHub, check it before writing.
    if key == "org":
        r = checks.check_org(str(value))
        if r.failed:
            out.say(f"error: {r.detail}")
            return 1
        if r.status == checks.WARN:
            out.note(r.detail)
    if key == "runner":
        r = checks.check_runner(course.org, str(value))
        out.say(f"  {r.name}: {r.detail}")
    if key == "image":
        r = checks.check_image(str(value))
        if r.status != checks.OK:
            out.note(r.detail)

    old = course.data.get(key)
    if old == value:
        out.say(f"{key} is already {value!r}; nothing changed")
        return 0
    cfg.save(course, {key: value})
    out.say(f"{key}: {old!r} -> {value!r}   (recorded in {cfg.HISTORY_NAME})")
    if key in cfg.WORKFLOW_KEYS:
        explain_workflow_change(course, key)
    if key == "grading":
        out.say(f"  Existing gradebooks stay under the old folder; nothing is moved.")
    return 0


def check(course: cfg.Course) -> int:
    out.say(f"Checking {course.course} ({course.org}):")
    results = checks.preconditions(course.org)
    results.append(checks.check_runner(course.org, course.runner))
    results.append(checks.check_image(course.image))
    results.append(checks.check_grading_folder(course.grading))
    ok = checks.print_results(results)
    out.say()
    out.say(f"  The runner check can only see runners that exist right now. The certain")
    out.say(f"  answer is a job that ran:  {course.course} doctor --smoke --go")
    return 0 if ok else 1


def edit(course: cfg.Course) -> int:
    editor = os.environ.get("VISUAL") or os.environ.get("EDITOR") or "nano"
    path = course.root / cfg.CONFIG_NAME
    before = path.read_text(encoding="utf-8")
    try:
        subprocess.run([editor, str(path)])
    except FileNotFoundError:
        out.say(f"error: editor {editor!r} not found; set $EDITOR")
        return 1
    after = path.read_text(encoding="utf-8")
    if after == before:
        out.say("unchanged")
        return 0
    try:
        data = json.loads(after)
    except json.JSONDecodeError as exc:
        path.write_text(before, encoding="utf-8")
        out.say(f"error: the edited file is not valid JSON ({exc}); the previous contents were restored")
        return 1
    problems = cfg.validate_all(data)
    if problems:
        path.write_text(before, encoding="utf-8")
        out.say("error: the edited file has problems; the previous contents were restored:")
        for p in problems:
            out.say(f"    {p}")
        return 1
    old = json.loads(before)
    changed = {k: data.get(k) for k in set(old) | set(data) if old.get(k) != data.get(k)}
    if "course" in changed:
        path.write_text(before, encoding="utf-8")
        out.say("error: the course code cannot be changed; the previous contents were restored")
        return 1
    for k, v in changed.items():
        cfg.append_history(course.root, f"config {k}: {old.get(k)!r} -> {v!r}  (via --edit)")
    out.say(f"saved; changed: {', '.join(sorted(changed)) or 'nothing'}")
    if any(k in cfg.WORKFLOW_KEYS for k in changed):
        explain_workflow_change(course, next(k for k in changed if k in cfg.WORKFLOW_KEYS))
    return 0


def run(course: cfg.Course, argv) -> int:
    ap = argparse.ArgumentParser(prog=f"{course.course} config",
                                 description="Show or change any setting.")
    ap.add_argument("key", nargs="?")
    ap.add_argument("value", nargs="?")
    ap.add_argument("--check", action="store_true", help="re-run every precondition check")
    ap.add_argument("--edit", action="store_true", help="open course.json in $EDITOR")
    args = ap.parse_args(argv)
    if args.check:
        return check(course)
    if args.edit:
        return edit(course)
    if args.key and args.value is not None:
        return set_value(course, args.key, args.value)
    return show(course, args.key)
