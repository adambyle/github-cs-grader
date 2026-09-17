"""
scaffold.py, rendering the files that `new` and the installer create.
=====================================================================

Every scaffold lives as a real file under coursekit/scaffold/ with
`{{placeholders}}`. Rendering is a plain replace, no templating language,
because these files are read far more often than they are written and a
`{{course}}` in a comment is obvious to anyone.

Recognised placeholders: course, course_title, title, assignment, kind, date,
expected_visible, folder_name. Anything else is left alone.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCAFFOLD = HERE / "scaffold"
TEMPLATES = HERE / "templates"


def render(text: str, **values) -> str:
    values.setdefault("date", dt.date.today().isoformat())
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", str(value))
    return text


def read(name: str) -> str:
    return (SCAFFOLD / name).read_text(encoding="utf-8")


def write(dest: Path, name: str, **values) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(render(read(name), **values), encoding="utf-8")


def render_workflow(template_path: Path, course) -> str:
    """Fill a workflow template with the course's runner, image and build.
    Called by `template` at publish time and by `patch` for the workflow, so
    a setting changed with `config` reaches the next publish automatically."""
    text = template_path.read_text(encoding="utf-8")
    return render(text, course=course.course, title=course.title,
                  runner=course.runner or "RUNNER-NOT-SET",
                  image=course.image, build=course.build)
