#!/usr/bin/env python3
"""
Acceptance tests, section 12.1 of the specification, run offline.
=================================================================

    python3 tests/run_tests.py            # or: python3 -m unittest tests.test_acceptance -v

Everything runs in a throwaway HOME with a fake `gh` (tests/fake_gh.py) on
PATH and a git URL rewrite, so no network, organization or runner is
needed. The one thing that cannot be tested here is the smoke test (12.1
item 4): a job actually running on the real organization's runners. That
one is `cs108 doctor --smoke --go`, against the real thing, by design.

The tests are numbered because they build on each other: install, then
scaffold, then publish, then assign, then push as a student, then grade.
"""

from __future__ import annotations

import csv
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

KIT = Path(__file__).resolve().parent.parent
FAKE_GH = KIT / "tests" / "fake_gh.py"
COURSE = "cs108"
ORG = "26fa-cs108"


class Env:
    """One throwaway machine: HOME, PATH with the fake gh, git config."""

    def __init__(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="coursekit-test-"))
        self.home = self.tmp / "home"
        self.bin = self.tmp / "bin"
        self.gh_home = self.tmp / "fake-gh"
        self.home.mkdir(), self.bin.mkdir()
        shim = self.bin / "gh"
        shim.write_text(f"#!/bin/sh\nexec {sys.executable} {FAKE_GH} \"$@\"\n")
        shim.chmod(0o755)
        self.env = dict(os.environ)
        self.env.update({
            "HOME": str(self.home),
            "PATH": f"{self.bin}:{os.environ['PATH']}",
            "FAKE_GH_HOME": str(self.gh_home),
            "COURSEKIT_COMMAND": COURSE,
            "NO_COLOR": "1",
            "GIT_CONFIG_NOSYSTEM": "1",
        })
        self.env.pop("COURSEKIT_COURSE", None)
        self.git("config", "--global", "user.name", "Test Student")
        self.git("config", "--global", "user.email", "student@example.edu")
        self.git("config", "--global", f"url.file://{self.gh_home}/repos/.insteadOf", "https://github.com/")
        self.git("config", "--global", "protocol.file.allow", "always")
        self.git("config", "--global", "init.defaultBranch", "main")
        self.gh_home.mkdir()
        (self.gh_home / "state.json").write_text(json.dumps(
            {"login": "instructor", "orgs": {}, "auto_accept": [], "runners": []}))
        self.course_dir = self.home / "Courses" / "26FA-CS108"
        self.grading = self.home / f"{COURSE}-grading"

    def git(self, *args, cwd=None, extra_env=None):
        env = dict(self.env)
        env.update(extra_env or {})
        return subprocess.run(["git", *args], cwd=cwd, env=env, capture_output=True, text=True)

    def run(self, *args, cwd=None, expect=0, extra_env=None, stdin=""):
        env = dict(self.env)
        env.update(extra_env or {})
        proc = subprocess.run([sys.executable, str(KIT / "coursekit" / "__main__.py"), *args],
                              cwd=str(cwd or self.course_dir), env=env, capture_output=True,
                              text=True, input=stdin)
        if expect is not None and proc.returncode != expect:
            raise AssertionError(f"{COURSE} {' '.join(args)} exited {proc.returncode}, expected {expect}\n"
                                 f"--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}")
        return proc.stdout + proc.stderr

    def install(self, *extra, expect=0, extra_env=None):
        env = dict(self.env)
        env.update(extra_env or {})
        proc = subprocess.run([sys.executable, str(KIT / "install"), "--non-interactive",
                               "--course", COURSE, "--title", "Web Programming", "--org", ORG,
                               "--folder", str(self.course_dir), "--runner", "runners-26fa-cs108",
                               "--bin-dir", str(self.home / ".local" / "bin"), *extra],
                              env=env, capture_output=True, text=True)
        if proc.returncode != expect:
            raise AssertionError(f"install exited {proc.returncode}\n{proc.stdout}\n{proc.stderr}")
        return proc.stdout + proc.stderr

    def gh_state(self):
        return json.loads((self.gh_home / "state.json").read_text())

    def set_gh_state(self, **changes):
        state = self.gh_state()
        state.update(changes)
        (self.gh_home / "state.json").write_text(json.dumps(state))

    def repo_files(self, name):
        proc = self.git("--git-dir", str(self.gh_home / "repos" / ORG / f"{name}.git"), "ls-tree", "-r", "--name-only", "HEAD")
        return sorted(proc.stdout.split())

    def repo_file(self, name, path) -> str:
        proc = self.git("--git-dir", str(self.gh_home / "repos" / ORG / f"{name}.git"), "show", f"HEAD:{path}")
        return proc.stdout

    def repo_commits(self, name) -> int:
        proc = self.git("--git-dir", str(self.gh_home / "repos" / ORG / f"{name}.git"), "rev-list", "--count", "HEAD")
        return int(proc.stdout.strip() or 0)

    def clone(self, name) -> Path:
        dest = self.tmp / "clones" / name
        if dest.exists():
            shutil.rmtree(dest)
        dest.parent.mkdir(exist_ok=True)
        proc = self.git("clone", "-q", f"https://github.com/{ORG}/{name}.git", str(dest))
        assert proc.returncode == 0, proc.stderr
        return dest

    def push(self, clone: Path, message="work", date=None):
        extra = {"GIT_COMMITTER_DATE": date, "GIT_AUTHOR_DATE": date} if date else None
        self.git("add", "-A", cwd=clone)
        r = self.git("commit", "-q", "-m", message, cwd=clone, extra_env=extra)
        assert r.returncode == 0, r.stderr
        r = self.git("push", "-q", "origin", "HEAD:main", cwd=clone)
        assert r.returncode == 0, r.stderr

    def gradebook(self, aid):
        with (self.grading / aid / "gradebook.csv").open(newline="") as fh:
            return {r["username"]: r for r in csv.DictReader(fh)}

    def snapshot_github(self):
        """Everything the fake org holds, for the preview-changes-nothing test."""
        listing = {}
        for repo in sorted((self.gh_home / "repos" / ORG).glob("*.git")) if (self.gh_home / "repos" / ORG).is_dir() else []:
            head = self.git("--git-dir", str(repo), "rev-parse", "HEAD").stdout.strip()
            listing[repo.name] = head
        return json.dumps(self.gh_state(), sort_keys=True), listing


