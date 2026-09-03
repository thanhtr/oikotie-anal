#!/usr/bin/env python3
"""Generate the PWA icon set from a simple vector glyph (no external assets).

Draws the same mark as static/favicon.svg — a white circle with a brand-blue
"growth line" glyph on a brand-blue square — at each size the manifest and
report template reference. Run manually whenever the mark changes:

    python3 scripts/gen_icons.py
"""

from pathlib import Path

from PIL import Image, ImageDraw

BRAND = (21, 101, 192, 255)     # #1565c0
WHITE = (255, 255, 255, 255)

OUT_DIR = Path(__file__).resolve().parent.parent / "static" / "icons"


def _draw_glyph(draw: ImageDraw.ImageDraw, cx: float, cy: float, r: float, line_w: float) -> None:
    """White circle of radius r centered at (cx, cy), with a brand-color
    'growth line + arrowhead' glyph inside it."""
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=WHITE)

    # Growth line: three segments forming a little zig-zag rising to the right,
    # scaled relative to the circle radius so it holds up at every icon size.
    pts = [
        (cx - r * 0.55, cy + r * 0.30),
        (cx - r * 0.10, cy - r * 0.30),
        (cx + r * 0.28, cy + r * 0.07),
        (cx + r * 0.55, cy - r * 0.55),
    ]
    draw.line(pts, fill=BRAND, width=max(1, round(line_w)), joint="curve")

    # Arrowhead at the top-right end of the line.
    tip = pts[-1]
    ax, ay = r * 0.28, r * 0.02
    draw.line([tip, (tip[0] - ax, tip[1] + ay)], fill=BRAND, width=max(1, round(line_w)))
    draw.line([tip, (tip[0] - ay, tip[1] + ax)], fill=BRAND, width=max(1, round(line_w)))

    for pt in [pts[0], pts[-1]]:
        cap = line_w / 2
        draw.ellipse([pt[0] - cap, pt[1] - cap, pt[0] + cap, pt[1] + cap], fill=BRAND)


def make_icon(size: int, *, maskable: bool = False, corner_radius_ratio: float = 0.22) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    if maskable:
        # Maskable icons are cropped to a circle/rounded-square by the OS —
        # fill edge-to-edge and keep the glyph within the ~80% safe zone.
        draw.rectangle([0, 0, size, size], fill=BRAND)
        r = size * 0.30
    else:
        radius = size * corner_radius_ratio
        draw.rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, fill=BRAND)
        r = size * 0.3125  # matches the 7.5/24 ratio used in favicon.svg

    _draw_glyph(draw, size / 2, size / 2, r, line_w=max(1.5, size * 0.035))
    return img


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    make_icon(192).save(OUT_DIR / "icon-192.png")
    make_icon(512).save(OUT_DIR / "icon-512.png")
    make_icon(512, maskable=True).save(OUT_DIR / "icon-512-maskable.png")
    # apple-touch-icon: iOS ignores alpha/transparency, so flatten onto white.
    apple = Image.new("RGB", (180, 180), (255, 255, 255))
    apple.paste(make_icon(180, corner_radius_ratio=0), (0, 0))
    apple.save(OUT_DIR / "apple-touch-icon.png")
    print(f"Wrote icons → {OUT_DIR}")


if __name__ == "__main__":
    main()
