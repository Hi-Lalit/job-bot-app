# Deploy Job Bot to AWS EC2 (Free for 1 year)

## Step 1 — Create AWS Account
1. Go to https://aws.amazon.com/free
2. Create account (needs credit card but won't charge for free tier)
3. Go to EC2 → Launch Instance

## Step 2 — Launch EC2 Instance
- Name: job-bot
- OS: Ubuntu 22.04 LTS
- Instance type: t2.micro (FREE TIER)
- Create new key pair → download .pem file → save it safely
- Security group: Allow SSH (22), HTTP (8000) from anywhere

## Step 3 — Connect to server
```bash
# On your laptop (one time setup)
chmod 400 your-key.pem
ssh -i your-key.pem ubuntu@YOUR_EC2_IP
```

## Step 4 — Install everything on server
```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install Python
sudo apt install python3 python3-pip -y

# Install Chromium for Playwright (headless)
sudo apt install chromium-browser -y

# Upload your project
# On your laptop:
scp -i your-key.pem -r job-bot/ ubuntu@YOUR_EC2_IP:~/
```

## Step 5 — Setup on server
```bash
cd ~/job-bot
pip3 install -r requirements.txt
playwright install chromium
playwright install-deps

# Copy your .env file
nano .env   # paste your credentials
```

## Step 6 — Run dashboard permanently
```bash
# Install screen (keeps bot running after you disconnect)
sudo apt install screen -y

# Start dashboard in background
screen -S jobbot
python3 dashboard/server.py

# Detach: press Ctrl+A then D
# Reattach anytime: screen -r jobbot
```

## Step 7 — Access from phone
Open browser on phone:
http://YOUR_EC2_IP:8000

Bookmark it. Works from anywhere in the world!

## Important notes
- Set headless: true in profile.yaml (no screen on server)
- Naukri/LinkedIn login: use save_session.py first on laptop,
  then upload sessions/ folder to server
- EC2 free tier: 750 hours/month = runs 24/7 free for 1 year
