#!/usr/bin/env bash
# start.sh — starts the PasteWise Python backend
# Usage: ./start.sh [--port 8000] [--reload]

set -e

PORT=${PORT:-8000}
RELOAD_FLAG=""

# Parse optional --reload flag
for arg in "$@"; do
  case $arg in
    --reload) RELOAD_FLAG="--reload" ;;
    --port=*) PORT="${arg#*=}" ;;
  esac
done

# Ensure we're in the right directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$SCRIPT_DIR/backend"

if [ ! -d "$BACKEND_DIR" ]; then
  echo "ERROR: backend/ directory not found next to start.sh"
  exit 1
fi

# Check .env exists
if [ ! -f "$BACKEND_DIR/.env" ]; then
  echo "WARNING: backend/.env not found."
  echo "         Copy backend/.env.example to backend/.env and add your GEMINI_API_KEY."
  echo ""
fi

# Activate virtual environment if one exists
VENV="$SCRIPT_DIR/venv"
if [ -d "$VENV" ]; then
  source "$VENV/bin/activate"
  echo "Virtual environment activated: $VENV"
fi

echo ""
echo "  PasteWise backend"
echo "  ─────────────────"
echo "  URL  : http://localhost:$PORT"
echo "  DB   : $BACKEND_DIR/pastewise.db"
echo "  Docs : http://localhost:$PORT/docs"
echo ""

cd "$BACKEND_DIR"
exec uvicorn main:app --host 127.0.0.1 --port "$PORT" $RELOAD_FLAG