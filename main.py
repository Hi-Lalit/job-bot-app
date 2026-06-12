"""
Job Application Bot — Main Entry Point
"""

import asyncio
import argparse
import sys
from loguru import logger
from scrapers.utils import load_config, close_shared_browser
from tracker.db import init_db, print_summary

logger.remove()
logger.add(sys.stdout, format="<green>{time:HH:mm:ss}</green> | <level>{level:<8}</level> | {message}", colorize=True)
logger.add("logs/bot_{time:YYYY-MM-DD}.log", rotation="1 day", retention="7 days")

async def run_all(config, sites):
    total = 0

    # Lazy imports ensure we don't load modules unless we need them
    if "naukri" in sites:
        from scrapers.naukri import run_naukri
        logger.info("===== Starting Naukri =====")
        count = await run_naukri(config)
        total += count

    if "linkedin" in sites:
        from scrapers.linkedin import run_linkedin
        logger.info("===== Starting LinkedIn Easy Apply =====")
        count = await run_linkedin(config)
        total += count

    if "linkedin-posts" in sites:
        from scrapers.linkedin_posts import run_linkedin_posts
        logger.info("===== Starting LinkedIn Post Search =====")
        count = await run_linkedin_posts(config)
        total += count

    if "indeed" in sites:
        from scrapers.indeed import run_indeed
        logger.info("===== Starting Indeed =====")
        count = await run_indeed(config)
        total += count

    if "instahyre" in sites:
        # We only call run_instahyre, which manages its own internal login logic
        from scrapers.instahyre import run_instahyre
        logger.info("===== Starting Instahyre =====")
        count = await run_instahyre(config)
        total += count

    return total

def main():
    parser = argparse.ArgumentParser(description="Job Application Bot")
    parser.add_argument(
        "--site",
        choices=["naukri", "linkedin", "linkedin-posts", "indeed", "instahyre", "all"],
        default="all",
        help="Which site to run (default: all)"
    )
    args = parser.parse_args()

    config = load_config()
    init_db()

    sites = ["naukri", "linkedin", "linkedin-posts", "indeed", "instahyre"] if args.site == "all" else [args.site]

    logger.info(f"Starting bot for: {', '.join(sites)}")
    logger.info(f"Max applications per run: {config['filters']['max_applications_per_run']}")
    logger.info("Press Ctrl+C at any time to stop.")

    try:
        total = asyncio.run(run_all(config, sites))
        logger.success(f"All done! Total applications this run: {total}")
    except KeyboardInterrupt:
        logger.warning("Stopped by user (Ctrl+C).")
    except Exception as e:
        logger.error(f"Bot crashed: {e}")
    finally:
        # Cleanup routine
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
        if loop.is_running():
            asyncio.ensure_future(close_shared_browser())
        else:
            loop.run_until_complete(close_shared_browser())
            
        print_summary()

if __name__ == "__main__":
    main()