import asyncio
import random
from loguru import logger
from scrapers.utils import load_config, human_delay, launch_browser, keyword_match
from tracker.db import log_application, already_applied

async def login_indeed(page, config):
    creds = config["credentials"]["indeed"]
    logger.info("Logging into Indeed...")
    await page.goto("https://in.indeed.com/account/login", wait_until="domcontentloaded")
    await asyncio.sleep(3)

    # Indeed uses a Google/email choice screen sometimes
    try:
        # Try direct email input first
        await page.wait_for_selector("input[type='email'], input[name='__email'], #ifl-InputFormField-3", timeout=10000)
        email_field = await page.query_selector("input[type='email'], input[name='__email'], #ifl-InputFormField-3")
        if email_field:
            await email_field.fill(creds["email"])
            await asyncio.sleep(1)

            # Click continue
            cont = await page.query_selector("button[type='submit'], #login-submit-button, button:has-text('Continue')")
            if cont:
                await cont.click()
            await asyncio.sleep(3)
    except Exception:
        logger.warning("Could not find Indeed email field — site may have changed layout.")

    # Password step
    try:
        pwd = await page.query_selector("input[type='password'], input[name='__password']")
        if pwd:
            await pwd.fill(creds["password"])
            await asyncio.sleep(1)
            submit = await page.query_selector("button[type='submit'], #login-submit-button")
            if submit:
                await submit.click()
            await asyncio.sleep(4)
    except Exception:
        logger.warning("Could not find Indeed password field.")

    # Handle CAPTCHA / verification
    if "challenge" in page.url or "security" in page.url or "verify" in page.url:
        logger.warning("Indeed verification required — please solve it manually in the browser window.")
        logger.warning("Waiting up to 60 seconds...")
        try:
            await page.wait_for_url("**indeed.com**", timeout=60000)
            await asyncio.sleep(3)
        except Exception:
            pass

    if "login" not in page.url:
        logger.success("Indeed login successful.")
        return True
    else:
        logger.warning("Indeed login may have failed — check credentials in profile.yaml.")
        return False

async def search_jobs_indeed(page, config, location):
    keywords = config["job_search"]["keywords"][0]
    url = (
        f"https://in.indeed.com/jobs?"
        f"q={keywords.replace(' ', '+')}"
        f"&l={location.replace(' ', '+')}"
        f"&iafilter=1"
    )
    logger.info(f"Searching Indeed: {keywords} in {location}")
    await page.goto(url)
    await asyncio.sleep(3)

async def handle_indeed_apply_modal(page, config):
    """Handle Indeed's multi-step apply modal."""
    max_steps = 6
    for step in range(max_steps):
        await asyncio.sleep(2)

        # Upload resume if prompted
        file_input = await page.query_selector("input[type='file']")
        if file_input:
            try:
                await file_input.set_input_files(config["resume"]["path"])
                await asyncio.sleep(1)
            except Exception:
                pass

        # Fill contact info fields
        for field_id, value in [
            ("input[name='name.first'], input[id*='firstName']", config["personal"]["full_name"].split()[0]),
            ("input[name='name.last'], input[id*='lastName']", config["personal"]["full_name"].split()[-1]),
            ("input[type='tel'], input[name*='phone']", config["personal"]["phone"]),
        ]:
            try:
                el = await page.query_selector(field_id)
                if el:
                    val = await el.input_value()
                    if not val:
                        await el.fill(value)
            except Exception:
                pass

        # Check for submit button
        submit = await page.query_selector("button[aria-label*='Submit'], button[data-testid='IndeedApplyButton']")
        if submit:
            await submit.click()
            await asyncio.sleep(2)
            return True

        # Next step
        next_btn = await page.query_selector("button[aria-label*='Continue'], button[type='submit']")
        if next_btn:
            await next_btn.click()
        else:
            return False

    return False

async def run_indeed(config):
    applied_count = 0
    max_apps = config["filters"]["max_applications_per_run"] or 20
    skip_kws = config["filters"]["skip_keywords"]
    locations = config["job_search"]["locations"]

    pw, browser, context, page = await launch_browser(config, site="indeed")
    try:
        await login_indeed(page, config)

        for location in locations:
            if applied_count >= max_apps:
                break
            logger.info(f"Indeed → location: {location}")
            await search_jobs_indeed(page, config, location)

            try:
                await page.wait_for_selector(".job_seen_beacon, .tapItem", timeout=10000)
            except Exception:
                logger.warning(f"No results found for {location} on Indeed.")
                continue

            cards = await page.query_selector_all(".job_seen_beacon, .tapItem")
            logger.info(f"Found {len(cards)} Indeed cards in {location}")

            for card in cards:
                if applied_count >= max_apps:
                    break
                try:
                    title_el = await card.query_selector("h2.jobTitle a, .jcs-JobTitle")
                    company_el = await card.query_selector("[data-testid='company-name'], .companyName")
                    location_el = await card.query_selector("[data-testid='text-location'], .companyLocation")

                    title = (await title_el.inner_text()).strip() if title_el else "Unknown"
                    company = (await company_el.inner_text()).strip() if company_el else "Unknown"
                    loc_text = (await location_el.inner_text()).strip() if location_el else location
                    href = await title_el.get_attribute("href") if title_el else ""
                    job_url = f"https://in.indeed.com{href}" if href.startswith("/") else href

                    if already_applied(job_url):
                        logger.info(f"Already applied to {title} — skipping.")
                        continue

                    if keyword_match(title, skip_kws):
                        logger.info(f"Skipping '{title}' — matches skip keyword.")
                        continue

                    await title_el.click()
                    await asyncio.sleep(2)

                    apply_btn = await page.query_selector("button.ia-IndeedApplyButton, button[id*='indeedApplyButton'], .jobsearch-IndeedApplyButton-newDesign")
                    if not apply_btn:
                        logger.info(f"No Easy Apply for '{title}' — skipping.")
                        continue

                    await apply_btn.click()
                    await asyncio.sleep(3)

                    success = await handle_indeed_apply_modal(page, config)
                    if success:
                        log_application("Indeed", title, company, loc_text, job_url)
                        applied_count += 1
                    else:
                        log_application("Indeed", title, company, loc_text, job_url, status="skipped", notes="Modal too complex")

                    delay = config["bot"]["delay_between_jobs_sec"]
                    await asyncio.sleep(random.uniform(delay, delay + 3))

                except Exception as e:
                    logger.error(f"Error on Indeed card: {e}")
                    continue

    finally:
        # Don't close shared browser — just close this page
        try:
            await page.close()
        except Exception:
            pass

    logger.info(f"Indeed done. Applied to {applied_count} jobs.")
    return applied_count
