"""
main.py
-------
Terminal demo. Ties scraper.py + color_extract.py + color_match.py together.

Usage:
    python main.py --html "path/to/saved_myntra_page.html" --skin "#8D5524" --top 15

What it does:
    1. Parses the saved HTML page -> list of products (with image URL + DOM
       background swatch already known, see scraper.py).
    2. For the first `--limit` products (default 20), downloads the
       thumbnail image and extracts the dominant garment color, masking out
       the known background first (see color_extract.py).
    3. Scores each garment color against the given skin hex using the
       undertone / hue-harmony / value-contrast heuristic (see
       color_match.py).
    4. Prints the top `--top` products ranked by match score.

Notes / honesty about limitations:
    - This needs real internet access to assets.myntassets.com to download
      images -- run it on your own machine, not in a sandboxed environment
      with restricted egress.
    - The matching algorithm is a styling heuristic, not validated
      colorimetry -- see the docstring in color_match.py.
    - Thumbnails are small (~210px) and sometimes show a model wearing the
      garment rather than a flat-lay -- skin/hair pixels from the model can
      pollute the "garment color" cluster. A production version should crop
      to the garment region (e.g. via a lightweight segmentation model)
      before clustering.
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

import requests

from color_extract import dominant_garment_color, load_image_from_bytes
from color_match import MatchResult, match_score, rgb_to_hex
from scraper import Product, parse_products_html

HEADERS = {"User-Agent": "Mozilla/5.0 (color-matcher-demo)"}


def load_products(html_source: str) -> list[Product]:
    """Accepts either a local file path or a live URL for --html.

    For live URLs, this renders the page in a real (headless) browser via
    Playwright and scrolls it to trigger lazy-loaded product images --
    necessary because Myntra's listing page is a React app that fills in
    the product grid with JavaScript after the initial page load, and
    lazy-loads each tile's real image URL only once it scrolls into view.
    See browser_fetch.py for details.
    """
    if html_source.startswith("http://") or html_source.startswith("https://"):
        print(f"Rendering {html_source} in a headless browser (~10-20s)...")
        try:
            from browser_fetch import fetch_rendered_html
        except ImportError as exc:
            raise RuntimeError(
                "Live URL support needs Playwright. Install it with:\n"
                "    pip install playwright\n"
                "    playwright install chromium\n"
                "...or pass a saved HTML file to --html instead."
            ) from exc
        html = fetch_rendered_html(html_source)
        base_url = html_source
    else:
        path = Path(html_source)
        if not path.exists():
            raise FileNotFoundError(
                f"'{html_source}' is not a URL and no such file exists. "
                f"Pass either a live http(s) URL or a path to a saved HTML file."
            )
        html = path.read_text(encoding="utf-8", errors="ignore")
        base_url = "https://www.myntra.com"  # resolves relative product links

    products = parse_products_html(html, base_url=base_url)
    if not products and html_source.startswith("http"):
        print(
            "\n  0 products parsed even after rendering. The site's markup "
            "may differ from what this scraper expects, or it served a "
            "bot-check page. Try saving the page manually instead: open it "
            "in a browser, let it fully load, Ctrl+S -> 'Webpage, Complete', "
            "then pass that .html file to --html.\n"
        )
    return products


@dataclass
class RankedProduct:
    product: Product
    garment_hex: str
    match: MatchResult


def fetch_image_bytes(url: str, timeout: float = 8.0) -> bytes:
    resp = requests.get(url, headers=HEADERS, timeout=timeout)
    resp.raise_for_status()
    return resp.content


def rank_products(
    products: list[Product], skin_hex: str, limit: int, verbose: bool = True
) -> list[RankedProduct]:
    results: list[RankedProduct] = []
    for i, p in enumerate(products[:limit], start=1):
        try:
            img_bytes = fetch_image_bytes(p.image_url)
            pixels = load_image_from_bytes(img_bytes)
            garment, _ = dominant_garment_color(pixels, bg_rgb=p.bg_rgb)
            garment_hex = rgb_to_hex(garment.rgb)
            m = match_score(skin_hex, garment.rgb)
            results.append(RankedProduct(product=p, garment_hex=garment_hex, match=m))
            if verbose:
                print(f"  [{i}/{limit}] OK    {p.brand} - {p.name[:40]:40s} "
                      f"garment~{garment_hex} score={m.score}")
        except Exception as exc:  # network hiccup, decode error, etc.
            if verbose:
                print(f"  [{i}/{limit}] SKIP  {p.brand} - {p.name[:40]:40s} ({exc})")
    results.sort(key=lambda r: r.match.score, reverse=True)
    return results


def print_ranked(results: list[RankedProduct], top: int) -> None:
    print(f"\nTop {min(top, len(results))} matches:\n")
    print(f"{'#':<3}{'Score':<8}{'Note':<20}{'Garment':<10}{'Price':<10}{'Brand - Product'}")
    print("-" * 100)
    for rank, r in enumerate(results[:top], start=1):
        p = r.product
        price = f"Rs.{p.price}" if p.price else "-"
        print(
            f"{rank:<3}{r.match.score:<8}{r.match.note:<20}{r.garment_hex:<10}"
            f"{price:<10}{p.brand} - {p.name}"
        )
        print(f"    {p.product_url}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Skin-tone based clothing color matcher (demo)")
    ap.add_argument("--html", required=True, help="Path to saved Myntra listing HTML page, OR a live http(s) URL (see caveat in load_products())")
    ap.add_argument("--skin", required=True, help="Skin tone as hex, e.g. #8D5524")
    ap.add_argument("--limit", type=int, default=30, help="How many products to analyze (default 20)")
    ap.add_argument("--top", type=int, default=10, help="How many top matches to display (default 10)")
    args = ap.parse_args()

    try:
        products = load_products(args.html)
    except (FileNotFoundError, RuntimeError, requests.RequestException) as exc:
        print(f"Could not load --html source: {exc}")
        sys.exit(1)

    if not products:
        print("No products found -- check the file/URL (see message above if fetched live).")
        sys.exit(1)

    print(f"Parsed {len(products)} products. Analyzing first {min(args.limit, len(products))}...\n")
    results = rank_products(products, args.skin, args.limit)

    if not results:
        print("\nNo images could be analyzed (check your internet connection).")
        sys.exit(1)

    print_ranked(results, args.top)


if __name__ == "__main__":
    main()