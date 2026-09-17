"""
out.py, how the toolkit talks.
==============================

Colour only when writing to a terminal; plain text into a pipe or the UI.
Every verb prints through these so the shape of a message is the same
everywhere: `ok`, `!!`, `--` prefixes for per-row results, PROBLEM lines in
red, and a final "Preview only" reminder when --go was not given.
"""

from __future__ import annotations

import os
import sys
import textwrap

_TTY = sys.stdout.isatty() and not os.environ.get("NO_COLOR")
BOLD, DIM, RED, YEL, GRN, OFF = (
    ("\033[1m", "\033[2m", "\033[91m", "\033[93m", "\033[92m", "\033[0m")
    if _TTY else ("", "", "", "", "", ""))


def bold(s): return f"{BOLD}{s}{OFF}"
def dim(s): return f"{DIM}{s}{OFF}"
def red(s): return f"{RED}{s}{OFF}"
def yellow(s): return f"{YEL}{s}{OFF}"
def green(s): return f"{GRN}{s}{OFF}"


def say(msg: str = "") -> None:
    print(msg, flush=True)


def problem(msg: str) -> None:
    print(f"    {red('PROBLEM')}  {msg}", flush=True)


def note(msg: str) -> None:
    print(f"    {yellow('note')}  {msg}", flush=True)


def ok_line(label: str, detail: str = "") -> None:
    print(f"  ok {label:<24} {detail}", flush=True)


def bad_line(label: str, detail: str = "") -> None:
    print(f"  !! {label:<24} {detail}", flush=True)


def skip_line(label: str, detail: str = "") -> None:
    print(f"  -- {label:<24} {detail}", flush=True)


def wrap(text: str, width: int = 74, indent: str = "      "):
    for line in textwrap.wrap(" ".join(text.split()), width) or [""]:
        print(f"{indent}{dim(line)}")


def preview_footer(command: str) -> None:
    """Printed by every preview-by-default verb when --go was absent."""
    print(f"\n{DIM}Preview only. Nothing was changed. To do it:{OFF}\n  {BOLD}{command} --go{OFF}",
          flush=True)


def header(title: str) -> None:
    print(f"{BOLD}── {title} {'─' * max(0, 64 - len(title))}{OFF}", flush=True)
