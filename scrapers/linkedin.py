import asyncio
import random
import re
from loguru import logger
from scrapers.utils import launch_browser, keyword_match
from tracker.db import log_application, already_applied


async def login_linkedin(page):
    logger.info("Opening LinkedIn login page...")
    await page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded")
    await asyncio.sleep(2)
    logger.warning("=" * 55)
    logger.warning("Please LOGIN to LinkedIn manually in the browser.")
    logger.warning("You have 3 minutes. Bot continues after login.")
    logger.warning("=" * 55)
    for i in range(36):
        await asyncio.sleep(5)
        if await page.query_selector("#global-nav, .global-nav, [data-global-nav-container], .global-nav__nav, button.global-nav__primary-link, input.search-global-typeahead__input"):
            logger.success("LinkedIn login detected! Continuing...")
            await asyncio.sleep(2)
            return True
        if i % 6 == 0 and i > 0:
            logger.info(f"Still waiting for login... ({(36-i)*5}s remaining)")
    logger.error("Login timeout.")
    return False


async def search_jobs_linkedin(page, keyword, location):
    """Navigates to job search page using direct URL, falling back to UI manual search if blocked."""
    url = (
        f"https://www.linkedin.com/jobs/search/?"
        f"keywords={keyword.replace(' ', '%20')}"
        f"&location={location.replace(' ', '%20')}"
        f"&f_LF=f_AL"       
        f"&f_E=1%2C2"       
        f"&distance=600"    
        f"&sortBy=DD"       
    )
    logger.info(f"Searching via URL: '{keyword}' in '{location}'...")
    await page.goto(url, wait_until="domcontentloaded")
    await asyncio.sleep(5) 

    current_url = page.url
    has_results = await page.query_selector(".jobs-search-results-list, [data-job-id], .scaffold-layout__list")
    
    if "feed" in current_url or not has_results:
        logger.warning("Direct URL injection search failed or redirected. Executing UI manual fallback search...")
        await page.goto("https://www.linkedin.com/jobs/", wait_until="domcontentloaded")
        await asyncio.sleep(3)
        
        try:
            keyword_input = await page.query_selector("input[aria-label='Search by title, skill, or company'], input[id*='jobs-search-box-keyword']")
            if keyword_input:
                await keyword_input.click()
                await keyword_input.fill("")
                await keyword_input.type(keyword, delay=random.randint(40, 90))
                await asyncio.sleep(0.5)
            
            location_input = await page.query_selector("input[aria-label='City, state, or zip code'], input[id*='jobs-search-box-location']")
            if location_input:
                await location_input.click()
                await page.keyboard.press("Control+A")
                await page.keyboard.press("Backspace")
                await location_input.type(location, delay=random.randint(40, 90))
                await asyncio.sleep(0.5)
            
            await page.keyboard.press("Enter")
            logger.info("Search submitted manually via keyboard simulation sequence.")
            await asyncio.sleep(4)
            
        except Exception as e:
            logger.error(f"UI Fallback manual search failed structural input tracking: {e}")


async def get_label_text(page, field):
    """Try to get the label text associated with a form field."""
    try:
        field_id = await field.get_attribute("id")
        if field_id:
            label = await page.query_selector(f"label[for='{field_id}']")
            if label:
                return (await label.inner_text()).lower()
    except Exception:
        pass
    try:
        aria = await field.get_attribute("aria-label") or ""
        return aria.lower()
    except Exception:
        return ""


async def fill_text_field(field, label, config):
    """Fill a text/number input based on its label."""
    val = await field.input_value()
    if val:
        return

    label = label.lower()
    phone   = config["personal"]["phone"]
    email   = config["personal"]["email"]
    exp     = str(config["job_search"].get("experience_years", 0))  
    salary  = str(config["job_search"].get("expected_salary_lpa", 0) or 0)
    notice  = str(config["job_search"].get("notice_period", 0))
    name    = config["personal"]["full_name"]
    location= config["personal"].get("location", "")

    if any(w in label for w in ["phone", "mobile", "contact number"]):
        await field.fill(phone)
    elif "email" in label:
        await field.fill(email)
    elif any(w in label for w in ["salary", "ctc", "expected", "compensation", "pay", "lpa", "lakh"]):
        await field.fill(salary)
    elif any(w in label for w in ["experience", "years of exp", "yrs", "total exp"]):
        await field.fill(exp)
    elif any(w in label for w in ["notice", "notice period", "joining", "availability"]):
        await field.fill(notice)
    elif any(w in label for w in ["city", "location", "current location", "current city"]):
        await field.fill(location)
    elif any(w in label for w in ["full name", "your name"]):
        await field.fill(name)
    elif "first name" in label:
        await field.fill(name.split()[0] if name else "")
    elif "last name" in label:
        await field.fill(name.split()[-1] if name else "")
    elif any(w in label for w in ["linkedin", "linkedin url", "profile url"]):
        await field.fill(config["personal"].get("linkedin_url", ""))
    elif any(w in label for w in ["github", "portfolio", "website", "portfolio url"]):
        await field.fill(config["personal"].get("portfolio_url", ""))
    else:
        ftype = await field.get_attribute("type") or "text"
        if ftype == "number":
            await field.fill("0")


