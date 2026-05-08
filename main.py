"""
API entrypoint from monorepo root.

    uvicorn main:app --reload --port 8080

For legacy video analysis paths (`./models`, `./assets`), run uvicorn from `backend/`
so working directory matches those relative paths.
"""

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
_SRC = _ROOT / "backend" / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from ai_interview_analysis.api.app import app  # noqa: E402
