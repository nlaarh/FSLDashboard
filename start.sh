#!/bin/bash
# FSLAPP Local Dev Startup
# Usage: ./start.sh          (starts both)
#        ./start.sh backend   (backend only)
#        ./start.sh frontend  (frontend only)

DIR="$(cd "$(dirname "$0")" && pwd)"
VENV="$DIR/../venv/bin"

stop_all() {
  echo "Shutting down..."
  kill $BE_PID $FE_PID 2>/dev/null
  exit 0
}
trap stop_all INT TERM

start_backend() {
  echo "Starting backend on http://localhost:8000 ..."
  cd "$DIR/backend"
  "$VENV/uvicorn" main:app --port 8000 --reload &
  BE_PID=$!
}

start_frontend() {
  echo "Starting frontend on http://localhost:5173 ..."
  cd "$DIR/frontend"
  npx vite --port 5173 &
  FE_PID=$!
}

MODE="${1:-all}"

case "$MODE" in
  backend)  start_backend ;;
  frontend) start_frontend ;;
  all|*)    start_backend; start_frontend ;;
esac

echo ""
echo "Press Ctrl+C to stop."
wait
