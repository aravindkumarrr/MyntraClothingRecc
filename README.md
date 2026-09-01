# Skin-tone Clothing Color Matcher — terminal (demo)

Given (1) a skin tone hex color and (2) a saved HTML page of a Myntra
listing (or search results), this ranks the listed products by how well
their garment color complements the given skin tone.

## Setup
```bash
pip install -r requirements.txt
playwright install chromium   # one-time; needed only for live --html URLs
```

## Run
```bash
# Option A: live URL (renders the page in a real headless browser first,
# scrolls it to trigger lazy-loaded images, then scrapes it -- see how this
# works in browser_fetch.py)
python main.py --html "https://www.myntra.com/jeans?rawQuery=jeans" --skin "#8D5524"

# Option B: a page you saved yourself (browser -> Ctrl+S -> "Webpage, Complete")
python main.py --html "path/to/saved_page.html" --skin "#8D5524" --limit 20 --top 10
```

- `--html`   Either a live http(s) URL, or a path to a page saved via
             browser "Save As -> Webpage, Complete" from a Myntra
             listing/search URL.
- `--skin`   Skin tone as a hex color, e.g. `#8D5524`.
- `--limit`  How many product tiles to analyze (default 20). Each one
             triggers an image download, so keep this reasonable.
- `--top`    How many top-ranked matches to print (default 10).

## How it works
1. **If `--html` is a live URL**, `browser_fetch.py` loads it in a headless
   Chromium browser (via Playwright), waits for the product grid to appear,
   and scrolls repeatedly to trigger Myntra's lazy-loaded thumbnail images
   -- a plain HTTP fetch can't do this because the grid is filled in by
   client-side JavaScript, and even once it appears, most tiles' real image
   URLs only populate once they've scrolled into view. If `--html` is a
   local file path instead, it's read directly (no browser needed).
2. `scraper.py` parses `li.product-base` tiles out of the resulting HTML,
   pulling brand/name/price/product URL, the real CDN thumbnail URL (from
   the `<source srcset>`, not the locally-rewritten `<img src>`), and —
   as a bonus Myntra gives us for free — the tile's background swatch color
   from its inline `style="background: rgb(...)"`.
3. `color_extract.py` downloads the thumbnail, masks out pixels close to
   that known background color, then k-means clusters the remaining pixels
   to find the dominant *garment* color.
4. `color_match.py` scores the garment color against the given skin hex
   using three heuristic components: undertone alignment (warm/cool lean),
   hue harmony (complementary/analogous relationships), and value contrast
   (lightness difference) — combined into a 0-100 score.
5. `main.py` orchestrates all of the above and prints a ranked table.

## Known limitations
- **The matching algorithm is a styling heuristic**, built from commonly
  cited personal-color-analysis rules of thumb — not a validated
  colorimetric or perceptual model. A stronger version would work in
  CIELAB space with CIEDE2000 distance instead of raw HSV/RGB.
- **Thumbnails sometimes show a model wearing the garment**, not a flat
  lay. Skin/hair pixels from the model can pollute the extracted "garment
  color" cluster since we only mask the known page background, not the
  model. A production version should crop to the garment region (e.g. a
  lightweight person/clothing segmentation model) before clustering.
- **Live URL fetching may still fail** if Myntra serves a bot-check /
  CAPTCHA page to headless browsers, or if their markup changes (the
  scraper looks for specific CSS classes like `li.product-base`). If that
  happens, `browser_fetch.py` raises a clear error telling you to fall
  back to a manually saved HTML page instead.
- Tested against a real saved Myntra "jeans" search page (50/50 tiles
  parsed correctly), a synthetic lazy-loading test page (verified the
  scroll logic loads all 40/40 simulated tiles, not just the ones
  initially in view), and a mocked end-to-end scoring run. The
  color-clustering logic also has its own synthetic self-test in
  `color_extract.py` (`python color_extract.py`).

## Files
- `scraper.py`       — HTML -> Product list
- `browser_fetch.py` — live URL -> fully-rendered HTML (headless Chromium)
- `color_extract.py` — image bytes -> dominant garment RGB
- `color_match.py`   — skin hex + garment RGB -> compatibility score
- `main.py`          — CLI that wires it all together
