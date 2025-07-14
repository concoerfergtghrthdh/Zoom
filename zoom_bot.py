import asyncio
import random
import string
import re
import os
from playwright.async_api import async_playwright, Playwright

# ==============================================================================
# ---  CONFIGURATION  ---
# ==============================================================================
# Read from environment variables, provided by GitHub Actions or a local shell
MEETING_URL = os.getenv("ZOOM_URL", "https://your-company.zoom.us/j/1234567890") # Added default for local testing
MEETING_PASSCODE = os.getenv("ZOOM_PASSCODE", "your_passcode") # Added default for local testing
NUM_BOTS = int(os.getenv("NUM_BOTS_ENV", 20))
BOT_BASE_NAME = "TestBot"

# --- NEW: CONCURRENCY LIMITER ---
# The maximum number of bots to launch and run simultaneously.
# This prevents overwhelming the server. Adjust based on your server's specs.
# A good starting point for a standard GitHub runner (2-core, 7GB RAM) is 4-6.
CONCURRENCY_LIMIT = 5
# ==============================================================================

# (USER_AGENTS, generate_random_name, and get_web_client_url functions remain the same)
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
    if not match:
        return None
    meeting_id = match.group(1)
    base_domain_match = re.search(r'https?://[^/]+', meeting_url)
    base_domain = base_domain_match.group(0) if base_domain_match else ""
    return f"{base_domain}/wc/join/{meeting_id}?pwd={passcode}"


async def run_bot(playwright: Playwright, bot_id: int, semaphore: asyncio.Semaphore): # <-- Added semaphore parameter
    """
    Launches a single bot instance, joins the meeting, and keeps it alive.
    Waits for the semaphore before starting.
    """
    bot_name = generate_random_name(BOT_BASE_NAME)
    
    # This bot will wait here until a "slot" in the semaphore is free
    async with semaphore:
        print(f"[{bot_name}] Semaphore acquired. Launching bot...")

        direct_url = get_web_client_url(MEETING_URL, MEETING_PASSCODE)
        if not direct_url:
            print(f"[{bot_name}] Halting due to invalid meeting URL.")
            return
        
        browser = await playwright.chromium.launch(
            headless=True,
            args=["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream"]
        )
        context = await browser.new_context(
            user_agent=random.choice(USER_AGENTS), ignore_https_errors=True, viewport={'width': 1280, 'height': 720}
        )
        page = await context.new_page()

        try:
            print(f"[{bot_name}] Navigating to direct web client URL...")
            await page.goto(direct_url, timeout=60000)

            # Initial dialog clearing loop
            for i in range(3):
                try:
                    await page.get_by_text("Continue without microphone and camera").click(timeout=2500)
                    print(f"[{bot_name}] Cleared initial dialog #{i + 1}.")
                    await page.wait_for_timeout(500)
                except Exception:
                    break

            await page.wait_for_timeout(1000)

            print(f"[{bot_name}] Looking for name input...")
            name_input_locator = page.locator('#input-for-name')
            await name_input_locator.wait_for(timeout=30000)
            await name_input_locator.fill(bot_name)

            # --- NEW CRITICAL FIX ---
            # Re-check for dialogs that may have appeared *after* filling the name
            print(f"[{bot_name}] Re-checking for dialogs after filling name...")
            for i in range(3):
                try:
                    await page.get_by_text("Continue without microphone and camera").click(timeout=2500)
                    print(f"[{bot_name}] Cleared recurring dialog #{i + 1}.")
                    await page.wait_for_timeout(500)
                except Exception:
                    break
            # --- END OF NEW FIX ---

            print(f"[{bot_name}] Clicking the join button...")
            await page.get_by_role("button", name="Join").click(timeout=30000) # Ensure button is now visible
            
            print(f"[{bot_name}] Waiting for lobby or final meeting entry...")
            await page.get_by_role("button", name="Join Audio by Computer").wait_for(timeout=60000)
            print(f"✅ [{bot_name}] Successfully joined the meeting! Keeping bot alive...")
            await asyncio.sleep(3600)

        except Exception as e:
            print(f"❌ [{bot_name}] A critical error occurred: {e}")
            screenshot_path = f'error_{bot_name}.png'
            await page.screenshot(path=screenshot_path)
            print(f"📸 Screenshot saved to {screenshot_path}")

        finally:
            print(f"[{bot_name}] Closing browser and releasing semaphore.")
            await browser.close()


async def main():
    """Main function to create a semaphore and launch all bots concurrently but controlled."""
    # Create the semaphore to limit concurrent runs to our defined limit
    semaphore = asyncio.Semaphore(CONCURRENCY_LIMIT)
    
    async with async_playwright() as p:
        # Pass the semaphore to each bot task
        tasks = [run_bot(p, i, semaphore) for i in range(NUM_BOTS)]
        await asyncio.gather(*tasks)


if __name__ == "__main__":
    if not MEETING_URL or not MEETING_PASSCODE or "/j/" not in MEETING_URL:
        print("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
        print("!!! ERROR: Ensure MEETING_URL and MEETING_PASSCODE are set correctly!")
        print("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
    else:
        print(f"Starting script for {NUM_BOTS} bots with a concurrency of {CONCURRENCY_LIMIT}...")
        asyncio.run(main())