ENV: Env = None


def setUpModule():
    global ENV
    ENV = Env()


def tearDownModule():
    shutil.rmtree(ENV.tmp, ignore_errors=True)


ROSTER = """username,first_name,last_name,email,section,github_id,role
ada,Ada,Lovelace,ada@example.edu,A,ada-gh,student
bob,Bob,Émile,bob@example.edu,A,bob-gh,student
noid,No,Identifier,noid@example.edu,B,,student
tester,Test,Account,,A,tester-gh,test
prof,The,Instructor,prof@example.edu,,instructor-gh,teacher
"""


class T01Install(unittest.TestCase):
    def test_01_install_from_nothing(self):
        text = ENV.install()
        self.assertIn("authenticated as instructor", text)
        self.assertIn("admin", text)
        self.assertTrue((ENV.course_dir / "course.json").is_file())
        self.assertTrue((ENV.course_dir / "CHEATSHEET.md").is_file())
        self.assertTrue((ENV.course_dir / "CHEATSHEET.pdf").is_file())
        self.assertIn(f"{COURSE} new a04", (ENV.course_dir / "CHEATSHEET.md").read_text())
        shim = ENV.home / ".local" / "bin" / COURSE
        self.assertTrue(shim.is_file())
        self.assertIn(f'COURSEKIT_COMMAND="{COURSE}"', shim.read_text())
        # The cheatsheet says cs108, never <course>.
        self.assertNotIn("<course>", (ENV.course_dir / "CHEATSHEET.md").read_text())
        (ENV.course_dir / "roster" / "roster.csv").write_text(ROSTER, encoding="utf-8")
        ENV.set_gh_state(auto_accept=["ada-gh", "tester-gh"])

    def test_02_second_run_destroys_nothing(self):
        marker = ENV.course_dir / "assignments" / "keep-me.txt"
        marker.write_text("still here")
        before = (ENV.course_dir / "roster" / "roster.csv").read_bytes()
        text = ENV.install("--image", "node:20")
        self.assertIn("Updated", text)
        self.assertTrue(marker.is_file())
        self.assertEqual(before, (ENV.course_dir / "roster" / "roster.csv").read_bytes())
        self.assertEqual(json.loads((ENV.course_dir / "course.json").read_text())["image"], "node:20")
        self.assertIn("image: 'node:22' -> 'node:20'", (ENV.course_dir / "course-history.log").read_text())
        marker.unlink()
        ENV.install("--image", "node:22")

    def test_03_precondition_failure_is_legible(self):
        home2 = ENV.tmp / "home2"
        home2.mkdir(exist_ok=True)
        text = ENV.install("--folder", str(home2 / "C"), expect=1, extra_env={"FAKE_GH_UNAUTH": "1", "HOME": str(home2)})
        self.assertIn("gh auth login", text)
        self.assertNotIn("HTTP", text)
        self.assertFalse((home2 / "C" / "course.json").exists())

    def test_04_refuses_to_shadow_an_existing_command(self):
        home3 = ENV.tmp / "home3"
        (home3 / "bin").mkdir(parents=True, exist_ok=True)
        (home3 / "bin" / "ls").write_text("#!/bin/sh\n")
        (home3 / "bin" / "ls").chmod(0o755)
        proc = subprocess.run([sys.executable, str(KIT / "install"), "--non-interactive", "--course", "ls",
                               "--org", ORG, "--folder", str(home3 / "C"), "--runner", "r", "--skip-checks",
                               "--bin-dir", str(home3 / "bin")],
                              env=dict(ENV.env, HOME=str(home3)), capture_output=True, text=True)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("already exists on PATH", proc.stdout)

    def test_05_bad_course_code_rejected(self):
        proc = subprocess.run([sys.executable, str(KIT / "install"), "--non-interactive", "--course", "CS-108",
                               "--org", ORG, "--folder", str(ENV.tmp / "x"), "--runner", "r", "--skip-checks"],
                              env=ENV.env, capture_output=True, text=True)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("lowercase", proc.stdout)


