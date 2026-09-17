"""
cli.py, one command for the whole course.
=========================================

    cs108                     what is out of step, and what to run
    cs108 new a04             make the assignment folders, auto or manual
    cs108 verify a04          check it before anyone sees it
    cs108 template a04 --go   starter folder -> GitHub template repository
    cs108 assign a04 --go     one private repository per student
    cs108 patch a04 --go      push a corrected do-not-edit file into existing repos
    cs108 marks a04           clone, autograde, write gradebook.csv
    cs108 collect a04         clone and stop, for reading by hand
    cs108 sheet a04           a CSV to type manual marks into
    cs108 students import f.csv --go    merge GitHub usernames into the roster
    cs108 doctor              check everything is still healthy
    cs108 config              show or change any setting
    cs108 ui                  a small local page

The command name is whatever the installer was told the course code is. The
shim it writes sets COURSEKIT_COMMAND, and everything printed here uses that
name, so the help text says `cs108` for CS 108 and never `<course>`.

PREVIEW BY DEFAULT
    template, assign, patch, students import and doctor --smoke change
    GitHub or the roster. Each shows what it WOULD do and stops; --go
    performs it. verify, marks, collect, sheet, config (reading), doctor and
    the bare command run directly: they read GitHub and write only to your
    own disk.

The harness is Python 3, standard library only. Nothing here imports
anything that is not shipped with Python.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import List, Optional

from . import config as cfg
from . import out

# verb -> (module, needs an assignment?, previews by default?, help)
VERBS = [
    ("new",      "new",       True,  False, "make the assignment folders, auto or manual"),
    ("verify",   "verify",    False, False, "check an assignment before anyone sees it"),
    ("template", "template",  False, True,  "starter folder -> GitHub template repository"),
    ("assign",   "assign",    True,  True,  "one private repository per student, from the template"),
    ("patch",    "patch",     True,  True,  "push a corrected do-not-edit file into existing repos"),
    ("marks",    "marks",     True,  False, "clone, autograde, write gradebook.csv"),
    ("collect",  "marks",     True,  False, "clone everything and stop, for reading by hand"),
    ("sheet",    "sheet",     True,  False, "a CSV to type manual marks into"),
    ("students", "students",  False, True,  "import FILE.csv: merge GitHub usernames into the roster"),
    ("doctor",   "doctor",    False, False, "check everything is still healthy"),
    ("config",   "configcmd", False, False, "show or change any setting"),
    ("ui",       "ui",        False, False, "a small local page"),
]

# The original course's names still work, so nothing anyone wrote down is wrong.
ALIASES = {"publish": "template", "distribute": "assign", "sync": "patch",
           "grade": "marks", "grades": "marks", "console": "ui", "status": "",
           "check": "doctor"}


def command_name() -> str:
    return os.environ.get("COURSEKIT_COMMAND") or "coursekit"


def usage(name: str) -> None:
    print(f"{out.bold(name)}  one command for the whole course\n")
    print(f"  {out.bold(name):<34} {out.dim('what is out of step, and what to run')}")
    rows = []
    for verb, _, needs, preview, help_text in VERBS:
        left = f"{name} {verb}" + (" aNN" if needs else "")
        if verb == "students":
            left = f"{name} students import FILE.csv"
        rows.append((left, "[--go]" if preview else "", help_text))
    w = max(len(l) for l, _, _ in rows)
    for left, flag, help_text in rows:
        print(f"  {out.bold(left)}{' ' * (w - len(left))}  {out.dim(flag):<8}  {out.dim(help_text)}")
    print()
    print(out.dim("  template, assign, patch and students import PREVIEW by default. Add --go to do it."))
    print(out.dim(f"  Each verb has --help. Settings live in course.json; see `{name} config`."))


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    name = command_name()

    explicit = None
    if "--course" in argv:
        i = argv.index("--course")
        if i + 1 >= len(argv):
            out.say("error: --course needs a path")
            return 2
        explicit = Path(argv[i + 1])
        del argv[i:i + 2]

    if argv and argv[0] in ("-h", "--help", "help"):
        usage(name)
        return 0

    verb = ALIASES.get(argv[0], argv[0]) if argv else ""
    rest = argv[1:]

    try:
        course = cfg.load(None if name == "coursekit" else name, explicit)
    except cfg.ConfigError as exc:
        out.say(f"error: {exc}")
        return 1
    # The command name is the course code once the course is known.
    if name == "coursekit":
        name = course.course
        os.environ["COURSEKIT_COMMAND"] = name

    if not verb:
        from .verbs import status
        return status.run(course, rest)

    table = {v[0]: v for v in VERBS}
    if verb not in table:
        near = ", ".join(v[0] for v in VERBS)
        out.say(f"error: unknown command {argv[0]!r}\n  try one of: {near}\n  or just: {name}")
        return 2

    _, module, needs, _, _ = table[verb]
    if needs and (not rest or rest[0].startswith("-")) and "--help" not in rest and "-h" not in rest:
        out.say(f"error: which assignment? e.g.  {name} {verb} a04")
        return 2

    if verb == "students":
        if not rest or rest[0] != "import":
            out.say(f"usage: {name} students import FILE.csv [--go]")
            return 2
        rest = rest[1:]

    import importlib
    mod = importlib.import_module(f".verbs.{module}", package=__package__)
    try:
        if verb == "collect":
            return mod.run(course, rest, collect_only=True)
        return mod.run(course, rest)
    except KeyboardInterrupt:
        out.say("\ninterrupted")
        return 130
