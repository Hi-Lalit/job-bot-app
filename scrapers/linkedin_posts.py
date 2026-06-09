import asyncio
import random
import re
import smtplib
import os
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from loguru import logger
from scrapers.utils import launch_browser, keyword_match
from tracker.db import log_application, already_applied

# ── Email sending ──────────────────────────────────────────────────────────────

def send_application_email(to_email, hr_name, job_title, company, config):
    """Send resume + cover email directly to HR."""
    from_email  = config["personal"]["email"]
    smtp_pass   = os.getenv("EMAIL_APP_PASSWORD", "")
    your_name   = config["personal"]["full_name"]
    phone       = config["personal"]["phone"]
    linkedin    = config["personal"].get("linkedin_url", "")
    github      = config["personal"].get("portfolio_url", "")
    resume_path = config["resume"]["path"]

    if not smtp_pass:
        logger.warning("EMAIL_APP_PASSWORD not set in .env — cannot send email.")
        return False

    subject = f"Application for {job_title} — {your_name}"

    body = f"""Dear {hr_name or 'Hiring Manager'},

I came across your post about the {job_title} opening{f' at {company}' if company and company != 'Unknown' else ''} on LinkedIn and would love to apply for this role.

I am an immediate joiner with hands-on experience in DevOps tools and practices including:
• CI/CD pipelines (Jenkins, GitHub Actions, GitLab CI)
• Containerization & orchestration (Docker, Kubernetes)
• Cloud platforms (AWS, Azure, GCP)
• Infrastructure as Code (Terraform, Ansible)
• Linux administration & scripting (Bash, Python)
• Monitoring & logging (Prometheus, Grafana, ELK stack)

I am willing to relocate anywhere across India and am available to join immediately.

Please find my resume attached. I would love the opportunity to discuss how I can contribute to your team.

LinkedIn : {linkedin}
GitHub   : {github}
Phone    : {phone}

Thank you for your time and consideration.

Best regards,
{your_name}
"""

    try:
        msg = MIMEMultipart()
        msg["From"]    = from_email
        msg["To"]      = to_email
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))

        # Attach resume
        try:
            with open(resume_path, "rb") as f:
                part = MIMEBase("application", "octet-stream")
                part.set_payload(f.read())
                encoders.encode_base64(part)
                part.add_header(
                    "Content-Disposition",
                    f"attachment; filename=\"{your_name} - DevOps Resume.pdf\""
                )
                msg.attach(part)
        except Exception as e:
            logger.warning(f"Could not attach resume: {e}")

        # Send via Gmail SMTP
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(from_email, smtp_pass)
            server.sendmail(from_email, to_email, msg.as_string())

        logger.success(f"Email sent to {to_email} ({hr_name}) for '{job_title}'")
        return True

    except Exception as e:
        logger.error(f"Failed to send email to {to_email}: {e}")
        return False


# ── Email extraction ───────────────────────────────────────────────────────────

def extract_emails(text):
    """Extract all email addresses from a block of text."""
    pattern = r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}"
    emails  = re.findall(pattern, text)
    # Filter out image/media URLs that look like emails
    filtered = [e for e in emails if not any(x in e for x in [".png", ".jpg", ".gif", ".mp4"])]
    return list(set(filtered))


def extract_job_title(text, keywords):
    """Try to find the job title mentioned in a post."""
    text_lower = text.lower()
    for kw in keywords:
        if kw.lower() in text_lower:
            return kw
    return "DevOps Engineer"


