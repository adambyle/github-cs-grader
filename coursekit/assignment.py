"""
assignment.py, the assignment contract, in one place.
=====================================================

    assignments/<a>/assignment.json

        {
          "title":   "Working with files",
          "kind":    "auto",                       auto or manual
          "grader":  "autograder.js",              omitted when manual
          "restore": ["test.js", "package.json", "fixtures/"],
          "ignore":  ["notes/"]                    never published, optional
        }

THE RESTORE LIST IS THE SAFETY MODEL
    One list, naming the files the student does NOT own. It drives three
    things, and every one of them reads it from here:

      grading   copies the instructor's authoritative copies over the
                student's before any test runs (so fixing a test fixes it
                for everyone, retroactively, with no student-repo work)
      patch     refuses to push anything not on the list (so a student's
                work can never be destroyed by a fix)
      verify    checks that every copy of every listed file is byte-identical

    A directory entry ("fixtures/") means every file under it.

ONE DEFINITION OF "THE STARTER"
    `collect()` decides which files in starter/ get published by `template`.
    The SAME function decides what `marks` compares a checkout against when
    it computes `complete`. Written twice, the two drift, and the symptom is
    a student marked incomplete because of a file that was never published.
    So it is written once, here, and both import it.

THE GRADER
    Named in assignment.json, Python or Node, dispatched by extension. The
    harness never reads its code, only the config block at its top:

        const EXPECTED_VISIBLE = 29;     // or  EXPECTED_VISIBLE = 29  in Python
        const EXPECTED_HIDDEN  = 0;
        const TIMEOUT          = 300;
        const HIDDEN_SUITE     = null;   // or None

    `config_of()` reads those with one regex per key that matches both
    languages, which is the whole reason the config block is plain literals.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional

from . import config as cfg

ASSIGNMENT_JSON = "assignment.json"
ASSIGNMENT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
WORKFLOW_PATH = ".github/workflows/autograde.yml"

# Never published, whatever is sitting in the starter folder.
SKIP_NAMES = {".git", ".DS_Store", "__pycache__", ".pytest_cache", ".vscode",
              "node_modules", ".verify.json", "result.json", "feedback.md"}
SKIP_SUFFIXES = {".o", ".obj", ".exe", ".out", ".pyc", ".dSYM", ".log"}

# Files in a starter that are neither given nor a deliverable: the
# instructions. Editing README.md counts as a change for `complete` (the
# student pushed something), but it is not a deliverable for `verify`.
INFORMATIONAL = {"README.md", ".gitignore"}

GRADER_RUNTIMES = {".py": "python3", ".js": "node"}


class AssignmentError(Exception):
    pass


class Assignment:
    """One assignment's contract, loaded from assignment.json."""

    def __init__(self, course: cfg.Course, aid: str, data: dict):
        self.course = course
        self.id = aid
        self.data = data
        self.title: str = data.get("title") or aid
        self.kind: str = (data.get("kind") or "auto").lower()
        self.grader: str = data.get("grader") or ""
        self.restore: List[str] = [str(x) for x in data.get("restore", [])]
        self.ignore: List[str] = [str(x) for x in data.get("ignore", [])]
        self.dir = course.assignment_dir(aid)
        self.starter = course.starter(aid)
        self.answers = course.answers(aid)
        self.bundle = course.bundle(aid)

    @property
    def is_auto(self) -> bool:
        return self.kind == "auto"

    @property
    def grader_path(self) -> Path:
        return self.bundle / self.grader

    @property
    def runtime(self) -> str:
        """The interpreter for the grader, by extension."""
        return GRADER_RUNTIMES.get(Path(self.grader).suffix, "")

    def problems(self) -> List[str]:
        """Contract problems that do not need anything run: the SHAPE check's
        cheap half. `verify` adds to these."""
        out = []
        if self.kind not in ("auto", "manual"):
            out.append(f"kind is {self.kind!r}; it must be auto or manual")
        if self.is_auto:
            if not self.grader:
                out.append("kind is auto but no grader is named")
            elif not self.runtime:
                out.append(f"grader {self.grader!r} must end in .js or .py")
            elif not self.grader_path.is_file():
                out.append(f"grader not found: {self.grader_path}")
            if not self.bundle.is_dir():
                out.append(f"kind is auto but there is no bundle at {self.bundle}")
        else:
            if self.grader:
                out.append("kind is manual but a grader is named; remove it or set kind to auto")
            if self.bundle.is_dir():
                out.append(f"kind is manual but a bundle exists at {self.bundle}; "
                           f"a manual assignment must have no bundle")
        if not self.starter.is_dir():
            out.append(f"no starter folder at {self.starter}")
        if not self.answers.is_dir():
            out.append(f"no answers folder at {self.answers}")
        for name in self.restore:
            if name.startswith("/") or ".." in Path(name).parts:
                out.append(f"restore entry {name!r} must be a relative path inside the starter")
        return out

    # ── files ──────────────────────────────────────────────────────────

    def restore_files(self, base: Path) -> List[str]:
        """Expand the restore list against a folder: directory entries become
        every file under them. Paths are POSIX-relative strings."""
        out = []
        for entry in self.restore:
            if entry.endswith("/"):
                folder = base / entry.rstrip("/")
                if folder.is_dir():
                    for p in sorted(folder.rglob("*")):
                        if p.is_file() and keep(p.relative_to(base)):
                            out.append(p.relative_to(base).as_posix())
                else:
                    out.append(entry)      # reported missing by verify
            else:
                out.append(entry)
        return out

    def is_restored(self, rel: str) -> bool:
        """Is this relative path covered by the restore list?"""
        for entry in self.restore:
            if entry.endswith("/"):
                if rel.startswith(entry) or rel == entry.rstrip("/"):
                    return True
            elif rel == entry:
                return True
        return False

    def source_dir(self) -> Path:
        """Where the authoritative copy of a restore file lives: the bundle
        for an autograded assignment, the starter for a manual one."""
        return self.bundle if self.is_auto else self.starter

    def keep_starter(self, rel: Path) -> bool:
        if not keep(rel):
            return False
        posix = rel.as_posix()
        for entry in self.ignore:
            if entry.endswith("/") and posix.startswith(entry):
                return False
            if posix == entry:
                return False
        return True

    def starter_files(self) -> List[str]:
        """EXACTLY what `template` publishes and `complete` compares against."""
        return [p.as_posix() for p in collect(self.starter, self.keep_starter)]

    def deliverables(self) -> List[str]:
        """Starter files that are neither restored nor informational: the
        files the student owns."""
        return [f for f in self.starter_files()
                if not self.is_restored(f) and Path(f).name not in INFORMATIONAL]

    def ships_workflow(self) -> bool:
        """Autograded assignments always carry the workflow. Manual ones only
        when the course says so (tick_on_manual)."""
        return self.is_auto or self.course.tick_on_manual

    def workflow_template(self) -> Path:
        name = "autograde.yml" if self.is_auto else "check.yml"
        return self.course.templates / name


