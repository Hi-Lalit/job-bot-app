"""
Import old log files into the database.
Run: python3 import_logs.py
"""
import re
import os
import sqlite3
from datetime import datetime
from loguru import logger

LOG_DIR = "logs"
DB_PATH = "tracker/applications.db"

# Pattern to match SUCCESS log lines like:
# 2026-05-18 18:26:02 | SUCCESS | tracker.db:log_application:36 - [Naukri] Applied → DevOps Engineer at Company
# 2026-05-18 18:26:02 | SUCCESS | scrapers.naukri:run_naukri:374 - [1/100] Applied → DevOps Engineer

PATTERN_TRACKER = re.compile(
    r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})"   # timestamp
    r".*?\[(\w+)\] Applied → (.+?) at (.+)"       # site, title, company
)
PATTERN_SCRAPER = re.compile(
    r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})"    # timestamp
    r".*?Applied → (.+)"                           # title
)
PATTERN_URL = re.compile(r"URL\s*:\s*(https?://\S+)")
PATTERN_COMPANY = re.compile(r"Company\s*:\s*(.+)")
PATTERN_LOCATION = re.compile(r"Location\s*:\s*(.+)")

def init_db():
    os.makedirs("tracker", exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS applications (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            site        TEXT NOT NULL,
            job_title   TEXT,
            company     TEXT,
            location    TEXT,
            job_url     TEXT,
            status      TEXT DEFAULT 'applied',
            applied_at  TEXT,
            notes       TEXT
        )
    """)
    conn.commit()
    return conn

def already_exists(conn, job_url):
    if not job_url:
        return False
    row = conn.execute("SELECT id FROM applications WHERE job_url = ?", (job_url,)).fetchone()
    return row is not None

def import_log_file(conn, log_path, date_str):
    imported = 0
    skipped  = 0

    with open(log_path, "r", errors="replace") as f:
        lines = f.readlines()

    i = 0
    while i < len(lines):
        line = lines[i].strip()

        # Match tracker.db SUCCESS line — most reliable
        m = PATTERN_TRACKER.search(line)
        if m and "SUCCESS" in line and "tracker.db" in line:
            timestamp = m.group(1)
            site      = m.group(2)
            title     = m.group(3).strip()
            company   = m.group(4).strip()

            # Look ahead for URL and location
            job_url  = ""
            location = "Unknown"
            for j in range(i+1, min(i+5, len(lines))):
                url_m = PATTERN_URL.search(lines[j])
                loc_m = PATTERN_LOCATION.search(lines[j])
                if url_m:
                    job_url = url_m.group(1).strip()
                if loc_m:
                    location = loc_m.group(1).strip()

            if already_exists(conn, job_url):
                skipped += 1
            else:
                conn.execute("""
                    INSERT INTO applications
                    (site, job_title, company, location, job_url, status, applied_at, notes)
                    VALUES (?, ?, ?, ?, ?, 'applied', ?, 'imported from log')
                """, (site, title, company, location, job_url, timestamp))
                imported += 1

        i += 1

    conn.commit()
    return imported, skipped

def main():
    if not os.path.exists(LOG_DIR):
        logger.error(f"Logs folder not found: {LOG_DIR}")
        return

    conn = init_db()
    total_imported = 0
    total_skipped  = 0

    log_files = sorted([
        f for f in os.listdir(LOG_DIR)
        if f.startswith("bot_") and f.endswith(".log")
    ])

    logger.info(f"Found {len(log_files)} log files: {log_files}")

    for fname in log_files:
        date_str = fname.replace("bot_", "").replace(".log", "")
        log_path = os.path.join(LOG_DIR, fname)
        size     = os.path.getsize(log_path)

        logger.info(f"Processing {fname} ({size} bytes)...")
        imp, skip = import_log_file(conn, log_path, date_str)
        logger.success(f"  → Imported: {imp}, Skipped (already in DB): {skip}")
        total_imported += imp
        total_skipped  += skip

    conn.close()
    logger.success(f"\nDone! Total imported: {total_imported}, Total skipped: {total_skipped}")
    logger.info("Restart the dashboard to see updated data.")

if __name__ == "__main__":
    main()