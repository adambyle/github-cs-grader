"""
roster.py, reading a roster CSV and working out what it would change.
=====================================================================

    username,first_name,last_name,email,section,github_id,role

The CLI's format (coursekit/roster.py), so existing rosters upload as they
are. `username` is the institution's identifier and the stable key: uploads
match rows by it, and repos are named after it. `github_id` is the GitHub
login, and may be blank until the student provides it.

Pure logic, no Flask and no GitHub, so every rule here is unit-tested:

    parse(data)                       bytes -> ParsedRoster (rows, problems, notes)
    normalize_login(text)             "https://github.com/x/" -> "x"
    diff(entries, parsed, mode)       what applying it would change (the preview)
    logins_to_check(preview)          which GitHub usernames need looking up

Applying a preview to the database is in routes/roster.py, which also does
the GitHub lookups.

GITHUB_ID_RE and the role names are copied from coursekit/roster.py rather
than imported: coursekit/ is the old tool, and will be removed.
"""

from __future__ import annotations

import csv
import io
import re
import unicodedata
from dataclasses import dataclass, field

FIELDS = ["username", "first_name", "last_name", "email", "section", "github_id", "role"]

# The fields an upload compares and updates. github_id is stored as github_login.
COMPARED = ["first_name", "last_name", "email", "section", "github_login", "role"]

# GitHub's own rule for logins: alphanumerics with single hyphens between,
# never at either end, at most 39 characters.
GITHUB_ID_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38}$")

ROLES = ("student", "test", "teacher", "staff")
# Roles that get invitations and repos. test rows are left out of class counts.
PARTICIPANT_ROLES = ("student", "test")

MAX_BYTES = 1_000_000
MODES = ("replace", "merge")


class RosterError(ValueError):
    """The file can't be read as a roster at all."""


@dataclass
class ParsedRoster:
    rows: list[dict] = field(default_factory=list)  # one dict per good row, with "line"
    problems: list[dict] = field(default_factory=list)  # {line, username, message}
    notes: list[str] = field(default_factory=list)

    def to_json(self) -> dict:
        return {"rows": self.rows, "problems": self.problems, "notes": self.notes}


def normalize_login(text: str) -> str:
    """A GitHub username from what people actually type: `@jsmith`,
    `github.com/jsmith/`, or a full profile URL."""
    text = (text or "").strip()
    text = re.sub(r"^https?://", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^(www\.)?github\.com/", "", text, flags=re.IGNORECASE)
    text = text.lstrip("@").strip("/")
    return text.split("/", 1)[0].split("?", 1)[0].strip()


def fold(text: str | None) -> str:
    """Lowercase with accents stripped, so Émile sorts with Emile rather than
    after Zimmerman. Only for sorting; names keep their accents."""
    decomposed = unicodedata.normalize("NFKD", text or "")
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).lower()


def sort_key(entry) -> tuple:
    """Last name, first name, username; works on dicts and RosterEntry."""
    get = entry.get if isinstance(entry, dict) else lambda k: getattr(entry, k)
    return (fold(get("last_name")), fold(get("first_name")), (get("username") or "").lower())


def display_name(row: dict) -> str:
    name = " ".join(x for x in (row.get("first_name"), row.get("last_name")) if x)
    return name or row["username"]


def _decode(data: bytes) -> tuple[str, str | None]:
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
    try:
        return data.decode("utf-8"), None
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace"), (
            "The file isn't UTF-8, so it was read as Windows-1252 (Excel's usual encoding). "
            "Check that accented names look right."
        )


def check_row(row: dict) -> str | None:
    """The problem with one row on its own, or None. Used by uploads and by
    the add/edit form."""
    if not row["username"]:
        return "no username"
    if row["role"] not in ROLES:
        return f"unknown role {row['role']!r} (use {', '.join(ROLES)})"
    if row["github_login"] and not GITHUB_ID_RE.match(row["github_login"]):
        return f"{row['github_login']!r} is not a valid GitHub username"
    return None


def clean_row(values: dict) -> dict:
    """A row with every field stripped, the role defaulted and lowercased,
    and github_id normalized into github_login."""
    row = {k: (values.get(k) or "").strip() for k in FIELDS}
    row["role"] = (row["role"] or "student").lower()
    row["github_login"] = normalize_login(row.pop("github_id"))
    return row