class T02Assignments(unittest.TestCase):
    def test_01_new_scaffolds_both_graders_and_manual(self):
        ENV.run("new", "a01", "--title", "Hello JS", "--kind", "auto", "--grader", "js")
        ENV.run("new", "a02", "--title", "Hello Py", "--kind", "auto", "--grader", "py")
        ENV.run("new", "a09", "--title", "Essay", "--kind", "manual")
        self.assertTrue((ENV.course_dir / "autograders" / "a01" / "autograder.js").is_file())
        self.assertTrue((ENV.course_dir / "autograders" / "a02" / "autograder.py").is_file())
        self.assertFalse((ENV.course_dir / "autograders" / "a09").exists())
        self.assertEqual(json.loads((ENV.course_dir / "assignments" / "a09" / "assignment.json").read_text())["kind"], "manual")
        # the grader language was remembered
        self.assertEqual(json.loads((ENV.course_dir / "course.json").read_text())["grader_default"], "py")

    def test_02_verify_passes_both_grader_languages_without_being_told(self):
        text = ENV.run("verify", "a01", "a02", "a09")
        self.assertIn("3/3 clean", text)
        self.assertIn("answers  4/4   starter  0/4", text)

    def test_03_verify_fails_each_broken_invariant_naming_the_file(self):
        cases = {
            "drift": (lambda d, b: (d / "starter" / "test.js").open("a").write("// drift\n"),
                      "test.js is not the same in all copies"),
            "bundle-missing": (lambda d, b: (b / "package.json").unlink(),
                               "restore names package.json, which is not in the bundle"),
            "full-marks": (lambda d, b: shutil.copy(d / "answers" / "app.js", d / "starter" / "app.js"),
                           "starter scores 4/4"),
            "leak": (lambda d, b: shutil.copy(d / "answers" / "app.js", d / "starter" / "app.js"),
                     "identical in starter/ and answers/: app.js"),
            "deliverable-in-bundle": (lambda d, b: shutil.copy(d / "starter" / "app.js", b / "app.js"),
                                      "app.js is a deliverable and is IN the bundle"),
            "denominator": (lambda d, b: (b / "autograder.js").write_text(
                (b / "autograder.js").read_text().replace("EXPECTED_VISIBLE = 4", "EXPECTED_VISIBLE = 9")),
                "EXPECTED_VISIBLE is 9 but the suite actually ran 4"),
        }
        for name, (breaker, expected) in cases.items():
            aid = "b" + name.replace("-", "")[:6]
            d = ENV.course_dir / "assignments" / aid
            b = ENV.course_dir / "autograders" / aid
            shutil.copytree(ENV.course_dir / "assignments" / "a01", d)
            shutil.copytree(ENV.course_dir / "autograders" / "a01", b)
            breaker(d, b)
            text = ENV.run("verify", aid, expect=1)
            self.assertIn(expected, text, f"case {name}:\n{text}")
            shutil.rmtree(d), shutil.rmtree(b)


