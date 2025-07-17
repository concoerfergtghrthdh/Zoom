import asyncio
import random
import re
import os
import argparse # Import the argparse library
from playwright.async_api import async_playwright, Playwright, Page

# ==============================================================================
# ---  CONFIGURATION DEFAULTS ---
# These will be overridden by command-line arguments.
# ==============================================================================
DEFAULT_TARGET_BOT_COUNT = 30
DEFAULT_CONCURRENCY_LIMIT = 15
DEFAULT_NAMES_FILE = "names.txt"
# ==============================================================================

# --- Global State Management ---
successful_bot_count = 0
target_reached = asyncio.Event()

# --- Helper Functions (No changes needed) ---
USER_AGENTS = ["Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36"]

def get_web_client_url(meeting_url, passcode):
    match = re.search(r'/j/(\d+)', meeting_url)
    if not match: return None
    meeting_id = match.group(1)
    base_domain_match = re.search(r'https?://[^/]+', meeting_url)
    return f"{base_domain_match.group(0)}/wc/join/{meeting_id}?pwd={passcode}" if base_domain_match else None

async def keep_alive_in_meeting(page: Page, context, browser, bot_name: str):
    """The 'forever' task for a successful bot. Cleans up its own resources."""
    global successful_bot_count, target_reached
    successful_bot_count += 1
    print(f"✅ [{bot_name}] SUCCESS! Current count: {successful_bot_count}/{TARGET_BOT_COUNT}")
    
    if successful_bot_count >= TARGET_BOT_COUNT:
        print(f"🎉 Target bot count of {TARGET_BOT_COUNT} reached!")
        target_reached.set()

    while True:
        try:
            # Check if a bot left, signaling we need more
            if target_reached.is_set() and successful_bot_count < TARGET_BOT_COUNT:
                 target_reached.clear()
            await asyncio.sleep(random.randint(90, 150))
            if page.is_closed(): break
            await page.mouse.move(random.randint(0, 500), random.randint(0, 500))
        except Exception: break
    
    print(f"🛑 [{bot_name}] Keep-alive stopped. Bot has left the meeting.")
    successful_bot_count -= 1
    # If we drop below the target, signal that we need more bots.
    if successful_bot_count < TARGET_BOT_COUNT:
        target_reached.clear()

    await context.close()
    await browser.close()


async def attempt_to_join(playwright: Playwright, name: str, semaphore: asyncio.Semaphore, meeting_url: str, passcode: str):
    """Performs ONE join attempt. Releases the semaphore when done."""
    async with semaphore:
        print(f"🚀 [{name}] Starting join attempt (Slot acquired)...")
        browser = None
        context = None
        try:
            browser = await playwright.chromium.launch(headless=True, args=["--use-fake-ui-for-media-stream", "--disable-gpu"])
            context = await browser.new_context(user_agent=random.choice(USER_AGENTS), ignore_https_errors=True, storage_state=None)
            page = await context.new_page()

            await page.goto(get_web_client_url(meeting_url, passcode), timeout=90000)
            
            try: await page.locator('iframe[title="reCAPTCHA"]').wait_for(timeout=7000); raise Exception("CAPTCHA DETECTED")
            except: pass
            for _ in range(3):
                try: await page.get_by_text("Continue without microphone and camera").click(timeout=5000)
                except: break
            await page.locator('#input-for-name').fill(name, timeout=45000)
            await page.get_by_role("button", name="Join").click(timeout=45000)
            try: await page.get_by_role("button", name="Join Audio by Computer").wait_for(timeout=60000)
            except: pass
                
            asyncio.create_task(keep_alive_in_meeting(page, context, browser, name))
            return
        except Exception as e:
            print(f"❌ [{name}] Join attempt failed: {e}")
            if context: await context.close()
            if browser: await browser.close()


async def main(args):
    """Reads names and creates a continuous stream of join attempts based on args."""
    global TARGET_BOT_COUNT # Make sure we can access the global target
    TARGET_BOT_COUNT = args.num_bots

    try:
        with open(args.names_file, 'r', encoding='utf-8') as f:
            all_names = [line.strip() for line in f if line.strip()]
        if not all_names: return print(f"❌ ERROR: '{args.names_file}' is empty.")
    except FileNotFoundError: return print(f"❌ ERROR: The names file '{args.names_file}' was not found.")
    
    print(f"Loaded {len(all_names)} names. Goal: {TARGET_BOT_COUNT} bots in meeting.")
    print(f"Running up to {args.concurrency} join attempts at a time.")
    
    semaphore = asyncio.Semaphore(args.concurrency)
    
    async with async_playwright() as p:
        tasks = []
        name_index = 0
        while not target_reached.is_set():
            if name_index >= len(all_names):
                print("⚠️ All names have been used. To add more bots, restart with a new name list or after bots leave.")
                await target_reached.wait()
                # Reset index to allow reusing names if bots leave
                if not target_reached.is_set():
                    print("🔄 Bot count dropped below target. Re-using names from the beginning...")
                    name_index = 0
                else:
                    break
            
            name_to_try = all_names[name_index]
            name_index += 1
            
            task = asyncio.create_task(attempt_to_join(p, name_to_try, semaphore, args.url, args.passcode))
            tasks.append(task)
            await asyncio.sleep(0.1)

        print("\n🏁 Target bot count was reached. No new bots will be launched unless the count drops.")
        # Create a final task that just waits forever or until the program is cancelled.
        # This keeps the main script alive so the background keep-alive tasks can run.
        await asyncio.Event().wait()


if __name__ == "__main__":
    # --- THIS IS THE NEW COMMAND-LINE PARSER ---
    parser = argparse.ArgumentParser(description="Launch Zoom bots for training purposes.")
    
    parser.add_argument("url", help="The full Zoom meeting URL (e.g., 'https://us05web.zoom.us/j/1234567890').")
    parser.add_argument("passcode", help="The passcode for the Zoom meeting.")
    
    parser.add_argument("-n", "--num_bots", type=int, default=DEFAULT_TARGET_BOT_COUNT,
                        help=f"The target number of bots to have in the meeting. Default: {DEFAULT_TARGET_BOT_COUNT}")
    
    parser.add_argument("-c", "--concurrency", type=int, default=DEFAULT_CONCURRENCY_LIMIT,
                        help=f"The maximum number of simultaneous join attempts. Default: {DEFAULT_CONCURRENCY_LIMIT}")

    parser.add_argument("--names_file", default=DEFAULT_NAMES_FILE,
                        help=f"The path to the text file containing one name per line. Default: '{DEFAULT_NAMES_FILE}'")

    args = parser.parse_args()

    # Pass the parsed arguments to the main async function
    asyncio.run(main(args))
