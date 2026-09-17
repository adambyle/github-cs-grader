#!/usr/bin/env python3
"""
autograder.py, {{course}} {{assignment}}: {{title}}

The grading bundle's entry point, in Python. `{{course}} marks` runs it once
per student, inside a clean checkout of the student's repository. There is
an identical grader written in JavaScript (autograder.js in the toolkit's
scaffold folder); an assignment names ONE of them in assignment.json and the
harness dispatches by extension. Pick the language you would rather read at
eleven at night.

THE CONTRACT (the same in both languages; see docs/writing-an-assignment.md)

    cwd                      the student's checkout
    Path(__file__).parent    this bundle; the authoritative files sit here
    reads (environment)      COURSE, ASSIGNMENT, USERNAME, SUBMISSION_TAG,
                             COMMIT_URL, RELEASE_URL, REVIEW_URL
                             RESTORE_FILES (JSON array, set by the harness)
    must write               ./result.json
    may write                ./feedback.md
    exit 0                   graded, whether the student passed or failed
    exit non-zero            infrastructure error, NOT a student failure

  That last line matters: a student whose code does not load scores zero and
  this exits 0. A missing bundle file or a broken runtime exits 1, and `marks`
  reports it as a tooling problem instead of recording a zero.

WHAT IT DOES, IN ORDER
  1. RESTORE   copies every file on the restore list from this bundle over
               the student's copy. The list lives in
               assignments/<a>/assignment.json; the harness hands it over in
               RESTORE_FILES so this file never has to find that path.
  2. VISIBLE   runs the suite (SUITE below) with COURSE_JSON_OUT set, and
               reads back one row per check.
  3. HIDDEN    optional. If HIDDEN_SUITE names a file in this bundle, its
               source is read, the file is DELETED from disk, and it is run
               from memory through stdin. Student code runs with this
               process's privileges and can read any file that exists at that
               moment; this is obscure, not secret. Never write a hidden test
               whose content is itself the answer.
  4. RESULT    writes result.json (schema course/result/v1) and feedback.md.
"""

import datetime
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# ── per-assignment configuration ────────────────────────────────────────
# Plain literals only. `verify` reads them with a regex, so keep the form
# `NAME = value` exactly.

EXPECTED_VISIBLE = {{expected_visible}}   # checks the visible suite runs
EXPECTED_HIDDEN = 0                       # and the hidden one
POINTS = {}                               # label prefix -> points; default 1
DEFAULT_POINTS = 1
HIDDEN_SUITE = None                       # e.g. "hidden_test.js", or None
HIDDEN_PREFIX = "Additional: "
SUITE = ["node", "test.js"]               # how to run the visible suite
TIMEOUT = 300                             # seconds, per suite

# ────────────────────────────────────────────────────────────────────────

HERE = Path(__file__).resolve().parent
REPO = Path.cwd()


def log(msg):
    print(msg, flush=True)


def restore_list():
    """The restore list, from the harness, falling back to assignment.json."""
    raw = os.environ.get("RESTORE_FILES")
    if raw:
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass
    aid = os.environ.get("ASSIGNMENT") or HERE.name
    candidate = HERE.parent.parent / "assignments" / aid / "assignment.json"
    if candidate.is_file():
        return json.loads(candidate.read_text(encoding="utf-8")).get("restore", [])
    log("::warning::no restore list available; grading the student's copies as they are")
    return []


def restore_files():
    """Overwrite student copies of provided files with the bundle's."""
    restored = []
    for entry in restore_list():
        if entry.endswith("/"):
            folder = HERE / entry.rstrip("/")
            names = [entry + p.relative_to(folder).as_posix()
                     for p in sorted(folder.rglob("*")) if p.is_file()] if folder.is_dir() else []
            if not names:
                log(f"::warning::bundle is missing {entry}; using the student's copy")
        else:
            names = [entry]
        for name in names:
            src = HERE / name
            if not src.is_file():
                log(f"::warning::bundle is missing {name}; using the student's copy")
                continue
            dst = REPO / name
            dst.parent.mkdir(parents=True, exist_ok=True)
            changed = (not dst.is_file()) or dst.read_bytes() != src.read_bytes()
            shutil.copyfile(src, dst)
            if changed:
                restored.append(name)
    return restored


def points_for(label):
    for prefix, pts in POINTS.items():
        if label.startswith(prefix):
            return pts
    return DEFAULT_POINTS


