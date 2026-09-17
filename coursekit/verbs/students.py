"""
students import, merge a form export into the roster.
=====================================================

    cs108 students import ~/Downloads/responses.csv         # preview
    cs108 students import ~/Downloads/responses.csv --go    # write

Reads the CSV exported from the Google Form where students give their GitHub
username, and merges it into roster/roster.csv, the one list every other
verb reads.

IT IS ADDITIVE ONLY
    It never rewrites and never removes an existing row, so hand corrections
    survive re-import. What it does:
      - a form row whose student is already on the roster: fills in a BLANK
        github_id (and other blank fields) and nothing else
      - a form row for a student not on the roster: appended, role=student
      - a GitHub username that is not a valid login: reported, not written

HOW COLUMNS ARE FOUND
    Form headings are question text and get reworded, so columns are matched
    on a distinctive fragment ("github", "email", "name", "section",
    "username" or "student id"). The institutional username is taken from a
    username column when the form has one, otherwise from the local part of
    the email address (jsmith@example.edu -> jsmith).

    Students paste a profile URL about as often as a username, so
    https://github.com/jsmith is accepted and trimmed.
"""

from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path

from .. import config as cfg
from .. import out, roster as rostermod

COLUMN_HINTS = {
    "github": ["github username", "github user", "github id", "github"],
    "username": ["student id", "institution", "username", "netid", "user id"],
    "name": ["your name", "full name", "name"],
    "email": ["email"],
    "section": ["lab section", "section"],
}


def find_column(headers, key):
    lowered = [(h, h.lower()) for h in headers]
    for hint in COLUMN_HINTS[key]:
        for original, low in lowered:
            if hint in low and (key != "username" or "github" not in low):
                return original
    return None


def split_name(full: str):
    parts = (full or "").strip().split()
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], " ".join(parts[1:])


def clean_github(raw: str) -> str:
    text = (raw or "").strip()
    text = re.sub(r"^https?://(www\.)?github\.com/", "", text)
    return text.strip().strip("/").lstrip("@")


def run(course: cfg.Course, argv) -> int:
    ap = argparse.ArgumentParser(prog=f"{course.course} students import",
                                 description="Merge a form export into the roster.")
    ap.add_argument("responses", type=Path, help="CSV exported from the form")
    ap.add_argument("--go", action="store_true", help="write the roster (default is a preview)")
    args = ap.parse_args(argv)

    responses = args.responses.expanduser()
    if not responses.is_file():
        out.say(f"error: no such file: {responses}")
        return 1
    with responses.open(newline="", encoding="utf-8-sig") as fh:
        form = list(csv.DictReader(fh))
    if not form:
        out.say(f"error: {responses} has no rows")
        return 1
    headers = list(form[0].keys())
    cols = {key: find_column(headers, key) for key in COLUMN_HINTS}
    if not cols["github"]:
        out.say("error: could not find a GitHub username column. Headers were:\n  "
                + "\n  ".join(headers))
        return 1

    roster_path = course.roster
    existing = rostermod.read_rows(roster_path) if roster_path.is_file() else []
    by_user = {r["username"].lower(): r for r in existing}
    by_email = {r["email"].lower(): r for r in existing if r["email"]}

    added, filled, same, rejected = [], [], [], []
    for row in form:
        github = clean_github(row.get(cols["github"], ""))
        email = (row.get(cols["email"], "") if cols["email"] else "").strip()
        username = (row.get(cols["username"], "") if cols["username"] else "").strip()
        if not username and email and "@" in email:
            username = email.split("@", 1)[0]
        if not username and github:
            username = github
        if not username:
            continue
        if github and not rostermod.GITHUB_ID_RE.match(github):
            rejected.append((github, username))
            continue
        first, last = split_name(row.get(cols["name"], "") if cols["name"] else "")
        record = {"username": username, "first_name": first, "last_name": last,
                  "email": email, "section": (row.get(cols["section"], "") if cols["section"] else "").strip(),
                  "github_id": github, "role": "student"}
        target = by_user.get(username.lower()) or (by_email.get(email.lower()) if email else None)
        if target:
            blanks = [f for f in rostermod.FIELDS if not target.get(f) and record[f] and f != "role"]
            for f in blanks:
                target[f] = record[f]
            (filled if blanks else same).append((target["username"], blanks))
            continue
        existing.append(record)
        by_user[username.lower()] = record
        if email:
            by_email[email.lower()] = record
        added.append(record)

    out.say(f"{'PREVIEW: ' if not args.go else ''}roster: {roster_path}")
    out.say(f"  responses read : {len(form)}")
    out.say(f"  new students   : {len(added)}")
    for r in added:
        out.say(f"                   {r['username']:<20} {rostermod.display_name(r):<24} github {r['github_id'] or '(none)'}")
    if filled:
        out.say(f"  filled in      : {len(filled)}")
        for u, fields in filled:
            out.say(f"                   {u:<20} {', '.join(fields)}")
    if same:
        out.say(f"  already there  : {len(same)}  ({', '.join(u for u, _ in same)})")
    if rejected:
        out.say(f"  NOT a GitHub username : {len(rejected)}; ask these students again")
        for bad, who in rejected:
            out.say(f"                   {bad!r} from {who}")

    if not args.go:
        out.preview_footer(f"{course.course} students import {args.responses}")
        return 0
    if not added and not filled:
        out.say("\nRoster unchanged.")
        return 0
    rostermod.write_rows(roster_path, existing)
    cfg.append_history(course.root, f"students import {responses.name}: +{len(added)} new, {len(filled)} filled")
    out.say(f"\nwrote {len(existing)} row(s) to {roster_path}")
    out.say(f"Next:  {course.course} assign <assignment> --go")
    return 0
