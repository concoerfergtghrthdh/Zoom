import asyncio
import random
import re
import os
from playwright.async_api import async_playwright, Playwright, Page

# ==============================================================================
# ---  CONFIGURATION DEFAULTS ---
# These are only used if the user just presses Enter at the prompts.
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
    # Default to us05web if the base domain isn't in a typical URL format
    if not base_domain_match: base_domain = "https://us05web.zoom.us"
    else: base_domain = base_domain_match.group(0)
    return f"{base_domain}/wc/join/{meeting_id}?pwd={passcode}"

async def keep_alive_in_meeting(page: Page, context, browser, bot_name: str, target_count):
    """The 'forever' task for a successful bot. Cleans up its own resources."""
    global successful_bot_count, target_reached
    successful_bot_count += 1
    print(f"✅ [{bot_name}] SUCCESS! Current count: {successful_bot_count}/{target_count}")
    
    if successful_bot_count >= target_count:
        print(f"🎉 Target bot count of {target_count} reached!")
        target_reached.set()

    while True:
        try:
            if target_reached.is_set() and successful_bot_count < target_count:
                 target_reached.clear()
            await asyncio.sleep(random.randint(90, 150))
            if page.is_closed(): break
            await page.mouse.move(random.randint(0, 500), random.randint(0, 500))
        except Exception: break
    
    print(f"🛑 [{bot_name}] Keep-alive stopped. Bot has left the meeting.")
    successful_bot_count -= 1
    if successful_bot_count < target_count:
        target_reached.clear()
    await context.close()
    await browser.close()


async def attempt_to_join(playwright: Playwright, name: str, semaphore: asyncio.Semaphore, meeting_url: str, passcode: str, target_count: int):
    """Performs ONE join attempt. Releases the semaphore when done."""
    async with semaphore:
        if target_reached.is_set(): return # Don't start new attempts if target is already met
        
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
                
            asyncio.create_task(keep_alive_in_meeting(page, context, browser, name, target_count))
            return
        except Exception as e:
            print(f"❌ [{name}] Join attempt failed: {e}")
            if context: await context.close()
            if browser: await browser.close()


async def main(url: str, passcode: str, num_bots: int, concurrency: int, names_file: str):
    """Reads names and creates a continuous stream of join attempts."""
    global target_reached, successful_bot_count
    target_reached.clear()
    successful_bot_count = 0

    try:
        with open(names_file, 'r', encoding='utf-8') as f:
            all_names = [line.strip() for line in f if line.strip()]
        if not all_names: return print(f"❌ ERROR: '{names_file}' is empty.")
    except FileNotFoundError: return print(f"❌ ERROR: The names file '{names_file}' was not found.")
    
    # Check if we have enough names for the target, otherwise use all available names.
    if len(all_names) < num_bots:
        print(f"⚠️ WARNING: You requested {num_bots} bots, but only found {len(all_names)} names.")
        num_bots = len(all_names)
        
    print(f"\nLoaded {len(all_names)} names. Goal: {num_bots} bots in meeting.")
    print(f"Running up to {concurrency} join attempts at a time.\n")
    
    semaphore = asyncio.Semaphore(concurrency)
    
    async with async_playwright() as p:
        tasks = []
        name_index = 0
        
        while not target_reached.is_set():
            if name_index >= len(all_names):
                print("⚠️ All names have been used. Waiting for bots to leave to try again...")
                # Wait until the target is met and then maybe drops, or wait indefinitely if never met.
                try:
                    await asyncio.wait_for(target_reached.wait(), timeout=30.0)
                except asyncio.TimeoutError:
                    pass
                
                if not target_reached.is_set():
                    print("🔄 Bot count dropped below target or target never met. Re-using names...")
                    name_index = 0
                else:
                    break # Target was met and remains so, end the launch loop.

            if successful_bot_count >= num_bots:
                target_reached.set()
                continue
            
            name_to_try = all_names[name_index]
            name_index += 1
            
            task = asyncio.create_task(attempt_to_join(p, name_to_try, semaphore, url, passcode, num_bots))
            tasks.append(task)
            # Give a tiny break just to prevent overwhelming the asyncio loop itself on startup
            await asyncio.sleep(0.1)

        print("\n🏁 Target bot count reached. The script will now only launch new bots if the count drops.")
        # Create a final task that just waits, keeping the script alive
        await asyncio.Event().wait()


if __name__ == "__main__":
    # --- THIS IS THE NEW INTERACTIVE PROMPT SECTION ---
    print("--- Zoom Bot Launcher ---")
    
    meeting_id = input("Enter the Zoom Meeting ID: ").strip()
    while not meeting_id.isdigit():
        print("Invalid Meeting ID. Please enter numbers only.")
        meeting_id = input("Enter the Zoom Meeting ID: ").strip()

    # We construct a standard URL. You can add more regions if needed.
    meeting_url = f"https://us05web.zoom.us/j/{meeting_id}"

    passcode = input("Enter the meeting passcode: ").strip()

    num_bots_str = input(f"Enter the target number of bots (default: {DEFAULT_TARGET_BOT_COUNT}): ").strip()
    target_bots = int(num_bots_str) if num_bots_str.isdigit() else DEFAULT_TARGET_BOT_COUNT

    concurrency_str = input(f"Enter concurrency limit (simultaneous attempts, default: {DEFAULT_CONCURRENCY_LIMIT}): ").strip()
    concurrency_limit = int(concurrency_str) if concurrency_str.isdigit() else DEFAULT_CONCURRENCY_LIMIT

    names_file_path = input(f"Enter path to names file (default: {DEFAULT_NAMES_FILE}): ").strip()
    if not names_file_path:
        names_file_path = DEFAULT_NAMES_FILE
    
    print("\nStarting bot launch process...")
    try:
        # Pass the collected info to the main async function
        asyncio.run(main(meeting_url, passcode, target_bots, concurrency_limit, names_file_path))
    except KeyboardInterrupt:
        print("\nScript cancelled by user. Exiting.")
