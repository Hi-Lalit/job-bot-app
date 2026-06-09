# Job Application Bot

Automates Easy Apply job applications on **LinkedIn**, **Naukri**, and **Indeed**.

---

## Setup (one time only)

### 1. Install Python 3.10+
Download from https://www.python.org/downloads/

### 2. Install dependencies
```bash
pip install -r requirements.txt
playwright install chromium
```

### 3. Configure your profile
```bash
cp .env.example .env
```
Open `.env` and fill in your name, phone, and login credentials.

### 4. Add your resume
Place your resume PDF at: `config/resume.pdf`

### 5. Tweak job preferences
Open `config/profile.yaml` to adjust keywords, locations, filters.
This file has NO personal details — safe to edit and push.

---

## Running the bot

```bash
# All sites
python main.py

# One site only
python main.py --site linkedin
python main.py --site naukri
python main.py --site indeed
```

---

## GitHub — what gets pushed and what doesn't

| File | Pushed? |
|---|---|
| `config/profile.yaml` | No — blocked by .gitignore |
| `.env` | No — blocked by .gitignore |
| `config/*.pdf` (resume) | No — blocked by .gitignore |
| `.env.example` | Yes — safe template |
| All Python files | Yes |
| `README.md` | Yes |

---

## Viewing applications

All applications saved in `tracker/applications.db`.
Open with [DB Browser for SQLite](https://sqlitebrowser.org/) (free).

---

## Tips

- Naukri requires manual login — bot waits 3 minutes for you to login
- Start with `max_applications_per_run: 5` to test first
- Keep `headless: false` while testing so you can watch and intervene
- Don't run more than once per day per site to avoid bans