class T03Publish(unittest.TestCase):
    def test_01_template_preview_changes_nothing(self):
        before = ENV.snapshot_github()
        text = ENV.run("template", "a01")
        self.assertIn("PREVIEW", text)
        self.assertIn("--go", text)
        self.assertEqual(before, ENV.snapshot_github())

    def test_02_template_publishes_with_workflow_and_flag(self):
        text = ENV.run("template", "a01", "--go")
        self.assertIn("marked as a template", text)
        files = ENV.repo_files(f"{COURSE}-a01-starter")
        self.assertEqual(files, [".github/workflows/autograde.yml", "README.md", "app.js", "package.json", "test.js"])
        wf = ENV.repo_file(f"{COURSE}-a01-starter", ".github/workflows/autograde.yml")
        self.assertIn("runs-on: runners-26fa-cs108", wf)
        self.assertIn("image: node:22", wf)
        self.assertIn("npm test", wf)
        self.assertTrue(ENV.gh_state()["orgs"][ORG]["repos"][f"{COURSE}-a01-starter"]["is_template"])
        ENV.run("template", "a02", "--go")

    def test_03_manual_template_ships_no_workflow(self):
        ENV.run("template", "a09", "--go")
        files = ENV.repo_files(f"{COURSE}-a09-starter")
        self.assertNotIn(".github/workflows/autograde.yml", files)
        self.assertNotIn(".github/workflows/check.yml", files)

    def test_04_config_change_reaches_the_next_publish_and_offers_repush(self):
        text = ENV.run("config", "runner", "runners-2026")
        self.assertIn("only reaches templates published from now on", text)
        self.assertIn("patch a01 --files .github/workflows/autograde.yml --go", text)
        ENV.run("template", "a01", "--go")
        wf = ENV.repo_file(f"{COURSE}-a01-starter", ".github/workflows/autograde.yml")
        self.assertIn("runs-on: runners-2026", wf)
        self.assertIn("config runner: 'runners-26fa-cs108' -> 'runners-2026'",
                      (ENV.course_dir / "course-history.log").read_text())
        text = ENV.run("config", "course", "other", expect=1)
        self.assertIn("cannot be changed", text)
        text = ENV.run("config", "org", "bad org!", expect=1)
        self.assertIn("letters, digits and hyphens", text)

    def test_05_template_with_no_argument_lists(self):
        text = ENV.run("template")
        self.assertIn("a09", text)
        self.assertIn("manual", text)
        text = ENV.run("template", "zz", expect=1)
        self.assertIn("new zz", text)


class T04Assign(unittest.TestCase):
    def test_01_assign_preview_changes_nothing(self):
        before = ENV.snapshot_github()
        text = ENV.run("assign", "a01")
        self.assertIn("would create", text)
        self.assertIn("skipped: no github_id", text)
        self.assertEqual(before, ENV.snapshot_github())

    def test_02_assign_creates_repos_invites_and_is_idempotent(self):
        text = ENV.run("assign", "a01", "--go")
        self.assertIn("awaiting organization invitation (1): bob", text)
        repos = ENV.gh_state()["orgs"][ORG]["repos"]
        for u in ("ada", "bob", "tester"):
            self.assertIn(f"{COURSE}-a01-{u}", repos)
        self.assertNotIn(f"{COURSE}-a01-noid", repos)
        self.assertNotIn(f"{COURSE}-a01-prof", repos)
        self.assertTrue((ENV.course_dir / "distribution-a01.csv").is_file())
        text2 = ENV.run("assign", "a01", "--go")
        self.assertIn("exists", text2)
        self.assertEqual(ENV.repo_commits(f"{COURSE}-a01-ada"), 1)
        ENV.run("assign", "a02", "--go")
        ENV.run("assign", "a09", "--go")


