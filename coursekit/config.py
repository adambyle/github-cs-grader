"""
config.py, the one file that ties the toolkit to a course.
===========================================================

Nothing in this package names a course, an organization, a runner or an
image. Every course-specific value comes from ONE file, `course.json`, at the
root of the course folder:

    {
      "course":         "cs108",                  required
      "title":          "Web Programming",
      "org":            "26fa-cs108",             required
      "runner":         "runners-26fa-cs108",     the ARC scale-set name
      "image":          "node:22",                container image, must run as root
      "build":          "npm test",               what the workflow runs
      "tick_on_manual": false,                    check on push for hand-graded work?
      "grader_default": "js",                     what `new` scaffolds: js or py
      "autograders":    "autograders",
      "roster":         "roster/roster.csv",
      "starter":        "assignments/{assignment}/starter",
      "template":       "{course}-{assignment}-starter",
      "repo":           "{course}-{assignment}-{username}",
      "grading":        "~/cs108-grading"
    }

`course` and `org` are required. Everything else has the default shown in
DEFAULTS below. The `{}` placeholders are the only templating there is, and
exactly three names are supported: course, assignment, username.

HOW THE COURSE FOLDER IS FOUND
    Three sources, in this order, and the first hit wins:

      1. the folder you are standing in, or any parent, that holds course.json
      2. the environment variable COURSEKIT_COURSE
      3. the path remembered in ~/.config/coursekit/courses.json under the
         command name (the installer writes it; every successful run refreshes it)

    The third one is what makes `cs108 marks a04` work from your home
    directory, which is the whole point of having one command.

    When the toolkit is started through a command shim, the shim sets
    COURSEKIT_COMMAND to the course code it was installed as. A course.json
    found by walking up is then only accepted if its `course` matches, so
    standing inside a DIFFERENT course's folder does not silently grade the
    wrong class.

HISTORY
    Every change made through `config` is appended, one line with a date, to
    `course-history.log` in the course folder. When something breaks in week 9
    the first useful question is what changed, and this is the answer.

Standard library only. This file must never import anything outside it.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import sys
from pathlib import Path
from typing import Optional

CONFIG_NAME = "course.json"
HISTORY_NAME = "course-history.log"
USER_CONFIG_DIR = Path.home() / ".config" / "coursekit"
USER_COURSES = USER_CONFIG_DIR / "courses.json"

# The course code becomes a shell command, a repository name fragment and a
# configuration key, so it is kept deliberately plain.
COURSE_CODE_RE = re.compile(r"^[a-z][a-z0-9]{1,15}$")

# GitHub organization and repository names: alphanumerics and hyphens.
ORG_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")

DEFAULTS = {
    "title": "",
    "runner": "",
    "image": "node:22",
    "build": "npm test",
    "tick_on_manual": False,
    "grader_default": "js",
    "autograders": "autograders",
    "roster": "roster/roster.csv",
    "starter": "assignments/{assignment}/starter",
    "template": "{course}-{assignment}-starter",
    "repo": "{course}-{assignment}-{username}",
    "grading": "",   # empty means ~/<course>-grading, filled in by Course
}

REQUIRED = ("course", "org")

# Every key the tool knows, with a one-line description used by `config` and by
# the Settings screen. Order matters: it is the order they are displayed in.
DESCRIPTIONS = {
    "course":         "course code; the command name (cannot be changed after install)",
    "title":          "course title, used in headings and help text",
    "org":            "GitHub organization that holds every repository",
    "runner":         "ARC runner scale-set name; the ONLY thing that routes a job",
    "image":          "container image for the workflow; must default to root",
    "build":          "command the workflow runs to build and test",
    "tick_on_manual": "run a loads-without-crashing check on hand-graded assignments?",
    "grader_default": "language `new` scaffolds a grader in: js or py",
    "autograders":    "folder holding the grading bundles",
    "roster":         "the roster CSV",
    "starter":        "pattern for an assignment's starter folder",
    "template":       "pattern for template repository names",
    "repo":           "pattern for student repository names",
    "grading":        "folder where marks, collect and sheet write",
}

# Keys that only reach templates published AFTER they change. `config` warns
# about these and offers to re-push the workflow.
WORKFLOW_KEYS = ("runner", "image", "build", "tick_on_manual")


class ConfigError(Exception):
    """A readable problem with course.json. Callers print str(exc) and exit 1."""


class Course:
    """One course's configuration plus every path derived from it.

    Tools construct this through `load()` and read attributes; they never
    parse course.json themselves.
    """

    def __init__(self, root: Path, data: dict, source: str = CONFIG_NAME):
        self.root = Path(root)
        self.source = source                  # where the values came from
        self.data = dict(DEFAULTS)
        self.data.update({k: v for k, v in data.items() if v is not None})
        self.course: str = self.data["course"]
        self.org: str = self.data["org"]
        self.title: str = self.data.get("title") or self.course.upper()
        self.runner: str = self.data.get("runner") or ""
        self.image: str = self.data.get("image") or DEFAULTS["image"]
        self.build: str = self.data.get("build") or DEFAULTS["build"]
        self.tick_on_manual: bool = bool(self.data.get("tick_on_manual", False))
        self.grader_default: str = (self.data.get("grader_default") or "js").lower()
        self.autograders = self.root / self.data["autograders"]
        self.roster = self.root / self.data["roster"]
        self.templates = self.root / "templates"
        self.assignments = self.root / "assignments"
        grading = self.data.get("grading") or f"~/{self.course}-grading"
        self.grading = Path(os.path.expanduser(grading))

    # ── naming ────────────────────────────────────────────────────────────

    def template_repo(self, assignment: str) -> str:
        """Template repository name, without the org prefix."""
        return self.data["template"].format(course=self.course,
                                            assignment=assignment)

    def student_repo(self, assignment: str, username: str) -> str:
        """Student repository name, without the org prefix.

        SCAR: lowercased, because GitHub lowercases the names of generated
        repositories. A tool that forms `CS108-a03-JSmith` and then looks for
        it will not find it.
        """
        return self.data["repo"].format(course=self.course,
                                        assignment=assignment,
                                        username=username).lower()

    def full(self, name: str) -> str:
        """`org/name`, the form gh wants."""
        return f"{self.org}/{name}"

    def repo_url(self, name: str) -> str:
        return f"https://github.com/{self.org}/{name}"

    # ── per-assignment paths ──────────────────────────────────────────────

    def assignment_dir(self, assignment: str) -> Path:
        return self.assignments / assignment

    def starter(self, assignment: str) -> Path:
        """What students receive. `template` publishes exactly this folder,
        and `complete` is measured against exactly this folder."""
        return self.root / self.data["starter"].format(assignment=assignment)

    def answers(self, assignment: str) -> Path:
        return self.assignment_dir(assignment) / "answers"

    def bundle(self, assignment: str) -> Path:
        """The grading bundle. Absent for a manual assignment."""
        return self.autograders / assignment

    def grading_dir(self, assignment: str) -> Path:
        return self.grading / assignment

    def __repr__(self) -> str:
        return f"<Course {self.course} in {self.org} at {self.root}>"


# ── validation ───────────────────────────────────────────────────────────

def validate_course_code(code: str) -> Optional[str]:
    """None when the code is acceptable, otherwise the reason it is not."""
    if not code:
        return "the course code is empty"
    if not COURSE_CODE_RE.match(code):
        return ("the course code must be 2 to 16 characters, lowercase letters "
                "and digits only, starting with a letter (it becomes a shell "
                "command and a repository name)")
    return None


def validate_value(key: str, value) -> Optional[str]:
    """Validate ONE setting without touching GitHub. Returns None when fine."""
    if key == "course":
        return validate_course_code(str(value))
    if key == "org":
        if not ORG_RE.match(str(value)):
            return ("a GitHub organization name is letters, digits and hyphens, "
                    "not starting or ending with a hyphen")
        return None
    if key == "runner":
        if not str(value).strip():
            return "the runner scale-set name is empty; a job with no runner queues forever"
        if not re.match(r"^[A-Za-z0-9][A-Za-z0-9._-]*$", str(value)):
            return "a runner scale-set name is letters, digits, dots, dashes and underscores"
        return None
    if key == "image":
        if not re.match(r"^[a-z0-9][a-z0-9./_:@-]*$", str(value)):
            return "that does not look like a container image reference (e.g. node:22)"
        return None
    if key == "build":
        return None if str(value).strip() else "the build command is empty"
    if key == "tick_on_manual":
        if not isinstance(value, bool):
            return "tick_on_manual must be true or false"
        return None
    if key == "grader_default":
        return None if str(value) in ("js", "py") else "grader_default must be js or py"
    if key in ("autograders", "roster", "grading"):
        return None if str(value).strip() else f"{key} is empty"
    if key == "starter":
        return None if "{assignment}" in str(value) else "starter must contain {assignment}"
    if key == "template":
        return None if "{assignment}" in str(value) else "template must contain {assignment}"
    if key == "repo":
        if "{assignment}" not in str(value) or "{username}" not in str(value):
            return "repo must contain both {assignment} and {username}"
        return None
    if key == "title":
        return None
    return f"unknown setting {key!r}"


def coerce(key: str, raw: str):
    """Turn the string typed on the command line into the type course.json holds."""
    if key == "tick_on_manual":
        low = raw.strip().lower()
        if low in ("true", "yes", "y", "1", "on"):
            return True
        if low in ("false", "no", "n", "0", "off"):
            return False
        return raw
    return raw.strip()


def validate_all(data: dict) -> list:
    """Every problem with a course.json dict, as readable strings."""
    problems = []
    for key in REQUIRED:
        if not data.get(key):
            problems.append(f"missing required key {key!r}")
    for key, value in data.items():
        if key not in DESCRIPTIONS:
            problems.append(f"unknown key {key!r} (ignored by the tools)")
            continue
        if key in REQUIRED and not value:
            continue
        why = validate_value(key, value)
        if why:
            problems.append(f"{key}: {why}")
    return problems


# ── finding and loading ──────────────────────────────────────────────────

def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{path} is not valid JSON: {exc}")


def remembered_courses() -> dict:
    """{command name: course folder} from the user config file."""
    if not USER_COURSES.is_file():
        return {}
    try:
        data = json.loads(USER_COURSES.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def remember_course(command: str, root: Path) -> None:
    """Record where a course lives, so the command works from anywhere.
    A cache that cannot be written is not worth failing over."""
    try:
        USER_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        data = remembered_courses()
        if data.get(command) == str(root):
            return
        data[command] = str(root)
        USER_COURSES.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    except OSError:
        pass


def walk_up(start: Optional[Path] = None) -> Optional[Path]:
    """The nearest folder at or above `start` that holds course.json."""
    here = (start or Path.cwd()).resolve()
    for candidate in (here, *here.parents):
        if (candidate / CONFIG_NAME).is_file():
            return candidate
    return None


def find_course(command: Optional[str] = None,
                explicit: Optional[Path] = None) -> Path:
    """Locate the course folder, or raise ConfigError saying where we looked."""
    looked = []

    if explicit:
        root = Path(explicit).expanduser().resolve()
        if (root / CONFIG_NAME).is_file():
            return root
        raise ConfigError(f"no {CONFIG_NAME} in {root}")

    root = walk_up()
    if root is not None:
        if command:
            # Only accept a folder that belongs to THIS command's course.
            try:
                data = _read_json(root / CONFIG_NAME)
            except ConfigError:
                data = {}
            if data.get("course") == command:
                return root
            looked.append(f"{root} (belongs to course {data.get('course')!r}, not {command!r})")
        else:
            return root
    else:
        looked.append(f"{Path.cwd()} and its parents")

    env = os.environ.get("COURSEKIT_COURSE")
    if env:
        candidate = Path(env).expanduser()
        if (candidate / CONFIG_NAME).is_file():
            return candidate.resolve()
        looked.append(f"$COURSEKIT_COURSE={env}")

    if command:
        remembered = remembered_courses().get(command)
        if remembered and (Path(remembered) / CONFIG_NAME).is_file():
            return Path(remembered)
        looked.append(f"{USER_COURSES} entry for {command!r}")

    raise ConfigError(
        "I cannot find the course folder. I looked in:\n"
        + "".join(f"    {where}\n" for where in looked)
        + "  Run this from inside the course folder once and I will remember it,\n"
        "  or set COURSEKIT_COURSE=~/path/to/course, or re-run ./install.")


def load(command: Optional[str] = None,
         explicit: Optional[Path] = None) -> Course:
    """Load the course, dying readably. Tools call this and nothing else."""
    root = find_course(command, explicit)
    data = _read_json(root / CONFIG_NAME)
    problems = [p for p in validate_all(data) if not p.startswith("unknown key")]
    if problems:
        raise ConfigError(f"{root / CONFIG_NAME} has problems:\n"
                          + "".join(f"    {p}\n" for p in problems)
                          + f"  Fix them with:  {data.get('course') or 'the command'} config --edit")
    course = Course(root, data)
    if command:
        remember_course(command, root)
    return course


def save(course: Course, changes: dict, note: str = "") -> None:
    """Write changed keys to course.json and append a line to the history.

    Only the keys given are touched; every other line of course.json is
    preserved as it was, so a hand-added comment key survives.
    """
    path = course.root / CONFIG_NAME
    data = _read_json(path)
    before = {k: data.get(k) for k in changes}
    data.update(changes)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    for key, value in changes.items():
        append_history(course.root, f"config {key}: {before[key]!r} -> {value!r}"
                       + (f"  ({note})" if note else ""))
    course.__init__(course.root, data)


def append_history(root: Path, line: str) -> None:
    """One line, dated, appended. Never fails the caller."""
    try:
        stamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
        with (root / HISTORY_NAME).open("a", encoding="utf-8") as fh:
            fh.write(f"{stamp}  {line}\n")
    except OSError:
        pass


def die(msg: str, code: int = 1) -> None:
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(code)
