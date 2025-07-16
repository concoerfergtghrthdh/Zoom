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

# The MAXIMUM number of bots (browsers) attempting to join at the same time.
# This controls the load on the server.
CONCURRENCY_LIMIT = 15
# ==============================================================================

# --- Global State Management ---
successful_bot_count = 0
target_reached = asyncio.Event()

# --- Helper Functions ---
USER_AGENTS = ["Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36"]
def get_web_client_url(meeting_url, passcode):
    match = re.search(r'/j/(\d+)', meeting_url)
    if not match: return None
    meeting_id = match.group(1)
    base_domain_match = re.search(r'https?://[^/]+', meeting_url)
    return f"{base_domain_match.group(0)}/wc/join/{meeting_id}?pwd={passcode}" if base_domain_match else None

async def keep_alive_in_meeting(page: Page, context, browser, bot_name: str):
    """The 'forever' task for a successful bot. Cleans up its own resources."""
    global successful_bot_count
    successful_bot_count += 1
    print(f"✅ [{bot_name}] SUCCESS! Current count: {successful_bot_count}/{TARGET_BOT_COUNT}")
    
    if successful_bot_count >= TARGET_BOT_COUNT:
        print("🎉 Target bot count reached!")
        target_reached.set()

    while True:
        try:
            # Check every minute if the main script signaled to stop
            if target_reached.is_set() and successful_bot_count < TARGET_BOT_COUNT:
                 # In case some bots leave, clear the flag to allow relaunching.
                 target_reached.clear()

            await asyncio.sleep(random.randint(90, 150))
            if page.is_closed(): break
            await page.mouse.move(random.randint(0, 500), random.randint(0, 500))
        except Exception:
            break
    
    print(f"🛑 [{bot_name}] Keep-alive stopped. Bot has left the meeting.")
    successful_bot_count -= 1
    # If we drop below the target, signal that we need more bots.
    if target_reached.is_set() and successful_bot_count < TARGET_BOT_COUNT:
        target_reached.clear()

    await context.close()
    await browser.close()


async def attempt_to_join(playwright: Playwright, name: str, semaphore: asyncio.Semaphore):
    """
    Performs ONE join attempt. Releases the semaphore when done.
    """
    async with semaphore: # Acquire a slot from the pool of 15
        print(f"🚀 [{name}] Starting join attempt (Slot acquired)...")
        browser = None
        context = None
        try:
            browser = await playwright.chromium.launch(headless=True, args=["--use-fake-ui-for-media-stream", "--disable-gpu"])
            context = await browser.new_context(user_agent=random.choice(USER_AGENTS), ignore_https_errors=True, storage_state=None)
            page = await context.new_page()

            await page.goto(get_web_client_url(MEETING_URL, MEETING_PASSCODE), timeout=90000)
            
            # Simplified login flow
            try: await page.locator('iframe[title="reCAPTCHA"]').wait_for(timeout=7000) ; raise Exception("CAPTCHA DETECTED")
            except: pass
            for _ in range(3):
                try: await page.get_by_text("Continue without microphone and camera").click(timeout=5000)
                except: break
            await page.locator('#input-for-name').fill(name, timeout=45000)
            await page.get_by_role("button", name="Join").click(timeout=45000)
            try: await page.get_by_role("button", name="Join Audio by Computer").wait_for(timeout=60000)
            except: pass
                
            # --- SUCCESS ---
            # Launch the keep-alive task in the background. It is now independent.
            # We hand over responsibility for the browser/context to this new task.
            asyncio.create_task(keep_alive_in_meeting(page, context, browser, name))
            return # IMPORTANT: Exit without cleaning up browser/context here.

        except Exception as e:
            # --- FAILURE ---
            print(f"❌ [{name}] Join attempt failed: {e}")
            if context: await context.close()
            if browser: await browser.close()
            # The semaphore is automatically released when this 'with' block ends.


async def main():
    """Reads all names and creates a continuous stream of join attempts."""
    try:
        with open(NAMES_FILE, 'r', encoding='utf-8') as f:
            all_names = [line.strip() for line in f if line.strip()]
        if not all_names: return print(f"❌ ERROR: '{NAMES_FILE}' is empty.")
    except FileNotFoundError: return print(f"❌ ERROR: '{NAMES_FILE}' not found.")
    
    print(f"Loaded {len(all_names)} names. Goal: {TARGET_BOT_COUNT} bots in meeting.")
    print(f"Running up to {CONCURRENCY_LIMIT} join attempts at a time.")
    
    semaphore = asyncio.Semaphore(CONCURRENCY_LIMIT)
    
    async with async_playwright() as p:
        tasks = []
        name_index = 0
        while not target_reached.is_set():
            if name_index >= len(all_names):
                print("⚠️ All names have been used. Waiting for bots to leave to try again...")
                await target_reached.wait() # Wait until the target is met and then maybe drops
                # Reset index to reuse names if necessary
                name_index = 0
            
            # Get the next name
            name_to_try = all_names[name_index]
            name_index += 1
            
            # Create a fire-and-forget task for the attempt
            task = asyncio.create_task(attempt_to_join(p, name_to_try, semaphore))
            tasks.append(task)
            # Give a tiny break just to prevent overwhelming the asyncio loop itself on startup
            await asyncio.sleep(0.1)

        print("\n🏁 Target bot count was reached. No new bots will be launched unless the count drops.")
        # We can gather the initial launch tasks, but the keep_alive tasks will live on.
        await asyncio.gather(*tasks)


if __name__ == "__main__":
    if not MEETING_URL or "your-company" in MEETING_URL:
        asyncio.run(main())
    else:
        asyncio.run(main())
