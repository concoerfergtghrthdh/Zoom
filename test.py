import asyncio
import random
import re
import os
from playwright.async_api import async_playwright, Playwright, Page

# ==============================================================================
# ---  CONFIGURATION ---
# ==============================================================================
MEETING_URL = os.getenv("ZOOM_URL")
MEETING_PASSCODE = os.getenv("ZOOM_PASSCODE")
# The TARGET number of bots you want to have successfully joined the meeting.
TARGET_BOT_COUNT = int(os.getenv("NUM_BOTS_ENV", 30))

NAMES_FILE = "names.txt"

# The MAXIMUM number of bots (browsers) attempting to join at the same time.
# Set this to a number the server can handle to prevent OOM errors.
CONCURRENCY_LIMIT = 15
# ==============================================================================

# --- Helper Functions ---
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36",
    # ... more user agents ...
]

def get_web_client_url(meeting_url, passcode):
    match = re.search(r'/j/(\d+)', meeting_url)
    if not match: return None
    meeting_id = match.group(1)
    base_domain_match = re.search(r'https?://[^/]+', meeting_url)
    return f"{base_domain_match.group(0)}/wc/join/{meeting_id}?pwd={passcode}" if base_domain_match else None

async def keep_alive_in_meeting(page: Page, bot_name: str):
    print(f"✅ [{bot_name}] Successfully joined! Entering keep-alive routine.")
    while True:
        try:
            await asyncio.sleep(random.randint(90, 150))
            await page.mouse.move(random.randint(0, 500), random.randint(0, 500))
            if await page.get_by_role("button", name="Participants").is_visible():
                await page.get_by_role("button", name="Participants").click()
        except Exception as e:
            print(f"🛑 [{bot_name}] Keep-alive stopped. Bot was likely kicked or meeting ended: {e}")
            break

async def join_meeting_attempt(playwright: Playwright, name: str):
    """A single attempt for a bot to join. Returns True on success, False on failure."""
    browser = None
    try:
        print(f"🚀 [{name}] Attempting to join...")
        browser = await playwright.chromium.launch(headless=True, args=["--use-fake-ui-for-media-stream", "--disable-gpu"])
        context = await browser.new_context(user_agent=random.choice(USER_AGENTS), ignore_https_errors=True)
        page = await context.new_page()

        await page.goto(get_web_client_url(MEETING_URL, MEETING_PASSCODE), timeout=90000)

        # Fail fast if CAPTCHA is detected
        try:
            await page.locator('iframe[title="reCAPTCHA"]').wait_for(timeout=7000)
            print(f"🚨 [{name}] CAPTCHA DETECTED. Aborting this attempt.")
            return False
        except:
            pass # No CAPTCHA, proceed

        for _ in range(3):
            try: await page.get_by_text("Continue without microphone and camera").click(timeout=5000)
            except: break

        await page.locator('#input-for-name').wait_for(timeout=45000)
        await page.locator('#input-for-name').fill(name)
        await page.get_by_role("button", name="Join").click(timeout=45000)

        try: await page.get_by_role("button", name="Join Audio by Computer").wait_for(timeout=60000)
        except: print(f"[{name}] Did not find audio button, but assuming success.")
            
        await keep_alive_in_meeting(page, name)
        # If keep_alive loop breaks, we consider the bot's job done.
        return True # Considered a "successful run" even if it gets kicked later.
    except Exception as e:
        print(f"❌ [{name}] Join attempt failed: {e}")
        return False
    finally:
        if browser: await browser.close()


async def worker(worker_id: int, queue: asyncio.Queue, playwright: Playwright, semaphore: asyncio.Semaphore, success_counter: asyncio.Event):
    """A worker that continuously grabs names from the queue and tries to join."""
    while not queue.empty() and not success_counter.is_set():
        name = await queue.get()
        print(f"👷 Worker #{worker_id} picked up name: {name}")

        async with semaphore:
            print(f"Worker #{worker_id} acquired a concurrency slot for {name}.")
            success = await join_meeting_attempt(playwright, name)
            if success:
                # If a bot gets in, great! This worker's job is technically done,
                # as the bot will now live on its own in keep_alive.
                # In a real-world scenario, you might have a global success count.
                pass
            else:
                # The attempt failed. This worker will now loop to grab another name.
                print(f"Worker #{worker_id} failed with {name}, will try another name if available.")
        
        queue.task_done()
    
    print(f"👷 Worker #{worker_id} is finishing: queue is empty or target met.")


async def main():
    """Main function to set up and run the bot pool."""
    try:
        with open(NAMES_FILE, 'r', encoding='utf-8') as f:
            all_names = [line.strip() for line in f if line.strip()]
        if not all_names: return print(f"❌ ERROR: '{NAMES_FILE}' is empty.")
    except FileNotFoundError: return print(f"❌ ERROR: '{NAMES_FILE}' not found.")
    
    name_queue = asyncio.Queue()
    for name in all_names:
        await name_queue.put(name)
    
    print(f"Loaded {name_queue.qsize()} names into the queue.")
    print(f"Goal: {TARGET_BOT_COUNT} successful bots.")
    print(f"Concurrency Limit: {CONCURRENCY_LIMIT} simultaneous join attempts.")

    semaphore = asyncio.Semaphore(CONCURRENCY_LIMIT)
    # This event is a placeholder for a more complex success counter.
    # For now, the script will run until the names list is exhausted or it's cancelled.
    success_counter = asyncio.Event()

    async with async_playwright() as p:
        # Create a pool of "workers". The number of workers is the target bot count.
        tasks = [worker(i + 1, name_queue, p, semaphore, success_counter) for i in range(TARGET_BOT_COUNT)]
        await asyncio.gather(*tasks)

if __name__ == "__main__":
    if not MEETING_URL or "your-company" in MEETING_URL:
        print("!!! ERROR: Please configure your MEETING_URL !!!")
    else:
        asyncio.run(main())
