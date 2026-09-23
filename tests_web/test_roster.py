"""The roster CSV rules (webapp/roster.py): no Flask, no GitHub."""

from pathlib import Path

import pytest

from webapp import roster as r

EXAMPLE = Path(__file__).resolve().parents[1] / "examples/sample-course/roster/roster.csv"
HEADER = "username,first_name,last_name,email,section,github_id,role\n"


def parse(text: str, encoding="utf-8") -> r.ParsedRoster:
    return r.parse(text.encode(encoding))


def test_the_example_roster_parses_cleanly():
    parsed = r.parse(EXAMPLE.read_bytes())
    assert [row["username"] for row in parsed.rows] == ["jsmith", "testacct"]
    assert parsed.rows[1]["role"] == "test"
    assert parsed.problems == []


@pytest.mark.parametrize(
    "typed, login",
    [
        ("jsmith", "jsmith"),
        ("@jsmith", "jsmith"),
        ("https://github.com/jsmith", "jsmith"),
        ("github.com/jsmith/", "jsmith"),
        ("HTTPS://www.GitHub.com/JSmith?tab=repositories", "JSmith"),
        ("  jsmith  ", "jsmith"),
        ("", ""),
    ],
)
def test_normalize_login(typed, login):
    assert r.normalize_login(typed) == login


def test_header_case_extra_columns_bom_and_blank_lines():
    text = "﻿UserName,GitHub_ID,Notes\n\njsmith,@jsmith,hi\n\n"
    parsed = parse(text)
    assert parsed.rows[0]["username"] == "jsmith"
    assert parsed.rows[0]["github_login"] == "jsmith"
    assert parsed.rows[0]["role"] == "student"
    assert any("Ignored columns: notes" in n for n in parsed.notes)


def test_windows_1252_fallback_keeps_accents():
    parsed = parse(HEADER + "eb,Émile,Brontë,,,,\n", encoding="cp1252")
    assert parsed.rows[0]["first_name"] == "Émile"
    assert any("Windows-1252" in n for n in parsed.notes)


def test_missing_username_column_and_empty_file_and_size():
    with pytest.raises(r.RosterError, match="no username column"):
        parse("name,email\nx,y\n")
    with pytest.raises(r.RosterError, match="empty"):
        parse("\n\n")
    with pytest.raises(r.RosterError, match="1 MB"):
        r.parse(b"x" * (r.MAX_BYTES + 1))


def test_row_problems_are_reported_with_line_numbers():
    text = HEADER + (
        "a,,,,,alpha,\n"  # line 2: fine
        ",,,,,,\n"  # blank row: skipped silently
        ",Ann,,,,,\n"  # line 4: no username
        "A,,,,,,\n"  # line 5: same username, other case
        "b,,,,,ALPHA,\n"  # line 6: same login, other case
        "c,,,,,bad_login,\n"  # line 7: invalid login
        "d,,,,,,wizard\n"  # line 8: unknown role
        "e,,,,,,\n"  # line 9: blank login is fine
    )
    parsed = parse(text)
    assert [row["username"] for row in parsed.rows] == ["a", "e"]
    problems = {p["line"]: p["message"] for p in parsed.problems}
    assert problems[4] == "no username"
    assert problems[5] == "the same username as line 2"
    assert problems[6] == "the same GitHub username as line 2"
    assert "not a valid GitHub username" in problems[7]
    assert "unknown role" in problems[8]
    assert any("1 row has no GitHub username" in n for n in parsed.notes)


def entry(username, dropped=False, **fields):
    base = {k: "" for k in r.COMPARED}
    base["role"] = "student"
    return {"username": username, **base, **fields, "dropped": dropped}


def test_diff_replace_mode():
    entries = [
        entry("keep", github_login="Keep-GH"),
        entry("edit", first_name="Old"),
        entry("gone"),
        entry("back", dropped=True),
        entry("oops"),
    ]
    text = HEADER + (
        "keep,,,,,keep-gh,\n"  # only the login's case differs: unchanged
        "edit,New,,,,,\n"
        "back,,,,,,\n"
        "new,,,,,newbie,\n"
        "oops,,,,,not_valid,\n"  # a problem row: not dropped for it
    )
    p = r.diff(entries, parse(text), "replace")
    assert p["unchanged"] == ["keep"]
    assert p["changed"] == [
        {"row": p["changed"][0]["row"], "changes": {"first_name": ["Old", "New"]}}
    ]
    assert [x["row"]["username"] for x in p["returning"]] == ["back"]
    assert [x["username"] for x in p["new"]] == ["new"]
    assert [d["username"] for d in p["dropped"]] == ["gone"]
    assert r.logins_to_check(p) == ["newbie"]


def test_diff_merge_mode_drops_nobody():
    p = r.diff([entry("gone")], parse(HEADER + "new,,,,,,\n"), "merge")
    assert p["dropped"] == []
    assert len(p["new"]) == 1


def test_a_row_cannot_take_a_login_someone_else_keeps():
    entries = [entry("owner", github_login="shared")]
    p = r.diff(entries, parse(HEADER + "thief,,,,,Shared,\n"), "merge")
    assert p["new"] == []
    assert "already belongs to owner" in p["problems"][0]["message"]
    # In replace mode the owner is dropped by the same upload, so it's free.
    p = r.diff(entries, parse(HEADER + "thief,,,,,Shared,\n"), "replace")
    assert [x["username"] for x in p["new"]] == ["thief"]


def test_changed_login_is_looked_up():
    p = r.diff([entry("a", github_login="old")], parse(HEADER + "a,,,,,new,\n"), "merge")
    assert p["changed"][0]["changes"] == {"github_login": ["old", "new"]}
    assert r.logins_to_check(p) == ["new"]


def test_csv_round_trip():
    rows = [{"username": "a", "first_name": "Ann", "github_id": "ann-gh", "role": "test"}]
    parsed = parse(r.csv_text(rows))
    assert parsed.rows[0]["github_login"] == "ann-gh"
    assert parsed.rows[0]["role"] == "test"


def test_sort_by_last_name_folding_accents():
    rows = [
        {"username": "z", "first_name": "", "last_name": "Zimmerman"},
        {"username": "e", "first_name": "", "last_name": "Émile"},
        {"username": "a", "first_name": "", "last_name": "Adams"},
    ]
    assert [x["username"] for x in sorted(rows, key=r.sort_key)] == ["a", "e", "z"]
