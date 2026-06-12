import asyncio
import random
import re
from loguru import logger
from playwright_stealth import stealth_async
from scrapers.utils import launch_browser, keyword_match
from tracker.db import log_application, already_applied

_stop_event = None

# --- SPEED ADJUSTMENT ---
SPEED_MULTIPLIER = 0.5 

def is_stopped():
    return _stop_event is not None and _stop_event.is_set()

async def sleep_or_stop(seconds):
    seconds = seconds * SPEED_MULTIPLIER
    if _stop_event is None:
        await asyncio.sleep(seconds)
        return
    try: 
        await asyncio.wait_for(_stop_event.wait(), timeout=seconds)
    except asyncio.TimeoutError: 
        pass

async def login_instahyre(page):
    logger.info("Opening Instahyre login...")
    await page.goto("https://www.instahyre.com/login/", wait_until="domcontentloaded")
    await asyncio.sleep(2)
    logger.warning("Please LOGIN manually. Bot continues after login detection.")
    
    for i in range(36):
        await asyncio.sleep(5)
        if await page.query_selector(".dashboard-container, .profile-dropdown, a[href*='/candidate/profile']"):
            logger.success("Login detected successfully!")
            return True
    return False

async def search_jobs_instahyre(page, keyword, location, experience=None):
    """Navigates and applies experience filter only if a specific year is provided."""
    kw_url = keyword.lower().strip().replace(" ", "-")
    loc_url = location.lower().strip().replace(" ", "-")
    
    # 1. Handle Unfiltered vs Filtered URL parameters
    if experience is None:
        url = f"https://www.instahyre.com/search-jobs/?skills={kw_url}&location={loc_url}"
        logger.info(f"Navigating to search: {keyword} in {location} | Target Exp: ALL (Unfiltered)")
    else:
        url = f"https://www.instahyre.com/search-jobs/?skills={kw_url}&location={loc_url}&experience={experience}"
        logger.info(f"Navigating to search: {keyword} in {location} | Target Exp: {experience} years")
        
    await page.goto(url, wait_until="domcontentloaded")
    await asyncio.sleep(2 * SPEED_MULTIPLIER)

    try:
        # 2. Only interact with the experience UI if we have a specific number (0, 1, 2)
        if experience is not None:
            exp_input = "input[placeholder='e.g. 4']"
            
            if await page.is_visible(exp_input):
                await page.click(exp_input)
                
                for _ in range(3):
                    await page.press(exp_input, "Backspace")
                
                await asyncio.sleep(0.5)
                await page.type(exp_input, str(experience), delay=150)
                await asyncio.sleep(0.5)
                await page.press(exp_input, "Enter")
                
                show_btn = "button:has-text('Show results')"
                if await page.is_visible(show_btn):
                    await page.click(show_btn, force=True)
                    
        # Wait for results to load regardless of filtered or unfiltered search
        await page.wait_for_selector(".job-card, .employer-block, #job-function, .no-results", timeout=4000)
    except Exception as e:
        logger.debug(f"Experience UI interaction bypass note: {e}")

async def get_job_links(page):
    """Extracts job URLs along with their real title, company, and location from the card layout."""
    jobs = []
    
    try:
        await page.wait_for_selector(".employer-block, .job-card", timeout=4000)
    except:
        logger.warning("No job cards loaded on page matching search filters.")
        return []

    cards = await page.query_selector_all(".employer-block, .job-card")

    for card in cards:
        try:
            view_btn = await card.query_selector("a:has-text('View »')")
            if not view_btn:
                continue
                
            href = await view_btn.get_attribute("href")
            if not href:
                continue
            if not href.startswith("http"): 
                href = "https://www.instahyre.com" + href

            card_text = await card.inner_text()
            lines = [line.strip() for line in card_text.split("\n") if line.strip()]
            
            if len(lines) < 2:
                continue

            first_line = lines[0]
            if " - " in first_line:
                company, title = first_line.split(" - ", 1)
            else:
                company, title = "Unknown Company", first_line
            
            second_line = lines[1]
            location = second_line.replace("Job available in ", "").strip()
            
            jobs.append({
                "url": href.strip(),
                "title": title.strip(),
                "company": company.strip(),
                "location": location.strip()
            })
        except Exception as e:
            logger.debug(f"Error parsing single job card layout data elements: {e}")
            continue
            
    unique_jobs = list({job["url"]: job for job in jobs}.values())
    return unique_jobs

async def apply_to_job(context, job_url, title, company, location):
    """Opens job page, removes overlays, applies, and logs real database details."""
    if is_stopped(): return False
    job_page = None
    try:
        job_page = await context.new_page()
        await stealth_async(job_page)
        await job_page.goto(job_url, wait_until="domcontentloaded", timeout=20000)
        await asyncio.sleep(1 * SPEED_MULTIPLIER)

        await job_page.evaluate("""() => {
            const elements = ['#intercom-container', '.intercom-lightweight-app', '[class*="intercom"]', '.modal-backdrop', '[role="dialog"]'];
            elements.forEach(sel => document.querySelectorAll(sel).forEach(el => el.remove()));
        }""")

        apply_selectors = [
            "button#btn-show-interest", 
            "button:has-text('Show Interest')", 
            "button:has-text('Apply')",
            "a:has-text('Apply')"
        ]
        
        apply_btn = None
        for sel in apply_selectors:
            btn = await job_page.query_selector(sel)
            if btn and await btn.is_visible():
                apply_btn = btn
                break
        
        if not apply_btn:
            return False

        await apply_btn.scroll_into_view_if_needed()
        await apply_btn.click(force=True)
        await asyncio.sleep(1.5 * SPEED_MULTIPLIER) 
        
        log_application("Instahyre", title, company, location, job_url)
        logger.success(f"Applied Successfully: {title} at {company} ({location})")
        return True

    except Exception as e:
        logger.error(f"Error executing application run: {e}")
        return False
    finally:
        if job_page: 
            await job_page.close()

async def run_instahyre(config):
    global _stop_event
    _stop_event = asyncio.Event()
    
    max_apps = config["filters"].get("max_applications_per_run", 20)
    
    # NEW: Sequence is 0 years, 1 year, 2 years, and then None (All/Unfiltered)
    experience_brackets = [0, 1, 2, None]
    
    pw, browser, context, page = await launch_browser(config, site="instahyre")
    if not await login_instahyre(page): 
        return 0
    
    applied_count = 0
    
    for keyword in config["job_search"]["keywords"]:
        for location in config["job_search"]["locations"]:
            for exp in experience_brackets:
                if is_stopped() or applied_count >= max_apps: 
                    break
                
                await search_jobs_instahyre(page, keyword, location, experience=exp)
                job_links = await get_job_links(page)
                
                for job in job_links:
                    if is_stopped() or applied_count >= max_apps: 
                        break
                    
                    # If we already applied during the 0, 1, or 2 passes, the unfiltered pass skips it here
                    if already_applied(job['url']): 
                        continue
                    
                    if await apply_to_job(context, job['url'], job['title'], job['company'], job['location']):
                        applied_count += 1
                        await sleep_or_stop(random.uniform(4, 8))
    
    await browser.close()
    await pw.stop()
    return applied_count