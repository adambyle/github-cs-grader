"""
roster.py, the single authoritative list of students.
=====================================================

    username,first_name,last_name,email,section,github_id,role

    username    the institution's identifier (jsmith). Forms the repository
                name, so it is stable even if the student renames their
                GitHub account.
    github_id   the GitHub login. Blank until the student supplies it, and a
                student with a blank github_id cannot be invited or given a
                repository. `assign` says so by name.
    role        student (the default), test, teacher or staff.

    role=test   accounts are distributed to and graded exactly like students,
                so an assignment can be tried end to end before anyone real
                sees it, and are EXCLUDED from class counts.
    role=teacher and role=staff rows belong on the list (it is the course's
                list of people) but are never distributed to or graded.

Every tool reads the roster through this module, because the day each tool
kept its own copy of the parsing was the day one of them created a repository
for the instructor.

This file holds names and email addresses. Keep the course folder in a
private repository.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import List, Optional

FIELDS = ["username", "first_name", "last_name", "email", "section",
          "github_id", "role"]

# GitHub's own rule for logins: alphanumerics with single hyphens between,
# never at either end, at most 39 characters.
GITHUB_ID_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38}$")

# Roles that receive repositories and get graded.
PARTICIPANT_ROLES = ("student", "test")


class RosterError(Exception):
    pass


def read_rows(path: Path) -> List[dict]:
    """Every row of the roster, untouched, in file order."""
    if not path.is_file():
        raise RosterError(f"roster not found: {path}\n"
                          f"  The roster is one CSV with the header\n"
                          f"    {','.join(FIELDS)}\n"
                          f"  Create it, or merge a form export with `students import`.")
    with path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        rows = list(reader)
        headers = reader.fieldnames or []
    if "username" not in headers:
        raise RosterError(f"{path} has no 'username' column; found {headers}")
    for row in rows:
        for key in FIELDS:
            row[key] = (row.get(key) or "").strip()
        row["role"] = (row["role"] or "student").lower()
    return [r for r in rows if r["username"]]


def participants(path: Path) -> List[dict]:
    """The rows that get repositories and marks: students and test accounts."""
    return [r for r in read_rows(path) if r["role"] in PARTICIPANT_ROLES]


def students_only(rows: List[dict]) -> List[dict]:
    """Class counts exclude test accounts."""
    return [r for r in rows if r["role"] == "student"]


def display_name(row: dict) -> str:
    name = " ".join(x for x in (row.get("first_name"), row.get("last_name")) if x)
    return name or row["username"]


def _fold(text: str) -> str:
    """Lowercase with accents stripped, so Émile sorts with Emile rather than
    after Zimmerman. Sorting is the only place this is used; the roster
    itself keeps the accents."""
    import unicodedata
    decomposed = unicodedata.normalize("NFKD", text or "")
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).lower()


def sort_key_last_name(row: dict):
    return (_fold(row.get("last_name")), _fold(row.get("first_name")), row["username"].lower())


def select(rows: List[dict], wanted: Optional[str]) -> List[dict]:
    """Apply a --students list (comma separated usernames or github ids)."""
    if not wanted:
        return rows
    keys = {s.strip().lower() for s in wanted.split(",") if s.strip()}
    picked = [r for r in rows
              if r["username"].lower() in keys or r["github_id"].lower() in keys]
    if not picked:
        raise RosterError("no roster rows matched --students " + wanted)
    return picked


def write_rows(path: Path, rows: List[dict], headers: Optional[List[str]] = None) -> None:
    """Write the roster back. Only `students import` calls this, and only
    additively; nothing else in the toolkit ever rewrites the roster."""
    out_headers = list(headers or FIELDS)
    for f in FIELDS:
        if f not in out_headers:
            out_headers.append(f)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=out_headers, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: (row.get(k) or "") for k in out_headers})


def problems(rows: List[dict]) -> List[str]:
    """What `doctor` reports about the roster: missing ids, bad ids, duplicates."""
    out = []
    seen_users, seen_ids = {}, {}
    for row in rows:
        u = row["username"].lower()
        if u in seen_users:
            out.append(f"duplicate username {row['username']!r}")
        seen_users[u] = row
        gid = row["github_id"]
        if row["role"] in PARTICIPANT_ROLES and not gid:
            out.append(f"{row['username']} has no github_id, so cannot receive a repository")
        elif gid and not GITHUB_ID_RE.match(gid):
            out.append(f"{row['username']}: github_id {gid!r} is not a valid GitHub login")
        if gid:
            if gid.lower() in seen_ids:
                out.append(f"github_id {gid!r} appears twice ({seen_ids[gid.lower()]} and {row['username']})")
            seen_ids[gid.lower()] = row["username"]
    return out
