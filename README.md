# AI Interview Preparation Platform

An end-to-end platform to **practice mock interviews** and get **AI-generated feedback** tailored to your **resume** and a target **job description**—plus a **resume analyzer** that scores match quality and suggests concrete improvements.

- **Frontend**: Next.js (App Router)
- **Backend**: FastAPI + Alembic + PostgreSQL

---

## Screenshots

Add screenshots to `docs/` and link them here.

- Mock Interview: `docs/mock-interview.png`
- Performance Report: `docs/performance-report.png`
- Resume Analyzer: `docs/resume-analyzer.png`

---

## Features

- **Mock Interview**: AI interviewer, follow-ups, topic roadmap, session history
- **Performance Report**: overall score + dimension scores + strengths/weaknesses + transcript
- **Resume Analyzer**: resume parsing + JD match analysis + coaching + bullet rewrite
- **Safety guardrails**: server-side input screening and prompt-level gates (e.g., JD validation)

---

## Project structure

```text
AI_Interview_Analysis/
  backend/              # FastAPI app, Alembic migrations, Python package
  frontend/             # Next.js App Router UI
  _archive/             # Legacy scripts/artifacts (see _archive/README.md)
  docker-compose.yml
  Dockerfile.api
  main.py
  .env.example
```

---

## Prerequisites

- **Python**: 3.10+ recommended
- **Node.js**: 18+ recommended
- **PostgreSQL**: via Docker (recommended) or local install

---

## Quickstart (Windows / PowerShell)

### 1) Start Postgres (repo root)

```powershell
docker compose up -d postgres
```

### 2) Backend (FastAPI)

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements-api.txt -e .
alembic upgrade head
uvicorn main:app --reload --port 8080
```

### 3) Frontend (Next.js)

```powershell
cd frontend
npm install
npm run dev
```

Open the app at `http://localhost:3000`.

---

## Configuration (env vars)

Copy `.env.example` to **either**:
- `backend/.env` (preferred), or
- repo-root `.env`

Common variables you’ll likely need:
- **`JWT_SECRET`**: strong random secret for auth tokens (do not commit)
- **Database**: values used by your FastAPI settings / SQLAlchemy URL
- **LLM provider keys**: whatever your `gemini_client`/provider expects

Frontend:
- **`NEXT_PUBLIC_API_URL`**: optional. If unset, the frontend uses same-origin `/api/...` and Next rewrites proxy to the backend.
  - If set, use `http://127.0.0.1:8080` (or your deployed API base URL).

---

## Running from repo root (backend only)

```powershell
pip install -r backend/requirements-api.txt -e ./backend
uvicorn main:app --reload --port 8080
```

---

## Docker

Build the API image:

```powershell
docker build -f Dockerfile.api -t interview-api .
```

---

## Tests

```powershell
cd backend
python -m pytest tests
```

---

## Notes

- **Archive**: see `_archive/README.md`. Repo-root `src/` (if present) is stale; active code lives in `backend/src/`.
- **Large model weights** under `backend/models/pretrained_models/` are **gitignored** (see that folder’s `README.md`). Use Git LFS or a download step for CI if needed.
- **PDF scratch files** may be ignored by `.gitignore`; adjust rules if you intend to commit sample PDFs.
