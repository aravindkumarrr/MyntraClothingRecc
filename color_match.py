"""
color_match.py
--------------
Heuristic skin-tone <-> garment-color compatibility scoring.

IMPORTANT: this is a rule-of-thumb heuristic built from commonly cited
personal-styling color theory (undertone matching, hue harmony, value
contrast) -- it is NOT a validated colorimetric/perceptual model. Treat
scores as a rough ranking signal, not ground truth. A stronger version
would use perceptual color space (CIELAB / CIEDE2000) instead of raw HSV.

Three components, each 0-1, combined with weights:

1. undertone_match  - does the garment's warm/cool lean match the skin's?
                       (skin undertone inferred from R-vs-B balance)
2. hue_harmony       - is the garment hue near a classically flattering
                       relationship to the skin hue (complementary ~150-210
                       deg apart, or analogous ~<45 deg apart)? Colors in
                       the awkward middle ground score lower.
3. value_contrast    - garments too close in lightness to skin tend to
                       "wash out"; a moderate-to-strong lightness contrast
                       generally reads as more flattering. Scored as an
                       inverted-U: some contrast good, extreme contrast
                       capped rather than rewarded further.
"""
from __future__ import annotations

import colorsys
from dataclasses import dataclass

RGB = tuple[int, int, int]


def hex_to_rgb(h: str) -> RGB:
    h = h.strip().lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) != 6:
        raise ValueError(f"Not a valid hex color: {h!r}")
    return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def rgb_to_hex(rgb: RGB) -> str:
    return "#{:02x}{:02x}{:02x}".format(*rgb)


def _hsv(rgb: RGB) -> tuple[float, float, float]:
    r, g, b = (c / 255.0 for c in rgb)
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    return h * 360.0, s, v


def _undertone(rgb: RGB) -> float:
    """Returns a warm<-1..+1>cool score from the R-B channel balance.
    Positive = cooler, negative = warmer, ~0 = neutral."""
    r, _, b = rgb
    return max(-1.0, min(1.0, (b - r) / 128.0))


def _hue_harmony_score(skin_hue: float, cloth_hue: float, cloth_sat: float) -> float:
    if cloth_sat < 0.08:
        # Near-greyscale garments (white/black/grey/denim-wash) sidestep hue
        # harmony rules entirely -- they're near-universally wearable.
        return 0.75

    diff = abs(skin_hue - cloth_hue) % 360
    diff = min(diff, 360 - diff)  # 0-180

    # Complementary sweet spot (~150-180 deg) and analogous sweet spot
    # (~0-40 deg) score highest; the 60-120 deg "in-between" zone scores
    # lowest (classic styling advice: near-misses read as clashing).
    if diff <= 40:
        return 0.6 + 0.4 * (1 - diff / 40)  # 0.6 - 1.0
    if diff >= 150:
        return 0.7 + 0.3 * ((diff - 150) / 30)  # 0.7 - 1.0
    # linearly dip through the middle zone
    mid = 95
    dist_from_mid = abs(diff - mid)
    return 0.25 + 0.25 * (dist_from_mid / (mid - 40))


def _value_contrast_score(skin_v: float, cloth_v: float) -> float:
    diff = abs(skin_v - cloth_v)
    # Inverted-U centered around a moderately strong contrast (~0.45);
    # too little (washed out) or too extreme (harsh) score lower.
    ideal = 0.45
    spread = 0.35
    return max(0.0, 1 - ((diff - ideal) / spread) ** 2)


@dataclass
class MatchResult:
    score: float  # 0-100
    undertone_score: float
    hue_score: float
    contrast_score: float
    note: str


def match_score(
    skin_hex: str,
    cloth_rgb: RGB,
    w_undertone: float = 0.35,
    w_hue: float = 0.35,
    w_contrast: float = 0.30,
) -> MatchResult:
    skin_rgb = hex_to_rgb(skin_hex)
    skin_hue, skin_sat, skin_v = _hsv(skin_rgb)
    cloth_hue, cloth_sat, cloth_v = _hsv(cloth_rgb)

    skin_undertone = _undertone(skin_rgb)
    cloth_undertone = _undertone(cloth_rgb)
    # 1 when undertones align, 0 when opposite; neutral garments (low sat)
    # get a friendly default since they don't strongly read as warm/cool.
    if cloth_sat < 0.08:
        undertone_score = 0.7
    else:
        undertone_score = 1 - abs(skin_undertone - cloth_undertone) / 2

    hue_score = _hue_harmony_score(skin_hue, cloth_hue, cloth_sat)
    contrast_score = _value_contrast_score(skin_v, cloth_v)

    total = (
        w_undertone * undertone_score + w_hue * hue_score + w_contrast * contrast_score
    ) * 100

    if total >= 75:
        note = "Strong match"
    elif total >= 55:
        note = "Good match"
    elif total >= 35:
        note = "Wearable, not ideal"
    else:
        note = "Likely clashes"

    return MatchResult(
        score=round(total, 1),
        undertone_score=round(undertone_score, 2),
        hue_score=round(hue_score, 2),
        contrast_score=round(contrast_score, 2),
        note=note,
    )


if __name__ == "__main__":
    # Sanity-check against a couple of textbook cases.
    warm_skin = "#C68642"  # medium warm/golden skin tone
    cool_skin = "#F1C27D"  # lighter, slightly cool-neutral for contrast test

    tests = {
        "warm skin + olive green": (warm_skin, (85, 107, 47)),
        "warm skin + icy blue": (warm_skin, (173, 216, 230)),
        "warm skin + dark indigo denim": (warm_skin, (40, 55, 90)),
        "warm skin + white": (warm_skin, (245, 245, 245)),
    }
    for label, (skin, cloth) in tests.items():
        r = match_score(skin, cloth)
        print(f"{label:32s} -> {r.score:5.1f}  ({r.note})  "
              f"[undertone={r.undertone_score}, hue={r.hue_score}, contrast={r.contrast_score}]")
