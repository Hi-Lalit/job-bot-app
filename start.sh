#!/bin/bash
cd "/home/lalit/Projects/job-bot"

# Kill any existing dashboard on port 8000
fuser -k 8000/tcp 2>/dev/null
sleep 1

# Get LAN IP
LOCAL_IP=$(hostname -I | awk '{print $1}')

# Start dashboard
python3 dashboard/server.py &
SERVER_PID=$!

# Wait for server to start
sleep 2

# Show notification
notify-send "JobBot Started 🤖" "Local: http://localhost:8000\nMobile: http://$LOCAL_IP:8000" --icon="/home/lalit/Projects/job-bot/icon.png" 2>/dev/null || true

# Open browser
xdg-open "http://localhost:8000" 2>/dev/null &

# Keep running until server stops
wait $SERVER_PID
