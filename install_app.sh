#!/bin/bash
# JobBot App Installer
# Run once: bash install_app.sh

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo ""
echo "╔══════════════════════════════════╗"
echo "║     JobBot App Installer         ║"
echo "╚══════════════════════════════════╝"
echo ""
echo "Installing from: $SCRIPT_DIR"
echo ""

# Install Python dependencies
echo "Installing Python dependencies..."
pip3 install fastapi uvicorn aiofiles --break-system-packages -q
echo "✅ Dependencies installed"

# Create the desktop file with correct absolute paths
cat > "$SCRIPT_DIR/JobBot.desktop" << DESKTOP
[Desktop Entry]
Version=1.0
Type=Application
Name=JobBot
Comment=Job Application Bot Dashboard
Exec=bash "$SCRIPT_DIR/start.sh"
Icon=$SCRIPT_DIR/icon.png
Terminal=false
StartupNotify=true
Categories=Utility;Network;
DESKTOP

echo "✅ Desktop file created"

# Copy to Desktop
DESKTOP_DIR="$HOME/Desktop"
mkdir -p "$DESKTOP_DIR"
cp "$SCRIPT_DIR/JobBot.desktop" "$DESKTOP_DIR/JobBot.desktop"
chmod +x "$DESKTOP_DIR/JobBot.desktop"

# Make trusted on GNOME (allows double-click without prompt)
if command -v gio &>/dev/null; then
    gio set "$DESKTOP_DIR/JobBot.desktop" metadata::trusted true 2>/dev/null || true
    echo "✅ Icon trusted on GNOME"
fi

# Also add to applications menu
APP_DIR="$HOME/.local/share/applications"
mkdir -p "$APP_DIR"
cp "$SCRIPT_DIR/JobBot.desktop" "$APP_DIR/JobBot.desktop"
echo "✅ Added to Applications menu"

# Fix start.sh to use absolute path and stay open
cat > "$SCRIPT_DIR/start.sh" << STARTSH
#!/bin/bash
cd "$SCRIPT_DIR"

# Kill any existing dashboard on port 8000
fuser -k 8000/tcp 2>/dev/null
sleep 1

# Get LAN IP
LOCAL_IP=\$(hostname -I | awk '{print \$1}')

# Start dashboard
python3 dashboard/server.py &
SERVER_PID=\$!

# Wait for server to start
sleep 2

# Show notification
notify-send "JobBot Started 🤖" "Local: http://localhost:8000\nMobile: http://\$LOCAL_IP:8000" --icon="$SCRIPT_DIR/icon.png" 2>/dev/null || true

# Open browser
xdg-open "http://localhost:8000" 2>/dev/null &

# Keep running until server stops
wait \$SERVER_PID
STARTSH
chmod +x "$SCRIPT_DIR/start.sh"
echo "✅ start.sh updated"

echo ""
echo "╔══════════════════════════════════╗"
echo "║   ✅ Installation Complete!      ║"
echo "╚══════════════════════════════════╝"
echo ""
echo "JobBot icon added to Desktop."
echo ""
echo "If double-click doesn't work:"
echo "  Right-click the icon → Allow Launching"
echo ""
echo "Or run manually:"
echo "  bash $SCRIPT_DIR/start.sh"
echo ""