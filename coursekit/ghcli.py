"""
ghcli.py, every GitHub call the toolkit makes, through the `gh` CLI.
====================================================================

WHY gh AND NOT A LIBRARY
    `gh auth login` is the one setup step every instructor already does, it
    stores the token, it refreshes it, and it handles the git credential
    helper so `git clone` of a private repository just works. Using it means
    the toolkit has no dependency and no secret of its own to keep.

TWO HALVES
    READS   `Gh.members()`, `Gh.pending()`, `Gh.repos()`, `Gh.tree()`, ...
            Cached for ninety seconds, because three calls describe the whole
            organization whatever the class size, and the status screen asks
            the same three questions on every refresh.

    WRITES  `invite()`, `create_from_template()`, `put_file()`, ...
            Never cached, never called from anything that did not receive
            --go. Each is an explicit act with a paper trail.

    If the UI or the status command ever calls a write here, something has
    gone wrong with the design, not just the code.

FAILURE
    A missing or unauthenticated gh raises GhUnavailable with the command to
    run. Callers that can carry on without GitHub (status, doctor) catch it
    and say what is UNKNOWN rather than reporting a confident wrong answer.
"""

from __future__ import annotations

import base64
import hashlib
import json
import subprocess
import time
from typing import Dict, List, Optional

CACHE_SECONDS = 90
AUTH_HINT = "gh is not authenticated. Run:  gh auth login"


class GhUnavailable(RuntimeError):
    """gh is missing, unauthenticated, or the network is down."""


def _run(args: List[str], timeout: int = 60, input_text: Optional[str] = None):
    """Run gh and return the CompletedProcess. A missing binary raises
    GhUnavailable so the caller can name the fix instead of a traceback."""
    try:
        return subprocess.run(["gh", *args], capture_output=True, text=True,
                              timeout=timeout, input=input_text)
    except FileNotFoundError:
        raise GhUnavailable("the GitHub CLI (gh) is not installed or not on PATH.\n"
                            "  Install it from https://cli.github.com then run: gh auth login")
    except subprocess.TimeoutExpired:
        raise GhUnavailable(f"gh timed out after {timeout}s: gh {' '.join(args[:3])}")


def auth_status() -> dict:
    """{'ok': bool, 'login': str, 'detail': str}. Never raises for a plain
    unauthenticated gh; raises GhUnavailable only when gh is absent."""
    proc = _run(["auth", "status"], timeout=30)
    text = (proc.stdout or "") + (proc.stderr or "")
    login = ""
    for line in text.splitlines():
        line = line.strip()
        # gh prints either "Logged in to github.com as octocat (...)" (older)
        # or "Logged in to github.com account octocat (keyring)" (newer).
        if "Logged in to" in line:
            for marker in (" account ", " as "):
                if marker in line:
                    login = line.split(marker, 1)[1].split()[0].strip("()")
                    break
            if login:
                break
    return {"ok": proc.returncode == 0, "login": login,
            "detail": text.strip().splitlines()[0] if text.strip() else ""}


def require_auth() -> None:
    """Die readably when gh cannot be used. Every write verb calls this first."""
    status = auth_status()
    if not status["ok"]:
        raise GhUnavailable(AUTH_HINT)


def version() -> str:
    proc = _run(["--version"], timeout=20)
    first = (proc.stdout or "").splitlines()
    return first[0].replace("gh version ", "").split()[0] if first else ""


def api(path: str, method: str = "GET", fields: Optional[dict] = None,
        raw_fields: Optional[dict] = None, paginate: bool = False,
        timeout: int = 60):
    """One REST call. Returns (ok, parsed-or-text, stderr)."""
    args = ["api", path]
    if method != "GET":
        args += ["--method", method]
    for k, v in (fields or {}).items():
        args += ["-f", f"{k}={v}"]
    for k, v in (raw_fields or {}).items():
        args += ["-F", f"{k}={v}"]
    if paginate:
        args += ["--paginate", "--slurp"]
    proc = _run(args, timeout=timeout)
    text = proc.stdout or ""
    if proc.returncode != 0:
        err = (proc.stderr or text).strip()
        if "gh auth login" in err or "authentication" in err.lower():
            raise GhUnavailable(AUTH_HINT)
        return False, text, err
    try:
        data = json.loads(text) if text.strip() else None
    except json.JSONDecodeError:
        data = text
    if paginate and isinstance(data, list) and data and isinstance(data[0], list):
        data = [item for page in data for item in page]
    return True, data, ""


