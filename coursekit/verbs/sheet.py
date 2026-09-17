"""
sheet, a CSV to type manual marks into.
=======================================

    cs108 sheet a04                                # writes <grading>/a04/marks-a04.csv
    cs108 sheet a04 --columns design,correctness,style
    cs108 sheet a04 --open                         # and open it in the spreadsheet app

    username,name,github_id,repo,last_push,complete,changed,score,max_score,mark,comment
    jsmith,"Smith, Jane",jsmith,https://github.com/...,2026-10-14T22:41Z,yes,"edited app.js (+2 more)",,,,

RULES THAT MAKE IT USABLE
  - Everything the system knows is filled in. The columns for you are LAST
    and EMPTY: mark, comment, then any --columns, at the right-hand end. Open
    it, click the first empty cell, type downward.
  - One row per participant in the roster, including those with no
    repository and those whose repository is an untouched starter, because a
    missing row is invisible and a zero is not.
  - Sorted by last name, the order you read names in.
  - score and max_score are filled when `marks` has run and blank otherwise.
    On a hand-graded assignment they are always blank, which is correct.
  - complete and changed come from the last `marks` or `collect` run. If
    neither has run yet, they are blank and the sheet says so.
  - NEVER overwrites a sheet that has marks in it. If marks-a04.csv exists
    and any mark cell is non-empty, marks-a04-2.csv is written instead.
  - UTF-8 with a BOM and CRLF line endings, so Excel on macOS does not
    mangle names with accents.

WHERE THIS SYSTEM STOPS
    sheet exports. Nothing imports. Fill it in and take it wherever you keep
    grades; the toolkit never reads it back and never merges it anywhere.
    Two files that both look authoritative is how grades get lost.
"""

from __future__ import annotations

import argparse
import csv
import io
import subprocess
import sys
from pathlib import Path

from .. import assignment as asg
from .. import config as cfg
from .. import ghcli, out, roster as rostermod
from .marks import read_gradebook

BASE_FIELDS = ["username", "name", "github_id", "repo", "last_push", "complete",
               "changed", "score", "max_score"]
MARK_FIELDS = ["mark", "comment"]


def has_marks(path: Path) -> bool:
    """Does an existing sheet hold anything typed into its mark columns?"""
    if not path.is_file():
        return False
    with path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        typed = [f for f in (reader.fieldnames or []) if f not in BASE_FIELDS]
        for row in reader:
            if any((row.get(f) or "").strip() for f in typed):
                return True
    return False


def next_free(outdir: Path, aid: str) -> Path:
    path = outdir / f"marks-{aid}.csv"
    n = 1
    while path.is_file() and has_marks(path):
        n += 1
        path = outdir / f"marks-{aid}-{n}.csv"
    return path


def build_rows(course: cfg.Course, a: asg.Assignment, extra: list) -> tuple:
    roster = sorted(rostermod.participants(course.roster), key=rostermod.sort_key_last_name)
    outdir = course.grading_dir(a.id)
    gradebook = read_gradebook(outdir / "gradebook.csv")
    collected = read_gradebook(outdir / "collect.csv") if not gradebook else {}
    source = "gradebook.csv" if gradebook else ("collect.csv" if collected else "")
    known = gradebook or collected

    repos = {}
    gh_note = ""
    try:
        repos = ghcli.Gh(course.org).repos()
    except ghcli.GhUnavailable as exc:
        gh_note = f"GitHub not reachable ({exc}); repo and last_push are blank"

    rows = []
    for s in roster:
        repo_name = course.student_repo(a.id, s["username"])
        repo = repos.get(repo_name)
        k = known.get(s["username"], {})
        complete = k.get("complete", "")
        if repos and not repo:
            complete = "no repository"
        row = {
            "username": s["username"],
            "name": f"{s['last_name']}, {s['first_name']}".strip(", ") or s["username"],
            "github_id": s["github_id"],
            "repo": repo["url"] if repo else "",
            "last_push": (repo or {}).get("pushed_at", ""),
            "complete": complete,
            "changed": k.get("changed", ""),
            "score": k.get("score", "") if gradebook else "",
            "max_score": k.get("max_score", "") if gradebook else "",
        }
        for f in MARK_FIELDS + extra:
            row[f] = ""
        rows.append(row)
    return rows, source, gh_note


def run(course: cfg.Course, argv) -> int:
    ap = argparse.ArgumentParser(prog=f"{course.course} sheet",
                                 description="Write a CSV to type manual marks into.")
    ap.add_argument("assignment")
    ap.add_argument("--columns", help="extra empty columns, comma-separated")
    ap.add_argument("--open", action="store_true", help="open the file afterwards")
    args = ap.parse_args(argv)

    try:
        a = asg.load(course, args.assignment)
    except asg.AssignmentError as exc:
        out.say(f"error: {exc}")
        return 1
    extra = [c.strip() for c in (args.columns or "").split(",") if c.strip()]
    try:
        rows, source, gh_note = build_rows(course, a, extra)
    except rostermod.RosterError as exc:
        out.say(f"error: {exc}")
        return 1

    outdir = course.grading_dir(a.id)
    outdir.mkdir(parents=True, exist_ok=True)
    path = next_free(outdir, a.id)
    fields = BASE_FIELDS + MARK_FIELDS + extra

    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=fields, lineterminator="\r\n")
    w.writeheader()
    w.writerows(rows)
    path.write_bytes(b"\xef\xbb\xbf" + buf.getvalue().encode("utf-8"))

    out.say(f"wrote {path}")
    out.say(f"  {len(rows)} row(s), sorted by last name; type into: {', '.join(MARK_FIELDS + extra)}")
    if source:
        out.say(f"  complete/changed{'/score' if source == 'gradebook.csv' else ''} from {outdir / source}")
    else:
        out.say(f"  complete and changed are blank: run `{course.course} collect {a.id}` first to fill them")
    if gh_note:
        out.note(gh_note)
    if path.name != f"marks-{a.id}.csv":
        out.say(f"  (marks-{a.id}.csv already has marks typed in, so it was left alone)")
    if args.open:
        opener = "open" if sys.platform == "darwin" else "xdg-open"
        try:
            subprocess.Popen([opener, str(path)])
        except OSError:
            out.say(f"  could not open it automatically; open {path} yourself")
    return 0