def run_suite(argv, results_path, label, stdin=None):
    """Run one suite in the checkout. Returns parsed JSON, or None."""
    if results_path.exists():
        results_path.unlink()
    env = dict(os.environ, COURSE_JSON_OUT=str(results_path), NO_COLOR="1")
    log(f"── running {label} ──────────────────────────────────────────────")
    try:
        proc = subprocess.run(argv, input=stdin, cwd=REPO, env=env,
                              capture_output=True, text=True, timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        log(f"::error::{label} exceeded {TIMEOUT}s; likely an infinite loop")
        return {"build": True, "build_error": "", "timeout": True,
                "tests": [{"name": f"{label} completed within {TIMEOUT}s", "passed": False,
                           "hints": ["the test suite timed out; check for an infinite loop"]}]}
    except FileNotFoundError:
        log(f"::error::{argv[0]} is not installed")
        return None
    log(proc.stdout)
    if proc.stderr.strip():
        log(f"── {label} stderr ──")
        log(proc.stderr[-4000:])
    log("──────────────────────────────────────────────────────────────────")
    if not results_path.is_file():
        return None
    try:
        return json.loads(results_path.read_text())
    except json.JSONDecodeError as exc:
        log(f"::error::could not parse {label} JSON output: {exc}")
        return None


def run_hidden(script, results_path, label):
    """Run the hidden suite from memory, after removing it from disk."""
    source = script.read_text()
    try:
        script.unlink()
    except OSError as exc:
        log(f"::warning::could not remove {script.name} from disk: {exc}")
    runtime = "node" if script.suffix == ".js" else sys.executable
    return run_suite([runtime, "-"], results_path, label, stdin=source)


def rows_from(data, prefix=""):
    rows, hints = [], {}
    for t in data.get("tests", []):
        pts = points_for(t["name"])
        name = prefix + t["name"]
        rows.append({"test-name": name, "passed": bool(t["passed"]),
                     "score": pts if t["passed"] else 0, "max-score": pts})
        hints[name] = t.get("hints", [])
    return rows, hints


def failure_section(title, rows, hints):
    failed = [r for r in rows if not r["passed"]]
    if not failed:
        return []
    out = [f"### {title}", ""]
    for r in failed:
        out.append(f"- **{r['test-name']}**")
        for h in hints.get(r["test-name"], []):
            out.append(f"  - {h}")
    out.append("")
    return out


def write_feedback(vis_rows, vis_hints, hid_rows, hid_hints, restored, build_error):
    rows = vis_rows + hid_rows
    score = sum(r["score"] for r in rows)
    max_score = sum(r["max-score"] for r in rows)
    out = [f"## {score} / {max_score}", ""]
    if build_error:
        out += ["### Your code did not load", "",
                "Fix the error below, run the tests locally until everything passes, "
                "then push again.", "", "```", build_error.strip()[-3000:], "```", ""]
        Path("feedback.md").write_text("\n".join(out))
        return
    out += failure_section(f"{sum(1 for r in vis_rows if not r['passed'])} visible check(s) failed",
                           vis_rows, vis_hints)
    if hid_rows:
        out += failure_section(f"{sum(1 for r in hid_rows if not r['passed'])} additional check(s) failed",
                               hid_rows, hid_hints)
    if score == max_score:
        out += ["All checks passed. Nice work.", ""]
    passing = [r for r in rows if r["passed"]]
    if passing:
        out += [f"<details><summary>{len(passing)} check(s) passed</summary>", ""]
        out += [f"- {r['test-name']}" for r in passing]
        out += ["", "</details>", ""]
    if restored:
        out += ["> Note: `" + "`, `".join(restored) + "` were restored from the course copy "
                "before grading. Grading always uses the official test suite.", ""]
    for label, actual, expected in (("visible", len(vis_rows), EXPECTED_VISIBLE),
                                    ("additional", len(hid_rows), EXPECTED_HIDDEN)):
        if actual != expected:
            out += [f"> Note: the {label} suite ran {actual} checks; {expected} were expected.", ""]
    Path("feedback.md").write_text("\n".join(out))


def main():
    restored = restore_files()
    tmp = Path(tempfile.mkdtemp(prefix="grader-"))

    visible = run_suite(SUITE, tmp / "visible.json", "visible suite")
    if visible is None:
        log("::error::the visible suite produced no results file; grading could not run")
        return 1

    total_max = (EXPECTED_VISIBLE + EXPECTED_HIDDEN) * DEFAULT_POINTS
    hid_rows, hid_hints, build_error = [], {}, ""

    if not visible.get("build", True):
        # Load failure: one row, worth the whole assignment, scored zero. The
        # denominator stays EXPECTED_VISIBLE, not 0/0.
        vis_rows = [{"test-name": "Build (code loads)", "passed": False,
                     "score": 0, "max-score": total_max}]
        vis_hints = {}
        build_error = visible.get("build_error", "")
    else:
        vis_rows, vis_hints = rows_from(visible)
        if HIDDEN_SUITE:
            hidden_path = HERE / HIDDEN_SUITE
            if hidden_path.is_file():
                hidden = run_hidden(hidden_path, tmp / "hidden.json", "additional checks")
                if hidden is None:
                    log("::warning::the additional-check suite produced no results; "
                        "grading on the visible suite alone")
                else:
                    hid_rows, hid_hints = rows_from(hidden, HIDDEN_PREFIX)
            else:
                log(f"::warning::{HIDDEN_SUITE} is missing from the bundle")

    rows = vis_rows + hid_rows
    score = sum(r["score"] for r in rows)
    max_score = sum(r["max-score"] for r in rows)
    env = os.environ

    Path("result.json").write_text(json.dumps({
        "schema": "course/result/v1",
        "course": env.get("COURSE", ""),
        "assignment": env.get("ASSIGNMENT", ""),
        "usernames": [env.get("USERNAME", "")],
        "submission": env.get("SUBMISSION_TAG", ""),
        "commit": env.get("COMMIT_URL", ""),
        "release": env.get("RELEASE_URL") or env.get("COMMIT_URL", ""),
        "review": env.get("REVIEW_URL") or env.get("COMMIT_URL", ""),
        "datetime": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "score": score,
        "max-score": max_score,
        "tests": rows,
    }, indent=2))

    write_feedback(vis_rows, vis_hints, hid_rows, hid_hints, restored, build_error)
    log(f"Score: {score}/{max_score}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
