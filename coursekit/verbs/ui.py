"""
ui, a small local page. Three screens, and no more.
===================================================

    cs108 ui                # serve on 127.0.0.1, open a browser, stop with Ctrl-C
    cs108 ui --port 5200 --no-browser

THE RULE THAT KEEPS IT SMALL
    Every button maps to exactly one command, shows that command as text,
    and does nothing the command line cannot do. This server does not
    implement any verb. A button POSTs the command line it displays; the
    server checks that the first word is a real verb and runs THE SAME
    COMMAND you would type, as a child process, and streams its output back.
    If a screen needs a capability, add the verb first and surface it second.

PREVIEW BY DEFAULT HOLDS HERE TOO
    A command that carries --go is refused unless the request also carries
    confirm=true, which the page only sends after showing the preview and
    asking a second time.

THREE SCREENS
    Status      one row per assignment, state first, then what is wrong with
                the command that fixes it
    Assignment  one row per participant, and the four or five buttons that
                apply to this assignment
    Settings    course.json as a form, with a Check button

WHAT IT MUST NOT BECOME (say it in the code, because a later agent will be
tempted): no charts, no per-student page, no code viewer, no editing of
assignments or rosters in the browser, no login, no multi-course switching,
no build step, no framework. Plain HTML and a little JavaScript, served from
one file, ui.html, next to this one.

WHY LOOPBACK ONLY
    It speaks for your gh login and shows student names and marks. Binding
    to 127.0.0.1 means nothing outside this machine can reach it, which is
    the whole security model and why it needs no password. Change the bind
    address and it needs authentication first; that is not a detail to
    postpone.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import threading
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from .. import advice
from .. import config as cfg
from .. import ghcli, state as statemod
from ..cli import VERBS
from .status import table_rows

HERE = Path(__file__).resolve().parent
UI_HTML = HERE.parent / "ui.html"
VERB_NAMES = {v[0] for v in VERBS}
PACKAGE_DIR = HERE.parent


class Job:
    """One command, run as a child, output tailed by the page."""

    def __init__(self, argv, cwd: Path, env: dict, label: str):
        self.id = uuid.uuid4().hex[:12]
        self.argv, self.label = argv, label
        self.lines, self.done, self.returncode = [], False, None
        self._lock = threading.Lock()
        self._thread = threading.Thread(target=self._run, args=(cwd, env), daemon=True)

    def start(self):
        self._thread.start()
        return self

    def _emit(self, text):
        with self._lock:
            self.lines.append(text)

    def _run(self, cwd, env):
        self._emit("$ " + self.label)
        try:
            proc = subprocess.Popen(self.argv, cwd=str(cwd), env=env, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                    text=True, bufsize=1)
        except FileNotFoundError as exc:
            self._emit(f"could not start: {exc}")
            self.returncode, self.done = 127, True
            return
        for line in proc.stdout:
            self._emit(line.rstrip("\n"))
        proc.wait()
        self.returncode = proc.returncode
        self._emit(f"[exit {proc.returncode}]")
        self.done = True

    def snapshot(self, since=0):
        with self._lock:
            return {"id": self.id, "label": self.label, "done": self.done,
                    "returncode": self.returncode, "lines": self.lines[since:],
                    "total": len(self.lines)}


class App:
    def __init__(self, course: cfg.Course):
        self.course = course
        self.gh = ghcli.Gh(course.org)
        self.jobs = {}

    def state(self):
        snap = statemod.snapshot(self.course, self.gh)
        snap["actions"] = advice.next_actions(snap)
        snap["table"] = table_rows(snap)
        snap["descriptions"] = cfg.DESCRIPTIONS
        snap["workflow_keys"] = list(cfg.WORKFLOW_KEYS)
        return snap

    def run_command(self, line: str, confirm: bool):
        """Run exactly the command the button showed. Returns (job, error)."""
        try:
            words = shlex.split(line)
        except ValueError as exc:
            return None, f"could not parse the command: {exc}"
        name = self.course.course
        if not words or words[0] != name:
            return None, f"a command starts with {name}"
        rest = words[1:]
        if rest and rest[0] not in VERB_NAMES:
            return None, f"unknown verb {rest[0]!r}"
        if rest and rest[0] == "ui":
            return None, "the UI cannot start itself"
        if "--go" in rest and not confirm:
            return None, "this changes GitHub or the roster; confirm the preview first"
        argv = [sys.executable, str(PACKAGE_DIR / "__main__.py"), *rest]
        env = dict(os.environ, COURSEKIT_COMMAND=name, COURSEKIT_COURSE=str(self.course.root),
                   NO_COLOR="1", PYTHONUNBUFFERED="1")
        job = Job(argv, self.course.root, env, line).start()
        self.jobs[job.id] = job
        self.gh.invalidate()
        return job, None


class Handler(BaseHTTPRequestHandler):
    app: App = None
    server_version = "coursekit-ui"

    def log_message(self, fmt, *args):
        if "/api/job/" not in (self.path or "") and "/api/state" not in (self.path or ""):
            sys.stderr.write("  %s %s\n" % (self.command, self.path))

    def _send(self, code, body: bytes, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, payload, code=200):
        self._send(code, json.dumps(payload, default=str).encode(), "application/json; charset=utf-8")

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n) or b"{}")
        except json.JSONDecodeError:
            return {}

    def do_GET(self):
        path = urlparse(self.path).path
        a = self.app
        if path in ("/", "/index.html"):
            return self._send(200, UI_HTML.read_bytes(), "text/html; charset=utf-8")
        if path == "/api/state":
            return self._json(a.state())
        if path.startswith("/api/assignment/"):
            aid = unquote(path.rsplit("/", 1)[-1])
            snap = a.state()
            found = next((x for x in snap["assignments"] if x["id"] == aid), None)
            if not found:
                return self._json({"error": f"no assignment {aid}"}, 404)
            detail = dict(found)
            detail["course"] = snap["course"]
            detail["github"] = snap["github"]
            detail["rows"] = [{"username": p["username"], "name": p["name"], "role": p["role"],
                               "github_id": p["github_id"], "membership": p["membership"],
                               **p["cells"].get(aid, {})} for p in snap["participants"]]
            # The tick, one call per repository. This is the one place a
            # per-repository request is made, and only for one assignment at
            # a time, never for the whole grid. Cached for ninety seconds.
            if snap["github"]["available"]:
                for row in detail["rows"]:
                    if row.get("has_repo"):
                        run = a.gh.last_run(a.course.full(row["repo"]))
                        row["tick"] = (run["conclusion"] or run["status"]) if run else "no run"
                        row["tick_url"] = run["url"] if run else ""
                    else:
                        row["tick"] = ""
            detail["sheet"] = []
            if found["sheets"]:
                sheet = Path(found["grading_dir"]) / found["sheets"][-1]
                try:
                    detail["sheet"] = statemod.read_sheet(sheet)
                    detail["sheet_name"] = sheet.name
                except OSError:
                    pass
            return self._json(detail)
        if path.startswith("/api/job/"):
            rest = unquote(path[len("/api/job/"):])
            job_id, _, since = rest.partition("/")
            job = a.jobs.get(job_id)
            if not job:
                return self._json({"error": "no such job"}, 404)
            return self._json(job.snapshot(int(since or 0)))
        return self._json({"error": "not found"}, 404)

    def do_POST(self):
        path = urlparse(self.path).path
        body = self._body()
        if path == "/api/refresh":
            self.app.gh.invalidate()
            return self._json(self.app.state())
        if path == "/api/run":
            job, err = self.app.run_command((body.get("command") or "").strip(),
                                            bool(body.get("confirm")))
            if err:
                return self._json({"error": err}, 400)
            return self._json(job.snapshot())
        return self._json({"error": "not found"}, 404)


def run(course: cfg.Course, argv) -> int:
    ap = argparse.ArgumentParser(prog=f"{course.course} ui", description="Open the local page.")
    ap.add_argument("--port", type=int, default=5117)
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args(argv)

    Handler.app = App(course)
    try:
        httpd = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    except OSError as exc:
        if exc.errno not in (48, 98):
            raise
        print(f"error: port {args.port} is already in use.", file=sys.stderr)
        print(f"  If a page is already running it is at http://127.0.0.1:{args.port}/\n"
              f"  Or:  {course.course} ui --port {args.port + 1}", file=sys.stderr)
        return 1
    url = f"http://127.0.0.1:{args.port}/"
    print(f"{course.course} ui  ->  {url}")
    print(f"  course : {course.root}\n  org    : {course.org}\n  grading: {course.grading}")
    print("\nLoopback only. Every button runs the command it shows. Ctrl-C to stop.\n")
    if not args.no_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        httpd.server_close()
    return 0
