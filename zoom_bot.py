import asyncio
import random
import string
import re
import os
from playwright.async_api import async_playwright, Playwright

# ==============================================================================
# ---  CONFIGURATION (no changes needed here) ---
# ==============================================================================
MEETING_URL = os.getenv("ZOOM_URL", "https://your-company.zoom.us/j/1234567890")
MEETING_PASSCODE = os.getenv("ZOOM_PASSCODE", "your_passcode")
NUM_BOTS = int(os.getenv("NUM_BOTS_ENV", 30))
BOT_BASE_NAME = "TestBot"
BATCH_SIZE = 5
INTERVAL_SECONDS = 60
CONCURRENCY_LIMIT = BATCH_SIZE
# ==============================================================================

# (All helper functions like USER_AGENTS, generate_random_name, get_web_client_url remain the same)
USER_AGENTS = ["..."] # Omitted for brevity
def generate_random_name(base_name):
    # ... code ...
    return f"{base_name}-{random.choices(string.digits, k=4)}"
def get_web_client_url(meeting_url, passcode):
    # ... code ...
    return f"{...}/wc/join/{...}?pwd={...}"


# --- NEW: KEEP-ALIVE FUNCTION ---
async def keep_alive_in_meeting(page: Playwright.page, bot_name: str):
    """
    Simulates user activity to prevent being kicked for inactivity.
    This runs in a loop after the bot has successfully joined.
    """
    print(f"✅ [{bot_name}] Successfully joined. Starting keep-alive routine.")
    while True:
        try:
            # 1. Wait a random interval to prevent all bots from acting at once
            sleep_duration = random.randint(60, 120)
            print(f"[{bot_name}] Keep-alive: Next action in {sleep_duration} seconds.")
            await asyncio.sleep(sleep_duration)

            # 2. Simulate mouse movement to a random coordinate
            viewport = page.viewport_size
            if viewport:
                rand_x = random.randint(100, viewport['width'] - 100)
                rand_y = random.randint(100, viewport['height'] - 100)
                print(f"[{bot_name}] Keep-alive: Moving mouse to ({rand_x}, {rand_y}).")
                await page.mouse.move(rand_x, rand_y)
            
            # 3. Simulate a safe click on the "Participants" button to seem active
            participants_button = page.get_by_role("button", name="Participants")
            if await participants_button.is_visible():
                 print(f"[{bot_name}] Keep-alive: Clicking Participants button.")
                 await participants_button.click()
            else:
                 print(f"[{bot_name}] Keep-alive: Participants button not found, skipping click.")

        except Exception as e:
            # If any error occurs (e.g., the meeting has ended, bot was kicked),
            # the bot will stop its routine.
            print(f"🛑 [{bot_name}] Keep-alive routine stopped (meeting likely ended or bot was kicked): {e}")
            break

# --- MODIFIED: run_bot FUNCTION ---
async def run_bot(playwright: Playwright, bot_id: int, semaphore: asyncio.Semaphore):
    bot_name = generate_random_name(BOT_BASE_NAME)
    async with semaphore:
        print(f"[{bot_name}] Semaphore acquired. Launching bot #{bot_id + 1}...")
        # ... (all setup logic for joining remains the same) ...
        # (This part of the code is stable and correct)
        direct_url = get_web_client_url(MEETING_URL, MEETING_PASSCODE)
        if not direct_url: return
        browser = await playwright.chromium.launch(headless=True, args=["..."])
        context = await browser.new_context(user_agent=random.choice(USER_AGENTS), ...)
        page = await context.new_page()
        try:
            # ... login flow from goto to click("Join") ...
            await page.goto(direct_url, timeout=60000)
            for _ in range(3):
                try: await page.get_by_text("Continue without microphone and camera").click(timeout=2500)
                except: break
            await page.wait_for_timeout(1000)
            await page.locator('#input-for-name').fill(bot_name)
            for _ in range(3):
                try: await page.get_by_text("Continue without microphone and camera").click(timeout=2500)
                except: break
            await page.get_by_role("button", name="Join").click(timeout=30000)
            await page.wait_for_timeout(3000)
            await page.get_by_role("button", name="Join Audio by Computer").wait_for(timeout=60000)

            # --- CRITICAL CHANGE: Replace simple sleep with active keep-alive ---
            await keep_alive_in_meeting(page, bot_name)

        except Exception as e:
            print(f"❌ [{bot_name}] A critical error occurred: {e}")
            await page.screenshot(path=f'error_{bot_name}.png')
        finally:
            print(f"[{bot_name}] Task finished. Closing browser and releasing semaphore.")
            await browser.close()


# (main function with batch processing remains the same, it is correct)
async def main():
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
