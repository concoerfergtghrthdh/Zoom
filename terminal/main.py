import asyncio
import random
import string
import re
import os
from playwright.async_api import async_playwright, Playwright, Page

# ==============================================================================
# ---  CONFIGURATION DEFAULTS ---
# These will be used if the user just presses Enter at the prompts.
# ==============================================================================
DEFAULT_NUM_BOTS = 30
DEFAULT_STAGGER_SECONDS = 5
DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_NAMES_FILE = "names.txt"
# ==============================================================================

# --- Helper Functions (No changes needed) ---
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36"
]
def get_web_client_url(meeting_url, passcode):
    match = re.search(r'/j/(\d+)', meeting_url)
    if not match: return None
    meeting_id = match.group(1)
    base_domain_match = re.search(r'https?://[^/]+', meeting_url)
    # Default to us05web if the base domain isn't in a typical URL format
    if not base_domain_match: base_domain = "https://us05web.zoom.us"
    else: base_domain = base_domain_match.group(0)
    return f"{base_domain}/wc/join/{meeting_id}?pwd={passcode}"

async def keep_alive_in_meeting(page: Page, bot_name: str):
    """Simulates user activity to prevent being kicked for inactivity."""
    print(f"✅ [{bot_name}] Successfully joined! Entering keep-alive routine.")
    while True:
        try:
            sleep_duration = random.randint(90, 150)
            await asyncio.sleep(sleep_duration)
            await page.mouse.move(random.randint(0, 500), random.randint(0, 500))
            participants_button = page.get_by_role("button", name="Participants")
            if await participants_button.is_visible():
                await participants_button.click()
        except Exception as e:
            print(f"🛑 [{bot_name}] Keep-alive stopped. Bot likely kicked or meeting ended: {e}")
            break

async def run_and_manage_bot(playwright: Playwright, name: str, bot_id: int, url: str, passcode: str, max_attempts: int):
    """
    A persistent 'slot' for one bot. If it fails to join, it will retry.
    """
    for attempt in range(1, max_attempts + 1):
        browser = None
        log_name = f"{name} (Bot #{bot_id})"
        try:
            print(f"[{log_name}] Launching attempt #{attempt}/{max_attempts}...")
            browser = await playwright.chromium.launch(
                headless=True,
                args=["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream", "--disable-gpu"]
            )
            context = await browser.new_context(user_agent=random.choice(USER_AGENTS), ignore_https_errors=True)
            page = await context.new_page()
            direct_url = get_web_client_url(url, passcode)
            await page.goto(direct_url, timeout=90000)

            for _ in range(3):
                try: await page.get_by_text("Continue without microphone and camera").click(timeout=5000)
                except: break
            
            await page.locator('#input-for-name').wait_for(timeout=45000)
            await page.locator('#input-for-name').fill(name)
            
            await page.get_by_role("button", name="Join").click(timeout=45000)
            
            try:
                await page.get_by_role("button", name="Join Audio by Computer").wait_for(timeout=60000)
            except:
                print(f"[{log_name}] Did not find audio button, but assuming success.")
            
            await keep_alive_in_meeting(page, log_name)
            # A successful bot never closes its browser, it lives in keep_alive
            # so we only break the retry loop here.
            break 
        except Exception as e:
            print(f"❌ [{log_name}] Attempt #{attempt} failed: {e}")
            if attempt == max_attempts:
                print(f"⚰️ [{log_name}] has failed all attempts and is giving up.")
            else:
                await asyncio.sleep(20)
        finally:
            # This only runs for failed attempts because a successful bot gets
            # stuck in the keep_alive loop and never reaches here.
            if browser:
                await browser.close()


async def main(url: str, passcode: str, num_bots: int, stagger: int, max_attempts: int, names_file: str):
    """Reads names from a file and launches the specified number of bots."""
    try:
        with open(names_file, 'r', encoding='utf-8') as f:
            all_names = [line.strip() for line in f if line.strip()]
        if not all_names:
            return print(f"❌ ERROR: '{names_file}' is empty. No names available.")
    except FileNotFoundError:
        return print(f"❌ ERROR: The names file '{names_file}' was not found.")
    
    # Determine the number of bots to launch
    if len(all_names) < num_bots:
        print(f"⚠️ WARNING: You requested {num_bots} bots, but only found {len(all_names)} names in '{names_file}'.")
        num_bots = len(all_names)
    
    names_to_use = all_names[:num_bots]
    print(f"Preparing to launch {num_bots} bots...")

    async with async_playwright() as p:
        tasks = []
        for i, name in enumerate(names_to_use):
            task = asyncio.create_task(run_and_manage_bot(p, name, i + 1, url, passcode, max_attempts))
            tasks.append(task)
            
            if i < len(names_to_use) - 1:
                print(f"--> Staggering: Waiting {stagger}s before starting next bot...")
                await asyncio.sleep(stagger)
        
        print(f"\nAll {len(tasks)} bot tasks have been launched. They will now run and retry as needed.")
        await asyncio.gather(*tasks)


if __name__ == "__main__":
    # --- THIS IS THE NEW INTERACTIVE PROMPT SECTION ---
    print("--- Zoom Bot Launcher ---")
    
    # Get Meeting ID
    meeting_id = input("Enter the Zoom Meeting ID: ").strip()
    while not meeting_id.isdigit():
        print("Invalid Meeting ID. Please enter numbers only.")
        meeting_id = input("Enter the Zoom Meeting ID: ").strip()

    # Get Passcode
    passcode = input("Enter the meeting passcode: ").strip()
    
    # Get Target Number of Bots
    num_bots_str = input(f"Enter the number of bots to launch (default: {DEFAULT_NUM_BOTS}): ").strip()
    target_bots = int(num_bots_str) if num_bots_str.isdigit() else DEFAULT_NUM_BOTS
    
    # Get Stagger Time
    stagger_str = input(f"Enter time in seconds to wait between starting each bot (default: {DEFAULT_STAGGER_SECONDS}): ").strip()
    stagger_time = int(stagger_str) if stagger_str.isdigit() else DEFAULT_STAGGER_SECONDS

    # Get Max Retries
    attempts_str = input(f"Enter max retries for each bot if it fails (default: {DEFAULT_MAX_ATTEMPTS}): ").strip()
    max_attempts = int(attempts_str) if attempts_str.isdigit() else DEFAULT_MAX_ATTEMPTS
    
    # Get Names File
    names_file_path = input(f"Enter path to names file (default: {DEFAULT_NAMES_FILE}): ").strip()
    if not names_file_path:
        names_file_path = DEFAULT_NAMES_FILE
    
    # We construct a standard URL. You can change 'us05web' if needed.
    meeting_url = f"https://us05web.zoom.us/j/{meeting_id}"
    
    print("\nStarting bot launch process...")
    try:
        # Pass the collected info to the main async function
        asyncio.run(main(meeting_url, passcode, target_bots, stagger_time, max_attempts, names_file_path))
    except KeyboardInterrupt:
        print("\nScript cancelled by user. Exiting.")
