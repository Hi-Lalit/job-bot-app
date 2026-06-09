"""
Job Bot Web Dashboard — FastAPI Server
Run:   python dashboard/server.py
Open:  http://localhost:8000
Phone: http://YOUR_LAN_IP:8000  (same WiFi)
"""

import asyncio
import subprocess
import sqlite3
import os
import sys
from datetime import datetime
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

# Add project root to path
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

DB_PATH  = os.path.join(ROOT, "tracker", "applications.db")
LOG_DIR  = os.path.join(ROOT, "logs")

# Debug — print resolved paths on startup
print(f"[server] ROOT    = {ROOT}")
print(f"[server] LOG_DIR = {LOG_DIR}")
print(f"[server] DB_PATH = {DB_PATH}")

bot_process = None
bot_status  = "idle"


# ── DB helpers ──────────────────────────────────────────────────────────────

def get_stats():
    if not os.path.exists(DB_PATH):
        return {"total": 0, "today": 0, "week": 0, "by_site": [], "recent": [], "daily": []}
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    try:
        total = conn.execute("SELECT COUNT(*) FROM applications").fetchone()[0]

        today = conn.execute(
            "SELECT COUNT(*) FROM applications WHERE applied_at LIKE ?",
            (datetime.now().strftime("%Y-%m-%d") + "%",)
        ).fetchone()[0]

        week = conn.execute(
            "SELECT COUNT(*) FROM applications WHERE applied_at >= date('now', '-7 days')"
        ).fetchone()[0]

        by_site = conn.execute(
            "SELECT site, COUNT(*) as count FROM applications GROUP BY site ORDER BY count DESC"
        ).fetchall()

        recent = conn.execute(
            "SELECT site, job_title, company, location, status, applied_at "
            "FROM applications ORDER BY applied_at DESC LIMIT 100"
        ).fetchall()

        daily = conn.execute(
            "SELECT date(applied_at) as day, COUNT(*) as count "
            "FROM applications "
            "WHERE applied_at >= date('now', '-14 days') "
            "GROUP BY day ORDER BY day"
        ).fetchall()

        datewise = conn.execute(
            "SELECT date(applied_at) as day, site, COUNT(*) as count "
            "FROM applications "
            "GROUP BY day, site ORDER BY day DESC"
        ).fetchall()

        datewise_map = {}
        for r in datewise:
            d = r["day"] or "Unknown"
            if d not in datewise_map:
                datewise_map[d] = {"day": d, "total": 0, "sites": {}}
            datewise_map[d]["sites"][r["site"]] = r["count"]
            datewise_map[d]["total"] += r["count"]

        datewise_list = sorted(datewise_map.values(), key=lambda x: x["day"], reverse=True)

    finally:
        conn.close()

    return {
        "total": total,
        "today": today,
        "week": week,
        "by_site": [{"site": r["site"], "count": r["count"]} for r in by_site],
        "recent":  [dict(r) for r in recent],
        "daily":   [{"day": r["day"], "count": r["count"]} for r in daily],
        "datewise": datewise_list,
    }


def get_log_dates():
    if not os.path.exists(LOG_DIR):
        return []
    dates = []
    for f in os.listdir(LOG_DIR):
        if f.startswith("bot_") and f.endswith(".log"):
            date = f.replace("bot_", "").replace(".log", "")
            dates.append(date)
    return sorted(dates, reverse=True)


def get_logs(lines=200, date=None):
    if not os.path.exists(LOG_DIR):
        return []
    
    if date:
        log_file = os.path.join(LOG_DIR, f"bot_{date}.log")
    else:
        today = datetime.now().strftime("%Y-%m-%d")
        log_file = os.path.join(LOG_DIR, f"bot_{today}.log")
        
    if not os.path.exists(log_file):
        return [f"No log file found for {date or 'today'}"]
        
    if os.path.getsize(log_file) == 0:
        return [f"Log file for {date or 'today'} is empty (bot may not have run that day)"]
        
    with open(log_file, "r", errors="replace") as f:
        all_lines = f.readlines()
        
    result = [l.rstrip() for l in all_lines if l.strip()]
    return result[-lines:] if result else [f"No log entries found for {date or 'today'}"]


# ── Bot control ─────────────────────────────────────────────────────────────

@app.post("/api/start")
async def start_bot(request: Request):
    global bot_process, bot_status

    if bot_process and bot_process.poll() is None:
        bot_status = "running"
        return JSONResponse({"status": "already_running", "pid": bot_process.pid})

    payload = await request.json()
    site    = payload.get("site", "naukri")
    cmd     = [sys.executable, os.path.join(ROOT, "main.py"), "--site", site]

    try:
        bot_process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            cwd=ROOT,
            bufsize=1
        )
        bot_status = "running"
        return JSONResponse({"status": "started", "site": site, "pid": bot_process.pid})
    except Exception as e:
        bot_status = "idle"
        return JSONResponse({"status": "error", "message": str(e)})


@app.post("/api/stop")
async def stop_bot():
    global bot_process, bot_status
    if bot_process and bot_process.poll() is None:
        bot_process.terminate()
        try:
            bot_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            bot_process.kill()
    bot_status = "idle"
    bot_process = None
    return JSONResponse({"status": "stopped"})


@app.get("/api/status")
async def get_status():
    global bot_process, bot_status
    
    # Check if process died or completed on its own
    if bot_process and bot_process.poll() is not None:
        bot_status = "idle"
        bot_process = None
        
    if bot_process is None:
        bot_status = "idle"
    else:
        bot_status = "running"
        
    return JSONResponse({
        "status": bot_status, 
        "pid": bot_process.pid if bot_process else None  # Fixed potential NoneType crash
    })


@app.get("/api/stats")
async def stats():
    return JSONResponse(get_stats())


@app.get("/api/logs")
async def logs(date: str = None):
    return JSONResponse({
        "lines": get_logs(date=date),
        "dates": get_log_dates(),
        "current": date or datetime.now().strftime("%Y-%m-%d")
    })


@app.delete("/api/clear")
async def clear_db():
    if os.path.exists(DB_PATH):
        conn = sqlite3.connect(DB_PATH)
        try:
            conn.execute("DELETE FROM applications")
            conn.commit()
        finally:
            conn.close()
    return JSONResponse({"status": "cleared"})


# ── Serve dashboard ──────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def dashboard():
    html_path = os.path.join(os.path.dirname(__file__), "index.html")
    with open(html_path) as f:
        return f.read()


if __name__ == "__main__":
    PORT = 8000  # <--- Change this number here if port 8000 is persistently busy!

    try:
        lan_ip = subprocess.check_output(
            "hostname -I | awk '{print $1}'", shell=True
        ).decode().strip()
    except Exception:
        lan_ip = "unknown"

    log_dates = get_log_dates()
    print(f"\n{'='*52}")
    print(f"  Job Bot Dashboard")
    print(f"  Local  → http://localhost:{PORT}")
    print(f"  Mobile → http://{lan_ip}:{PORT}  (same WiFi)")
    print(f"  Log dir: {LOG_DIR}")
    print(f"  Logs found: {log_dates if log_dates else 'NONE — check logs/ folder'}")
    print(f"{'='*52}\n")
    
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="warning")