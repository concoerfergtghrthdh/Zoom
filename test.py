import asyncio
import random
import string
import re
import os
from playwright.async_api import async_playwright, Playwright, Page

# ==============================================================================
# ---  CONFIGURATION ---
# ==============================================================================
MEETING_URL = os.getenv("ZOOM_URL")
MEETING_PASSCODE = os.getenv("ZOOM_PASSCODE")
NUM_BOTS = int(os.getenv("NUM_BOTS_ENV", 30))
NAMES_FILE = "names.txt"

# --- SERVER STABILITY CONTROLS ---
# The MAXIMUM number of bots (browsers) to run at the same time.
# Based on your logs, the GitHub runner can handle about 15-18. Let's set it to a safe 15.
# This prevents the Out-of-Memory Killer from terminating your successful bots.
CONCURRENCY_LIMIT = 15

MAX_ATTEMPTS_PER_BOT = 3
# ==============================================================================

# --- Helper Functions ---
USER_AGENTS = ["..."] # Omitted for brevity
def get_web_client_url(meeting_url, passcode):
    match = re.search(r'/j/(\d+)', meeting_url)
    if not match: return None
    meeting_id = match.group(1)
    base_domain_match = re.search(r'https?://[^/]+', meeting_url)
    return f"{base_domain_match.group(0)}/wc/join/{meeting_id}?pwd={passcode}" if base_domain_match else None

async def keep_alive_in_meeting(page: Page, bot_name: str):
    """Simulates user activity to prevent being kicked for inactivity."""
    print(f"✅ [{bot_name}] Successfully joined! Entering keep-alive routine.")
    while True:
        try:
            await asyncio.sleep(random.randint(90, 150))
            await page.mouse.move(random.randint(0, 500), random.randint(0, 500))
            if await page.get_by_role("button", name="Participants").is_visible():
                await page.get_by_role("button", name="Participants").click()
        except Exception as e:
            print(f"🛑 [{bot_name}] Keep-alive stopped. Bot likely kicked or meeting ended: {e}")
            break

async def run_and_manage_bot(playwright: Playwright, name: str, bot_id: int, semaphore: asyncio.Semaphore):
    """
    Acquires a concurrency slot and manages the lifecycle of one bot,
    including retries, until it succeeds or gives up.
    """
    async with semaphore:
        log_name = f"{name} (Bot #{bot_id})"
        print(f"[{log_name}] Acquired a concurrency slot. Starting attempts...")
        for attempt in range(1, MAX_ATTEMPTS_PER_BOT + 1):
            browser = None
            try:
                print(f"[{log_name}] Launching attempt #{attempt}/{MAX_ATTEMPTS_PER_BOT}...")
                browser = await playwright.chromium.launch(headless=True, args=["--use-fake-ui-for-media-stream", "--disable-gpu"])
                context = await browser.new_context(user_agent=random.choice(USER_AGENTS), ignore_https_errors=True)
                page = await context.new_page()
                await page.goto(get_web_client_url(MEETING_URL, MEETING_PASSCODE), timeout=90000)

                for _ in range(3):
                    try: await page.get_by_text("Continue without microphone and camera").click(timeout=5000)
                    except: break
                
                await page.locator('#input-for-name').wait_for(timeout=45000)
                await page.locator('#input-for-name').fill(name)
                await page.get_by_role("button", name="Join").click(timeout=45000)
                
                try: await page.get_by_role("button", name="Join Audio by Computer").wait_for(timeout=60000)
                except: print(f"[{log_name}] Did not find audio button, but assuming success.")
                
                await keep_alive_in_meeting(page, log_name)
                # Successful bot will stay in keep_alive loop and hold its semaphore slot.
                # It will only exit this 'with' block if it's kicked.
                break
            except Exception as e:
                print(f"❌ [{log_name}] Attempt #{attempt} failed: {e}")
                if attempt < MAX_ATTEMPTS_PER_BOT:
                    await asyncio.sleep(20)
                else:
                    print(f"⚰️ [{log_name}] has failed all attempts and is giving up.")
            finally:
                if browser: await browser.close()
    print(f"[{log_name}] has released its concurrency slot.")


async def main():
    """Reads names and creates a managed task for each bot."""
    try:
        with open(NAMES_FILE, 'r', encoding='utf-8') as f:
            all_names = [line.strip() for line in f if line.strip()]
        if not all_names: return print(f"❌ ERROR: '{NAMES_FILE}' is empty.")
    except FileNotFoundError: return print(f"❌ ERROR: '{NAMES_FILE}' not found.")
    
    num_to_launch = min(NUM_BOTS, len(all_names))
    if num_to_launch < NUM_BOTS:
        print(f"⚠️ WARNING: Requested {NUM_BOTS} bots, but only {num_to_launch} names available.")
    
    names_for_this_run = all_names[:num_to_launch]
    print(f"Preparing to launch {num_to_launch} bots with a concurrency limit of {CONCURRENCY_LIMIT}.")
    
    semaphore = asyncio.Semaphore(CONCURRENCY_LIMIT)
    
    async with async_playwright() as p:
        # Create all tasks at once. The semaphore will manage the queue.
        tasks = [run_and_manage_bot(p, name, i + 1, semaphore) for i, name in enumerate(names_for_this_run)]
        await asyncio.gather(*tasks)

if __name__ == "__main__":
    if not MEETING_URL or "your-company" in MEETING_URL:
        print("!!! ERROR: Please configure your MEETING_URL !!!")
    else:
        asyncio.run(main())