class T05Grading(unittest.TestCase):
    def test_01_complete_in_three_cases_and_both_graders(self):
        # ada: one-character edit; tester: untouched; bob: a file the starter never had
        ada = ENV.clone(f"{COURSE}-a01-ada")
        app = ada / "app.js"
        app.write_text(app.read_text().replace("throw new Error(\"add is not implemented yet\");", "return a + b;"))
        ENV.push(ada, "implement add")
        bob = ENV.clone(f"{COURSE}-a01-bob")
        (bob / "notes.js").write_text("// my own file\n")
        ENV.push(bob, "add notes")

        text = ENV.run("marks", "a01")
        gb = ENV.gradebook("a01")
        self.assertEqual(gb["tester"]["complete"], "no")
        self.assertEqual(gb["tester"]["changed"], "untouched starter")
        self.assertEqual(gb["ada"]["complete"], "yes")
        self.assertEqual(gb["ada"]["changed"], "edited app.js")
        self.assertEqual(gb["bob"]["complete"], "yes")
        self.assertEqual(gb["bob"]["changed"], "added notes.js")
        self.assertEqual((gb["ada"]["score"], gb["ada"]["max_score"]), ("2", "4"))
        self.assertEqual(gb["tester"]["score"], "0")
        self.assertEqual(gb["noid"]["status"], "no repository")
        self.assertIn("complete 2/4", text)
        # No timestamp inside the gradebook, so it is reproducible.
        self.assertNotIn("graded_at", (ENV.grading / "a01" / "gradebook.csv").read_text())
        self.assertTrue((ENV.grading / "a01" / "results" / "ada.json").is_file())
        self.assertTrue((ENV.grading / "a01" / "feedback" / "ada.md").is_file())

        # The Python grader, without being told which is which.
        text = ENV.run("marks", "a02")
        gb2 = ENV.gradebook("a02")
        self.assertEqual(gb2["tester"]["status"], "graded")
        self.assertEqual(gb2["tester"]["score"], "0")

    def test_02_marks_is_reproducible_and_complete_never_regresses(self):
        text = ENV.run("marks", "a01", "--verify-reproducible")
        self.assertIn("byte-identical", text)
        self.assertIn("complete never regressed", text)
        self.assertTrue((ENV.grading / "a01" / "gradebook.previous.csv").is_file())

    def test_03_as_of_grades_the_earlier_commit(self):
        ada = ENV.clone(f"{COURSE}-a01-ada")
        app = ada / "app.js"
        app.write_text(app.read_text().replace("throw new Error(\"greet is not implemented yet\");",
                                               "return `Hello, ${name === undefined ? 'world' : name}!`;"))
        ENV.push(ada, "implement greet", date="2026-10-15T12:00:00-04:00")
        ENV.run("marks", "a01", "--students", "ada")
        self.assertEqual(ENV.gradebook("a01")["ada"]["score"], "4")
        ENV.run("marks", "a01", "--students", "ada", "--as-of", "2026-10-14T23:59:59-04:00")
        self.assertEqual(ENV.gradebook("a01")["ada"]["score"], "2")
        ENV.run("marks", "a01")

    def test_04_marks_refuses_manual_and_collect_works(self):
        text = ENV.run("marks", "a09", expect=1)
        self.assertIn("collect a09", text)
        self.assertIn("sheet a09", text)
        tester = ENV.clone(f"{COURSE}-a09-tester")
        (tester / "app.js").write_text("// essay\nmodule.exports = {};\n")
        ENV.push(tester, "essay")
        text = ENV.run("collect", "a09")
        self.assertIn("collected", text)
        self.assertTrue((ENV.grading / "a09" / "checkouts" / "tester" / "app.js").is_file())
        self.assertFalse((ENV.grading / "a09" / "gradebook.csv").exists())

    def test_05_sheet_has_the_right_rows_and_does_not_eat_work(self):
        text = ENV.run("sheet", "a09", "--columns", "design,style")
        path = ENV.grading / "a09" / "marks-a09.csv"
        raw = path.read_bytes()
        self.assertTrue(raw.startswith(b"\xef\xbb\xbf"))
        self.assertIn(b"\r\n", raw)
        rows = list(csv.DictReader(raw.decode("utf-8-sig").splitlines()))
        self.assertEqual([r["username"] for r in rows], ["tester", "bob", "noid", "ada"])   # by last name
        self.assertEqual(list(rows[0].keys())[-4:], ["mark", "comment", "design", "style"])
        by = {r["username"]: r for r in rows}
        self.assertEqual(by["tester"]["complete"], "yes")
        self.assertEqual(by["ada"]["complete"], "no")
        self.assertEqual(by["noid"]["complete"], "no repository")
        self.assertEqual(by["tester"]["score"], "")
        self.assertTrue(all(r["mark"] == "" for r in rows))
        # type two marks, re-run, original untouched, a second file appears
        rows[0]["mark"], rows[1]["mark"] = "9", "7"
        with path.open("w", newline="", encoding="utf-8-sig") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()), lineterminator="\r\n")
            w.writeheader(), w.writerows(rows)
        typed = path.read_bytes()
        text = ENV.run("sheet", "a09")
        self.assertEqual(path.read_bytes(), typed)
        self.assertTrue((ENV.grading / "a09" / "marks-a09-2.csv").is_file())
        self.assertIn("left alone", text)
        # an autograded sheet carries scores
        ENV.run("sheet", "a01")
        rows = list(csv.DictReader((ENV.grading / "a01" / "marks-a01.csv").read_text("utf-8-sig").splitlines()))
        self.assertEqual({r["username"]: r["score"] for r in rows}["ada"], "4")

    def test_06_tick_on_manual_adds_the_check_workflow(self):
        ENV.run("config", "tick_on_manual", "true")
        ENV.run("template", "a09", "--go")
        self.assertIn(".github/workflows/check.yml", ENV.repo_files(f"{COURSE}-a09-starter"))
        self.assertIn("node --check", ENV.repo_file(f"{COURSE}-a09-starter", ".github/workflows/check.yml"))
        ENV.run("config", "tick_on_manual", "false")


