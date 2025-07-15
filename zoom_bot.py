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
BOT_BASE_NAME = "TestBot"

# The time to wait before starting the *next* new bot
STAGGER_SECONDS = 5

# How many times a bot will retry before giving up completely.
MAX_ATTEMPTS_PER_BOT = 3
# ==============================================================================

# --- Helper Functions (No changes needed) ---
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36"
]
def generate_random_name(base_name):
    return f"{base_name}-{random.choices(string.digits, k=4)[0]}"
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
            sleep_duration = random.randint(90, 150) # Increased interval
            await asyncio.sleep(sleep_duration)
            await page.mouse.move(random.randint(0, 500), random.randint(0, 500))
            participants_button = page.get_by_role("button", name="Participants")
            if await participants_button.is_visible():
                await participants_button.click()
        except Exception as e:
            print(f"🛑 [{bot_name}] Keep-alive stopped. Bot likely kicked or meeting ended: {e}")
            break # Exit keep-alive loop, which will then allow the browser to close

async def run_bot_instance(playwright: Playwright, bot_id: int):
    """
    Represents a single 'slot' for a bot. It will keep retrying to fill
    that slot until it succeeds or runs out of attempts.
    """
    base_bot_name = f"{BOT_BASE_NAME}-{str(bot_id).zfill(2)}" # e.g., TestBot-01
    
    for attempt in range(1, MAX_ATTEMPTS_PER_BOT + 1):
        browser = None
        unique_bot_name = f"{base_bot_name} (A{attempt})"
        
        try:
            print(f"[{base_bot_name}] Launching attempt #{attempt}/{MAX_ATTEMPTS_PER_BOT}...")
            browser = await playwright.chromium.launch(
                headless=True,
                args=["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream", "--disable-gpu"]
            )
            context = await browser.new_context(
                user_agent=random.choice(USER_AGENTS),
                ignore_https_errors=True,
                viewport={'width': 1280, 'height': 720}
            )
            page = await context.new_page()

            direct_url = get_web_client_url(MEETING_URL, MEETING_PASSCODE)
            await page.goto(direct_url, timeout=90000)

            for _ in range(3):
                try: await page.get_by_text("Continue without microphone and camera").click(timeout=5000)
                except: break
            
            await page.locator('#input-for-name').wait_for(timeout=45000)
            await page.locator('#input-for-name').fill(unique_bot_name)

            await page.get_by_role("button", name="Join").click(timeout=45000)

            try:
                await page.get_by_role("button", name="Join Audio by Computer").wait_for(timeout=60000)
            except:
                print(f"[{unique_bot_name}] Did not find audio button, but assuming success.")
            
            # --- SUCCESS ---
            # If we get here, the bot is in. It starts its forever loop.
            # It will NEVER reach the 'finally' block from here unless keep_alive breaks.
            await keep_alive_in_meeting(page, unique_bot_name)
            
            # This 'break' is only reached if keep_alive stops gracefully.
            break

        except Exception as e:
            # --- FAILURE ---
            print(f"❌ [{unique_bot_name}] Attempt #{attempt} failed: {e}")
            if attempt == MAX_ATTEMPTS_PER_BOT:
                print(f"⚰️ [{base_bot_name}] Has failed all attempts and is giving up.")
            else:
                # Wait before the next attempt to let server/resources recover.
                await asyncio.sleep(20)

        finally:
            # THIS IS KEY: This block is now ONLY reached if keep_alive breaks,
            # or if the try block throws a critical exception (failure).
            # A successful, active bot will be stuck in the keep_alive loop and never get here.
            if browser:
                await browser.close()
                print(f"[{unique_bot_name}] Browser closed.")
                
async def main():
    """Main function launches all bot "slots" with a stagger."""
    async with async_playwright() as p:
        tasks = []
        for i in range(NUM_BOTS):
            # Create a task for the bot "slot". This slot will manage its own retries.
            task = asyncio.create_task(run_bot_instance(p, i))
            tasks.append(task)
            
            # Stagger the *initial start* of each bot slot.
            if i < NUM_BOTS - 1:
                print(f"--> Staggering: Waiting {STAGGER_SECONDS}s before starting next bot slot...")
                await asyncio.sleep(STAGGER_SECONDS)
        
        print(f"\nAll {NUM_BOTS} bot slots have been launched. They will now run and retry as needed.")
        await asyncio.gather(*tasks)

if __name__ == "__main__":
    if not MEETING_URL or "your-company" in MEETING_URL:
        print("!!! ERROR: Please configure your MEETING_URL !!!")
    else:
        asyncio.run(main())