def git_blob_sha(data: bytes) -> str:
    """Git's object id for a blob, so a local file can be compared with what
    GitHub holds without downloading it."""
    header = f"blob {len(data)}\0".encode()
    return hashlib.sha1(header + data).hexdigest()


# ── reads ───────────────────────────────────────────────────────────────

class Gh:
    """Cached read-only view of one organization."""

    def __init__(self, org: str, cache_seconds: int = CACHE_SECONDS):
        self.org = org
        self.cache_seconds = cache_seconds
        self._cache: Dict[str, tuple] = {}

    def _cached(self, key: str, produce):
        hit = self._cache.get(key)
        now = time.monotonic()
        if hit and now - hit[0] < self.cache_seconds:
            return hit[1]
        value = produce()
        self._cache[key] = (now, value)
        return value

    def invalidate(self) -> None:
        self._cache.clear()

    def _get(self, path: str, paginate: bool = True):
        ok, data, err = api(path, paginate=paginate)
        if not ok:
            raise GhUnavailable(f"gh api {path.split('?')[0]} failed: {err.splitlines()[0] if err else 'unknown error'}")
        return data if data is not None else []

    def org_info(self) -> dict:
        return self._cached("org", lambda: self._get(f"orgs/{self.org}", paginate=False) or {})

    def my_role(self) -> str:
        """'admin', 'member' or '' for the authenticated user in this org."""
        def produce():
            ok, data, _ = api(f"user/memberships/orgs/{self.org}")
            return (data or {}).get("role", "") if ok and isinstance(data, dict) else ""
        return self._cached("role", produce)

    def members(self) -> List[str]:
        """Logins of people actually in the organization."""
        return self._cached("members", lambda: sorted(
            r["login"] for r in self._get(f"orgs/{self.org}/members?per_page=100")
            if r.get("login")))

    def pending(self) -> List[dict]:
        """Invited, not yet accepted. `login` is empty for email invitations."""
        def produce():
            return [{"login": r.get("login") or "", "email": r.get("email") or "",
                     "created_at": r.get("created_at") or ""}
                    for r in self._get(f"orgs/{self.org}/invitations?per_page=100")]
        return self._cached("pending", produce)

    def repos(self) -> Dict[str, dict]:
        """Every repository in the org, keyed by lowercase name."""
        def produce():
            rows = self._get(f"orgs/{self.org}/repos?per_page=100&sort=full_name")
            return {r["name"].lower(): {
                        "name": r["name"],
                        "private": bool(r.get("private")),
                        "is_template": bool(r.get("is_template")),
                        "pushed_at": r.get("pushed_at") or "",
                        "url": r.get("html_url") or f"https://github.com/{self.org}/{r['name']}",
                    } for r in rows if r.get("name")}
        return self._cached("repos", produce)

    def tree(self, full_name: str) -> Dict[str, str]:
        """{path: blob sha} for the default branch, or {} if there is none."""
        def produce():
            ok, data, _ = api(f"repos/{full_name}/git/trees/HEAD?recursive=1")
            if not ok or not isinstance(data, dict):
                return {}
            return {n["path"]: n["sha"] for n in data.get("tree", [])
                    if n.get("type") == "blob"}
        return self._cached(f"tree:{full_name}", produce)

    def last_run(self, full_name: str) -> Optional[dict]:
        """The most recent Actions run of a repository, or None."""
        def produce():
            ok, data, _ = api(f"repos/{full_name}/actions/runs?per_page=1")
            runs = (data or {}).get("workflow_runs") if ok and isinstance(data, dict) else None
            if not runs:
                return None
            run = runs[0]
            return {"status": run.get("status") or "", "conclusion": run.get("conclusion") or "",
                    "created_at": run.get("created_at") or "", "url": run.get("html_url") or ""}
        return self._cached(f"run:{full_name}", produce)

    def runners(self) -> List[dict]:
        """Self-hosted runners registered to the org, as GitHub reports them.

        ARC scale-set runners appear here only while a runner pod exists. A
        scale set with min runners 0 and no job in flight lists nothing, which
        is why `doctor --smoke` exists: the only certain answer is a job that
        ran.
        """
        def produce():
            ok, data, _ = api(f"orgs/{self.org}/actions/runners?per_page=100")
            rows = (data or {}).get("runners", []) if ok and isinstance(data, dict) else []
            return [{"name": r.get("name", ""), "status": r.get("status", ""),
                     "busy": bool(r.get("busy")),
                     "labels": [l.get("name", "") for l in r.get("labels", [])]}
                    for r in rows]
        return self._cached("runners", produce)