class T06Patch(unittest.TestCase):
    def test_01_patch_refuses_a_deliverable_and_prints_restore(self):
        text = ENV.run("patch", "a01", "--files", "app.js", expect=1)
        self.assertIn("refusing to push", text)
        self.assertIn("package.json, test.js", text)

    def test_02_patch_preview_changes_nothing(self):
        (ENV.course_dir / "autograders" / "a01" / "test.js").open("a").write("// fixed a hint\n")
        shutil.copy(ENV.course_dir / "autograders" / "a01" / "test.js", ENV.course_dir / "assignments" / "a01" / "starter" / "test.js")
        shutil.copy(ENV.course_dir / "autograders" / "a01" / "test.js", ENV.course_dir / "assignments" / "a01" / "answers" / "test.js")
        before = ENV.snapshot_github()
        text = ENV.run("patch", "a01")
        self.assertIn("would update", text)
        self.assertEqual(before, ENV.snapshot_github())

    def test_03_patch_pushes_and_is_idempotent_with_zero_deliverables_changed(self):
        ada_before = ENV.repo_file(f"{COURSE}-a01-ada", "app.js")
        text = ENV.run("patch", "a01", "--go")
        self.assertIn("0 deliverables changed", text)
        self.assertIn("test.js: updated", text)
        self.assertIn("// fixed a hint", ENV.repo_file(f"{COURSE}-a01-ada", "test.js"))
        self.assertIn("// fixed a hint", ENV.repo_file(f"{COURSE}-a01-starter", "test.js"))
        self.assertEqual(ada_before, ENV.repo_file(f"{COURSE}-a01-ada", "app.js"))
        commits = ENV.repo_commits(f"{COURSE}-a01-ada")
        text = ENV.run("patch", "a01", "--go")
        self.assertIn("0 file write(s)", text)
        self.assertEqual(commits, ENV.repo_commits(f"{COURSE}-a01-ada"))

    def test_03b_patch_creates_files_added_to_restore_after_assign(self):
        """A provided file that did not exist when the repos went out (a new
        helper, a new fixtures folder) is created in every repository once it
        is on the restore list and in the bundle."""
        for d in ("assignments/a01/starter", "assignments/a01/answers", "autograders/a01"):
            (ENV.course_dir / d / "helper.js").write_text("module.exports = {};\n")
            (ENV.course_dir / d / "fixtures").mkdir(exist_ok=True)
            (ENV.course_dir / d / "fixtures" / "data.txt").write_text("1,2,3\n")
        aj = ENV.course_dir / "assignments/a01/assignment.json"
        data = json.loads(aj.read_text())
        data["restore"] += ["helper.js", "fixtures/"]
        aj.write_text(json.dumps(data))
        ENV.run("verify", "a01", "--quick")
        text = ENV.run("patch", "a01")
        self.assertIn("helper.js: would create", text)
        self.assertIn("fixtures/data.txt: would create", text)
        self.assertNotIn("helper.js", ENV.repo_files(f"{COURSE}-a01-ada"))
        text = ENV.run("patch", "a01", "--go")
        self.assertIn("0 deliverables changed", text)
        for repo in (f"{COURSE}-a01-ada", f"{COURSE}-a01-starter"):
            files = ENV.repo_files(repo)
            self.assertIn("helper.js", files)
            self.assertIn("fixtures/data.txt", files)
        # a second run adds nothing
        commits = ENV.repo_commits(f"{COURSE}-a01-ada")
        ENV.run("patch", "a01", "--go")
        self.assertEqual(commits, ENV.repo_commits(f"{COURSE}-a01-ada"))

    def test_03c_a_file_added_only_to_the_starter_is_named_not_skipped(self):
        """A folder entry on restore is expanded over every copy, so a file
        dropped into starter/fixtures/ without a bundle copy is reported by
        verify and refused by patch, never silently left out."""
        (ENV.course_dir / "assignments/a01/starter/fixtures/extra.txt").write_text("x\n")
        text = ENV.run("verify", "a01", "--quick", expect=1)
        self.assertIn("fixtures/extra.txt, which is not in the bundle", text)
        text = ENV.run("patch", "a01", expect=1)
        self.assertIn("not found", text)
        self.assertIn("fixtures/extra.txt", text)
        (ENV.course_dir / "assignments/a01/starter/fixtures/extra.txt").unlink()

    def test_03d_patch_missing_adds_new_starter_files_and_never_overwrites(self):
        """--missing pushes starter files a repository lacks, with an empty
        restore list, and leaves every existing file alone, including a
        deliverable the student has edited."""
        # a09 is manual with an empty restore list; ada's repo is untouched
        # starter, tester's has an edited app.js (from test_04 in T05).
        (ENV.course_dir / "assignments/a09/starter/extra.md").write_text("new guidance\n")
        (ENV.course_dir / "assignments/a09/answers/extra.md").write_text("new guidance\n")
        tester_app = ENV.repo_file(f"{COURSE}-a09-tester", "app.js")
        text = ENV.run("patch", "a09", "--missing")
        self.assertIn("extra.md: would create", text)
        self.assertNotIn("app.js: would", text)
        self.assertNotIn("extra.md", ENV.repo_files(f"{COURSE}-a09-tester"))
        text = ENV.run("patch", "a09", "--missing", "--go")
        self.assertIn("0 deliverables changed", text)
        self.assertIn("extra.md", ENV.repo_files(f"{COURSE}-a09-tester"))
        self.assertIn("extra.md", ENV.repo_files(f"{COURSE}-a09-ada"))
        self.assertEqual(tester_app, ENV.repo_file(f"{COURSE}-a09-tester", "app.js"))
        commits = ENV.repo_commits(f"{COURSE}-a09-tester")
        text = ENV.run("patch", "a09", "--missing", "--go")
        self.assertIn("nothing missing", text)
        self.assertEqual(commits, ENV.repo_commits(f"{COURSE}-a09-tester"))
        text = ENV.run("patch", "a09", "--missing", "--files", "x", expect=2)
        self.assertIn("do not combine", text)

    def test_04_patch_works_for_manual_assignments_from_the_starter(self):
        readme = ENV.course_dir / "assignments" / "a09" / "starter" / "README.md"
        readme.open("a").write("\nClarified.\n")
        shutil.copy(readme, ENV.course_dir / "assignments" / "a09" / "answers" / "README.md")
        data = json.loads((ENV.course_dir / "assignments" / "a09" / "assignment.json").read_text())
        data["restore"] = ["README.md"]
        (ENV.course_dir / "assignments" / "a09" / "assignment.json").write_text(json.dumps(data))
        text = ENV.run("patch", "a09", "--go")
        self.assertIn("0 deliverables changed", text)
        self.assertIn("Clarified.", ENV.repo_file(f"{COURSE}-a09-tester", "README.md"))


