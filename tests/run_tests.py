#!/usr/bin/env python3
"""
Run the offline acceptance tests.

    python3 tests/run_tests.py

Needs python3, git and node on PATH, and nothing else: GitHub is replaced
by tests/fake_gh.py for the duration of the run.
"""

import shutil
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

for tool in ("git", "node"):
    if not shutil.which(tool):
        print(f"error: {tool} is not on PATH; the tests need it")
        sys.exit(2)

suite = unittest.defaultTestLoader.discover(str(HERE), pattern="test_*.py", top_level_dir=str(HERE.parent))
result = unittest.TextTestRunner(verbosity=2).run(suite)
sys.exit(0 if result.wasSuccessful() else 1)
