#!/usr/bin/env bash
# Run on EC2 from repo root after `git fetch` / `git reset --hard`.
# Mirrors the manual rollout in DEPLOYMENT.md §12.

set -e

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT/backend"

source .venv/bin/activate
pip install -r requirements-api.txt -e .
set -a
# shellcheck source=/dev/null
source .env
set +a
alembic upgrade head

cd "$ROOT/frontend"
if [ -f package-lock.json ]; then
  npm ci
else
  npm install
fi
npm run build

sudo systemctl restart interview-backend
sudo systemctl restart interview-frontend
sudo nginx -t
sudo systemctl reload nginx

echo "Deploy finished OK."
