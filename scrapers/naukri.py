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
        
        # Updated Naukri login detection logic
        profile = await page.query_selector(
            "[class*='profile'],"
            "[class*='userName'],"
            "a[href*='mnjuser']"
        )

        if profile:
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
        ".srp-jobtuple-container a.title",  
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
        return []

    # Filter unique links
    seen = set()
    unique_links = []

    for job in links:
        if job["url"] not in seen:
            seen.add(job["url"])
            unique_links.append(job)

    return unique_links


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

        # --- LIQUIDATE POINTER-BLOCKING CHATBOT OVERLAYS ---
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

        # --- DEVOPS SKILL SCORING ---
        DEVOPS_SKILLS = [
            "aws",
            "azure",
            "gcp",
            "docker",
            "kubernetes",
            "terraform",
            "linux",
            "ansible",
            "jenkins",
            "gitlab"
        ]

        try:
            page_text = (
                await job_page.locator("body").inner_text()
            ).lower()

            score = sum(
                1
                for skill in DEVOPS_SKILLS
                if skill in page_text
            )

            if score < 2:
                logger.info(f"Skip '{title}' (low DevOps skill score: {score})")
                return False

        except Exception:
            pass

        # --- EXTRACT COMPANY NAME ---
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

            MAX_ALLOWED_EXP = 2

            if range_match:
                min_exp = int(range_match.group(1))
                if min_exp > MAX_ALLOWED_EXP:
                    logger.warning(f"Skipping '{title}' — requires minimum {min_exp} years experience.")
                    return False
            elif plus_match:
                val = int(plus_match.group(1))
                if val > MAX_ALLOWED_EXP:
                    logger.warning(f"Skipping '{title}' — requires {val}+ years.")
                    return False
            elif single_match:
                val = int(single_match.group(1))
                if val > MAX_ALLOWED_EXP:
                    logger.warning(f"Skipping '{title}' — requires {val} years.")
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
            "button.styles_btn__KzI_x",                  
            "[class*='styles_btn__']",
            "button:has-text('Apply on company site')",
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

        # Fallback button checking based on user requirements
        if not apply_btn:
            buttons = await job_page.query_selector_all("button,a")
            for btn in buttons:
                try:
                    txt = (await btn.inner_text()).strip().lower()
                    if (
                        any(word in txt for word in [
                            "apply",
                            "apply now",
                            "easy apply",
                            "apply on company site"
                        ])
                        and "applied" not in txt
                    ):
                        apply_btn = btn
                        break
                except Exception:
                    pass

        # Final evaluation fallback
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

        await apply_btn.scroll_into_view_if_needed()
        await asyncio.sleep(0.5)
        
        # FORCE INTERACTION TO BYPASS INTERCEPTIONS
        await apply_btn.click(force=True)
        await asyncio.sleep(4)

        # --- EXTERNAL APPLY DETECTION (Moved after button click) ---
        if "naukri.com" not in job_page.url:
            logger.info(f"External Apply Detected: {job_page.url}")
            return False

        # --- DYNAMIC POST-CLICK MODAL OVERLAY PROCESSING ---
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

    # --- CORE TECHNOLOGY ATOM TOKENS ---
    core_tech_tokens = [
        "devops",
        "cloud",
        "platform",
        "infrastructure",
        "site reliability",
        "sre",
        "linux",
        "aws",
        "azure",
        "gcp",
        "docker",
        "terraform",
        "kubernetes",
        "ansible",
        "jenkins",
        "gitlab",
        "cloud engineer",
        "platform engineer",
        "linux engineer"        
        "junior",
        "cloud support",
        "operations",
        "cloud operations",
        "system engineer",
        "systems engineer"
    ]

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
                    title_lower = title.lower()

                    # --- SMART DOMAIN MATCHING ---
                    if not keyword_match(title, core_tech_tokens):
                        logger.info(f"  ↳ Skip: '{title}' is not related to your domain.")
                        continue

                    if already_applied(job_url):
                        logger.info(f"  ↳ Skip: Already processed '{title}' (In DB history).")
                        continue

                    if any(skip_kw.lower() in title_lower for skip_kw in skip_kws):
                        logger.info(f"  ↳ Skip: '{title}' contains senior/excluded keyword restriction rules.")
                        continue

                    # Forward to processing automation track engine
                    success = await apply_to_job(context, job_url, title)
                    if success:
                        applied_count += 1
                        
                        await sleep_or_stop(random.uniform(8, 15))

                        if applied_count % 10 == 0:
                            logger.info("Cooling down for anti-ban safety...")
                            await sleep_or_stop(random.uniform(60, 120))

        return applied_count

    except Exception as e:
        logger.error(f"Critical breakdown in run_naukri loop workflow: {e}")
        return applied_count
    finally:
        try:
            await browser.close()
            await pw.stop()
        except Exception:
            pass