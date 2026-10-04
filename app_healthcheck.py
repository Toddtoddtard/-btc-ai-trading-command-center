"""Check the public access gate and wake a sleeping app without signing in."""
import re
import time
from pathlib import Path
from playwright.sync_api import sync_playwright


def main():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        deadline = time.monotonic() + 150
        woke = False
        try:
            page.goto('https://bettingbusa.streamlit.app/', wait_until='domcontentloaded', timeout=45000)
            while time.monotonic() < deadline:
                for frame in page.frames:
                    wake = frame.get_by_role('button', name='Yes, get this app back up!', exact=True)
                    if not woke and wake.is_visible():
                        wake.click(timeout=5000)
                        woke = True
                    if frame.get_by_role('heading', name=re.compile('Private Access')).is_visible():
                        if frame.get_by_role('button', name='Unlock', exact=True).is_visible():
                            print('Public access gate renders. Authenticated dashboard was not tested. Wake requested:', woke)
                            return
                page.wait_for_timeout(2000)
            raise RuntimeError('App did not reach its expected private access gate')
        finally:
            Path('health-artifacts').mkdir(exist_ok=True)
            page.screenshot(path='health-artifacts/app-health.png', full_page=True)
            browser.close()


if __name__ == '__main__':
    main()
