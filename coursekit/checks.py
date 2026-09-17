"""
checks.py, the precondition checks, in one place.
=================================================

The installer, `config --check` and `doctor` all run these and report each
by name. A check returns a Result with a status of ok, warn or fail and a
detail line. The rule for details: name the fix, not the API error. A
missing or unauthenticated gh is the most common failure by a wide margin,
and "run: gh auth login" is worth more than any stack trace.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from dataclasses import dataclass
from typing import Callable, List, Optional

from . import ghcli

OK, WARN, FAIL = "ok", "warn", "fail"


@dataclass
class Result:
    name: str
    status: str
    detail: str

    @property
    def failed(self) -> bool:
        return self.status == FAIL


def _version(argv: List[str]) -> str:
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=20)
        line = (proc.stdout or proc.stderr).strip().splitlines()
        return line[0] if line else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def check_gh() -> Result:
    if not shutil.which("gh"):
        return Result("gh", FAIL, "not installed. Install from https://cli.github.com then run: gh auth login")
    try:
        status = ghcli.auth_status()
    except ghcli.GhUnavailable as exc:
        return Result("gh", FAIL, str(exc))
    ver = ghcli.version()
    if not status["ok"]:
        return Result("gh", FAIL, f"{ver}, not authenticated. Run:  gh auth login")
    return Result("gh", OK, f"{ver}, authenticated as {status['login'] or '?'}")


def check_org(org: str) -> Result:
    if not org:
        return Result("gh org access", FAIL, "no organization configured")
    try:
        gh = ghcli.Gh(org)
        info = gh.org_info()
    except ghcli.GhUnavailable as exc:
        return Result("gh org access", FAIL, f"{org}: {exc}")
    if not info:
        return Result("gh org access", FAIL, f"{org}: organization not found, or no access")
    role = gh.my_role()
    if role == "admin":
        return Result("gh org access", OK, f"{org}, admin")
    if role:
        return Result("gh org access", WARN, f"{org}, role {role}: creating repositories and inviting students needs owner (admin)")
    return Result("gh org access", WARN, f"{org} exists, but your membership could not be read; owner access is needed")


def check_git() -> Result:
    if not shutil.which("git"):
        return Result("git", FAIL, "not installed")
    return Result("git", OK, _version(["git", "--version"]).replace("git version ", ""))


def check_git_credentials() -> Result:
    """Cloning private repositories over HTTPS needs git to ask gh for the
    token. `gh auth setup-git` configures that once; without it, `marks`
    hangs on a password prompt or fails with 'could not read Username'."""
    try:
        proc = subprocess.run(["git", "config", "--get-all", "credential.helper"],
                              capture_output=True, text=True, timeout=20)
        helpers = proc.stdout
        proc2 = subprocess.run(["git", "config", "--get-regexp", r"credential\.https://github\.com\.helper"],
                               capture_output=True, text=True, timeout=20)
        helpers += proc2.stdout
    except (OSError, subprocess.SubprocessError):
        helpers = ""
    if "gh " in helpers or "gh auth" in helpers or "!gh" in helpers:
        return Result("git credentials", OK, "git asks gh for the token (gh auth setup-git)")
    if helpers.strip():
        return Result("git credentials", WARN, f"a credential helper is set ({helpers.strip().splitlines()[0][:40]}); "
                      f"if clones of private repos fail, run: gh auth setup-git")
    return Result("git credentials", WARN, "no credential helper; private clones will fail. Run:  gh auth setup-git")


def check_python() -> Result:
    v = sys.version_info
    if v < (3, 8):
        return Result("python3", FAIL, f"{v.major}.{v.minor} is too old; 3.8 or newer is needed")
    return Result("python3", OK, f"{v.major}.{v.minor}.{v.micro} ({sys.executable})")


def check_node() -> Result:
    if not shutil.which("node"):
        return Result("node", WARN, "not installed; needed to run JavaScript suites and graders locally (https://nodejs.org)")
    ver = _version(["node", "--version"])
    try:
        major = int(ver.lstrip("v").split(".")[0])
    except ValueError:
        major = 0
    if major and major < 18:
        return Result("node", WARN, f"{ver}; node --test and node:assert need 18 or newer")
    return Result("node", OK, f"{ver} ({shutil.which('node')})")


def check_runner(org: str, runner: str) -> Result:
    """Does the scale set show any runners? See Gh.runners() for why 'none'
    is not proof of absence."""
    if not runner:
        return Result("runner scale set", FAIL, "no runner name configured; a job with no runner queues forever")
    try:
        runners = ghcli.Gh(org).runners()
    except ghcli.GhUnavailable as exc:
        return Result("runner scale set", WARN, f"could not list runners: {exc}")
    matching = [r for r in runners if r["name"].startswith(runner) or runner in r["labels"]]
    if matching:
        idle = sum(1 for r in matching if r["status"] == "online" and not r["busy"])
        return Result("runner scale set", OK, f"{runner}: {len(matching)} runner(s) registered, {idle} idle")
    if runners:
        names = ", ".join(sorted({r["name"].rsplit('-', 1)[0] for r in runners})[:4])
        return Result("runner scale set", WARN,
                      f"{runner}: no runner with that name is registered to {org} right now "
                      f"(seen: {names}). A scale set at minimum 0 shows nothing while idle; "
                      f"the certain answer is a smoke test:  doctor --smoke --go")
    return Result("runner scale set", WARN,
                  f"{runner}: no runners registered to {org} right now. A scale set at minimum 0 "
                  f"shows nothing while idle; the certain answer is a smoke test:  doctor --smoke --go")


def check_image(image: str) -> Result:
    """The image must default to root. Only confirmed for the official images
    the toolkit knows run as root; anything else is a warning, not a pass."""
    known_root = ("node", "python", "gcc", "debian", "ubuntu", "alpine", "golang", "ruby", "openjdk", "eclipse-temurin")
    base = image.split("/")[-1].split(":")[0].split("@")[0]
    if not image:
        return Result("container image", FAIL, "no image configured; ARC rejects a job without a container")
    if base in known_root and "/" not in image:
        return Result("container image", OK, f"{image} (official image, runs as root)")
    return Result("container image", WARN,
                  f"{image}: cannot confirm it runs as root. The Kubernetes hook ignores the "
                  f"container user setting, so a non-root image fails with EACCES in actions/checkout.")


def check_grading_folder(path) -> Result:
    from pathlib import Path
    p = Path(path).expanduser()
    try:
        p.mkdir(parents=True, exist_ok=True)
        probe = p / ".write-test"
        probe.write_text("ok")
        probe.unlink()
    except OSError as exc:
        return Result("grading folder", FAIL, f"{p}: not writable ({exc})")
    return Result("grading folder", OK, str(p))


def preconditions(org: Optional[str] = None) -> List[Result]:
    """The installer's five checks: gh, org access, git, python3, node."""
    results = [check_gh()]
    if org is not None:
        results.append(check_org(org) if results[0].status == OK
                       else Result("gh org access", FAIL, "skipped: gh is not usable"))
    results += [check_git(), check_git_credentials(), check_python(), check_node()]
    return results


def print_results(results: List[Result], indent: str = "    ") -> bool:
    """Print `name .... detail   status` lines; return True when nothing failed."""
    from . import out
    width = max(len(r.name) for r in results) + 2
    colours = {OK: out.green, WARN: out.yellow, FAIL: out.red}
    for r in results:
        dots = "." * max(2, 26 - len(r.name))
        print(f"{indent}{r.name} {dots} {r.detail:<50} {colours[r.status](r.status)}")
    return not any(r.failed for r in results)
