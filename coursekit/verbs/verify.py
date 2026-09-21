"""
verify, prove an assignment before anyone sees it.
==================================================

    cs108 verify a04
    cs108 verify                 # every assignment
    cs108 verify a04 --quick     # skip running anything
    cs108 verify a04 --json      # machine-readable report on stdout

Runs everything in a throwaway copy under the system temp directory, so
`git status` in the course folder is as clean after a run as before it.

WHAT IT CHECKS, AND WHY EACH ONE EXISTS

  SHAPE      starter/ and answers/ exist and differ, README.md is present,
             assignment.json parses, and no answers/ file has leaked into
             starter/. Not clever, and the check that has saved the most
             embarrassment: a reference solution copied into the starter.

  SYNC       every restore file is byte-identical in starter/, answers/ and
             (for autograded work) the bundle. Three copies of a test file
             that have drifted apart is the most common way for grading to
             disagree with what students saw.

  BUNDLE     autograded only. Every restore file is present in the bundle and
             no deliverable is. A missing bundle file silently falls back to
             the student's copy; a deliverable in the bundle would overwrite
             the student's work with the stub at grading time.

  SCORE      autograded only. answers/ scores exactly EXPECTED_VISIBLE, and
             that many checks ACTUALLY RAN. The second half is the one that
             matters: a real assignment generated checks inside a loop, the
             hand-written constant did not match, and the denominator was
             wrong for every student until it was caught.

  STARTER    autograded: the untouched starter loads, runs, and scores
             strictly LESS than answers/. A starter that fails to load is a
             broken assignment; a starter that scores full marks is a broken
             suite. Manual: the starter's source files load (node --check).

  TOOLCHAIN  if BOTH starter and answers fail to load at the same point, the
             report blames the toolchain on this machine, not the assignment.

  TIME       how long the suite takes against the grader's TIMEOUT.

Run it after any change to an assignment, however small.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tempfile
from pathlib import Path
from typing import Dict, List

from .. import assignment as asg
from .. import config as cfg
from .. import grading, out


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _copy_to_tmp(src: Path, label: str) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix=f"verify_{label}_"))
    work = tmp / "work"
    shutil.copytree(src, work, ignore=shutil.ignore_patterns(*asg.SKIP_NAMES))
    return work


def _run(course, a, folder: Path, label: str) -> dict:
    """Grade a throwaway copy of `folder`. Returns a summary dict."""
    work = _copy_to_tmp(folder, label)
    try:
        run = grading.run_grader(course, a, work, username=f"verify-{label}")
        summary = {"seconds": run["seconds"], "rc": run["rc"], "error": run["error"],
                   "build": True, "total": None, "passed": None, "failed": [],
                   "first_error": grading.first_error_line(run["log"]),
                   "log_tail": run["log"][-1500:]}
        result = run["result"]
        if result:
            if grading.build_failed(result):
                summary["build"] = False
            tests = result.get("tests", [])
            summary["total"] = len(tests)
            summary["passed"] = sum(1 for t in tests if t.get("passed"))
            summary["failed"] = [t["test-name"] for t in tests if not t.get("passed")]
            names = [t["test-name"] for t in tests]
            summary["duplicates"] = sorted({n for n in names if names.count(n) > 1})
            summary["score"] = result.get("score")
            summary["max"] = result.get("max-score")
        return summary
    finally:
        shutil.rmtree(work.parent, ignore_errors=True)


def verify(course: cfg.Course, aid: str, quick: bool = False) -> dict:
    report: Dict[str, object] = {"assignment": aid, "kind": "", "problems": [], "notes": []}
    problems: List[str] = report["problems"]        # type: ignore
    notes: List[str] = report["notes"]              # type: ignore

    try:
        a = asg.load(course, aid)
    except asg.AssignmentError as exc:
        problems.append(str(exc))
        return report
    report["kind"] = a.kind

    # ── SHAPE ─────────────────────────────────────────────────────────
    for p in a.problems():
        problems.append(p)
    if not a.starter.is_dir() or (a.is_auto and not a.bundle.is_dir()):
        return report
    starter_files = a.starter_files()
    if not starter_files:
        problems.append(f"{a.starter} is empty; there is nothing to publish")
        return report
    if not ((a.dir / "README.md").is_file() or (a.starter / "README.md").is_file()):
        problems.append("no README.md in the assignment folder or the starter")
    if a.answers.is_dir():
        answer_files = [p.as_posix() for p in asg.collect(a.answers)]
        if set(answer_files) == set(starter_files) and all(
                (a.starter / f).read_bytes() == (a.answers / f).read_bytes() for f in starter_files):
            problems.append("starter/ and answers/ are identical; the solution has leaked "
                            "into the starter, or the starter is already solved")
        else:
            # Deliverables that are byte-identical in starter/ and answers/.
            # For an autograded assignment that is a leak (or a provided file
            # missing from restore) and is reported as a problem. For a manual
            # assignment it is usually scaffolding (assets, configs, a lock
            # file) that simply has not been listed in restore yet, so it is
            # ONE note naming them, not one problem per file. A Vic-sized
            # Expo project produced twenty-one of those on 2026-09-21.
            same = [f for f in a.deliverables()
                    if (a.answers / f).is_file()
                    and (a.starter / f).read_bytes() == (a.answers / f).read_bytes()]
            if same:
                shown = ", ".join(same[:6]) + (f" (+{len(same) - 6} more)" if len(same) > 6 else "")
                text = (f"{len(same)} deliverable(s) identical in starter/ and answers/: {shown}. "
                        f"Either the solution leaked into the starter, or these are provided "
                        f"files and belong on the restore list in {asg.ASSIGNMENT_JSON} "
                        f"(which is also what lets patch push them)")
                (problems if a.is_auto else notes).append(text)
    deliverables = a.deliverables()
    report["deliverables"] = deliverables
    if a.is_auto and not deliverables:
        problems.append("every starter file is on the restore list, so there is nothing "
                        "for the student to write")

    # ── SYNC ──────────────────────────────────────────────────────────
    restore_names = a.restore_names()
    for name in restore_names:
        copies = {"starter": a.starter / name, "answers": a.answers / name}
        if a.is_auto:
            copies["bundle"] = a.bundle / name
        digests = {where: sha256(p) for where, p in copies.items() if p.is_file()}
        if "starter" not in digests:
            problems.append(f"restore names {name}, which is not in the starter")
        if a.answers.is_dir() and "answers" not in digests:
            problems.append(f"restore names {name}, which is not in answers/ (the reference "
                            f"solution must be tested with the same provided files)")
        if len(set(digests.values())) > 1:
            problems.append(f"{name} is not the same in all copies ({', '.join(sorted(digests))}); "
                            f"students would be graded against a file they never saw")

    # ── BUNDLE ────────────────────────────────────────────────────────
    if a.is_auto:
        cfgblock = asg.config_of(a.grader_path)
        report["config"] = cfgblock
        bundle_files = {p.as_posix() for p in asg.collect(a.bundle)}
        bundle_files.discard(a.grader)
        hidden = cfgblock.get("hidden_suite")
        if hidden:
            if hidden not in bundle_files:
                problems.append(f"HIDDEN_SUITE names {hidden}, which is not in the bundle")
            bundle_files.discard(str(hidden))
            if (a.starter / str(hidden)).is_file():
                problems.append(f"the hidden suite {hidden} is in the starter; it must live "
                                f"only in the bundle")
        for name in restore_names:
            if name not in bundle_files:
                problems.append(f"restore names {name}, which is not in the bundle; grading "
                                f"would silently fall back to the student's copy")
        for name in sorted(bundle_files):
            if not a.is_restored(name):
                if name in deliverables:
                    problems.append(f"{name} is a deliverable and is IN the bundle; grading "
                                    f"would overwrite the student's work with it. Remove it "
                                    f"from the bundle, or add it to restore if it is provided.")
                else:
                    notes.append(f"{name} is in the bundle but not on the restore list, so it "
                                 f"is never copied into a checkout (fine for grader helpers)")
        if cfgblock.get("expected_visible") is None:
            problems.append(f"{a.grader} has no EXPECTED_VISIBLE constant")
    else:
        report["config"] = {}

    if quick:
        return report

    # ── STARTER (manual) ──────────────────────────────────────────────
    if not a.is_auto:
        check = asg.load_check(a.starter)
        report["starter"] = check
        for err in check["errors"]:
            problems.append(f"the starter does not load: {err}")
        if check["checked"] == 0:
            notes.append("no .js or .py files in the starter, so nothing was load-checked")
        if a.answers.is_dir():
            ans = asg.load_check(a.answers)
            for err in ans["errors"]:
                problems.append(f"answers/ does not load: {err}")
        return report

    # ── SCORE and STARTER (auto) ──────────────────────────────────────
    expected = cfgblock.get("expected_visible")
    timeout = cfgblock.get("timeout") or 300
    ans = _run(course, a, a.answers, f"{aid}_ans") if a.answers.is_dir() else {}
    report["answers"] = ans
    if ans:
        if ans.get("error"):
            problems.append(f"answers/: {ans['error']}: {ans.get('first_error') or ans.get('log_tail', '')[-300:]}")
        elif ans.get("build") is False:
            problems.append("answers/ does not load:\n        " + (ans.get("first_error") or ans.get("log_tail", "")[-400:]))
        else:
            if ans.get("passed") != ans.get("total"):
                problems.append(f"answers/ scores {ans.get('passed')}/{ans.get('total')}; the "
                                f"reference solution must pass everything. Failing: "
                                + ", ".join(ans.get("failed", [])[:4]))
            if expected is not None and expected != ans.get("total"):
                problems.append(f"EXPECTED_VISIBLE is {expected} but the suite actually ran "
                                f"{ans.get('total')} checks; the denominator every student is "
                                f"scored out of is wrong")
            if ans.get("duplicates"):
                problems.append("two checks share a name, so one of them is invisible in the "
                                "feedback: " + ", ".join(ans["duplicates"]))
            if ans.get("seconds", 0) > 0.5 * timeout:
                problems.append(f"the suite takes {ans['seconds']}s against TIMEOUT={timeout}; "
                                f"uncomfortably close")

    sta = _run(course, a, a.starter, f"{aid}_sta")
    report["starter"] = sta
    if sta.get("error"):
        problems.append(f"starter/: {sta['error']}: {sta.get('first_error') or sta.get('log_tail', '')[-300:]}")
    elif sta.get("build") is False:
        problems.append("the untouched starter does not load:\n        "
                        + (sta.get("first_error") or sta.get("log_tail", "")[-400:]))
    elif ans and ans.get("passed") is not None and sta.get("passed") is not None:
        if sta["passed"] >= ans["passed"]:
            problems.append(f"the untouched starter scores {sta['passed']}/{sta['total']}, which "
                            f"is not less than answers/; the suite is not testing the deliverable")

    if ans.get("build") is False and sta.get("build") is False:
        if ans.get("first_error") and ans.get("first_error") == sta.get("first_error"):
            problems.append("BOTH answers/ and the starter failed to load at the same point. "
                            "That is the signature of a broken toolchain on this machine, "
                            "not a broken assignment. Check `which -a node` (or python3) "
                            "and the runtime line printed above.")
    return report


def run(course: cfg.Course, argv) -> int:
    ap = argparse.ArgumentParser(prog=f"{course.course} verify",
                                 description="Check an assignment before anyone sees it.")
    ap.add_argument("which", nargs="*", help="assignments to check (default: all)")
    ap.add_argument("--quick", action="store_true", help="skip running anything")
    ap.add_argument("--json", action="store_true", help="print the report as JSON")
    args = ap.parse_args(argv)

    names = args.which or asg.list_ids(course)
    if not names:
        out.say(f"No assignments found under {course.assignments}.")
        out.say(f"  Create one with:  {course.course} new a00")
        return 1

    reports = []
    for name in names:
        report = verify(course, name, quick=args.quick)
        reports.append(report)
        if args.json:
            continue
        out.header(f"{name}  ({report.get('kind') or '?'})")
        try:
            a = asg.load(course, name)
            if a.is_auto and not args.quick:
                out.say(f"    {out.dim(grading.runtime_report(a))}")
        except asg.AssignmentError:
            pass
        ans, sta, cfgb = report.get("answers"), report.get("starter"), report.get("config", {})
        if isinstance(ans, dict) and ans:
            sta_p = sta.get("passed") if isinstance(sta, dict) else "?"
            sta_t = sta.get("total") if isinstance(sta, dict) else "?"
            knobs = out.dim("(EXPECTED_VISIBLE=%s, TIMEOUT=%s)" % (cfgb.get("expected_visible"),
                                                                    cfgb.get("timeout")))
            out.say(f"    answers  {ans.get('passed')}/{ans.get('total')}   "
                    f"starter  {sta_p}/{sta_t}   {ans.get('seconds')}s   {knobs}")
        elif isinstance(sta, dict) and "checked" in sta:
            out.say(f"    starter  {sta['checked']} source file(s) load-checked")
        if report.get("deliverables"):
            out.say(f"    {out.dim('deliverables: ' + ', '.join(report['deliverables']))}")
        for n in report["notes"]:
            out.note(n)
        if report["problems"]:
            for p in report["problems"]:
                out.problem(p)
        else:
            out.say(f"    {out.green('all invariants hold')}")
        out.say()

    broken = [r["assignment"] for r in reports if r["problems"]]
    if args.json:
        print(json.dumps(reports, indent=1, default=str))
    else:
        out.say(f"{out.bold(f'{len(reports) - len(broken)}/{len(reports)} clean')}")
        if broken:
            out.say(out.red(f"problems in: {', '.join(broken)}"))
    return 1 if broken else 0
