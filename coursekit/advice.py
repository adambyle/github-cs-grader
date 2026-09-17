"""
advice.py, what is out of step, and the exact command that fixes it.
====================================================================

The snapshot knows what is true; this turns it into a short, ordered list
of "here is what is wrong, and here is the line to paste".

TWO RULES
  1. Never invent a command. Every string produced here is a real verb
     spelled the way the cheatsheet spells it. If a situation needs a
     command that does not exist, say so in words.
  2. Order by consequence. A drifted restore file means students are running
     different tests than the grader; that outranks an unpublished template
     for an assignment nobody has started.

Severity is a claim about what happens if you ignore it:
    stop     students are, or will be, marked against something wrong
    do       real work is blocked until you run this
    note     worth knowing, nothing is broken
"""

from __future__ import annotations

from typing import List

STOP, DO, NOTE = "stop", "do", "note"
_ORDER = {STOP: 0, DO: 1, NOTE: 2}


def _item(severity, title, detail, command=None, assignment=None):
    return {"severity": severity, "title": title, "detail": detail,
            "command": command, "assignment": assignment}


def next_actions(snap: dict) -> List[dict]:
    c = snap["course"]["course"]
    out = []
    participants = snap["participants"]
    assignments = snap["assignments"]
    gh_ok = snap["github"]["available"]

    if not gh_ok:
        out.append(_item(NOTE, "GitHub is not being read",
                         snap["github"]["error"] + " Everything below is from disk only; "
                         "repository and membership columns are unknown, not empty.",
                         command="gh auth status"))

    if snap.get("roster_error"):
        out.append(_item(DO, "The roster cannot be read", snap["roster_error"],
                         command=f"{c} students import ~/Downloads/responses.csv"))
    elif not participants:
        out.append(_item(DO, "The roster has no students",
                         "Export the form's responses and merge them in. Nothing else can happen first.",
                         command=f"{c} students import ~/Downloads/responses.csv"))

    for p in snap.get("roster_problems", [])[:8]:
        out.append(_item(DO, "Roster problem", p + ". Edit roster/roster.csv by hand, or re-import the form.",
                         command=f"{c} students import ~/Downloads/responses.csv"))

    if not any(a["role"] == "test" for a in participants) and participants:
        out.append(_item(NOTE, "No test account in the roster",
                         "Add one row with role=test (a GitHub account you control). Every "
                         "assignment should go to it, be pushed to, and be graded, before any "
                         "student sees it."))

    pending = [p for p in participants if p["membership"] == "pending"]
    if pending:
        names = ", ".join(p["username"] for p in pending[:6]) + (f" and {len(pending) - 6} more" if len(pending) > 6 else "")
        out.append(_item(NOTE, f"{len(pending)} student(s) have not accepted the invitation",
                         f"{names}. They cannot see their repositories until they do, and the "
                         f"invitation expires after seven days. Chase it; it looks identical to "
                         f"a missing repository on the day of the lab."))

    unpublished, live = [], []
    for a in assignments:
        aid = a["id"]
        if a["drift"]:
            files = ", ".join(d["file"] for d in a["drift"][:4])
            out.append(_item(STOP, f"{aid}: the copies of a provided file disagree",
                             f"{files}. Students are running a different file than the grader "
                             f"will use. Fix the authoritative copy first (the bundle for "
                             f"autograded, the starter for manual), then verify, then patch.",
                             command=f"{c} verify {aid}", assignment=aid))
        if a["problems"]:
            out.append(_item(DO, f"{aid}: {a['problems'][0]}",
                             "The assignment contract is not satisfied; nothing downstream can be trusted until it is.",
                             command=f"{c} verify {aid}", assignment=aid))
            continue
        if not a["has_starter"]:
            out.append(_item(NOTE, f"{aid}: no starter files yet",
                             "The folder exists but starter/ is empty.",
                             command=f"{c} new {aid} --force", assignment=aid))
            continue
        if not gh_ok:
            continue
        if not a["template_exists"]:
            unpublished.append(aid)
            continue
        live.append(aid)
        if a["is_template"] is False:
            out.append(_item(DO, f"{aid}: the repository is not marked as a template",
                             "assign cannot generate student repositories from it until it is. "
                             "Re-running template sets the flag.",
                             command=f"{c} template {aid} --go", assignment=aid))
        missing = [p for p in participants if p["membership"] == "active" and not p["cells"][aid]["has_repo"]]
        if missing:
            out.append(_item(DO, f"{aid}: {len(missing)} student(s) have no repository",
                             ", ".join(p["username"] for p in missing[:6])
                             + (f" and {len(missing) - 6} more" if len(missing) > 6 else "")
                             + ". Assigning is idempotent; run it as often as you like.",
                             command=f"{c} assign {aid} --go", assignment=aid))
        absent = [p for p in participants if p["membership"] == "absent"]
        if absent and not missing:
            out.append(_item(DO, f"{aid}: {len(absent)} student(s) not yet invited",
                             ", ".join(p["username"] for p in absent[:6]) + ". assign invites anyone missing.",
                             command=f"{c} assign {aid} --go", assignment=aid))
        no_id = [p for p in participants if p["membership"] == "no github_id"]
        if no_id and a["repos"] and not missing:
            out.append(_item(NOTE, f"{aid}: {len(no_id)} student(s) have no github_id",
                             ", ".join(p["username"] for p in no_id[:6]) + ". Nothing can be "
                             "done for them until the roster has it.",
                             command=f"{c} students import ~/Downloads/responses.csv", assignment=aid))
        tester = [p for p in participants if p["role"] == "test"]
        if a["repos"] and tester and not any(p["cells"][aid]["has_repo"] for p in tester):
            out.append(_item(DO, f"{aid}: the test account has no repository",
                             "Every assignment should be received, pushed to and graded by the "
                             "test account before students see it.",
                             command=f"{c} assign {aid} --go --students {tester[0]['username']}", assignment=aid))
        if a["repos"] and a["kind"] == "auto" and not a["graded"]:
            out.append(_item(NOTE, f"{aid}: not graded yet",
                             f"{a['repos']} repositories exist and no gradebook has been produced. "
                             f"Add --as-of to grade what existed at the deadline.",
                             command=f"{c} marks {aid}", assignment=aid))
        elif a["repos"] and a["kind"] == "manual" and not a["collected"]:
            out.append(_item(NOTE, f"{aid}: not collected yet",
                             f"{a['repos']} repositories exist. collect downloads them; sheet makes the CSV.",
                             command=f"{c} collect {aid}", assignment=aid))
        elif a["graded"] and a["repos"] > a["graded_count"]:
            out.append(_item(NOTE, f"{aid}: the gradebook is behind",
                             f"{a['repos']} repositories, {a['graded_count']} rows in the gradebook.",
                             command=f"{c} marks {aid}", assignment=aid))
        if a["stale_count"]:
            out.append(_item(DO, f"{aid}: {a['stale_count']} mark(s) taken before the student's last push",
                             f"They pushed after the gradebook was written ({a['graded_at'][:16].replace('T', ' ')} UTC). "
                             f"The marks shown are a correct record of an older commit. Grading again fixes it.",
                             command=f"{c} marks {aid}", assignment=aid))

    if unpublished:
        span = f"{unpublished[0]} to {unpublished[-1]}" if len(unpublished) > 2 else ", ".join(unpublished)
        out.append(_item(NOTE, f"{len(unpublished)} assignment(s) not published: {span}",
                         "Normal for most of the term. Each needs verifying, then publishing, "
                         "then assigning. The command is for the first of them.",
                         command=f"{c} verify {unpublished[0]}"))

    out.sort(key=lambda i: (_ORDER[i["severity"]], i["title"]))
    return out