class T07RosterStatusDoctor(unittest.TestCase):
    def test_01_students_import_previews_then_merges_additively(self):
        form = ENV.tmp / "responses.csv"
        form.write_text("Timestamp,Your name,Calvin email,GitHub username,Lab section\n"
                        "1,No Identifier,noid@example.edu,https://github.com/noid-gh,B\n"
                        "2,Carol New,carol@example.edu,carol-gh,A\n"
                        "3,Bad One,bad@example.edu,not a login!,A\n"
                        "4,Ada Lovelace,ada@example.edu,SOMETHING-ELSE,A\n", encoding="utf-8")
        before = (ENV.course_dir / "roster" / "roster.csv").read_bytes()
        text = ENV.run("students", "import", str(form))
        self.assertIn("PREVIEW", text)
        self.assertIn("carol", text)
        self.assertIn("NOT a GitHub username", text)
        self.assertEqual(before, (ENV.course_dir / "roster" / "roster.csv").read_bytes())
        ENV.run("students", "import", str(form), "--go")
        rows = {r["username"]: r for r in csv.DictReader((ENV.course_dir / "roster" / "roster.csv").open())}
        self.assertEqual(rows["noid"]["github_id"], "noid-gh")       # blank filled
        self.assertEqual(rows["ada"]["github_id"], "ada-gh")         # existing value kept
        self.assertEqual(rows["carol"]["role"], "student")
        self.assertEqual(rows["prof"]["role"], "teacher")            # untouched
        self.assertNotIn("bad", rows)

    def test_02_status_shows_state_first_then_exceptions(self):
        text = ENV.run()
        self.assertIn("published", text)
        self.assertIn("a01", text)
        self.assertIn("not yet invited", text)         # carol and noid now have ids but no repos
        self.assertIn(f"{COURSE} assign a01 --go", text)

    def test_03_status_without_github_says_unknown(self):
        text = ENV.run(extra_env={"PATH": os.environ["PATH"]})
        self.assertIn("unknown", text)
        self.assertNotIn("not published", text)

    def test_04_doctor_reports_by_name_and_exits_nonzero_on_failure(self):
        text = ENV.run("doctor", expect=0)
        for name in ("gh ", "gh org access", "runner scale set", "template flags", "published workflows",
                     "restore copies agree", "roster", "grading folder", "test account pre-flight"):
            self.assertIn(name, text)
        # a02's workflow still carries the old runner name: doctor notices
        self.assertIn("out of date: a02", text)
        # break a restore copy: doctor must fail
        (ENV.course_dir / "assignments" / "a02" / "starter" / "test.js").open("a").write("// drift\n")
        text = ENV.run("doctor", expect=1)
        self.assertIn("restore copies agree", text)
        self.assertIn("a02/test.js", text)
        shutil.copy(ENV.course_dir / "autograders" / "a02" / "test.js", ENV.course_dir / "assignments" / "a02" / "starter" / "test.js")
        ENV.run("doctor", expect=0)

    def test_05_doctor_smoke_previews_without_go(self):
        before = ENV.snapshot_github()
        text = ENV.run("doctor", "--smoke")
        self.assertIn("PREVIEW", text)
        self.assertEqual(before, ENV.snapshot_github())

    def test_06_ui_runs_the_same_commands_and_refuses_unconfirmed_go(self):
        import http.client
        import time
        proc = subprocess.Popen([sys.executable, str(KIT / "coursekit" / "__main__.py"), "ui", "--no-browser", "--port", "5977"],
                                cwd=str(ENV.course_dir), env=ENV.env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        try:
            time.sleep(1.5)
            conn = http.client.HTTPConnection("127.0.0.1", 5977, timeout=30)
            conn.request("GET", "/api/state")
            state = json.loads(conn.getresponse().read())
            self.assertEqual(state["course"]["course"], COURSE)
            self.assertTrue(any(r["id"] == "a01" for r in state["table"]))
            conn.request("POST", "/api/run", body=json.dumps({"command": f"{COURSE} assign a01 --go"}),
                         headers={"Content-Type": "application/json"})
            resp = conn.getresponse()
            self.assertEqual(resp.status, 400)
            self.assertIn("confirm", json.loads(resp.read())["error"])
            conn.request("POST", "/api/run", body=json.dumps({"command": f"{COURSE} verify a01 --quick"}),
                         headers={"Content-Type": "application/json"})
            job = json.loads(conn.getresponse().read())
            for _ in range(40):
                time.sleep(0.5)
                conn.request("GET", f"/api/job/{job['id']}/0")
                j = json.loads(conn.getresponse().read())
                if j["done"]:
                    break
            self.assertEqual(j["returncode"], 0)
            self.assertIn("all invariants hold", "\n".join(j["lines"]))
            conn.request("POST", "/api/run", body=json.dumps({"command": "rm -rf /"}),
                         headers={"Content-Type": "application/json"})
            self.assertEqual(conn.getresponse().status, 400)
        finally:
            proc.terminate()

    def test_07_config_show_and_check(self):
        text = ENV.run("config")
        self.assertIn("runner", text)
        self.assertIn("course.json", text)
        text = ENV.run("config", "--check")
        self.assertIn("authenticated as instructor", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
