#!/usr/bin/env python3
"""
fake_gh.py, a stand-in for the gh CLI, so the toolkit can be tested offline.
============================================================================

The toolkit talks to GitHub only through `gh`. This script answers the same
commands from a folder of bare git repositories and one JSON file, so every
acceptance test in tests/ runs on a laptop with no network, no organization
and no runners, in a few seconds.

    FAKE_GH_HOME=/tmp/x   where state.json and repos/<org>/<name>.git live

The tests put a `gh` shim on PATH that execs this file, and add a git
config rewrite so `https://github.com/<org>/<name>.git` resolves to the
bare repository under FAKE_GH_HOME. Nothing in the toolkit knows the
difference, which is the point: the code under test is the real code.

WHAT IS SIMULATED
    auth status / --version
    repo view, repo create [--template]
    api: orgs/{org}, user memberships, members, invitations,
         memberships/{login} GET and PUT (invite), repos list, repo PATCH
         (is_template), commits, collaborators PUT, contents GET and PUT,
         git/trees/HEAD, actions/runs, actions/runners, DELETE repo

WHAT IS NOT
    Actions never run here. The smoke test is the one thing that must be
    tried against the real organization, which is what the spec says too.

Test hooks (state.json):
    "auto_accept": [logins]    invitations to these logins become active at once
    "runners": [...]           what orgs/{org}/actions/runners returns
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import parse_qs, urlparse

HOME = Path(os.environ.get("FAKE_GH_HOME", "/tmp/fake-gh"))
STATE = HOME / "state.json"
REPOS = HOME / "repos"


def load():
    if STATE.is_file():
        return json.loads(STATE.read_text())
    return {"login": "instructor", "orgs": {}, "auto_accept": [], "runners": []}


def save(state):
    HOME.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, indent=1))


def org_of(state, org):
    return state["orgs"].setdefault(org, {"members": [state["login"]], "pending": [], "repos": {}})


def die(msg, code=1):
    print(msg, file=sys.stderr)
    sys.exit(code)


def out(data):
    print(json.dumps(data))
    sys.exit(0)


def git(args, cwd=None):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)


def bare(org, name) -> Path:
    return REPOS / org / f"{name}.git"


def blob_sha(data: bytes) -> str:
    return hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()


def repo_json(state, org, name):
    r = org_of(state, org)["repos"][name]
    pushed = ""
    b = bare(org, name)
    if b.is_dir():
        log = git(["--git-dir", str(b), "log", "-1", "--format=%cI"])
        pushed = log.stdout.strip() if log.returncode == 0 else ""
        if pushed:
            # normalise to GitHub's Z form
            import datetime as dt
            try:
                pushed = dt.datetime.fromisoformat(pushed).astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            except ValueError:
                pass
    return {"name": name, "private": r.get("private", True), "is_template": r.get("is_template", False),
            "pushed_at": pushed, "updated_at": pushed, "html_url": f"https://github.com/{org}/{name}"}


def has_commits(org, name) -> bool:
    b = bare(org, name)
    return b.is_dir() and git(["--git-dir", str(b), "rev-parse", "HEAD"]).returncode == 0


def tree(org, name):
    if not has_commits(org, name):
        return []
    ls = git(["--git-dir", str(bare(org, name)), "ls-tree", "-r", "HEAD"])
    items = []
    for line in ls.stdout.splitlines():
        meta, path = line.split("\t", 1)
        _, typ, sha = meta.split()
        items.append({"path": path, "type": typ, "sha": sha})
    return items


def contents_get(org, name, path):
    for item in tree(org, name):
        if item["path"] == path:
            data = git(["--git-dir", str(bare(org, name)), "cat-file", "-p", item["sha"]])
            return {"sha": item["sha"], "path": path, "type": "file",
                    "content": base64.b64encode(data.stdout.encode()).decode()}
    return None


def contents_put(org, name, path, fields):
    data = base64.b64decode(fields.get("content", ""))
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / "w"
        if has_commits(org, name):
            r = git(["clone", "-q", str(bare(org, name)), str(work)])
            if r.returncode != 0:
                die(r.stderr)
        else:
            work.mkdir()
            git(["init", "-q", "-b", "main"], cwd=work)
            git(["remote", "add", "origin", str(bare(org, name))], cwd=work)
        dest = work / path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        git(["add", "-A"], cwd=work)
        r = git(["-c", "user.name=fake-gh", "-c", "user.email=fake@gh", "commit", "-q", "-m",
                 fields.get("message", "update")], cwd=work)
        if r.returncode != 0:
            die(r.stderr)
        r = git(["push", "-q", "origin", "HEAD:main"], cwd=work)
        if r.returncode != 0:
            die(r.stderr)
    return {"content": {"sha": blob_sha(data), "path": path}}


def api(args, state):
    method = "GET"
    fields, path = {}, None
    paginate = False
    i = 0
    while i < len(args):
        a = args[i]
        if a in ("--method", "-X"):
            method = args[i + 1]; i += 2
        elif a in ("-f", "-F"):
            k, v = args[i + 1].split("=", 1); fields[k] = v; i += 2
        elif a == "--paginate":
            paginate = True; i += 1
        elif a == "--slurp":
            i += 1
        elif a.startswith("--jq"):
            i += 2
        elif path is None:
            path = a; i += 1
        else:
            i += 1
    if path is None:
        die("gh: no path")
    parsed = urlparse(path)
    parts = parsed.path.strip("/").split("/")
    qs = parse_qs(parsed.query)

    def paged(items):
        out([items] if paginate else items)

    if parts[0] == "user" and parts[1:3] == ["memberships", "orgs"]:
        org_of(state, parts[3])
        out({"role": "admin", "state": "active"})
    if parts[0] == "orgs":
        org = parts[1]
        o = org_of(state, org)
        if len(parts) == 2:
            out({"login": org, "id": 1})
        sub = parts[2]
        if sub == "members":
            paged([{"login": m} for m in o["members"]])
        if sub == "invitations":
            paged([{"login": p, "email": "", "created_at": "2026-09-01T00:00:00Z"} for p in o["pending"]])
        if sub == "memberships":
            login = parts[3]
            if method == "PUT":
                if login.startswith("nosuch"):
                    die("gh: Not Found (HTTP 404)")
                if login in o["members"]:
                    st = "active"
                elif login in state.get("auto_accept", []):
                    o["members"].append(login); st = "active"
                else:
                    if login not in o["pending"]:
                        o["pending"].append(login)
                    st = "pending"
                save(state)
                out({"state": st, "role": "member"})
            if login in o["members"]:
                out({"state": "active", "role": "member"})
            if login in o["pending"]:
                out({"state": "pending", "role": "member"})
            die("gh: Not Found (HTTP 404)")
        if sub == "repos":
            paged([repo_json(state, org, n) for n in sorted(o["repos"])])
        if sub == "actions" and parts[3] == "runners":
            out({"total_count": len(state.get("runners", [])), "runners": state.get("runners", [])})
        die(f"gh: unsupported org path {path}")
    if parts[0] == "repos":
        org, name = parts[1], parts[2]
        o = org_of(state, org)
        if name not in o["repos"]:
            die("gh: Not Found (HTTP 404)")
        if len(parts) == 3:
            if method == "PATCH":
                if "is_template" in fields:
                    o["repos"][name]["is_template"] = fields["is_template"] == "true"
                save(state)
                out(repo_json(state, org, name))
            if method == "DELETE":
                del o["repos"][name]
                shutil.rmtree(bare(org, name), ignore_errors=True)
                save(state)
                out({})
            out(repo_json(state, org, name))
        sub = parts[3]
        if sub == "commits":
            if not has_commits(org, name):
                out([])
            log = git(["--git-dir", str(bare(org, name)), "log", "-1", "--format=%H"])
            out([{"sha": log.stdout.strip()}])
        if sub == "collaborators":
            o["repos"][name].setdefault("collaborators", []).append(parts[4])
            save(state)
            out({})
        if sub == "contents":
            rel = "/".join(parts[4:])
            if method == "PUT":
                out(contents_put(org, name, rel, fields))
            found = contents_get(org, name, rel)
            if found is None:
                die("gh: Not Found (HTTP 404)")
            out(found)
        if sub == "git" and parts[4] == "trees":
            out({"sha": "HEAD", "tree": tree(org, name)})
        if sub == "actions" and parts[4] == "runs":
            out({"total_count": 0, "workflow_runs": []})
        die(f"gh: unsupported repo path {path}")
    die(f"gh: unsupported path {path}")


def repo(args, state):
    sub = args[0]
    if sub == "view":
        full = args[1]
        org, name = full.split("/", 1)
        if name in org_of(state, org)["repos"]:
            out({"name": name})
        die("GraphQL: Could not resolve to a Repository (HTTP 404)")
    if sub == "create":
        full = args[1]
        org, name = full.split("/", 1)
        o = org_of(state, org)
        if name in o["repos"]:
            die(f"gh: Name already exists on this account (HTTP 422)")
        template = None
        if "--template" in args:
            template = args[args.index("--template") + 1]
            torg, tname = template.split("/", 1)
            if tname not in org_of(state, torg)["repos"]:
                die("gh: template repository not found")
            if not org_of(state, torg)["repos"][tname].get("is_template"):
                die("gh: the source repository is not a template repository")
        dest = bare(org, name)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if template:
            # GitHub generates an independent copy; a bare clone with the
            # history squashed is close enough for the tools' purposes.
            with tempfile.TemporaryDirectory() as tmp:
                work = Path(tmp) / "w"
                git(["clone", "-q", str(bare(torg, tname)), str(work)])
                shutil.rmtree(work / ".git")
                git(["init", "-q", "-b", "main"], cwd=work)
                git(["add", "-A"], cwd=work)
                git(["-c", "user.name=fake-gh", "-c", "user.email=fake@gh", "commit", "-q", "-m",
                     "Initial commit"], cwd=work)
                git(["init", "-q", "--bare", "-b", "main", str(dest)])
                git(["push", "-q", str(dest), "HEAD:main"], cwd=work)
        else:
            git(["init", "-q", "--bare", "-b", "main", str(dest)])
        o["repos"][name] = {"private": "--private" in args, "is_template": False}
        save(state)
        print(f"https://github.com/{full}")
        sys.exit(0)
    die(f"gh: unsupported repo subcommand {sub}")


def main():
    args = sys.argv[1:]
    state = load()
    if not args:
        die("gh: no command")
    if args[0] == "--version":
        print("gh version 2.62.0 (2026-01-01)")
        sys.exit(0)
    if args[0] == "auth":
        if os.environ.get("FAKE_GH_UNAUTH"):
            print("You are not logged into any GitHub hosts. To log in, run: gh auth login", file=sys.stderr)
            sys.exit(1)
        print(f"github.com\n  ✓ Logged in to github.com account {state['login']} (keyring)")
        sys.exit(0)
    if args[0] == "api":
        api(args[1:], state)
    if args[0] == "repo":
        repo(args[1:], state)
    die(f"gh: unsupported command {args[0]}")


if __name__ == "__main__":
    main()
