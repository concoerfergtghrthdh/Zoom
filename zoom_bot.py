import asyncio
import random
import string
import re
import os
from playwright.async_api import async_playwright, Playwright, Page

# ==============================================================================
# ---  CONFIGURATION ---
# ==============================================================================
MEETING_URL = os.getenv("ZOOM_URL", "https://your-company.zoom.us/j/1234567890")
MEETING_PASSCODE = os.getenv("ZOOM_PASSCODE", "your_passcode")
NUM_BOTS = int(os.getenv("NUM_BOTS_ENV", 30))
BOT_BASE_NAME = "TestBot"

# --- RATE-LIMITING CONTROL ---
# The number of seconds to wait before starting the *next* bot.
# This prevents Zoom from rate-limiting your IP for too many concurrent connection attempts.
# A value between 3-5 is recommended.
STAGGER_SECONDS = 4
# ==============================================================================

# --- List of potential user agents ---
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36"
]

def generate_random_name(base_name):
    random_suffix = ''.join(random.choices(string.digits, k=4))
    return f"{base_name}-{random_suffix}"

def get_web_client_url(meeting_url, passcode):
    match = re.search(r'/j/(\d+)', meeting_url)
    if not match: return None
    meeting_id = match.group(1)
    base_domain_match = re.search(r'https?://[^/]+', meeting_url)
    base_domain = base_domain_match.group(0) if base_domain_match else ""
    return f"{base_domain}/wc/join/{meeting_id}?pwd={passcode}"

async def keep_alive_in_meeting(page: Page, bot_name: str):
    """Simulates user activity to prevent being kicked for inactivity."""
    print(f"✅ [{bot_name}] Bot is stable in meeting. Starting keep-alive routine.")
    while True:
        try:
            sleep_duration = random.randint(60, 120)
            await asyncio.sleep(sleep_duration)
            viewport = page.viewport_size
            if viewport:
                rand_x, rand_y = random.randint(100, viewport['width'] - 100), random.randint(100, viewport['height'] - 100)
                await page.mouse.move(rand_x, rand_y)
            participants_button = page.get_by_role("button", name="Participants")
            if await participants_button.is_visible():
                 await participants_button.click()
        except Exception as e:
            print(f"🛑 [{bot_name}] Keep-alive routine stopped (meeting likely ended or bot was kicked): {e}")
            break

async def run_bot(playwright: Playwright, bot_id: int): # <-- Semaphore removed
    bot_name = generate_random_name(BOT_BASE_NAME)
    print(f"[{bot_name}] Preparing to launch bot #{bot_id + 1}...")
    direct_url = get_web_client_url(MEETING_URL, MEETING_PASSCODE)
    if not direct_url: return

    browser = await playwright.chromium.launch(
        headless=True,
        args=["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream"]
    )
    context = await browser.new_context(
        user_agent=random.choice(USER_AGENTS),
        ignore_https_errors=True,
        viewport={'width': 1280, 'height': 720}
    )
    page = await context.new_page()
    try:
        await page.goto(direct_url, timeout=90000) # Increased timeout for heavily loaded servers
        
        for _ in range(3):
            try: await page.get_by_text("Continue without microphone and camera").click(timeout=3000)
            except Exception: break
        
        await page.wait_for_timeout(1000)
        await page.locator('#input-for-name').fill(bot_name)

        for _ in range(3):
            try: await page.get_by_text("Continue without microphone and camera").click(timeout=3000)
            except Exception: break

        await page.get_by_role("button", name="Join").click(timeout=30000)
        
        try:
            join_audio_button = page.get_by_role("button", name="Join Audio by Computer")
            await join_audio_button.wait_for(timeout=30000)
            await join_audio_button.click()
        except Exception:
            print(f"[{bot_name}] Could not connect audio, but assuming successful entry.")
        
        await keep_alive_in_meeting(page, bot_name)
    except Exception as e:
        print(f"❌ [{bot_name}] A critical error occurred during login: {e}")
        await page.screenshot(path=f'error_{bot_name}.png')
    finally:
        # This part will now only run if the bot fails login or gets kicked
        print(f"[{bot_name}] Task finished or failed. Closing its browser.")
        await browser.close()


async def main():
    """Main function to launch all bots with a staggered start."""
    async with async_playwright() as p:
        tasks = []
        for i in range(NUM_BOTS):
            # Create a task for the bot to run.
            # This doesn't block; the task is added to the event loop.
            task = asyncio.create_task(run_bot(p, i))
            tasks.append(task)
            
            # Wait for the specified interval before starting the next one.
            if i < NUM_BOTS - 1: # No need to wait after the last bot
                print(f"--> Staggering: Waiting {STAGGER_SECONDS}s before launching next bot...")
                await asyncio.sleep(STAGGER_SECONDS)
        
        print("\nAll bot tasks have been launched. They will now run indefinitely.")
        # Wait for all the launched tasks to complete.
        # Since successful bots run forever, this line will effectively wait forever.
        await asyncio.gather(*tasks)


if __name__ == "__main__":
    if "your-company.zoom.us" in MEETING_URL:
        print("!!! ERROR: Please configure your MEETING_URL before running! !!!")
    else:
        print(f"Starting script to launch {NUM_BOTS} bots.")
        print(f"A new bot will be launched every {STAGGER_SECONDS} seconds.")
        asyncio.run(main())
