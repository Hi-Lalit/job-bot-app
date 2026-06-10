import asyncio
import random
import re
from loguru import logger
from scrapers.utils import launch_browser, keyword_match
from tracker.db import log_application, already_applied


async def login_naukri(page):
    """Open Naukri login page and wait for user to login manually."""
    logger.info("Opening Naukri login page...")
    await page.goto("https://www.naukri.com/nlogin/login", wait_until="domcontentloaded")
    await asyncio.sleep(2)

    logger.warning("=" * 55)
    logger.warning("Please LOGIN to Naukri manually in the browser.")
    logger.warning("You have 3 minutes. Bot continues after login.")
    logger.warning("=" * 55)

    for i in range(36):  # 36 x 5sec = 3 minutes
        await asyncio.sleep(5)
        current_url = page.url
        if "login" not in current_url and "naukri.com" in current_url:
            logger.success("Naukri login detected! Continuing...")
            await asyncio.sleep(2)
            return True
        if i % 6 == 0 and i > 0:
            remaining = (36 - i) * 5
            logger.info(f"Still waiting for login... ({remaining}s remaining)")

    logger.error("Login timeout — did not detect successful login.")
    return False


async def search_jobs_naukri(page, keyword, location, experience=0):
    """Navigate to Naukri job search results page using standard paths with experience filtering."""
    kw_url = keyword.lower().strip().replace(" ", "-")
    loc_url = location.lower().strip().replace(" ", "-")
    
    url = f"https://www.naukri.com/{kw_url}-jobs-in-{loc_url}?experience={experience}"
    
    logger.info(f"Searching via URL: {url}")
    await page.goto(url, wait_until="domcontentloaded")
    await asyncio.sleep(4)


async def get_job_links(page):
    """Extract all job URLs from search results using broadened modern selectors."""
    links = []
    selectors = [
        "a.title",
        ".srp-jobtuple-container a.title",  # Updated target context wrapper variant
        "article.jobTuple a.title",
        ".srp-jobtuple-wrapper a.title",
        ".cust-job-tuple a.title",
        "div[class*='jobTuple'] a[title]",
        "a.job-title-anchor",
        "div[id^='jobid'] a.title"
    ]
    for selector in selectors:
        els = await page.query_selector_all(selector)
        if els:
            logger.info(f"Found {len(els)} jobs using selector: {selector}")
            for el in els:
                href = await el.get_attribute("href")
                title = (await el.inner_text()).strip()
                if href:
                    if not href.startswith("http"):
                        href = "https://www.naukri.com" + href
                    if "naukri.com" in href:
                        links.append({"url": href.strip(), "title": title})
            break

    if not links:
        logger.warning("No job links found — Naukri may have changed layout.")
    return links


async def is_login_page(page):
    """Check if current page is asking for login."""
    url = page.url
    if "login" in url or "signin" in url or "nlogin" in url:
        return True
    login_el = await page.query_selector("input[type='password'], #usernameField, .loginForm")
    return login_el is not None


