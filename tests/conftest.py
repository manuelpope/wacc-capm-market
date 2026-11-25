"""The tests never read the env file of the repository.

The app loads that file when it starts, so the variable that points at it is
set to a path that does not exist before the app is imported. The tests that
need a file of their own point it somewhere else.
"""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault(
    "WACC_LAB_ENV_FILE", str(Path(__file__).resolve().parent / "no-such-env-file")
)
