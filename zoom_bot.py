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

STAGGER_SECONDS = 4
# How many times a single bot should attempt to join before giving up.
MAX_ATTEMPTS_PER_BOT = 3
# ==============================================================================

# ... (Helper functions remain the same) ...
USER_AGENTS = [...] # Omitted for brevity
def generate_random_name(base_name): ...
def get_web_client_url(meeting_url, passcode): ...
async def keep_alive_in_meeting(page: Page, bot_name: str): ...


async def run_bot(playwright: Playwright, bot_id: int):
    """
    Main bot logic. It will now try to join multiple times before giving up.
    """
    bot_name = f"{BOT_BASE_NAME}-{str(bot_id).zfill(2)}" # e.g., TestBot-01
    
    for attempt in range(1, MAX_ATTEMPTS_PER_BOT + 1):
        print(f"[{bot_name}] Launching attempt #{attempt}/{MAX_ATTEMPTS_PER_BOT}...")
        
        browser = None  # Ensure browser is defined in the outer scope
        try:
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

            direct_url = get_web_client_url(MEETING_URL, MEETING_PASSCODE)
            await page.goto(direct_url, timeout=90000)

            for _ in range(3):
                try: await page.get_by_text("Continue without microphone and camera").click(timeout=3000)
                except: break
            
            await page.wait_for_timeout(1000)
            unique_bot_name = f"{bot_name}-{attempt}" # Make name unique per attempt
            await page.locator('#input-for-name').fill(unique_bot_name)

            for _ in range(3):
                try: await page.get_by_text("Continue without microphone and camera").click(timeout=3000)
                except: break
                
            await page.get_by_role("button", name="Join").click(timeout=45000) # Increased timeout

            try:
                await page.get_by_role("button", name="Join Audio by Computer").wait_for(timeout=30000)
            except:
                print(f"[{unique_bot_name}] Could not find audio button, but proceeding.")
            
            # If we reach this line, the bot joined successfully!
            print(f"✅ [{unique_bot_name}] Successfully joined on attempt #{attempt}.")
            await keep_alive_in_meeting(page, unique_bot_name)
            
            # Break the loop since we succeeded
            break

        except Exception as e:
            print(f"❌ [{bot_name}] Attempt #{attempt} failed: {e}")
            if attempt == MAX_ATTEMPTS_PER_BOT:
                print(f"⚰️ [{bot_name}] Reached max attempts. This bot will now stop.")
                # Save a screenshot only on the final failure
                if 'page' in locals() and page:
                     await page.screenshot(path=f'error_{bot_name}_final_attempt.png')
            else:
                # Wait before the next attempt
                print(f"[{bot_name}] Waiting 20 seconds before next attempt.")
                await asyncio.sleep(20)

        finally:
            # Always close the browser after each attempt, successful or not
            if browser:
                await browser.close()
                
# --- Main function does not need changes ---
async def main():
    async with async_playwright() as p:
        tasks = []
        for i in range(NUM_BOTS):
            task = asyncio.create_task(run_bot(p, i))
            tasks.append(task)
            if i < NUM_BOTS - 1:
                await asyncio.sleep(STAGGER_SECONDS)
        print("\nAll bot tasks have been launched. They will now run indefinitely.")
        await asyncio.gather(*tasks)

if __name__ == "__main__":
    if not MEETING_URL or "your-company" in MEETING_URL:
        print("!!! ERROR: Please configure your MEETING_URL !!!")
    else:
        asyncio.run(main())
