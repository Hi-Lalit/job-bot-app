#!/bin/bash
# Run this on your EC2 server after uploading the project
# Usage: bash setup_server.sh

echo "Setting up Job Bot on server..."

# Update system
sudo apt-get update -y
sudo apt-get install -y python3 python3-pip screen

# Install dependencies
pip3 install -r requirements.txt --break-system-packages

# Install Playwright browser
python3 -m playwright install chromium
python3 -m playwright install-deps chromium

# Create required folders
mkdir -p logs sessions tracker

echo ""
echo "Setup complete!"
echo ""
echo "Next steps:"
echo "  1. Add your .env file: nano .env"
echo "  2. Upload sessions: copy sessions/ folder from laptop"
echo "  3. Start dashboard: screen -S jobbot python3 dashboard/server.py"
echo "  4. Open on phone: http://$(curl -s ifconfig.me):8000"
echo ""
