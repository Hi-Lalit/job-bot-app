"""
Run this ONCE to save your login session for each site.
After that, main.py will reuse the saved session and run fully headless.

Usage:
    python3 save_session.py --site naukri
    python3 save_session.py --site linkedin
    python3 save_session.py --site indeed
"""

import asyncio
import argparse
import os
from playwright.async_api import async_playwright
from playwright_stealth import stealth_async
from loguru import logger

SESSIONS_DIR = "sessions"

async def save_session(site):
    os.makedirs(SESSIONS_DIR, exist_ok=True)
    session_path = f"{SESSIONS_DIR}/{site}_session.json"

    urls = {
        "naukri":   "https://www.naukri.com/nlogin/login",
        "linkedin":  "https://www.linkedin.com/login",
        "indeed":    "https://in.indeed.com/account/login",
    }

    success_urls = {
        "naukri":   ["mnjuser", "homepage"],
        "linkedin":  ["feed", "mynetwork", "jobs"],
        "indeed":    ["indeed.com/jobs", "indeed.com/?"],
    }

    pw = await async_playwright().start()
    browser = await pw.chromium.launch(
        headless=False,
        args=["--start-maximized", "--window-size=1920,1080"]
    )
    context = await browser.new_context(
        viewport={"width": 1920, "height": 1080},
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
    page = await context.new_page()
    await stealth_async(page)

    await page.goto(urls[site], wait_until="domcontentloaded")

    logger.warning("=" * 55)
    logger.warning(f"Please LOGIN to {site.title()} manually.")
    logger.warning("Session will be saved automatically after login.")
    logger.warning("You have 3 minutes.")
    logger.warning("=" * 55)

    # Wait for successful login
    for i in range(36):
        await asyncio.sleep(5)
        current_url = page.url
        if any(s in current_url for s in success_urls[site]):
            logger.success(f"Login detected! Saving session...")
            await asyncio.sleep(2)
            # Save cookies + storage
            storage = await context.storage_state(path=session_path)
            logger.success(f"Session saved to {session_path}")
            logger.info("You can now run main.py with headless: true")
            break
        if i % 6 == 0 and i > 0:
            logger.info(f"Waiting for login... ({(36-i)*5}s remaining)")
    else:
        logger.error("Login timeout — session not saved.")

    await browser.close()
    await pw.stop()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--site", choices=["naukri", "linkedin", "indeed", "all"], required=True)
    args = parser.parse_args()

    sites = ["naukri", "linkedin", "indeed"] if args.site == "all" else [args.site]
    for site in sites:
        logger.info(f"Saving session for {site}...")
        asyncio.run(save_session(site))

if __name__ == "__main__":
    main()
