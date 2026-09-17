"""
status, the bare command: where everything stands, then what to do.
===================================================================

    cs108              # state first, exceptions second

SCAR on ordering: state first, exceptions second. An exception report alone
is right for "what should I do next" and useless for "where is everything",
which is the question an instructor actually has on a Monday morning.

When GitHub is unreachable, say what is UNKNOWN rather than reporting a
confident wrong answer like "not published".
"""

from __future__ import annotations

from .. import advice
from .. import config as cfg
from .. import out, state as statemod


def table_rows(snap: dict):
    """The Status table, as plain strings; shared with the UI's text mode."""
    total = len(snap["participants"])
    rows = []
    for a in snap["assignments"]:
        if a["template_exists"] is None:
            tmpl = "unknown"
        elif a["template_exists"]:
            tmpl = "published" + ("" if a["is_template"] else " (flag not set)")
        else:
            tmpl = "not published"
        repos = f"{a['repos']}/{total}" if a["repos"] is not None else "?"
        if a["kind"] == "manual":
            marks = f"collected" if a["collected"] else "-"
        else:
            marks = f"{a['graded_count']}/{total}" if a["graded"] else "-"
        complete = f"{a['complete_count']}/{total}" if (a["graded"] or a["collected"]) else "-"
        flags = []
        if a["drift"]:
            flags.append("drift")
        if a["problems"]:
            flags.append("contract problem")
        if a["stale_count"]:
            flags.append(f"{a['stale_count']} stale mark(s)")
        if a["template_exists"] and a["repos"] is not None and a["repos"] < total:
            flags.append(f"{total - a['repos']} repo(s) missing")
        if a["template_exists"] and a["repos"] and a["kind"] == "auto" and not a["graded"]:
            flags.append("not graded yet")
        rows.append({"id": a["id"], "kind": a["kind"], "template": tmpl, "repos": repos,
                     "marks": marks, "complete": complete, "flags": ", ".join(flags)})
    return rows


def run(course: cfg.Course, argv) -> int:
    snap = statemod.snapshot(course)
    actions = advice.next_actions(snap)
    n_students = len(snap["students"])
    n_test = len(snap["participants"]) - n_students

    out.say(f"{out.bold(course.course)} {out.dim('·')} {course.title} {out.dim('·')} {course.org} "
            f"{out.dim('·')} {n_students} student(s)"
            + (f" + {n_test} test" if n_test else "")
            + f" {out.dim('·')} {len(snap['assignments'])} assignment(s)\n")

    rows = table_rows(snap)
    if rows:
        if not snap["github"]["available"]:
            out.say(f"  {out.dim('GitHub is not reachable; template and repository columns are unknown.')}")
        out.say(f"  {'':<8}{'kind':<8}{'template':<26}{'repos':<9}{'marks':<11}{'complete':<11}flags")
        for r in rows:
            colour = out.green if r["template"].startswith("published") else out.dim
            out.say(f"  {out.bold(r['id']):<8}{r['kind']:<8}{colour(r['template']):<26}"
                    f"{r['repos']:<9}{r['marks']:<11}{r['complete']:<11}{out.yellow(r['flags'])}")
        out.say()
    else:
        out.say(f"  No assignments yet. Start with:  {course.course} new a00\n")

    if not actions:
        out.say(out.green("Nothing out of step."))
        return 0
    colour = {"stop": out.red, "do": out.yellow, "note": out.dim}
    for a in actions:
        out.say(f"{colour[a['severity']](a['severity'].upper().ljust(5))} {out.bold(a['title'])}")
        out.wrap(a["detail"])
        if a["command"]:
            out.say(f"      {out.bold('$ ' + a['command'])}")
        out.say()
    return 0
