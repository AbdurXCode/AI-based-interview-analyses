"""
Legacy entrypoint kept for compatibility.

Run with:
  uvicorn main:app --reload

The real FastAPI app lives in `src/ai_interview_analysis/api/app.py`.
"""

import sys
from pathlib import Path

# Allow running without installing the package
_ROOT = Path(__file__).resolve().parent
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from ai_interview_analysis.api.app import app
