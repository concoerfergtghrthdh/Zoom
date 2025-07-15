import asyncio
import random
import string
import re
import os
from playwright.async_api import async_playwright, Playwright

# ==============================================================================
# ---  CONFIGURATION ---
# ==============================================================================
MEETING_URL = os.getenv("ZOOM_URL", "https://your-company.zoom.us/j/1234567890")
MEETING_PASSCODE = os.getenv("ZOOM_PASSCODE", "your_passcode")
NUM_BOTS = int(os.getenv("NUM_BOTS_ENV", 30))
BOT_BASE_NAME = "TestBot"

# --- BATCH PROCESSING CONTROLS ---
BATCH_SIZE = 5
INTERVAL_SECONDS = 60
CONCURRENCY_LIMIT = BATCH_SIZE
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

async def keep_alive_in_meeting(page: Playwright.page, bot_name: str):
    """Simulates user activity to prevent being kicked for inactivity."""
    print(f"✅ [{bot_name}] Successfully joined. Starting keep-alive routine.")
    while True:
        try:
            sleep_duration = random.randint(60, 120)
            print(f"[{bot_name}] Keep-alive: Next action in {sleep_duration} seconds.")
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

async def run_bot(playwright: Playwright, bot_id: int, semaphore: asyncio.Semaphore):
    bot_name = generate_random_name(BOT_BASE_NAME)
    async with semaphore:
        print(f"[{bot_name}] Semaphore acquired. Launching bot #{bot_id + 1}...")
        
        direct_url = get_web_client_url(MEETING_URL, MEETING_PASSCODE)
        if not direct_url: return

        # --- THIS IS THE CORRECTED LINE 1 ---
        browser = await playwright.chromium.launch(
            headless=True,
            args=["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream"]
        )
        
        # --- THIS IS THE CORRECTED LINE 2 ---
        context = await browser.new_context(
            user_agent=random.choice(USER_AGENTS),
            ignore_https_errors=True,
            viewport={'width': 1280, 'height': 720}
        )

        page = await context.new_page()
        try:
            await page.goto(direct_url, timeout=60000)
            
            for _ in range(3):
                try: await page.get_by_text("Continue without microphone and camera").click(timeout=2500)
                except Exception: break
            
            await page.wait_for_timeout(1000)
            await page.locator('#input-for-name').fill(bot_name)

            for _ in range(3):
                try: await page.get_by_text("Continue without microphone and camera").click(timeout=2500)
                except Exception: break

            await page.get_by_role("button", name="Join").click(timeout=30000)
            await page.wait_for_timeout(3000)
            await page.get_by_role("button", name="Join Audio by Computer").wait_for(timeout=60000)
            
            # Switch to the active keep-alive routine
            await keep_alive_in_meeting(page, bot_name)

        except Exception as e:
            print(f"❌ [{bot_name}] A critical error occurred: {e}")
            await page.screenshot(path=f'error_{bot_name}.png')
        finally:
            print(f"[{bot_name}] Task finished. Closing browser and releasing semaphore.")
            await browser.close()


async def main():
    """Main function to launch bots in controlled batches with a pause in between."""
    semaphore = asyncio.Semaphore(CONCURRENCY_LIMIT)
    async with async_playwright() as p:
        all_tasks = [run_bot(p, i, semaphore) for i in range(NUM_BOTS)]
        for i in range(0, len(all_tasks), BATCH_SIZE):
            batch = all_tasks[i:i + BATCH_SIZE]
            print(f"\n--- Starting Batch {i // BATCH_SIZE + 1} of {len(batch)} bots ---")
            await asyncio.gather(*batch)
            if i + BATCH_SIZE < len(all_tasks):
                print(f"--- Batch Complete. Pausing for {INTERVAL_SECONDS} seconds before next batch... ---\n")
                await asyncio.sleep(INTERVAL_SECONDS)
    print("\n--- All batches processed. Script finished. ---")


if __name__ == "__main__":
    if "your-company.zoom.us" in MEETING_URL:
        print("!!! ERROR: Please configure your MEETING_URL before running! !!!")
    else:
        print(f"Starting script for {NUM_BOTS} bots in batches of {BATCH_SIZE}.")
        print(f"There will be a {INTERVAL_SECONDS} second interval between batches.")
        asyncio.run(main())