async def handle_select_field(field, label, config):
    """Handle dropdown selects based on label."""
    label = label.lower()
    try:
        options = await field.query_selector_all("option")
        values = []
        for opt in options:
            val = await opt.get_attribute("value") or ""
            text = (await opt.inner_text()).lower()
            values.append((val, text))

        willing = config.get("job_search", {}).get("willing_to_relocate", True)
        for val, text in values:
            if not val or text in ("select", "choose", "please select", ""):
                continue
            if any(w in label for w in ["relocat", "willing to relocat", "open to relocat"]):
                target = "yes" if willing else "no"
                if target in text:
                    await field.select_option(val)
                    return
            elif any(w in label for w in ["notice", "joining", "availability"]):
                if any(w in text for w in ["immediate", "0", "less than", "no notice"]):
                    await field.select_option(val)
                    return
            elif any(w in label for w in ["experience", "years", "exp"]):
                if any(w in text for w in ["0", "fresher", "less than 1", "0-1", "1", "2"]):
                    await field.select_option(val)
                    return

        for val, text in values:
            if val and text not in ("select", "choose", "please select", ""):
                await field.select_option(val)
                return
    except Exception as e:
        logger.warning(f"Could not fill select '{label}': {e}")


async def handle_easy_apply_modal(page, config):
    """Fill and submit LinkedIn Easy Apply modal using comprehensive container selectors."""
    for step in range(10):
        await asyncio.sleep(1)

        modal_text = ""
        try:
            modal_body = await page.query_selector(".jobs-easy-apply-modal, div[role='dialog']")
            if modal_body:
                modal_text = (await modal_body.inner_text()).lower()
        except Exception:
            pass

        if "how many years" in modal_text or "years of experience" in modal_text:
            numeric_inputs = await page.query_selector_all(".jobs-easy-apply-modal input[type='number']")
            for n_inp in numeric_inputs:
                try:
                    lbl = await get_label_text(page, n_inp)
                    if any(w in lbl for w in ["experience", "years", "exp"]):
                        val = await n_inp.input_value()
                        if val and int(val) > 2:
                            logger.warning("Aborting modal flow — question asks for higher experience than profile bracket.")
                            return False
                except Exception:
                    pass

        resume_input = await page.query_selector(".jobs-easy-apply-modal input[type='file'], input[type='file']")
        if resume_input:
            try:
                await resume_input.set_input_files(config["resume"]["path"])
                await asyncio.sleep(1)
            except Exception:
                logger.warning("Resume upload failed — file missing?")

        inputs = await page.query_selector_all(
            ".jobs-easy-apply-modal input[type='text'], "
            ".jobs-easy-apply-modal input[type='tel'], "
            ".jobs-easy-apply-modal input[type='email'], "
            ".jobs-easy-apply-modal input[type='number'], "
            "div[role='dialog'] input[type='text'], "
            "input[id*='phoneNumber']"
        )
        for inp in inputs:
            try:
                label = await get_label_text(page, inp)
                await fill_text_field(inp, label, config)
                await asyncio.sleep(0.2)
            except Exception:
                pass

        selects = await page.query_selector_all(
            ".jobs-easy-apply-modal select, "
            "div[role='dialog'] select"
        )
        for sel in selects:
            try:
                label = await get_label_text(page, sel)
                await handle_select_field(sel, label, config)
                await asyncio.sleep(0.2)
            except Exception:
                pass

        radios = await page.query_selector_all(
            ".jobs-easy-apply-modal input[type='radio'], "
            "div[role='dialog'] input[type='radio']"
        )
        seen_groups = set()
        for radio in radios:
            try:
                name = await radio.get_attribute("name")
                if not name or name in seen_groups:
                    continue
                label_el = await page.query_selector(f"label[for='{await radio.get_attribute('id')}']")
                label_text = (await label_el.inner_text()).lower() if label_el else ""
                if "yes" in label_text:
                    await radio.check()
                    seen_groups.add(name)
                else:
                    group = await page.query_selector_all(f"input[name='{name}']")
                    picked = False
                    for r in group:
                        rid = await r.get_attribute("id") or ""
                        rlabel = await page.query_selector(f"label[for='{rid}']")
                        rtext = (await rlabel.inner_text()).lower() if rlabel else ""
                        if "yes" in rtext:
                            await r.check()
                            picked = True
                            break
                    if not picked and group:
                        await group[0].check()
                    seen_groups.add(name)
                await asyncio.sleep(0.2)
            except Exception:
                pass

        submit_btn = await page.query_selector(
            "button[aria-label='Submit application'], button:has-text('Submit application')"
        )
        if submit_btn:
            await submit_btn.click()
            await asyncio.sleep(1)
            for dismiss_sel in [
                "button[aria-label='Dismiss']",
                "button[aria-label='Done']",
                "button:has-text('Done')",
            ]:
                try:
                    btn = await page.query_selector(dismiss_sel)
                    if btn:
                        await btn.click()
                        break
                except Exception:
                    pass
            return True

        next_btn = None
        for sel in [
            "button[aria-label='Continue to next step']",
            "button[aria-label='Review your application']",
            "button[aria-label='Next']",
            "button:has-text('Next')",
            "button:has-text('Review')",
            ".artdeco-button--primary",
        ]:
            try:
                btn = await page.query_selector(sel)
                if btn and await btn.is_visible():
                    next_btn = btn
                    break
            except Exception:
                pass

        if next_btn:
            await next_btn.click()
            await asyncio.sleep(1)
        else:
            logger.warning(f"No next/submit button on step {step+1} — stopping.")
            return False

    return False


