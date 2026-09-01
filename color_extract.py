"""
color_extract.py
-----------------
Given a product image URL (+ optionally the known DOM background color),
extracts the dominant *garment* color.

Key idea: Myntra tells us the tile's background color in the DOM
(div style="background: rgb(...)"). Rather than blindly clustering the whole
image, we first mask out pixels close to that known background, then run
k-means only on the remaining ("foreground" / garment) pixels. This is more
reliable than guessing which cluster is background from pixel counts alone,
especially for wide/loose garments that fill most of the frame.

If bg_rgb isn't known (e.g. a non-Myntra site), we fall back to clustering
the whole image and treating the single largest, near-edge-color cluster as
background.
"""
from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Optional

import numpy as np
from PIL import Image
from sklearn.cluster import KMeans

RGB = tuple[int, int, int]


@dataclass
class ColorCluster:
    rgb: RGB
    weight: float  # fraction of (considered) pixels in this cluster


def _rgb_distance(a: np.ndarray, b: RGB) -> np.ndarray:
    return np.linalg.norm(a - np.array(b, dtype=np.float32), axis=-1)


def load_image_from_bytes(data: bytes, max_side: int = 150) -> np.ndarray:
    """Load image bytes -> small RGB pixel array (downsampled for speed;
    150px is plenty for color clustering)."""
    img = Image.open(io.BytesIO(data)).convert("RGB")
    img.thumbnail((max_side, max_side))
    return np.asarray(img, dtype=np.float32).reshape(-1, 3)


def dominant_garment_color(
    pixels: np.ndarray,
    bg_rgb: Optional[RGB] = None,
    bg_threshold: float = 28.0,
    k: int = 3,
    min_foreground_fraction: float = 0.05,
) -> tuple[ColorCluster, list[ColorCluster]]:
    """
    Returns (best_garment_cluster, all_clusters_considered).

    - If bg_rgb is given: pixels within `bg_threshold` (Euclidean RGB
      distance) of it are masked out as background before clustering.
    - Clusters k-means on the remaining pixels; the *largest* remaining
      cluster is taken as the garment color (loose/baggy garments in the
      screenshots fill most of the non-background frame, so "largest
      foreground cluster" is a reasonable proxy for "the garment").
    - If masking removes almost everything (e.g. a mostly-background shot,
      or bg_rgb unknown), falls back to clustering the whole image and
      excludes the single largest cluster (assumed background) instead.
    """
    if bg_rgb is not None:
        dist = _rgb_distance(pixels, bg_rgb)
        fg_pixels = pixels[dist > bg_threshold]
    else:
        fg_pixels = pixels

    used_fallback = False
    if len(fg_pixels) < len(pixels) * min_foreground_fraction:
        # Masking left too little to cluster meaningfully -> fall back.
        fg_pixels = pixels
        used_fallback = True

    n_clusters = min(k, max(1, len(np.unique(fg_pixels.round(), axis=0))))
    km = KMeans(n_clusters=n_clusters, n_init=4, random_state=0)
    labels = km.fit_predict(fg_pixels)

    clusters = []
    for i in range(n_clusters):
        mask = labels == i
        weight = mask.sum() / len(fg_pixels)
        rgb = tuple(int(round(c)) for c in km.cluster_centers_[i])
        clusters.append(ColorCluster(rgb=rgb, weight=weight))  # type: ignore[arg-type]
    clusters.sort(key=lambda c: c.weight, reverse=True)

    if used_fallback and bg_rgb is None and len(clusters) > 1:
        # No DOM ground truth available: assume the single largest cluster
        # over the WHOLE image is background, garment is the next biggest.
        garment = clusters[1]
    else:
        garment = clusters[0]

    return garment, clusters


if __name__ == "__main__":
    # Self-test with a synthetic image: a light-blue background square with
    # a dark-indigo "jeans" rectangle in the middle -- verifies the masking
    # + clustering logic end-to-end without needing network access.
    bg = (229, 241, 255)
    garment_true = (40, 55, 90)

    arr = np.tile(np.array(bg, dtype=np.uint8), (150, 150, 1))
    arr[40:140, 55:100] = garment_true  # "jeans" patch
    img = Image.fromarray(arr, "RGB")
    buf = io.BytesIO()
    img.save(buf, format="PNG")

    pixels = load_image_from_bytes(buf.getvalue())
    best, all_clusters = dominant_garment_color(pixels, bg_rgb=bg)

    print("Synthetic self-test")
    print("  true background :", bg)
    print("  true garment    :", garment_true)
    print("  detected garment:", best.rgb, f"(weight={best.weight:.2f})")
    err = sum(abs(a - b) for a, b in zip(best.rgb, garment_true))
    print("  abs channel error:", err, "-> PASS" if err < 15 else "-> FAIL")
