"""
grading.py, running a bundle against one checkout.
==================================================

Shared by `verify` (against a throwaway copy of starter/ or answers/) and by
`marks` (against a student's clone). One implementation, so the two cannot
disagree about how a grader is started.

THE GRADER IS RUN IN PLACE, FROM THE BUNDLE
    Its own path is how it finds the authoritative copies of the restore
    files. Copy the grader somewhere else first and RESTORE silently restores
    nothing. So the bundle stays where it is, the working directory is the
    checkout, and the harness supplies the environment.

THE ENVIRONMENT
    COURSE, ASSIGNMENT, USERNAME, SUBMISSION_TAG, COMMIT_URL, RELEASE_URL,
    REVIEW_URL, exactly as the contract says, plus RESTORE_FILES (the restore
    list as JSON) and BUNDLE_DIR, so the grader never has to locate
    assignment.json itself.

EXIT CODES
    0 with result.json      graded
    non-zero, no result     infrastructure error, reported as such, never a 0
"""

from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

from . import assignment as asg
from . import config as cfg

DEFAULT_TIMEOUT = 600


def grader_env(course: cfg.Course, a: asg.Assignment, username: str,
               sha: str, commit_url: str) -> dict:
    tag = f"local/{dt.datetime.now(dt.timezone.utc):%Y-%m-%dT%H-%M-%SZ}-{sha[:7]}"
    env = dict(
        os.environ,
        COURSE=course.course,
        ASSIGNMENT=a.id,
        USERNAME=username,
        SUBMISSION_TAG=tag,
        COMMIT_URL=commit_url,
        RELEASE_URL=commit_url,
        REVIEW_URL=commit_url,
        RESTORE_FILES=json.dumps(a.restore),
        BUNDLE_DIR=str(a.bundle),
        NO_COLOR="1",
    )
    env.pop("GITHUB_OUTPUT", None)
    return env


def run_grader(course: cfg.Course, a: asg.Assignment, checkout: Path,
               username: str = "verify", sha: str = "0000000",
               commit_url: str = "", timeout: int = DEFAULT_TIMEOUT) -> dict:
    """Run the assignment's grader against `checkout`.

    Returns a dict:
        rc         exit status (-1 on timeout)
        log        stdout + stderr
        result     parsed result.json or None
        seconds    wall time
        error      a one-line reason when there is no usable result
    """
    argv = asg.grader_argv(a)
    env = grader_env(course, a, username, sha, commit_url or f"local/{sha}")
    result_path = checkout / "result.json"
    if result_path.exists():
        result_path.unlink()
    started = time.monotonic()
    try:
        proc = subprocess.run(argv, cwd=str(checkout), env=env,
                              capture_output=True, text=True, timeout=timeout)
        log = proc.stdout + ("\n--- stderr ---\n" + proc.stderr if proc.stderr else "")
        rc = proc.returncode
    except subprocess.TimeoutExpired:
        log, rc = f"grader exceeded {timeout}s", -1
    except FileNotFoundError:
        log, rc = f"{argv[0]} is not installed or not on PATH", 127
    seconds = round(time.monotonic() - started, 1)

    out = {"rc": rc, "log": log, "result": None, "seconds": seconds, "error": ""}
    if rc != 0 and not result_path.exists():
        out["error"] = f"grader error (exit {rc})"
        if rc == 127:
            out["error"] = log
        return out
    if not result_path.exists():
        out["error"] = "grader wrote no result.json"
        return out
    try:
        out["result"] = json.loads(result_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        out["error"] = f"result.json is not valid JSON: {exc}"
    return out


def build_failed(result: Optional[dict]) -> bool:
    """Did the grader report that the code never loaded? Both scaffolded
    graders record that as a single 'Build' row worth the whole total."""
    if not result:
        return False
    tests = result.get("tests") or []
    return len(tests) == 1 and str(tests[0].get("test-name", "")).startswith("Build")


def first_error_line(log: str) -> str:
    markers = ("build failed", "could not be loaded", "error", "exception", "traceback")
    for line in log.splitlines():
        low = line.lower()
        if "::warning" in low or not line.strip():
            continue
        if any(m in low for m in markers):
            return line.strip()[:160]
    return ""


def runtime_report(a: asg.Assignment) -> str:
    """Which interpreter THIS process will hand the grader, printed on every
    run. On 2026-08-23 the original course graded three zeros because the
    process had inherited a PATH with the wrong compiler first; a fresh
    terminal looked fine because a fresh terminal was not the process doing
    the work. The only PATH that matters is this one."""
    import shutil
    if a.runtime == "python3":
        return f"python3 : {sys.executable}"
    path = shutil.which("node") or "not found on PATH"
    ver = ""
    if shutil.which("node"):
        try:
            ver = subprocess.run(["node", "--version"], capture_output=True, text=True,
                                 timeout=20).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            ver = ""
    return f"node    : {path} {ver}".rstrip()
