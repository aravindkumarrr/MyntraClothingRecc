"""
scraper.py
----------
Parses a saved Myntra search-results HTML page (e.g. "Ctrl+S -> Webpage, Complete"
of a URL like myntra.com/jeans?rawQuery=jeans) and extracts, per product tile:

  - id, brand, name, price, product_url
  - image_url          -> the real CDN thumbnail URL (from the <source srcset>,
                           NOT the <img src>, which after a local save points to
                           a relative "..._files/" folder that won't exist elsewhere)
  - bg_rgb             -> the tile's background swatch color. Myntra renders each
                           thumbnail inside a <div style="background: rgb(r,g,b)">
                           wrapper (visible in the uploaded DevTools screenshot).
                           This is "free" ground-truth background color straight
                           from the DOM -- no need to infer it from the image.

Only stdlib + BeautifulSoup are used. No network calls happen here.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

_BG_RGB_RE = re.compile(r"rgb\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)")
_PRICE_RE = re.compile(r"Rs\.\s*([\d,]+)")
DEFAULT_BASE_URL = "https://www.myntra.com"


@dataclass
class Product:
    id: str
    brand: str
    name: str
    price: Optional[int]
    product_url: str
    image_url: str
    bg_rgb: Optional[tuple[int, int, int]]

    def __repr__(self) -> str:  # tidy console output
        return f"<Product {self.id} {self.brand} - {self.name} Rs.{self.price}>"


def _best_image_url(tile) -> Optional[str]:
    """Prefer the webp <source srcset> (real absolute CDN URL). Fall back to
    the <img src> only if it's already absolute (http/https)."""
    source = tile.select_one("picture source[srcset]")
    if source and source["srcset"].startswith("http"):
        return source["srcset"].strip()

    img = tile.select_one("picture img[src]")
    if img and img["src"].startswith("http"):
        return img["src"].strip()

    return None


def _bg_rgb(tile) -> Optional[tuple[int, int, int]]:
    bg_div = tile.select_one("div.product-sliderContainer > div[style*='background']")
    if not bg_div:
        return None
    m = _BG_RGB_RE.search(bg_div["style"])
    if not m:
        return None
    return tuple(int(x) for x in m.groups())  # type: ignore[return-value]


def _price(tile) -> Optional[int]:
    price_div = tile.select_one("div.product-price")
    if not price_div:
        return None
    m = _PRICE_RE.search(price_div.get_text(" ", strip=True))
    if not m:
        return None
    return int(m.group(1).replace(",", ""))


def parse_products_html(html: str, base_url: str = DEFAULT_BASE_URL) -> list[Product]:
    """Parse already-loaded HTML text into a list of Product records.

    `base_url` resolves relative product links (some category pages, e.g.
    "tops", link with hrefs like "tops/brand/name/123/buy" instead of a full
    "https://www.myntra.com/tops/..." URL) into clickable absolute URLs.
    Already-absolute hrefs are left untouched.

    Tiles missing a usable (absolute) image URL are silently skipped.
    """
    soup = BeautifulSoup(html, "lxml")

    products: list[Product] = []
    for tile in soup.select("li.product-base"):
        image_url = _best_image_url(tile)
        if not image_url:
            continue  # can't fetch a garment photo for this one -> skip

        link = tile.select_one("a[href]")
        brand_el = tile.select_one("h3.product-brand")
        name_el = tile.select_one("h4.product-product")

        product_url = urljoin(base_url, link["href"]) if link else ""

        products.append(
            Product(
                id=tile.get("id", ""),
                brand=brand_el.get_text(strip=True) if brand_el else "",
                name=name_el.get_text(strip=True) if name_el else "",
                price=_price(tile),
                product_url=product_url,
                image_url=image_url,
                bg_rgb=_bg_rgb(tile),
            )
        )
    return products


def parse_products(html_path: str | Path, base_url: str = DEFAULT_BASE_URL) -> list[Product]:
    """Read a saved Myntra listing page from disk and parse it.
    Tiles missing a usable (absolute) image URL are silently skipped."""
    html = Path(html_path).read_text(encoding="utf-8", errors="ignore")
    return parse_products_html(html, base_url=base_url)


if __name__ == "__main__":
    import sys

    path = sys.argv[1] if len(sys.argv) > 1 else None
    if not path:
        print("usage: python scraper.py <path-to-saved-myntra-html>")
        raise SystemExit(1)

    prods = parse_products(path)
    print(f"Parsed {len(prods)} products\n")
    for p in prods[:10]:
        print(p)
        print(f"  image_url: {p.image_url}")
        print(f"  bg_rgb   : {p.bg_rgb}")