async def apply_to_job(context, job_url, title):
    """Open job in a new tab, verify experience constraints + work environment, apply, then close tab."""
    if is_stopped():
        return False

    job_page = None
    try:
        job_page = await context.new_page()
        
        from playwright_stealth import stealth_async
        await stealth_async(job_page)

        if is_stopped():
            return False
        try:
            await job_page.goto(job_url, wait_until="domcontentloaded", timeout=20000)
        except Exception as e:
            if is_stopped():
                return False
            logger.warning(f"Page load failed for '{title}': {e}")
            return False
        await sleep_or_stop(2.0)

        if is_stopped():
            return False

        # --- CRITICAL FIX 1: LIQUIDATE POINTER-BLOCKING CHATBOT OVERLAYS ---
        try:
            await job_page.evaluate("""() => {
                const elementsToDestroy = [
                    '.chatbot_Overlay', 
                    '._chatBotContainer', 
                    '[id*="chatbot"]', 
                    '[class*="chatbot"]', 
                    '[id*="Chatbot"]'
                ];
                elementsToDestroy.forEach(selector => {
                    document.querySelectorAll(selector).forEach(el => el.remove());
                });
            }""")
        except Exception as e:
            logger.debug(f"Non-critical issue stripping overlays: {e}")

        if await is_login_page(job_page):
            logger.warning(f"Login required for '{title}' — skipping.")
            return False

        # --- CRITICAL FIX: EXTRACT COMPANY NAME FIRST BEFORE APPLYING ---
        company = "Unknown"
        company_selectors = [
            ".jd-header-comp-name a",
            "[class*='jd-header-comp-name'] a",
            "[class*='companyName'] a",
            "a.pad-rt-8",
            ".comp-name",
            "a.comp-name",
            "[class*='about-company'] [class*='title']",
            ".styles_jd-header-comp-name__w1v6Z a"
        ]
        for comp_sel in company_selectors:
            try:
                el = await job_page.query_selector(comp_sel)
                if el:
                    text = (await el.inner_text()).strip()
                    # Clean up reviews string if attached (e.g. "Google 4.2 (120 Reviews)" -> "Google")
                    text = re.sub(r'\d+\.\d+\s*\(.*\)', '', text).strip()
                    if text:
                        company = text
                        break
            except Exception:
                continue

        # --- MANDATORY EXPERIENCE CHECK ---
        job_exp_text = ""
        exp_selectors = [
            ".exp span", 
            ".expWdth", 
            "[class*='experience'] span", 
            ".jd-header-comp-meta span",
            "span[class*='exp']",
            "div.expHeading",
            ".exp-wrap span",
            "li.fleft.grey-text.br2.span.ver-line"
        ]
        
        for sel in exp_selectors:
            try:
                el = await job_page.query_selector(sel)
                if el:
                    text = (await el.inner_text()).strip()
                    if text and any(char.isdigit() for char in text):
                        job_exp_text = text
                        break
            except Exception:
                continue

        if not job_exp_text:
            try:
                body_element = await job_page.query_selector(".jd-header-comp-meta, .job-meta")
                if body_element:
                    job_exp_text = (await body_element.inner_text()).strip()
            except Exception:
                pass

        if job_exp_text:
            range_match = re.search(r'(\d+)\s*-\s*(\d+)', job_exp_text)
            plus_match = re.search(r'(\d+)\s*\+', job_exp_text)
            single_match = re.search(r'\b(\d+)\s*(?:yrs|years|Yrs)', job_exp_text, re.IGNORECASE)

            if range_match:
                min_exp = int(range_match.group(1))
                max_exp = int(range_match.group(2))
                if min_exp >= 2 or max_exp > 2:
                    logger.warning(f"Skipping '{title}' — Experience requirement too high: '{range_match.group(0)} Yrs'")
                    return False
            elif plus_match:
                val = int(plus_match.group(1))
                if val >= 2:  
                    logger.warning(f"Skipping '{title}' — Experience requirement too high: '{plus_match.group(0)} Yrs'")
                    return False
            elif single_match:
                val = int(single_match.group(1))
                if val >= 2:
                    logger.warning(f"Skipping '{title}' — Experience requirement too high: '{single_match.group(0)}'")
                    return False

        # --- MANDATORY REMOTE/WFH ELIMINATION CHECK ---
        location_text = ""
        loc_selectors = [
            ".loc span", ".loc", "[class*='location'] span", 
            "[class*='location']", ".jd-header-loc", "[data-qa='location']",
            "li.fleft.grey-text.br2.location span"
        ]
        for sel in loc_selectors:
            try:
                el = await job_page.query_selector(sel)
                if el:
                    location_text += " " + (await el.inner_text()).lower()
            except Exception:
                continue

        if any(w in location_text or w in title.lower() for w in ["remote", "work from home", "wfh", "home-based"]):
            logger.warning(f"Skipping '{title}' — Detected Remote/WFH workspace policy context.")
            return False

        # --- ADVANCED ROBUST APPLY BUTTON EXTRACTION ENGINE ---
        apply_btn = None
        apply_selectors = [
            "button.styles_btn__KzI_x",                  # Modern layout design system core button footprint
            "[class*='styles_btn__']",                     # Partial design footprint string match
            "button:has-text('Apply on company site')",   # Catching external apply endpoints
            "button#apply-button",
            "button.apply-button", 
            "a#apply-button",
            "button.apply-btn",
            "button:has-text('Apply')", 
            "a:has-text('Apply')",
            "button[class*='apply']", 
            "a[class*='apply']",
            ".apply-button-container button",
            "[id*='apply']",
            ".apply-btn"
        ]
        
        for sel in apply_selectors:
            try:
                btn = await job_page.query_selector(sel)
                if btn and await btn.is_visible():
                    btn_text = (await btn.inner_text()).lower()
                    if "apply" in btn_text and "applied" not in btn_text:
                        apply_btn = btn
                        break
            except Exception:
                continue

        if not apply_btn:
            try:
                apply_btn = await job_page.evaluate_handle(
                    "() => [...document.querySelectorAll('button, a')].find(el => el.textContent.toLowerCase().includes('apply'))"
                )
                if apply_btn:
                    apply_btn = apply_btn.as_element()
            except Exception:
                pass

        if not apply_btn:
            already_applied_el = await job_page.query_selector("button:has-text('Applied'), .applied")
            if already_applied_el:
                logger.info(f"Already applied to '{title}' on Naukri dashboard interface.")
                return True
            
            logger.info(f"No valid apply button found for '{title}' — skipping.")
            return False

        # Attempt structural click
        await apply_btn.scroll_into_view_if_needed()
        await asyncio.sleep(0.5)
        
        # --- CRITICAL FIX 2: FORCE INTERACTION TO BYPASS REMAINING POINTER INTERCEPTIONS ---
        await apply_btn.click(force=True)
        await asyncio.sleep(4)

        # --- DYNAMIC POST-CLICK MODAL OVERLAY WRAPPER PROCESSING ---
        for step in range(3):
            confirm_btn = await job_page.query_selector(
                "button:has-text('Apply'), button:has-text('Submit'), button:has-text('Confirm'), "
                "button.submit-btn, .chatbot-container button:has-text('Next')"
            )
            if confirm_btn and await confirm_btn.is_visible():
                await confirm_btn.click(force=True)
                await asyncio.sleep(2)
            else:
                break

        try:
            skip_quiz = await job_page.query_selector("button:has-text('Skip'), .skip-btn")
            if skip_quiz and await skip_quiz.is_visible():
                await skip_quiz.click(force=True)
                await asyncio.sleep(1)
        except Exception:
            pass

        log_application("Naukri", title, company, location_text.strip().title(), job_url)
        logger.info(f"  Company  : {company}")
        logger.info(f"  Location : {location_text.strip().title()}")
        logger.info(f"  URL      : {job_url}")
        return True

    except Exception as e:
        logger.error(f"Error in apply_to_job for '{title}': {e}")
        return False
    finally:
        if job_page:
            try:
                await job_page.close()
            except Exception:
                pass


