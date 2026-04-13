#!/usr/bin/env bash
# Start the Collig admin console (FastAPI + frontend) on port 5005
set -e

cd "$(dirname "$0")/core"

# Ensure frontend is built
if [ ! -d "../frontend/dist" ]; then
  echo "Building frontend..."
  (cd ../frontend && npm run build)
fi

echo "Starting Collig Admin Console on http://localhost:5005 ..."
echo "  Admin UI:  http://localhost:5005/admin"
echo "  API:       http://localhost:5005/api/*"
echo ""

exec uvicorn main:app --host 0.0.0.0 --port 5005 --reload