# ── writes ──────────────────────────────────────────────────────────────

def repo_exists(full_name: str) -> bool:
    proc = _run(["repo", "view", full_name, "--json", "name"], timeout=45)
    return proc.returncode == 0


def membership_state(org: str, login: str) -> Optional[str]:
    """'active', 'pending', or None."""
    ok, data, _ = api(f"orgs/{org}/memberships/{login}")
    return (data or {}).get("state") if ok and isinstance(data, dict) else None


def invite(org: str, login: str) -> tuple:
    """Invite one login to the organization. Returns (state, error)."""
    ok, data, err = api(f"orgs/{org}/memberships/{login}", method="PUT",
                        fields={"role": "member"})
    if not ok:
        if "Not Found" in err:
            return None, f"no such GitHub user {login!r}; check github_id in the roster"
        return None, f"invite failed: {err[:180]}"
    return (data or {}).get("state", "pending"), None


def create_repo(full_name: str, private: bool = True, template: Optional[str] = None,
                cwd=None) -> tuple:
    """Create a repository, optionally generated from a template. (ok, error)."""
    args = ["repo", "create", full_name, "--private" if private else "--public"]
    if template:
        args += ["--template", template]
    try:
        proc = subprocess.run(["gh", *args], capture_output=True, text=True,
                              cwd=cwd, timeout=120)
    except FileNotFoundError:
        raise GhUnavailable(AUTH_HINT)
    if proc.returncode != 0:
        err = (proc.stderr + proc.stdout).strip()
        if template and "template" in err.lower() and "not" in err.lower():
            return False, (f"could not generate from {template}: is it marked as a "
                           f"template repository? Re-run `template` to set the flag.")
        return False, err[:200]
    return True, None


def set_template_flag(full_name: str) -> Optional[str]:
    ok, _, err = api(f"repos/{full_name}", method="PATCH", raw_fields={"is_template": "true"})
    return None if ok else err[:200]


def wait_for_content(full_name: str, timeout: int = 60) -> Optional[str]:
    """Generating from a template is asynchronous; block until a commit exists."""
    deadline = time.monotonic() + timeout
    delay = 0.5
    while time.monotonic() < deadline:
        ok, data, _ = api(f"repos/{full_name}/commits?per_page=1")
        if ok and isinstance(data, list) and data:
            return None
        time.sleep(delay)
        delay = min(delay * 1.5, 4.0)
    return f"repository created but still empty after {timeout}s; re-run to confirm"


def grant_push(full_name: str, login: str) -> Optional[str]:
    ok, _, err = api(f"repos/{full_name}/collaborators/{login}", method="PUT",
                     fields={"permission": "push"})
    return None if ok else f"could not grant push: {err[:180]}"


def put_file(full_name: str, path: str, data: bytes, message: str,
             dry_run: bool) -> str:
    """Create or update one file through the Contents API.

    Returns 'same', 'updated', 'created', 'would update' or 'would create',
    or raises RuntimeError. 'same' costs one GET and no commit, which is what
    makes `patch` idempotent.
    """
    ok, info, err = api(f"repos/{full_name}/contents/{path}")
    sha = None
    if ok and isinstance(info, dict):
        sha = info.get("sha")
        if sha == git_blob_sha(data):
            return "same"
    elif not ok and "Not Found" not in err and err.strip():
        raise RuntimeError(err.strip()[:160])
    if dry_run:
        return "would update" if sha else "would create"
    fields = {"message": message, "content": base64.b64encode(data).decode()}
    if sha:
        fields["sha"] = sha
    ok, _, err = api(f"repos/{full_name}/contents/{path}", method="PUT", fields=fields)
    if not ok:
        raise RuntimeError(err.strip()[:160])
    return "updated" if sha else "created"


def workflow_runs(full_name: str, limit: int = 5) -> List[dict]:
    ok, data, _ = api(f"repos/{full_name}/actions/runs?per_page={limit}")
    if not ok or not isinstance(data, dict):
        return []
    return data.get("workflow_runs") or []


def delete_repo(full_name: str) -> Optional[str]:
    """Only the smoke test uses this, on a repository it created itself."""
    ok, _, err = api(f"repos/{full_name}", method="DELETE")
    return None if ok else err[:200]
