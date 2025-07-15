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
# The number of bots you want to join, as specified in your GitHub Action workflow.
NUM_BOTS = int(os.getenv("NUM_BOTS_ENV", 30))

# --- Bot Controls ---
STAGGER_SECONDS = 5
MAX_ATTEMPTS_PER_BOT = 3
NAMES_FILE = "names.txt" # The name of your file containing the list of names
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
    return f"{base_domain_match.group(0)}/wc/join/{meeting_id}?pwd={passcode}" if base_domain_match else None

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

async def run_and_manage_bot(playwright: Playwright, name: str, bot_id: int):
    """
    A persistent 'slot' for one bot. If it fails to join, it will retry.
    Uses a specific name provided to it.
    """
    for attempt in range(1, MAX_ATTEMPTS_PER_BOT + 1):
        browser = None
        # Display the bot's given name and its number for clearer logs
        log_name = f"{name} (Bot #{bot_id})"
        try:
            print(f"[{log_name}] Launching attempt #{attempt}/{MAX_ATTEMPTS_PER_BOT}...")
            browser = await playwright.chromium.launch(
                headless=True,
                args=["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream", "--disable-gpu"]
            )
            context = await browser.new_context(user_agent=random.choice(USER_AGENTS), ignore_https_errors=True)
            page = await context.new_page()
            direct_url = get_web_client_url(MEETING_URL, MEETING_PASSCODE)
            await page.goto(direct_url, timeout=90000)

            for _ in range(3):
                try: await page.get_by_text("Continue without microphone and camera").click(timeout=5000)
                except: break
            
            # --- MODIFIED: Uses the passed 'name' variable ---
            await page.locator('#input-for-name').wait_for(timeout=45000)
            await page.locator('#input-for-name').fill(name)
            
            await page.get_by_role("button", name="Join").click(timeout=45000)
            
            try:
                await page.get_by_role("button", name="Join Audio by Computer").wait_for(timeout=60000)
            except:
                print(f"[{log_name}] Did not find audio button, but assuming success.")
            
            # --- SUCCESS ---
            await keep_alive_in_meeting(page, log_name)
            break
        except Exception as e:
            print(f"❌ [{log_name}] Attempt #{attempt} failed: {e}")
            if attempt == MAX_ATTEMPTS_PER_BOT:
                print(f"⚰️ [{log_name}] has failed all attempts and is giving up.")
            else:
                await asyncio.sleep(20)
        finally:
            if browser:
                await browser.close()


# --- THIS IS THE MAIN LOGIC TO READ THE FILE AND LAUNCH BOTS ---
async def main():
    """Reads names from a file and launches the specified number of bots."""
    try:
        with open(NAMES_FILE, 'r', encoding='utf-8') as f:
            all_names = [line.strip() for line in f if line.strip()]
        if not all_names:
            print(f"❌ ERROR: '{NAMES_FILE}' is empty. No names available to assign.")
            return
    except FileNotFoundError:
        print(f"❌ ERROR: The names file '{NAMES_FILE}' was not found.")
        print("Please create it in your repository and add one name per line.")
        return
    
    # Check if there are enough names for the number of bots requested.
    if len(all_names) < NUM_BOTS:
        print(f"⚠️ WARNING: You requested {NUM_BOTS} bots, but only found {len(all_names)} names in '{NAMES_FILE}'.")
        print(f"Will launch {len(all_names)} bots instead.")
        num_to_launch = len(all_names)
    else:
        num_to_launch = NUM_BOTS
    
    # Get the specific slice of names we will use for this run
    names_for_this_run = all_names[:num_to_launch]
    print(f"Preparing to launch {num_to_launch} bots using the first {num_to_launch} names from the file.")

    async with async_playwright() as p:
        tasks = []
        for i, name in enumerate(names_for_this_run):
            # Pass the playwright instance, the name from the list, and the bot's index (for logging)
            task = asyncio.create_task(run_and_manage_bot(p, name, i + 1))
            tasks.append(task)
            
            if i < len(names_for_this_run) - 1:
                print(f"--> Staggering: Waiting {STAGGER_SECONDS}s before starting next bot...")
                await asyncio.sleep(STAGGER_SECONDS)
        
        print(f"\nAll {len(tasks)} bot tasks have been launched.")
        await asyncio.gather(*tasks)


if __name__ == "__main__":
    if not MEETING_URL or "your-company" in MEETING_URL:
        print("!!! ERROR: Please configure your MEETING_URL !!!")
    else:
        asyncio.run(main())
