# Backend (FastAPI)

| Path | Role |
|------|------|
| `src/ai_interview_analysis/` | Application package |
| `src/ai_interview_analysis/video/` | Gaze, body language, speaking-from-video (mounted when `FEATURE_VIDEO_ANALYSIS=1`) |
| `main.py` | Uvicorn target: `main:app` |
| `requirements-api.txt` | Production API deps (no TensorFlow video stack) |
| `requirements-legacy-ml.txt` | Full pins for gaze/body/video (optional) |
| `alembic/` | DB migrations |

From **this directory**:

```powershell
pip install -r requirements-api.txt -e .
uvicorn main:app --reload --port 8080
```

From the **monorepo root**, install the editable package then use the repo-level `main.py`:

```powershell
pip install -r backend/requirements-api.txt -e ./backend
uvicorn main:app --reload --port 8080
```

Put `.env` in **`backend/`** or at the repo root (both are supported).

**Legacy video analysis:** relative paths `./models/` expect the process cwd to be this `backend/` folder—run uvicorn from here when `FEATURE_VIDEO_ANALYSIS=1`.
