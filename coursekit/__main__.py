"""
Entry point: `python3 -m coursekit ...` or, through the installed shim,
`cs108 ...`. When run as a file (the shim does that), the package's parent
folder is put on sys.path so the relative imports resolve.
"""

import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from coursekit.cli import main
else:
    from .cli import main

if __name__ == "__main__":
    sys.exit(main())
