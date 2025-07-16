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
TARGET_BOT_COUNT = int(os.getenv("NUM_BOTS_ENV", 40))
NAMES_FILE = "names.txt"

# Max number of simultaneous JOIN ATTEMPTS to prevent server overload/CAPTCHAs
CONCURRENCY_LIMIT = 15
# Time to wait after a FAILED attempt before adding the name back to the queue
RETRY_DELAY_SECONDS = 30
# ==============================================================================

# --- Helper Functions (No changes needed) ---
USER_AGENTS = ["Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36"]

def get_web_client_url(meeting_url, passcode):
    match = re.search(r'/j/(\d+)', meeting_url)
    if not match: return None
    meeting_id = match.group(1)
    base_domain_match = re.search(r'https?://[^/]+', meeting_url)
    return f"{base_domain_match.group(0)}/wc/join/{meeting_id}?pwd={passcode}" if base_domain_match else None

async def keep_alive_in_meeting(page: Page, context, browser, bot_name: str):
    """
    Simulates user activity and is responsible for its own resource cleanup.
    """
    print(f"✅ [{bot_name}] Successfully joined! Entering keep-alive routine.")
    while True:
        try:
            await asyncio.sleep(random.randint(90, 150))
            if page.is_closed():
                print(f"🛑 [{bot_name}] Page was closed. Ending keep-alive.")
                break
            await page.mouse.move(random.randint(0, 500), random.randint(0, 500))
            participants_button = page.get_by_role("button", name="Participants")
            if await participants_button.is_visible():
                await participants_button.click()
        except Exception as e:
            print(f"🛑 [{bot_name}] Keep-alive stopped. Bot likely kicked or meeting ended: {e}")
            break
    
    # When keep_alive ends, clean up this bot's resources.
    print(f"🧹 [{bot_name}] Cleaning up resources...")
    await context.close()
    await browser.close()

async def join_attempt_worker(playwright: Playwright, name: str, semaphore: asyncio.Semaphore, name_queue: asyncio.Queue, successful_bots: list):
    """
    A worker that performs ONE join attempt. If successful, it launches the keep-alive
    task. If it fails, it can put the name back in the queue.
    """
    async with semaphore:
        print(f"🚀 [{name}] Attempting to join (Concurrency slot acquired)...")
        browser = None
        context = None
        try:
            browser = await playwright.chromium.launch(headless=True, args=["--use-fake-ui-for-media-stream", "--disable-gpu"])
            context = await browser.new_context(user_agent=random.choice(USER_AGENTS), ignore_https_errors=True, storage_state=None)
            page = await context.new_page()

            await page.goto(get_web_client_url(MEETING_URL, MEETING_PASSCODE), timeout=90000)

            captcha_locator = page.locator('iframe[title="reCAPTCHA"]')
            try:
                await captcha_locator.wait_for(timeout=7000)
                print(f"🚨 [{name}] CAPTCHA DETECTED. Failing attempt.")
                raise Exception("CAPTCHA")
            except:
                pass

            for _ in range(3):
                try: await page.get_by_text("Continue without microphone and camera").click(timeout=5000)
                except: break

            await page.locator('#input-for-name').wait_for(timeout=45000)
            await page.locator('#input-for-name').fill(name)
            await page.get_by_role("button", name="Join").click(timeout=45000)
            try: await page.get_by_role("button", name="Join Audio by Computer").wait_for(timeout=60000)
            except: print(f"[{name}] Did not find audio button, but assuming success.")
                
            # --- SUCCESS ---
            # Launch keep_alive as a background task. This bot is now independent.
            # Pass ALL resources (browser, context, page) to it for cleanup.
            keep_alive_task = asyncio.create_task(keep_alive_in_meeting(page, context, browser, name))
            successful_bots.append(keep_alive_task)
            
            # Since this attempt succeeded, we do NOT close the browser here.
            # We return True to signal success to the producer.
            return True

        except Exception as e:
            print(f"❌ [{name}] Join attempt failed: {e}")
            # --- FAILURE ---
            # Clean up resources immediately on failure.
            if context: await context.close()
            if browser: await browser.close()
            # Put the name back in the queue to be retried later.
            print(f"↪️ [{name}] Placing name back in queue for a later retry.")
            await asyncio.sleep(RETRY_DELAY_SECONDS)
            await name_queue.put(name)
            return False

async def producer(playwright: Playwright, name_queue: asyncio.Queue, semaphore: asyncio.Semaphore):
    """The main task that produces join attempts until the target is met."""
    successful_bots = []
    
    while len(successful_bots) < TARGET_BOT_COUNT:
        if name_queue.empty():
            print("⚠️ Name queue is empty. Cannot launch more bots. Waiting for retries or finishing.")
            await asyncio.sleep(30)
            # If still empty after waiting, all possible bots might have failed.
            if name_queue.empty() and all(bot.done() for bot in successful_bots):
                break
            continue

        name_to_try = await name_queue.get()
        print(f"\n--- Launching new join attempt for: {name_to_try} ---")
        print(f"--- Current Success Count: {len(successful_bots)}/{TARGET_BOT_COUNT} ---")

        # Start the worker but don't wait for it here. It runs in the background.
        # The semaphore controls how many can run at once.
        asyncio.create_task(join_attempt_worker(playwright, name_to_try, semaphore, name_queue, successful_bots))

        # Small stagger to prevent a thundering herd, even with semaphore.
        await asyncio.sleep(1) 
    
    print(f"\nTarget of {TARGET_BOT_COUNT} bots reached or name queue exhausted. Monitoring living bots.")
    # Wait for all the long-lived bot tasks to eventually finish (i.e., when they get kicked)
    if successful_bots:
        await asyncio.gather(*successful_bots)

async def main():
    """Sets up the producer/consumer model."""
    try:
        with open(NAMES_FILE, 'r', encoding='utf-8') as f:
            all_names = [line.strip() for line in f if line.strip()]
        if not all_names: return print(f"❌ ERROR: '{NAMES_FILE}' is empty.")
    except FileNotFoundError: return print(f"❌ ERROR: '{NAMES_FILE}' not found.")
    
    name_queue = asyncio.Queue()
    for name in all_names:
        await name_queue.put(name)

    print(f"Loaded {name_queue.qsize()} names into the queue.")
    print(f"Target: {TARGET_BOT_COUNT} successful bots.")
    print(f"Concurrency Limit: {CONCURRENCY_LIMIT} simultaneous join attempts.")

    semaphore = asyncio.Semaphore(CONCURRENCY_LIMIT)

    async with async_playwright() as p:
        await producer(p, name_queue, semaphore)
        
if __name__ == "__main__":
    if not MEETING_URL or "your-company" in MEETING_URL:
        asyncio.run(main())
    else:
        asyncio.run(main())
