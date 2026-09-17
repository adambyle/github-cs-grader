"""
assign, one private repository per student, from the template.
==============================================================

    cs108 assign a04            # show the plan
    cs108 assign a04 --go       # do it
    cs108 assign a04 --go --students jsmith,test-account
    cs108 assign a04 --go --template some-other-name

For each participant in the roster (role student or test), three idempotent
steps:

  1. INVITE to the organization, by github_id. Skipped if already a member
     or already invited. GitHub requires the student to accept; nobody is
     added to an organization without consent, and no tool changes that.
  2. CREATE <org>/<course>-a04-<username>, private, GENERATED from the
     template. Skipped if it already exists. Generated, not forked: no
     upstream link, no "fork of a fork", a clean history the student owns.
  3. GRANT push access, once they are an active member.

Re-run it freely as late usernames arrive. Everyone already set up is left
alone. A student with no github_id in the roster is reported by name and
skipped; nothing can be done for them until the roster has it.

Writes distribution-a04.csv in the course folder, recording each repository
and invitation state.

WHY PUSH IS GRANTED ONLY TO ACTIVE MEMBERS
    Adding an existing member as a collaborator applies silently. Adding
    someone still pending creates a SECOND, repository-level invitation, one
    more email per assignment they must also accept. Deferring keeps it to a
    single organization invitation, ever. That is why re-running assign after
    students accept is part of the routine, and why the status screen nags
    about it.
"""

from __future__ import annotations

import argparse
import csv

from .. import assignment as asg
from .. import config as cfg
from .. import ghcli, out, roster as rostermod


def run(course: cfg.Course, argv) -> int:
    ap = argparse.ArgumentParser(prog=f"{course.course} assign",
                                 description="Create each student's private repository.")
    ap.add_argument("assignment")
    ap.add_argument("--go", action="store_true", help="perform it (default is a preview)")
    ap.add_argument("--students", help="comma-separated usernames; default all")
    ap.add_argument("--template", help="template repository name (default from course.json)")
    args = ap.parse_args(argv)

    try:
        a = asg.load(course, args.assignment)
    except asg.AssignmentError as exc:
        out.say(f"error: {exc}")
        return 1

    try:
        ghcli.require_auth()
    except ghcli.GhUnavailable as exc:
        out.say(f"error: {exc}")
        return 1

    template = args.template or course.template_repo(a.id)
    full_template = course.full(template)
    if not ghcli.repo_exists(full_template):
        out.say(f"error: template repository {full_template} not found.")
        out.say(f"  Publish it first:  {course.course} template {a.id} --go")
        return 1

    try:
        roster = rostermod.select(rostermod.participants(course.roster), args.students)
    except rostermod.RosterError as exc:
        out.say(f"error: {exc}")
        return 1

    # Put the students who still need a repository first, newest first, so a
    # re-run for three latecomers does not begin with twenty-two lines of
    # "already exists". Ordering only; everyone is still visited.
    try:
        have = set(ghcli.Gh(course.org).repos())
    except ghcli.GhUnavailable:
        have = set()
    indexed = list(enumerate(roster))
    indexed.sort(key=lambda pair: (
        0 if course.student_repo(a.id, pair[1]["username"]) not in have else 1, -pair[0]))
    roster = [r for _, r in indexed]
    todo = sum(1 for r in roster if course.student_repo(a.id, r["username"]) not in have)

    out.say(f"{'PREVIEW: ' if not args.go else ''}Assigning {a.id} to {len(roster)} participant(s)")
    out.say(f"  template : {full_template}")
    out.say(f"  roster   : {course.roster}")
    out.say(f"  order    : {todo} still to do, first; then the rest\n")

    rows, problems, pending, skipped = [], [], [], []
    for student in roster:
        username = student["username"]
        login = student["github_id"]
        full_name = course.full(course.student_repo(a.id, username))
        row = {"username": username, "github_id": login, "repo": full_name,
               "membership": "", "repo_state": "", "error": ""}
        if not login:
            # Not a failure of this run: nothing can be done until the roster
            # has the login. Reported by name, and again by the status screen.
            row["error"] = "no github_id in the roster"
            skipped.append(username)
            out.skip_line(username, "skipped: no github_id in the roster yet")
            rows.append(row)
            continue

        state = ghcli.membership_state(course.org, login)
        if state not in ("active", "pending"):
            if args.go:
                state, err = ghcli.invite(course.org, login)
                if err:
                    row["error"] = err
                    problems.append((username, err))
                    out.bad_line(username, err)
                    rows.append(row)
                    continue
            else:
                state = "would invite"
        row["membership"] = state
        if state in ("pending", "would invite"):
            pending.append(username)

        if full_name.lower() in {course.full(n).lower() for n in have} or ghcli.repo_exists(full_name):
            repo_state = "exists"
        elif args.go:
            ok, err = ghcli.create_repo(full_name, private=True, template=full_template)
            if not ok:
                row["error"] = err
                problems.append((username, err))
                out.bad_line(username, err)
                rows.append(row)
                continue
            repo_state = "created"
            wait_err = ghcli.wait_for_content(full_name)
            if wait_err:
                row["error"] = wait_err
                problems.append((username, wait_err))
        else:
            repo_state = "would create"
        row["repo_state"] = repo_state

        if state == "active" and args.go:
            err = ghcli.grant_push(full_name, login)
            if err:
                row["error"] = err
                problems.append((username, err))

        out.ok_line(username, f"{state:<14} {repo_state:<12} {full_name}")
        rows.append(row)

    out.say()
    out.say(f"{len(rows) - len(problems) - len(skipped)}/{len(rows)} ready")
    if skipped:
        out.say(f"skipped, no github_id yet ({len(skipped)}): {', '.join(skipped)}")
        out.say(f"  Add their logins to the roster (or `{course.course} students import`) and re-run.")
    if pending:
        out.say(f"awaiting organization invitation ({len(pending)}): {', '.join(pending)}")
        out.say("  Their repositories exist but are invisible to them, and push access is")
        out.say("  granted on the NEXT run, once they are members. Re-run after they accept.")
    if problems:
        out.say(f"problems ({len(problems)}):")
        for username, err in problems:
            out.say(f"  {username:<24} {err}")

    if args.go:
        path = course.root / f"distribution-{a.id}.csv"
        with path.open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=["username", "github_id", "repo", "membership",
                                               "repo_state", "error"])
            w.writeheader()
            w.writerows(rows)
        cfg.append_history(course.root, f"assign {a.id}: {len(rows) - len(problems) - len(skipped)}/{len(rows)} ready")
        out.say(f"\nwrote {path}")
    else:
        out.preview_footer(f"{course.course} assign {a.id}"
                           + (f" --students {args.students}" if args.students else ""))
    return 1 if (problems and args.go) else 0
