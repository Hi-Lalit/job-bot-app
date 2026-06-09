#!/bin/bash
# Run this to open the dashboard
# Usage: ./start_dashboard.sh
cd "$(dirname "$0")"
echo ""
echo "Starting Job Bot Dashboard..."
echo "Open http://localhost:8000 in your browser"
echo "Press Ctrl+C to stop"
echo ""
python3 dashboard/server.py