# ── the one definition of what is published ────────────────────────────

def keep(rel: Path) -> bool:
    """Is this relative path publishable? Shared by template and complete."""
    if rel.name in SKIP_NAMES or rel.suffix in SKIP_SUFFIXES:
        return False
    return not any(part in SKIP_NAMES for part in rel.parts)


def collect(folder: Path, predicate=keep) -> List[Path]:
    """Every publishable file under folder, as sorted relative paths."""
    out = []
    if not folder.is_dir():
        return out
    for p in sorted(folder.rglob("*")):
        if p.is_file():
            rel = p.relative_to(folder)
            if predicate(rel):
                out.append(rel)
    return out


# ── loading ────────────────────────────────────────────────────────────

def list_ids(course: cfg.Course) -> List[str]:
    """Assignment folders, sorted. A folder counts if it has assignment.json
    or a starter/ inside it."""
    if not course.assignments.is_dir():
        return []
    out = []
    for p in sorted(course.assignments.iterdir()):
        if not p.is_dir() or not ASSIGNMENT_ID_RE.match(p.name):
            continue
        if (p / ASSIGNMENT_JSON).is_file() or (p / "starter").is_dir():
            out.append(p.name)
    return out


def load(course: cfg.Course, aid: str) -> Assignment:
    """Load one assignment, or raise AssignmentError naming the path."""
    if not ASSIGNMENT_ID_RE.match(aid or ""):
        raise AssignmentError(f"{aid!r} is not an assignment id (lowercase letters, "
                              f"digits, dashes; e.g. a04)")
    folder = course.assignment_dir(aid)
    path = folder / ASSIGNMENT_JSON
    if not folder.is_dir():
        raise AssignmentError(
            f"there is no assignment folder at\n    {folder}\n"
            f"  That is where an assignment lives: starter/ (what the student "
            f"gets), answers/ (your solution)\n  and assignment.json. Create it with:\n"
            f"    {course.course} new {aid}")
    if not path.is_file():
        raise AssignmentError(
            f"{folder} has no {ASSIGNMENT_JSON}.\n"
            f"  Create the missing pieces with:  {course.course} new {aid}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise AssignmentError(f"{path} is not valid JSON: {exc}")
    if not isinstance(data, dict):
        raise AssignmentError(f"{path} must hold a JSON object")
    return Assignment(course, aid, data)


def write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


# ── the grader's config block ──────────────────────────────────────────

_CONFIG_PATTERNS = {
    "expected_visible": r"EXPECTED_VISIBLE\s*=\s*(\d+)",
    "expected_hidden":  r"EXPECTED_HIDDEN\s*=\s*(\d+)",
    "timeout":          r"TIMEOUT\s*=\s*(\d+)",
}


def config_of(grader: Path) -> Dict[str, object]:
    """The literals at the top of a grader, whichever language it is in."""
    out: Dict[str, object] = {"expected_visible": None, "expected_hidden": 0,
                              "timeout": 300, "hidden_suite": None}
    if not grader.is_file():
        return out
    src = grader.read_text(encoding="utf-8", errors="replace")
    for key, pattern in _CONFIG_PATTERNS.items():
        m = re.search(pattern, src)
        if m:
            out[key] = int(m.group(1))
    m = re.search(r"""HIDDEN_SUITE\s*=\s*(?:"([^"]*)"|'([^']*)'|(null|None))""", src)
    if m:
        out["hidden_suite"] = m.group(1) or m.group(2) or None
    return out


# ── running things ─────────────────────────────────────────────────────

def grader_argv(a: Assignment) -> List[str]:
    """How to start the grader. Python graders use THIS interpreter, so the
    grader sees the same python3 the harness was started with."""
    if a.runtime == "python3":
        return [sys.executable, str(a.grader_path)]
    return [a.runtime, str(a.grader_path)]


def load_check(folder: Path) -> Dict[str, object]:
    """Does the code in `folder` at least parse? The STARTER check for a
    manual assignment, and the loads-without-crashing tick.

    Language by extension: .js through `node --check`, .py through
    py_compile. Anything else is not checked. Returns {ok, checked, errors}.
    """
    errors, checked = [], 0
    for rel in collect(folder):
        path = folder / rel
        if rel.suffix in (".js", ".mjs", ".cjs"):
            argv = ["node", "--check", str(path)]
        elif rel.suffix == ".py":
            argv = [sys.executable, "-m", "py_compile", str(path)]
        else:
            continue
        checked += 1
        if not shutil.which(argv[0]):
            errors.append(f"{argv[0]} is not installed, so {rel} could not be checked")
            continue
        try:
            proc = subprocess.run(argv, capture_output=True, text=True, timeout=60)
        except subprocess.TimeoutExpired:
            errors.append(f"{rel}: check timed out")
            continue
        if proc.returncode != 0:
            first = (proc.stderr or proc.stdout).strip().splitlines()
            errors.append(f"{rel}: {first[-1] if first else 'does not load'}")
    return {"ok": not errors, "checked": checked, "errors": errors}
