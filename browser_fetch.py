"""
browser_fetch.py
-----------------
Fetches a JS-rendered page (e.g. a live Myntra listing URL) using a headless
Chromium browser via Playwright, so the product grid that's normally filled
in by client-side JavaScript is actually present in the returned HTML.

One-time setup (in addition to `pip install -r requirements.txt`):
    playwright install chromium

Why this is needed: requests.get() on a URL like
    https://www.myntra.com/jeans?rawQuery=jeans
only returns the server's initial HTML response. Myntra's listing page is a
React app that fetches and renders the product grid client-side after that
-- so a plain HTTP fetch sees an (almost) empty page. Waiting for a real
browser to run the JS is the reliable fix for THAT problem.

Myntra also lazy-loads product thumbnails as you scroll, so we scroll the
page down in steps to trigger loading of tiles beyond the initial viewport.

IMPORTANT HONEST CAVEAT: sites like Myntra commonly run bot protection
(e.g. Akamai Bot Manager) that fingerprints automated browsers at the
TLS/HTTP2 connection level -- before any JavaScript even runs. If that's
what's happening, you'll see errors like `net::ERR_HTTP2_PROTOCOL_ERROR` or
the connection being refused/reset outright. This module defaults to
launching your actual installed Google Chrome (not Playwright's bundled
Chromium) in a visible, non-headless window, since that fingerprints much
closer to ordinary human browsing than headless automation -- but there is
still NO guaranteed fix for network-level bot detection short of
residential proxies or manual browsing, and even those are an arms race,
not a permanent solution. If mitigations don't work, the saved-HTML-file
fallback (--html path/to/saved_page.html) remains the reliable option; it
doesn't touch the target site's servers at request time at all.
"""
from __future__ import annotations

from playwright.sync_api import sync_playwright

PRODUCT_TILE_SELECTOR = "li.product-base"

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# Hides the most obvious automation fingerprint (navigator.webdriver=true),
# which some basic bot checks key off of. Not a full stealth solution.
_STEALTH_INIT_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
"""


def _launch_and_load(
    p,
    url: str,
    wait_selector: str,
    initial_timeout_ms: int,
    max_scrolls: int,
    scroll_pause_ms: int,
    headless: bool,
    disable_http2: bool,
    channel: str | None,
) -> str:
    args = ["--disable-blink-features=AutomationControlled"]
    if disable_http2:
        args.append("--disable-http2")

    launch_kwargs = dict(headless=headless, args=args)
    if channel:
        launch_kwargs["channel"] = channel  # e.g. "chrome" -> real installed Chrome

    browser = p.chromium.launch(**launch_kwargs)
    try:
        page = browser.new_page(
            user_agent=_UA,
            viewport={"width": 1400, "height": 1000},
            locale="en-US",
            extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
        )
        page.add_init_script(_STEALTH_INIT_SCRIPT)
        page.goto(url, timeout=initial_timeout_ms, wait_until="domcontentloaded")

        page.wait_for_selector(wait_selector, timeout=initial_timeout_ms)

        prev_count = 0
        for _ in range(max_scrolls):
            page.mouse.wheel(0, 3000)
            page.wait_for_timeout(scroll_pause_ms)
            count = page.locator(wait_selector).count()
            if count == prev_count:
                break
            prev_count = count

        return page.content()
    finally:
        browser.close()


def fetch_rendered_html(
    url: str,
    wait_selector: str = PRODUCT_TILE_SELECTOR,
    initial_timeout_ms: int = 20000,
    max_scrolls: int = 15,
    scroll_pause_ms: int = 800,
    headless: bool = False,
    use_real_chrome: bool = True,
) -> str:
    """Load `url` in a browser, wait for the product grid to appear, scroll
    to trigger lazy-loaded images, and return the fully rendered
    page.content() HTML.

    headless=False by default and use_real_chrome=True by default: WAFs
    like Akamai specifically fingerprint headless/bundled-Chromium traffic,
    so we default to launching your actual installed Google Chrome
    (channel="chrome") in a visible window -- this looks much more like an
    ordinary human browsing session. Falls back to Playwright's bundled
    Chromium automatically if Chrome isn't installed.

    Retries once with HTTP/2 disabled if the first attempt fails with a
    connection-level error. Raises RuntimeError with an actionable message
    if all attempts fail, or if the product grid never appears.
    """
    with sync_playwright() as p:
        channel = "chrome" if use_real_chrome else None
        try:
            return _launch_and_load(
                p, url, wait_selector, initial_timeout_ms, max_scrolls,
                scroll_pause_ms, headless, disable_http2=False, channel=channel,
            )
        except Exception as first_exc:
            first_msg = str(first_exc)

            # Chrome channel not installed -> retry once on bundled Chromium
            # before giving up (this is a setup issue, not bot-blocking).
            if channel and ("Chromium distribution" in first_msg or "channel" in first_msg.lower()):
                channel = None
                try:
                    return _launch_and_load(
                        p, url, wait_selector, initial_timeout_ms, max_scrolls,
                        scroll_pause_ms, headless, disable_http2=False, channel=None,
                    )
                except Exception as retry_exc:
                    first_exc, first_msg = retry_exc, str(retry_exc)

            is_conn_error = "ERR_HTTP2" in first_msg or "ERR_CONNECTION" in first_msg
            if is_conn_error:
                try:
                    return _launch_and_load(
                        p, url, wait_selector, initial_timeout_ms, max_scrolls,
                        scroll_pause_ms, headless, disable_http2=True, channel=channel,
                    )
                except Exception as second_exc:
                    raise RuntimeError(
                        f"Could not load {url} even with HTTP/2 disabled as a "
                        f"retry, using {'real Chrome' if channel else 'bundled Chromium'}. "
                        f"This looks like connection-level bot blocking (e.g. a "
                        f"WAF fingerprinting the automated browser), which this "
                        f"script cannot reliably get past -- that's a different "
                        f"problem than 'JS didn't render'. Original error: "
                        f"{first_msg!r}. Retry error: {second_exc!r}. Fall back "
                        f"to saving the page manually instead: open it in your "
                        f"normal browser, let it fully load, Ctrl+S -> "
                        f"'Webpage, Complete', then pass that .html file to "
                        f"--html."
                    ) from second_exc
            raise RuntimeError(
                f"Product tiles ('{wait_selector}') never appeared on {url}: "
                f"{first_msg!r}. The site may have served a bot-check/CAPTCHA "
                f"page instead of the real listing, or its markup has changed "
                f"since this scraper was written. Fall back to saving the "
                f"page manually (open in a browser, let it fully load, "
                f"Ctrl+S -> 'Webpage, Complete') and pass that .html file to "
                f"--html."
            ) from first_exc


if __name__ == "__main__":
    import sys

    url = sys.argv[1] if len(sys.argv) > 1 else None
    if not url:
        print("usage: python browser_fetch.py <live-url>")
        raise SystemExit(1)

    html = fetch_rendered_html(url)
    out_path = "rendered_page.html"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Saved rendered HTML ({len(html)} chars) to {out_path}")