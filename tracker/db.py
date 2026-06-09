import sqlite3
import os
from datetime import datetime
from loguru import logger

DB_PATH = "tracker/applications.db"

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
    conn.close()
    logger.info("Database ready.")

def log_application(site, job_title, company, location, job_url, status="applied", notes=""):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        INSERT INTO applications (site, job_title, company, location, job_url, status, applied_at, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (site, job_title, company, location, job_url, status, datetime.now().isoformat(), notes))
    conn.commit()
    conn.close()
    logger.success(f"[{site}] Applied → {job_title} at {company}")

def already_applied(job_url):
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute("SELECT id FROM applications WHERE job_url = ?", (job_url,)).fetchone()
    conn.close()
    return row is not None

def print_summary():
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("""
        SELECT site, COUNT(*) as total FROM applications
        GROUP BY site
    """).fetchall()
    total = conn.execute("SELECT COUNT(*) FROM applications").fetchone()[0]
    conn.close()
    print("\n========== APPLICATION SUMMARY ==========")
    for site, count in rows:
        print(f"  {site:<12} : {count} applications")
    print(f"  {'TOTAL':<12} : {total} applications")
    print("=========================================\n")
