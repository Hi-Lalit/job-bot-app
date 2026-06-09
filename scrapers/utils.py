import yaml
import random
import asyncio
import os
from loguru import logger
from dotenv import load_dotenv
from playwright.async_api import async_playwright
from playwright_stealth import stealth_async

load_dotenv()

CONFIG_PATH = "config/profile.yaml"

# Shared elements — using persistent context framework
_pw      = None
_context = None  # Persistent context acts as both browser and context layers


def load_config():
    with open(CONFIG_PATH, "r") as f:
        config = yaml.safe_load(f)

    config["personal"]["full_name"]    = os.getenv("FULL_NAME", "")
    config["personal"]["phone"]        = os.getenv("PHONE", "")
    config["personal"]["email"]        = os.getenv("EMAIL", "")
    config["personal"]["linkedin_url"] = os.getenv("LINKEDIN_URL", "")
    config["personal"]["portfolio_url"]= os.getenv("PORTFOLIO_URL", "")

    config["credentials"]["linkedin"]["email"]    = os.getenv("LINKEDIN_EMAIL", "")
    config["credentials"]["linkedin"]["password"] = os.getenv("LINKEDIN_PASSWORD", "")
    config["credentials"]["naukri"]["email"]      = os.getenv("NAUKRI_EMAIL", "")
    config["credentials"]["naukri"]["password"]   = os.getenv("NAUKRI_PASSWORD", "")
    config["credentials"]["indeed"]["email"]      = os.getenv("INDEED_EMAIL", "")
    config["credentials"]["indeed"]["password"]   = os.getenv("INDEED_PASSWORD", "")

    config["job_search"]["notice_period"]       = int(os.getenv("NOTICE_PERIOD", config["job_search"].get("notice_period", 0)))
    config["job_search"]["willing_to_relocate"] = os.getenv("WILLING_TO_RELOCATE", "Yes").lower() in ("yes", "true", "1")
    config["job_search"]["expected_salary_lpa"] = int(os.getenv("EXPECTED_SALARY", config["job_search"].get("expected_salary_lpa") or 0))

    return config


async def open_shared_browser(config):
    """Open browser profile once. Reused for all sites to preserve sessions."""
    global _pw, _context
    if _context is not None:
        return  
        
    _pw = await async_playwright().start()
    
    # Absolute local directory path to preserve logging/state details
    user_data_path = os.path.abspath("./user_data")
    os.makedirs(user_data_path, exist_ok=True)
    
    logger.info("Initializing Playwright with Persistent Context profile...")
    
    _context = await _pw.chromium.launch_persistent_context(
        user_data_dir=user_data_path,
        headless=config["bot"]["headless"],
        viewport={"width": 1920, "height": 1080},
        screen={"width": 1920, "height": 1080},
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        args=["--start-maximized", "--window-size=1920,1080", "--disable-infobars", "--disable-blink-features=AutomationControlled"]
    )
    logger.info("Browser profile opened — sessions will save automatically.")


async def close_shared_browser():
    """Close browser and flush session state data to storage at the very end."""
    global _pw, _context
    try:
        if _context:
            await _context.close()
        if _pw:
            await _pw.stop()
    except Exception:
        pass
    _pw = _context = None


async def launch_browser(config, site=None):
    """Get a fresh page within the shared persistent browser context."""
    global _context, _pw
    await open_shared_browser(config)
    # Always create a new page so each scraper gets a clean tab
    page = await _context.new_page()
    await stealth_async(page)
    # Return (pw, browser, context, page) — browser=context for persistent context
    return _pw, _context, _context, page


async def human_delay(config, short=False):
    base = config["bot"]["delay_between_actions_sec"]
    if short:
        await asyncio.sleep(random.uniform(0.3, 0.8))
    else:
        await asyncio.sleep(random.uniform(base, base + 1))


async def human_type(page, selector, text):
    await page.click(selector)
    await page.fill(selector, "")
    for char in text:
        await page.type(selector, char, delay=random.randint(40, 120))


def keyword_match(text, skip_keywords):
    text_lower = text.lower()
    for kw in skip_keywords:
        if kw.lower() in text_lower:
            return True
    return False