browser_closed_linkedin = False


async def run_linkedin(config):
    global browser_closed_linkedin
    browser_closed_linkedin = False

    applied_count = 0
    max_apps = config["filters"]["max_applications_per_run"] or 20
    skip_kws = config["filters"]["skip_keywords"]
    locations = config["job_search"]["locations"]
    keywords  = config["job_search"]["keywords"]
    job_keywords_lower = [k.lower() for k in keywords]

    pw, browser, context, page = await launch_browser(config, site="linkedin")

    def on_disconnect():
        global browser_closed_linkedin
        browser_closed_linkedin = True
        logger.warning("Browser closed — stopping LinkedIn bot.")

    context.on("close", lambda ctx: on_disconnect())

    try:
        first_kw = keywords[0] if keywords else "DevOps"
        first_loc = locations[0] if locations else "Noida"
        
        logger.info("Verifying global session state against target pages...")
        await search_jobs_linkedin(page, first_kw, first_loc)
        
        if "linkedin.com/checkpoint" in page.url or "linkedin.com/login" in page.url:
            logger.warning("Session context completely unauthenticated. Booting manual fallback login panel...")
            logged_in = await login_linkedin(page)
            if not logged_in:
                logger.error("Skipping LinkedIn — manual login verification loop timed out.")
                return 0

        done = False
        for keyword in keywords:
            if done or browser_closed_linkedin:
                break
            for location in locations:
                if done or browser_closed_linkedin or applied_count >= max_apps:
                    done = True
                    break

                try:
                    await search_jobs_linkedin(page, keyword, location)
                except Exception as e:
                    logger.warning(f"Search failed: {e}")
                    continue

                for _ in range(3):
                    await page.keyboard.press("End")
                    await asyncio.sleep(1.5)

                job_links = []
                try:
                    link_els = await page.query_selector_all(
                        "a.job-card-list__title, "
                        "a.job-card-container__link, "
                        "a[href*='/jobs/view/']"
                    )
                    for el in link_els:
                        try:
                            href = await el.get_attribute("href")
                            title = (await el.inner_text()).strip()
                            if href and "/jobs/view/" in href:
                                if href.startswith("/"):
                                    href = "https://www.linkedin.com" + href
                                
                                clean = href.split("?")[0]
                                if not any(kw in title.lower() for kw in job_keywords_lower):
                                    continue
                                if keyword_match(title, skip_kws):
                                    continue
                                
                                tl = title.lower()
                                senior_words = [
                                    "senior", "sr.", "lead", "principal", "staff", "head", 
                                    "manager", "architect", "vice president", "director",
                                    "ii", "iii", "mid", "expert"
                                ]
                                if any(f" {w} " in f" {tl} " or tl.startswith(w) for w in senior_words):
                                    continue
                                job_links.append({"url": clean, "title": title})
                        except Exception:
                            continue
                except Exception as e:
                    logger.warning(f"Could not collect job links: {e}")
                    continue

                seen = set()
                unique_jobs = []
                for j in job_links:
                    if j["url"] not in seen:
                        seen.add(j["url"])
                        unique_jobs.append(j)

                logger.info(f"Found {len(unique_jobs)} matching jobs for '{keyword}' in '{location}'")

                for job in unique_jobs:
                    if done or browser_closed_linkedin or applied_count >= max_apps:
                        done = True
                        break

                    title   = job["title"]
                    job_url = job["url"]

                    if already_applied(job_url):
                        logger.info(f"Already applied → {title}")
                        continue

                    try:
                        await page.goto(job_url, wait_until="domcontentloaded")
                        try:
                            await page.evaluate("window.moveTo(-32000, -32000)")
                        except Exception:
                            pass
                        await asyncio.sleep(2.5) # Increased page load buffer slightly

                        jd_element = await page.query_selector("#job-details, .jobs-description-content__text, .jobs-box__html-content")
                        if jd_element:
                            jd_text = (await jd_element.inner_text()).lower()
                            
                            range_match = re.search(r'(\d+)\s*-\s*(\d+)\s*(?:yrs|years)', jd_text)
                            plus_match  = re.search(r'(\d+)\s*\+\s*(?:yrs|years)', jd_text)
                            min_match   = re.search(r'(?:minimum|at least|req|require)\s*(\d+)\s*(?:yrs|years)', jd_text)

                            dropped = False
                            if range_match:
                                min_exp, max_exp = int(range_match.group(1)), int(range_match.group(2))
                                if min_exp >= 2 or max_exp > 3:
                                    dropped = True
                            elif plus_match:
                                if int(plus_match.group(1)) >= 2:
                                    dropped = True
                            elif min_match:
                                if int(min_match.group(1)) >= 2:
                                    dropped = True

                            if dropped:
                                logger.warning(f"Skipping '{title}' — Contextual description demands >2 years experience.")
                                continue

                        company_el = await page.query_selector(
                            ".jobs-unified-top-card__company-name a, "
                            ".jobs-unified-top-card__subtitle-primary-grouping a"
                        )
                        loc_el = await page.query_selector(".jobs-unified-top-card__bullet")
                        company = (await company_el.inner_text()).strip() if company_el else "Unknown"
                        loc     = (await loc_el.inner_text()).strip()     if loc_el     else location

                        # --- DEEP EASY APPLY DETECTOR OVERHAUL ---
                        easy_btn = None
                        
                        # Phase 1: Try structured, highly specific semantic text matching via Playwright locators
                        try:
                            btn_locator = page.get_by_role("button", name=re.compile(r"Easy Apply", re.IGNORECASE))
                            if await btn_locator.count() > 0:
                                for idx in range(await btn_locator.count()):
                                    candidate = btn_locator.nth(idx)
                                    if await candidate.is_visible():
                                        easy_btn = candidate
                                        break
                        except Exception:
                            pass

                        # Phase 2: Comprehensive element fallback cascade array
                        if not easy_btn:
                            for btn_selector in [
                                "button.jobs-apply-button",
                                ".jobs-apply-button button",
                                "button[class*='jobs-apply-button']",
                                ".jobs-top-card button:has-text('Easy Apply')",
                                "div[class*='top-card'] button:has-text('Easy Apply')",
                                "button:has-text('Easy Apply')",
                                ".artdeco-button--primary:has-text('Easy Apply')"
                            ]:
                                try:
                                    btn = await page.query_selector(btn_selector)
                                    if btn and await btn.is_visible():
                                        easy_btn = btn
                                        break
                                except Exception:
                                    pass

                        if not easy_btn:
                            logger.info(f"No Easy Apply for '{title}' — skipping.")
                            continue

                        await easy_btn.scroll_into_view_if_needed()
                        await asyncio.sleep(0.5)
                        await easy_btn.click()
                        await asyncio.sleep(1.5)

                        success = await handle_easy_apply_modal(page, config)
                        if success:
                            log_application("LinkedIn", title, company, loc, job_url)
                            applied_count += 1
                            logger.success(f"[{applied_count}/{max_apps}] Applied → {title} at {company} ({loc})")
                            if applied_count >= max_apps:
                                done = True
                                break
                        else:
                            log_application("LinkedIn", title, company, loc, job_url, status="skipped", notes="Modal too complex")
                            try:
                                close = await page.query_selector("button[aria-label='Dismiss']")
                                if close:
                                    await close.click()
                                    await asyncio.sleep(0.5)
                                    confirm_dialog = await page.query_selector("button[data-control-name='discard_application_confirm_btn']")
                                    if confirm_dialog:
                                        await confirm_dialog.click()
                            except Exception:
                                pass

                        await asyncio.sleep(config["bot"]["delay_between_jobs_sec"])

                    except Exception as e:
                        if browser_closed_linkedin:
                            done = True
                            break
                        logger.error(f"Error on job '{title}': {e}")
                        try:
                            close = await page.query_selector("button[aria-label='Dismiss']")
                            if close:
                                await close.click()
                        except Exception:
                            pass
                        continue

    finally:
        try:
            await page.close()
        except Exception:
            pass

    logger.info(f"LinkedIn done. Applied to {applied_count} jobs.")
    return applied_count