def parse(data: bytes) -> ParsedRoster:
    """Read a roster CSV. Raises RosterError when the file as a whole can't
    be used; problems with single rows are reported, not raised."""
    if len(data) > MAX_BYTES:
        raise RosterError("The file is over 1 MB, which is far more than any class roster.")
    text, encoding_note = _decode(data)
    out = ParsedRoster()
    if encoding_note:
        out.notes.append(encoding_note)

    reader = csv.reader(io.StringIO(text, newline=""))
    header = None
    for cells in reader:
        if any(c.strip() for c in cells):
            header = [c.strip().lower() for c in cells]
            break
    if header is None:
        raise RosterError("The file is empty.")
    if "username" not in header:
        raise RosterError(
            "The file has no username column. The first row must be the header: " + ",".join(FIELDS)
        )
    extra = [h for h in header if h and h not in FIELDS]
    if extra:
        out.notes.append("Ignored columns: " + ", ".join(extra) + ".")

    seen_users: dict[str, int] = {}
    seen_logins: dict[str, int] = {}
    blank_logins = 0
    for cells in reader:
        if not any(c.strip() for c in cells):
            continue
        line = reader.line_num
        row = clean_row(
            {name: cells[i] for i, name in enumerate(header) if name in FIELDS and i < len(cells)}
        )
        problem = check_row(row)
        key, login = row["username"].lower(), row["github_login"].lower()
        if problem is None and key in seen_users:
            problem = f"the same username as line {seen_users[key]}"
        if problem is None and login and login in seen_logins:
            problem = f"the same GitHub username as line {seen_logins[login]}"
        if problem:
            out.problems.append({"line": line, "username": row["username"], "message": problem})
            continue
        seen_users[key] = line
        if login:
            seen_logins[login] = line
        else:
            blank_logins += 1
        out.rows.append({"line": line, **row})

    if blank_logins:
        out.notes.append(
            f"{blank_logins} {'row has' if blank_logins == 1 else 'rows have'} no GitHub "
            "username yet. They're added, and listed as needing one."
        )
    return out


def entry_values(entry) -> dict:
    """A RosterEntry (or a dict like one) as the fields an upload compares."""
    if isinstance(entry, dict):
        return entry
    return {
        "username": entry.username,
        **{k: getattr(entry, k) or "" for k in COMPARED},
        "dropped": entry.dropped_at is not None,
    }


def _changes(old: dict, new: dict) -> dict:
    out = {}
    for k in COMPARED:
        before, after = old.get(k) or "", new.get(k) or ""
        # GitHub usernames aren't case-sensitive; the stored one has GitHub's
        # capitalization, which the file needn't match.
        same = before.lower() == after.lower() if k == "github_login" else before == after
        if not same:
            out[k] = [before, after]
    return out


def diff(entries, parsed: ParsedRoster, mode: str) -> dict:
    """What applying `parsed` to the current roster would do. `entries` are
    the offering's RosterEntry rows (or dicts from entry_values).

    In "replace" mode, students missing from the file are dropped; in
    "merge" mode nobody is. A row with a problem is left out, but it never
    causes its student to be dropped: a typo shouldn't remove someone.
    """
    current = {e["username"].lower(): e for e in map(entry_values, entries)}
    problems = list(parsed.problems)
    in_file = {r["username"].lower() for r in parsed.rows}
    mentioned = in_file | {p["username"].lower() for p in parsed.problems if p["username"]}

    preview: dict = {
        "mode": mode,
        "new": [],
        "changed": [],
        "returning": [],
        "dropped": [],
        "unchanged": [],
        "problems": problems,
        "notes": list(parsed.notes),
    }
    if mode == "replace":
        for key, e in current.items():
            if key not in mentioned and not e.get("dropped"):
                preview["dropped"].append({"username": e["username"], "name": display_name(e)})

    # GitHub usernames held by students who stay on the roster and aren't in
    # the file: a row can't take one of those.
    dropped_now = {d["username"].lower() for d in preview["dropped"]}
    held = {
        e["github_login"].lower(): e["username"]
        for key, e in current.items()
        if e["github_login"]
        and key not in in_file
        and key not in dropped_now
        and not e.get("dropped")
    }

    for row in parsed.rows:
        login = row["github_login"].lower()
        if login and login in held:
            problems.append(
                {
                    "line": row["line"],
                    "username": row["username"],
                    "message": f"GitHub username {row['github_login']} already belongs to "
                    f"{held[login]} on this roster",
                }
            )
            continue
        old = current.get(row["username"].lower())
        if old is None:
            preview["new"].append(row)
        elif old.get("dropped"):
            preview["returning"].append({"row": row, "changes": _changes(old, row)})
        else:
            changes = _changes(old, row)
            if changes:
                preview["changed"].append({"row": row, "changes": changes})
            else:
                preview["unchanged"].append(row["username"])
    problems.sort(key=lambda p: p["line"])
    return preview


def logins_to_check(preview: dict) -> list[str]:
    """GitHub usernames the preview needs looked up: those of new rows, and of
    changed or returning rows whose GitHub username changed. Unchanged ones
    were checked when they were saved."""
    out = [r["github_login"] for r in preview["new"] if r["github_login"]]
    for item in preview["changed"] + preview["returning"]:
        if item["row"]["github_login"] and "github_login" in item["changes"]:
            out.append(item["row"]["github_login"])
    return sorted(set(out), key=str.lower)


def csv_text(rows: list[dict]) -> str:
    """Rows (dicts with the CLI's column names) as a CSV, header first."""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=FIELDS, extrasaction="ignore", lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({k: row.get(k) or "" for k in FIELDS})
    return buf.getvalue()
