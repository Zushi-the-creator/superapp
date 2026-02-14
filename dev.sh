#!/bin/bash
# Start local dev environment
echo "Starting dev environment..."

# Kill any old processes on these ports
lsof -ti:8000 | xargs kill -9 2>/dev/null
lsof -ti:3000 | xargs kill -9 2>/dev/null

# Backend
cd backend && uvicorn main:app --reload --port 8000 &
BACK=$!
cd ..

# Frontend
cd frontend && npx next dev -p 3000 &
FRONT=$!
cd ..

echo ""
echo "Dev ready:"
echo "  Frontend: http://localhost:3000"
echo "  Backend:  http://localhost:8000"
echo ""
echo "Press Ctrl+C to stop"
trap "kill $BACK $FRONT 2>/dev/null" EXIT
wait
