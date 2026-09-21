"""
state.py, one snapshot of the whole course: disk, GitHub, gradebooks.
=====================================================================

Everything the bare command and the UI show comes from `snapshot()`. One
function, one plain dict, the browser gets it as JSON, and there is no
second source of truth to drift.

WHAT IT READS
    disk      course.json, roster.csv, assignments/, autograders/
    GitHub    three read-only calls (members, invitations, repositories)
    grading   <grading>/<a>/gradebook.csv or collect.csv, if they exist

WHAT IT NEVER DOES
    Change anything. Not a file, not a repository. Rendering a page must be
    safe to do a hundred times.

WHEN GITHUB IS UNREACHABLE
    `github.available` is false and every GitHub-derived field is None
    rather than False. "Not published" would be a confident wrong answer;
    "unknown" is the truth.
"""

from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from . import assignment as asg
from . import config as cfg
from . import ghcli, roster as rostermod


def _when(text: str) -> Optional[datetime]:
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _read_csv(path: Path) -> Dict[str, dict]:
    if not path.is_file():
        return {}
    with path.open(newline="", encoding="utf-8-sig") as fh:
        return {r["username"]: r for r in csv.DictReader(fh) if r.get("username")}


def _mtime(path: Path) -> Optional[datetime]:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
    except OSError:
        return None


def snapshot(course: cfg.Course, gh: Optional[ghcli.Gh] = None) -> dict:
    gh = gh or ghcli.Gh(course.org)
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    github = {"available": True, "error": None}
    members, pending, repos = [], [], {}
    try:
        members = gh.members()
        pending = gh.pending()
        repos = gh.repos()
    except ghcli.GhUnavailable as exc:
        github = {"available": False, "error": str(exc)}
    member_set = {m.lower() for m in members}
    pending_set = {p["login"].lower() for p in pending if p["login"]}

    # ── people ─────────────────────────────────────────────────────────
    roster_error = ""
    try:
        rows = rostermod.read_rows(course.roster)
    except rostermod.RosterError as exc:
        rows, roster_error = [], str(exc)
    people = []
    for r in rows:
        login = r["github_id"].lower()
        if not github["available"]:
            membership = None
        elif not login:
            membership = "no github_id"
        elif login in member_set:
            membership = "active"
        elif login in pending_set:
            membership = "pending"
        else:
            membership = "absent"
        people.append({"username": r["username"], "name": rostermod.display_name(r),
                       "last_name": r["last_name"], "email": r["email"],
                       "section": r["section"], "github_id": r["github_id"],
                       "role": r["role"], "membership": membership, "cells": {}})
    participants = [p for p in people if p["role"] in rostermod.PARTICIPANT_ROLES]
    students = [p for p in participants if p["role"] == "student"]

    # ── assignments ────────────────────────────────────────────────────
    assignments = []
    for aid in asg.list_ids(course):
        try:
            a = asg.load(course, aid)
            problems = a.problems()
            kind = a.kind
        except asg.AssignmentError as exc:
            a, problems, kind = None, [str(exc)], "?"

        drift = []
        if a and a.starter.is_dir():
            for name in a.restore_names():
                copies = {"starter": a.starter / name, "answers": a.answers / name}
                if a.is_auto:
                    copies["bundle"] = a.bundle / name
                present = {k: p.read_bytes() for k, p in copies.items() if p.is_file()}
                if "starter" not in present or (a.is_auto and "bundle" not in present):
                    drift.append({"file": name, "problem": "missing from " + ", ".join(
                        k for k in copies if k not in present)})
                elif len(set(present.values())) > 1:
                    drift.append({"file": name, "problem": "copies differ"})

        template_name = course.template_repo(aid)
        template = repos.get(template_name.lower()) if github["available"] else None
        outdir = course.grading_dir(aid)
        gradebook = _read_csv(outdir / "gradebook.csv")
        collected = _read_csv(outdir / "collect.csv")
        known = gradebook or collected
        graded_at = _mtime(outdir / "gradebook.csv") if gradebook else None
        sheets = sorted(p.name for p in outdir.glob(f"marks-{aid}*.csv")) if outdir.is_dir() else []

        repo_count = complete_count = stale = 0
        for p in participants:
            repo_name = course.student_repo(aid, p["username"])
            repo = repos.get(repo_name) if github["available"] else None
            row = known.get(p["username"], {})
            pushed = _when((repo or {}).get("pushed_at", ""))
            is_stale = bool(graded_at and pushed and pushed > graded_at and p["username"] in gradebook)
            cell = {
                "repo": repo_name,
                "has_repo": (repo is not None) if github["available"] else None,
                "url": (repo or {}).get("url", ""),
                "pushed_at": (repo or {}).get("pushed_at", ""),
                "score": row.get("score", "") if gradebook else "",
                "max": row.get("max_score", "") if gradebook else "",
                "complete": row.get("complete", ""),
                "changed": row.get("changed", ""),
                "status": row.get("status", ""),
                "stale": is_stale,
            }
            if repo is not None:
                repo_count += 1
            if cell["complete"] == "yes":
                complete_count += 1
            if is_stale:
                stale += 1
            p["cells"][aid] = cell

        assignments.append({
            "id": aid, "kind": kind, "title": a.title if a else aid,
            "has_starter": bool(a and a.starter.is_dir() and asg.collect(a.starter)),
            "has_answers": bool(a and a.answers.is_dir()),
            "has_bundle": bool(a and a.bundle.is_dir()),
            "restore": a.restore if a else [],
            "problems": problems, "drift": drift,
            "template": template_name,
            "template_exists": (template is not None) if github["available"] else None,
            "is_template": bool((template or {}).get("is_template")) if template else None,
            "template_url": (template or {}).get("url", ""),
            "repos": repo_count if github["available"] else None,
            "graded": bool(gradebook), "graded_count": len(gradebook),
            "collected": bool(collected),
            "complete_count": complete_count,
            "graded_at": graded_at.replace(microsecond=0).isoformat() if graded_at else "",
            "stale_count": stale, "sheets": sheets,
            "grading_dir": str(outdir),
        })

    return {
        "generated": now,
        "course": {k: course.data.get(k, cfg.DEFAULTS.get(k)) for k in cfg.DESCRIPTIONS},
        "paths": {"root": str(course.root), "roster": str(course.roster),
                  "grading": str(course.grading), "config": str(course.root / cfg.CONFIG_NAME)},
        "github": github,
        "roster_error": roster_error,
        "roster_problems": rostermod.problems(rows) if rows else [],
        "people": people,
        "participants": participants,
        "students": students,
        "assignments": assignments,
    }


def read_sheet(path: Path) -> List[dict]:
    with path.open(newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))
