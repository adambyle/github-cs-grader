"""
new, scaffold one assignment.
=============================

    cs108 new a04
    cs108 new a04 --title "Working with files" --kind auto --grader js
    cs108 new a09 --kind manual

Creates assignments/a04/ with starter/, answers/, assignment.json, a README
stub and a MAINTENANCE stub, and, for an autograded assignment, the grading
bundle autograders/a04/ with a working test suite and a grader in the
language you pick. The scaffolded assignment is complete: `verify` passes on
it as created (starter scores 0, answers score full), so you start from
something that works and change it, rather than from nothing.

The grader language is asked once and remembered in course.json as
`grader_default`, so later assignments do not ask again unless you pass
--grader.

Nothing here touches GitHub, so there is no --go.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from .. import assignment as asg
from .. import config as cfg
from .. import out, scaffold

# The scaffolded suite runs this many checks. verify reads the same number
# out of the grader's config block, so the two are written from one place.
SCAFFOLD_CHECKS = 4


def prompt(question: str, default: str = "", choices=None) -> str:
    """Ask on a terminal; take the default when there is no terminal."""
    if not sys.stdin.isatty():
        return default
    shown = f" [{default}]" if default else ""
    while True:
        answer = input(f"  {question}{shown}: ").strip()
        if not answer:
            answer = default
        if choices and answer not in choices:
            print(f"    please answer one of: {', '.join(choices)}")
            continue
        if answer or not choices:
            return answer


def run(course: cfg.Course, argv) -> int:
    ap = argparse.ArgumentParser(prog=f"{course.course} new",
                                 description="Scaffold one assignment.")
    ap.add_argument("assignment", help="assignment id, e.g. a04")
    ap.add_argument("--title", help="assignment title")
    ap.add_argument("--kind", choices=["auto", "manual"],
                    help="autograded, or graded by hand")
    ap.add_argument("--grader", choices=["js", "py"],
                    help="language of the grader (autograded assignments only)")
    ap.add_argument("--force", action="store_true",
                    help="scaffold into a folder that already has content")
    args = ap.parse_args(argv)

    aid = args.assignment
    if not asg.ASSIGNMENT_ID_RE.match(aid):
        out.say(f"error: {aid!r} is not an assignment id (lowercase letters, digits, "
                f"dashes; e.g. a04)")
        return 1

    folder = course.assignment_dir(aid)
    bundle = course.bundle(aid)
    existing = [p for p in (folder, bundle) if p.exists() and any(p.iterdir())]
    if existing and not args.force:
        out.say(f"error: {existing[0]} already exists and is not empty.")
        out.say(f"  Pick another id, or pass --force to add the missing pieces.")
        return 1

    title = args.title or prompt("Title", aid)
    kind = args.kind or prompt("Autograded, or manual? [auto/manual]", "auto",
                               choices=["auto", "manual"])
    grader_lang = None
    if kind == "auto":
        grader_lang = args.grader or (course.grader_default if course.data.get("grader_default") else None)
        if grader_lang is None:
            grader_lang = prompt("Grader language, js or py? (remembered for next time)",
                                 "js", choices=["js", "py"])
        if grader_lang != course.data.get("grader_default"):
            cfg.save(course, {"grader_default": grader_lang},
                     note=f"chosen while scaffolding {aid}")

    values = dict(course=course.course, course_title=course.title, title=title,
                  assignment=aid, kind=kind, expected_visible=SCAFFOLD_CHECKS)

    starter = folder / "starter"
    answers = folder / "answers"
    starter.mkdir(parents=True, exist_ok=True)
    answers.mkdir(parents=True, exist_ok=True)

    def put(dest: Path, name: str):
        if dest.exists() and args.force:
            return
        scaffold.write(dest, name, **values)

    put(folder / "README.md", "README.starter.md")
    put(folder / "MAINTENANCE.md", "MAINTENANCE.md")
    put(starter / "README.md", "README.starter.md")
    put(starter / "app.js", "app.starter.js")
    put(answers / "app.js", "app.answers.js")

    if kind == "auto":
        restore = ["test.js", "package.json"]
        for dest in (starter, answers, bundle):
            put(dest / "test.js", "test.js")
            put(dest / "package.json", "package.json")
        grader_name = "autograder.js" if grader_lang == "js" else "autograder.py"
        put(bundle / grader_name, grader_name)
        if grader_lang == "py":
            (bundle / grader_name).chmod(0o755)
        data = {"title": title, "kind": "auto", "grader": grader_name, "restore": restore}
    else:
        # Manual: no tests ship, so no package.json either. The starter is the
        # instructions and the stub; the student's work is read by hand.
        data = {"title": title, "kind": "manual", "restore": []}

    if not (folder / asg.ASSIGNMENT_JSON).exists() or not args.force:
        asg.write_json(folder / asg.ASSIGNMENT_JSON, data)

    if course.title and not (course.templates / "autograde.yml").is_file():
        out.note(f"templates/autograde.yml is missing from the course folder; "
                 f"run ./install again or copy it from the toolkit")

    rel = folder.relative_to(course.root)
    out.say(f"\n  Created {rel}/")
    out.say(f"           starter/     put here EXACTLY what the student receives")
    out.say(f"           answers/     your reference solution, never published")
    out.say(f"           assignment.json   kind={kind}"
            + (f", grader={data['grader']}, restore={data['restore']}" if kind == "auto" else ""))
    if kind == "auto":
        out.say(f"  Created {bundle.relative_to(course.root)}/   with {data['grader']} and a test.js stub")
    out.say(f"\n  Next:  put your files in {rel}/starter/ (and the solution in answers/)")
    if kind == "auto":
        out.say(f"         keep test.js identical in starter/, answers/ and the bundle")
    out.say(f"         then:  {course.course} verify {aid}")
    return 0