def extract_company(text):
    """Try to find company name from post text."""
    patterns = [
        r"at\s+([A-Z][a-zA-Z\s&.]{2,30}(?:Ltd|Inc|Pvt|Technologies|Tech|Solutions|Systems|Services)?)",
        r"with\s+([A-Z][a-zA-Z\s&.]{2,30}(?:Ltd|Inc|Pvt|Technologies|Tech|Solutions|Systems|Services)?)",
        r"for\s+([A-Z][a-zA-Z\s&.]{2,30}(?:Ltd|Inc|Pvt|Technologies|Tech|Solutions|Systems|Services)?)",
        r"company[:\s]+([A-Z][a-zA-Z\s&.]{2,30})",
        r"organization[:\s]+([A-Z][a-zA-Z\s&.]{2,30})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1).strip()
    return "Unknown"


# ── LinkedIn post scraper ──────────────────────────────────────────────────────

HIRING_TRIGGERS = [
    "hiring", "we are hiring", "looking for", "job opening",
    "urgent requirement", "immediate requirement", "vacancy",
    "opportunity", "join our team", "we need", "recruiting",
    "job opportunity", "open position", "apply now",
    "send your resume", "send cv", "dm me", "reach out",
    "connect with me", "email me", "send resume to",
]

async def is_hiring_post(text):
    """Check if a LinkedIn post is a job/hiring post."""
    text_lower = text.lower()
    return any(trigger in text_lower for trigger in HIRING_TRIGGERS)


async def expand_post(page, post):
    """Click 'see more' to expand truncated post text."""
    try:
        see_more = await post.query_selector("button.feed-shared-inline-show-more-text__see-more-less-toggle")
        if see_more:
            await see_more.click()
            await asyncio.sleep(0.5)
    except Exception:
        pass


async def get_post_text(post):
    """Extract full text from a LinkedIn post."""
    try:
        text_el = await post.query_selector(
            ".feed-shared-update-v2__description, "
            ".feed-shared-text, "
            ".update-components-text"
        )
        if text_el:
            return (await text_el.inner_text()).strip()
    except Exception:
        pass
    return ""


async def get_post_author(post):
    """Extract author name from a LinkedIn post."""
    try:
        author_el = await post.query_selector(
            ".feed-shared-actor__name, "
            ".update-components-actor__name, "
            "span.hoverable-link-text"
        )
        if author_el:
            return (await author_el.inner_text()).strip()
    except Exception:
        pass
    return "HR"


async def get_post_url(post, page):
    """Extract the post URL."""
    try:
        link_el = await post.query_selector(
            "a.app-aware-link[href*='activity'], "
            "a[href*='/posts/'], "
            "time a"
        )
        if link_el:
            href = await link_el.get_attribute("href")
            if href:
                return href if href.startswith("http") else f"https://www.linkedin.com{href}"
    except Exception:
        pass
    return page.url


async def open_post_and_get_emails(context, post_url):
    """Open individual post page to extract emails from text + comments."""
    page = None
    emails = []
    try:
        page = await context.new_page()
        await page.goto(post_url, wait_until="domcontentloaded", timeout=15000)
        await asyncio.sleep(2)

        # Get full page text
        full_text = await page.inner_text("body")
        emails = extract_emails(full_text)

        # Also try expanding comments
        try:
            load_more = await page.query_selector("button:has-text('Load more comments')")
            if load_more:
                await load_more.click()
                await asyncio.sleep(1)
                full_text = await page.inner_text("body")
                emails = extract_emails(full_text)
        except Exception:
            pass

    except Exception as e:
        logger.warning(f"Could not open post page: {e}")
    finally:
        if page:
            try:
                await page.close()
            except Exception:
                pass
    return emails


# ── Main runner ────────────────────────────────────────────────────────────────

browser_closed_posts = False


async def search_linkedin_posts(page, keyword, location="India"):
    """Search LinkedIn feed for hiring posts."""
    query = f"{keyword} hiring"
    url = (
        f"https://www.linkedin.com/search/results/content/?"
        f"keywords={query.replace(' ', '%20')}"
        f"&origin=GLOBAL_SEARCH_HEADER"
        f"&sortBy=date_posted"
    )
    logger.info(f"Searching LinkedIn posts: '{query}'")
    await page.goto(url, wait_until="domcontentloaded")
    await asyncio.sleep(3)


async def run_linkedin_posts(config):
    """Search LinkedIn posts by HRs and send application emails."""
    global browser_closed_posts
    browser_closed_posts = False

    keywords    = config["job_search"]["keywords"]
    skip_kws    = config["filters"]["skip_keywords"]
    max_apps    = config["filters"]["max_applications_per_run"] or 20
    sent_count  = 0
    emailed_hrs = set()  # avoid emailing same HR twice

    pw, browser, context, page = await launch_browser(config, site="linkedin")

    def on_disconnect():
        global browser_closed_posts
        browser_closed_posts = True
        logger.warning("Browser closed — stopping post search.")

    browser.on("disconnected", lambda: on_disconnect())

    try:
        # Login
        logger.info("Opening LinkedIn...")
        await page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded")
        await asyncio.sleep(2)
        logger.warning("=" * 55)
        logger.warning("Please LOGIN to LinkedIn manually in the browser.")
        logger.warning("You have 3 minutes. Bot continues after login.")
        logger.warning("=" * 55)

        logged_in = False
        for i in range(36):
            await asyncio.sleep(5)
            if any(x in page.url for x in ["feed", "mynetwork", "jobs"]):
                logger.success("Login detected!")
                logged_in = True
                break
            if i % 6 == 0 and i > 0:
                logger.info(f"Waiting for login... ({(36-i)*5}s remaining)")

        if not logged_in:
            logger.error("Login timeout — skipping post search.")
            return 0

        done = False
        for keyword in keywords:
            if done or browser_closed_posts or sent_count >= max_apps:
                break
            if keyword_match(keyword, skip_kws):
                continue

            await search_linkedin_posts(page, keyword)

            # Scroll to load more posts
            for _ in range(3):
                await page.keyboard.press("End")
                await asyncio.sleep(1.5)

            # Get all post containers
            posts = await page.query_selector_all(
                ".search-results__list .search-result, "
                ".feed-shared-update-v2, "
                ".occludable-update"
            )
            logger.info(f"Found {len(posts)} posts for '{keyword}'")

            for post in posts:
                if done or browser_closed_posts or sent_count >= max_apps:
                    done = True
                    break

                try:
                    # Expand truncated post
                    await expand_post(page, post)

                    post_text = await get_post_text(post)
                    if not post_text:
                        continue

                    # Only process hiring posts
                    if not await is_hiring_post(post_text):
                        continue

                    # Skip if matches skip keywords
                    if keyword_match(post_text, skip_kws):
                        continue

                    author    = await get_post_author(post)
                    post_url  = await get_post_url(post, page)
                    job_title = extract_job_title(post_text, keywords)
                    company   = extract_company(post_text)

                    logger.info(f"Hiring post found: '{job_title}' by {author}")

                    # First check if email is directly in post text
                    emails = extract_emails(post_text)

                    # If no email in post, open full post page to look deeper
                    if not emails and post_url:
                        logger.info("No email in post — checking full post page...")
                        emails = await open_post_and_get_emails(context, post_url)

                    if not emails:
                        logger.info(f"No email found for post by {author} — skipping.")
                        continue

                    # Send email to each address found
                    for email in emails:
                        if email in emailed_hrs:
                            logger.info(f"Already emailed {email} — skipping.")
                            continue
                        if already_applied(post_url + email):
                            logger.info(f"Already applied via {email} — skipping.")
                            continue

                        success = send_application_email(
                            to_email=email,
                            hr_name=author,
                            job_title=job_title,
                            company=company,
                            config=config
                        )
                        if success:
                            emailed_hrs.add(email)
                            log_application(
                                site="LinkedIn-Post",
                                job_title=job_title,
                                company=company,
                                location="LinkedIn Post",
                                job_url=post_url + email,
                                notes=f"Email sent to {email}"
                            )
                            sent_count += 1
                            logger.success(f"[{sent_count}/{max_apps}] Emailed → {email} for '{job_title}'")

                    delay = config["bot"]["delay_between_jobs_sec"]
                    await asyncio.sleep(random.uniform(delay, delay + 2))

                except Exception as e:
                    logger.error(f"Error processing post: {e}")
                    continue

    finally:
        # Close only this page — shared browser stays open for next site
        try:
            await page.close()
        except Exception:
            pass

    logger.info(f"LinkedIn post search done. Emails sent: {sent_count}")
    return sent_count