# asyncio Event — set when browser is closed by user
_stop_event = None

def is_stopped():
    return _stop_event is not None and _stop_event.is_set()

async def sleep_or_stop(seconds):
    if _stop_event is None:
        await asyncio.sleep(seconds)
        return
    try:
        await asyncio.wait_for(_stop_event.wait(), timeout=seconds)
    except asyncio.TimeoutError:
        pass

async def get_fresh_page(context):
    if is_stopped():
        return None
    try:
        page = await context.new_page()
        from playwright_stealth import stealth_async
        await stealth_async(page)
        return page
    except Exception as e:
        logger.error(f"Could not create new page: {e}")
        if _stop_event:
            _stop_event.set()
        return None


async def run_naukri(config):
    global _stop_event
    _stop_event = asyncio.Event()

    applied_count = 0
    max_apps = config["filters"]["max_applications_per_run"] or 20
    skip_kws = config["filters"]["skip_keywords"]
    locations = config["job_search"]["locations"]
    keywords = config["job_search"]["keywords"]
    
    experience = config["job_search"].get("experience_years", 0) 
    job_keywords_lower = [k.lower() for k in keywords]

    pw, browser, context, page = await launch_browser(config, site="naukri")

    def on_browser_disconnected():
        logger.warning("Browser was closed — stopping bot.")
        if _stop_event:
            _stop_event.set()

    browser.on("disconnected", lambda: on_browser_disconnected())

    try:
        await page.goto("https://www.naukri.com", wait_until="domcontentloaded")
        await asyncio.sleep(3)

        logged_in_el = await page.query_selector(
            ".nI-gNb-drawer__icon, [class*='userNameDesktop'], a[href*='mnjuser/homepage'], [class*='profileName']"
        )
        not_logged_in_el = await page.query_selector(
            "a[href*='nlogin/login'], .login-signup-block, a:has-text('Login')"
        )

        if logged_in_el and not not_logged_in_el:
            logger.success("Already logged into Naukri — continuing.")
        else:
            logger.info("Not logged in — opening login page.")
            logged_in = await login_naukri(page)
            if not logged_in:
                logger.error("Skipping Naukri — login failed.")
                return 0

        done = False
        for keyword in keywords:
            if done or is_stopped() or applied_count >= max_apps:
                break
            for location in locations:
                if is_stopped() or applied_count >= max_apps:
                    done = True
                    break

                try:
                    await search_jobs_naukri(page, keyword, location, experience)
                except Exception as e:
                    logger.warning(f"Search page crashed: {e} — recreating page.")
                    page = await get_fresh_page(context)
                    if not page:
                        continue
                    try:
                        await search_jobs_naukri(page, keyword, location, experience)
                    except Exception:
                        continue

                try:
                    job_links = await get_job_links(page)
                except Exception as e:
                    logger.warning(f"Could not get job links: {e}")
                    continue

                for job in job_links:
                    if is_stopped() or applied_count >= max_apps:
                        done = True
                        break

                    title = job["title"]
                    job_url = job["url"]

                    if not any(kw in title.lower() for kw in job_keywords_lower):
                        continue

                    if already_applied(job_url):
                        continue

                    if keyword_match(title, skip_kws):
                        logger.info(f"Skipping '{title}' — matched skip keyword from config.")
                        continue

                    title_lower = title.lower()
                    senior_words = [
                        "senior", "sr.", "lead", "principal", "manager", "architect", 
                        "ii", "iii", "iv", "head", "director", "expert", "consultant"
                    ]
                    if any(f" {w} " in f" {title_lower} " or title_lower.startswith(w) for w in senior_words):
                        logger.info(f"Skipping '{title}' — contains senior experience indicators.")
                        continue

                    try:
                        success = await apply_to_job(context, job_url, title)
                    except Exception as e:
                        if is_stopped():
                            done = True
                            break
                        logger.error(f"Error applying to '{title}': {e}")
                        page = await get_fresh_page(context)
                        if not page:
                            done = True
                            break
                        continue

                    if success:
                        applied_count += 1
                        logger.success(f"[{applied_count}/{max_apps}] Applied → {title}")

                    delay = config["bot"]["delay_between_jobs_sec"]
                    await sleep_or_stop(random.uniform(delay, delay + 2))

    finally:
        try:
            await page.close()
        except Exception:
            pass

    logger.info(f"Naukri done. Applied to {applied_count} jobs.")
    return applied_count