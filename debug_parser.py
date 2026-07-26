"""
Diagnostic: Fetch with raw curl to see what Amazon returns from Render IP.
Also test if the CAPTCHA detection is triggering correctly and
show what signals the parser picks up from a CAPTCHA page.
"""
import asyncio
import sys
sys.path.insert(0, ".")

from app.amazon.client import AmazonClient, _is_captcha_page
from app.amazon.parser import parse_product_page

ASIN = "B087N288NT"
URL = f"https://www.amazon.in/dp/{ASIN}"

async def main():
    client = AmazonClient(timeout_seconds=20)

    # Override the _is_captcha_page to NOT block, so we can see what parser gets
    import app.amazon.client as client_mod
    _orig = client_mod._is_captcha_page

    def _no_captcha_block(html, url):
        if _orig(html, url):
            print(f"\n[!] CAPTCHA detected — Amazon is BLOCKING this server IP!")
            print(f"[!] The HTML we're getting is a CAPTCHA page, NOT the real product page.")
            print(f"[!] That's why the parser reports OUT_OF_STOCK — there are no ATC buttons on a CAPTCHA page!\n")
        return False  # Don't block, let parser see raw html

    client_mod._is_captcha_page = _no_captcha_block

    html, err = await client.fetch_product_page(URL, ASIN)
    if err:
        print(f"FETCH ERROR: {err}")
        await client.close()
        return

    print("=== FIRST 500 chars of raw HTML ===")
    print(html[:500])

    print("\n=== FULL PARSER RESULT from CAPTCHA page ===")
    state = parse_product_page(html, ASIN)
    print(f"Status: {state.status}")
    print(f"Confidence: {state.confidence:.2f}")
    print(f"Evidence: {state.evidence}")
    print(f"Availability text: {state.raw_availability_text!r}")

    client_mod._is_captcha_page = _orig
    await client.close()

asyncio.run(main())
