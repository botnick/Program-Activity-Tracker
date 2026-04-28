"""Regenerate tracker.ico (and ui/public/favicon.ico) from a procedural drawing.

We draw the icon directly with Pillow primitives instead of rasterizing the
SVG, because cairosvg / svglib aren't always installable on a fresh dev box.
The drawing mirrors `tracker.svg` exactly (eye + pulse line on a dark rounded
square) so editors can preview the SVG and the rendered ICO will match.

Usage:
    pip install Pillow
    python regenerate_icons.py
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]

BG_TOP    = (15, 23, 42)        # #0F172A
BG_BOTTOM = (30, 41, 59)        # #1E293B
EYE       = (6, 182, 212)       # #06B6D4
PULSE     = (16, 185, 129)      # #10B981
DARK      = (15, 23, 42)        # pupil highlight uses bg-top


def render(size: int) -> Image.Image:
    """Render the tracker icon at `size` x `size`. Anti-aliased via 4x SSAA."""
    SS = 4  # super-sampling factor
    big = size * SS
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # ---- background: rounded square with vertical gradient -------------------
    radius = int(round(big * 48 / 256))
    # Build gradient as a separate image then mask it through a rounded rect.
    grad = Image.new("RGBA", (big, big), BG_TOP)
    gd = ImageDraw.Draw(grad)
    for y in range(big):
        t = y / max(1, big - 1)
        r = int(BG_TOP[0] + (BG_BOTTOM[0] - BG_TOP[0]) * t)
        g = int(BG_TOP[1] + (BG_BOTTOM[1] - BG_TOP[1]) * t)
        b = int(BG_TOP[2] + (BG_BOTTOM[2] - BG_TOP[2]) * t)
        gd.line([(0, y), (big, y)], fill=(r, g, b, 255))

    mask = Image.new("L", (big, big), 0)
    md = ImageDraw.Draw(mask)
    md.rounded_rectangle((0, 0, big - 1, big - 1), radius=radius, fill=255)
    img.paste(grad, (0, 0), mask)
    draw = ImageDraw.Draw(img)

    # ---- eye outline ---------------------------------------------------------
    cx, cy = big // 2, int(round(big * 120 / 256))
    rx, ry = int(round(big * 80 / 256)), int(round(big * 48 / 256))
    sw = max(2, int(round(big * 10 / 256)))
    draw.ellipse((cx - rx, cy - ry, cx + rx, cy + ry), outline=EYE, width=sw)

    # ---- pupil ---------------------------------------------------------------
    pr = int(round(big * 22 / 256))
    draw.ellipse((cx - pr, cy - pr, cx + pr, cy + pr), fill=EYE)

    # tiny highlight inside pupil
    hr = int(round(big * 6 / 256))
    hx = cx - int(round(big * 8 / 256))
    hy = cy - int(round(big * 8 / 256))
    draw.ellipse((hx - hr, hy - hr, hx + hr, hy + hr), fill=DARK)

    # ---- pulse line ----------------------------------------------------------
    pts_norm = [
        (32, 200), (80, 200), (96, 180), (112, 216),
        (128, 168), (144, 216), (160, 188), (176, 200), (224, 200),
    ]
    pts = [(int(round(x * big / 256)), int(round(y * big / 256))) for x, y in pts_norm]
    psw = max(2, int(round(big * 8 / 256)))
    draw.line(pts, fill=PULSE, width=psw, joint="curve")
    # round caps
    for x, y in (pts[0], pts[-1]):
        draw.ellipse((x - psw // 2, y - psw // 2, x + psw // 2, y + psw // 2), fill=PULSE)

    # ---- downsample with antialiasing ----------------------------------------
    # Pillow >=10 renamed Image.LANCZOS to Image.Resampling.LANCZOS;
    # keep both branches so the script runs on either side.
    resample = getattr(
        getattr(Image, "Resampling", Image), "LANCZOS", None
    ) or getattr(Image, "LANCZOS", None) or 1
    return img.resize((size, size), resample)


def main() -> int:
    # Pillow's ICO writer takes a single source image and resizes it DOWN to
    # each of `sizes`. Render at the largest size (256) so all sub-images come
    # from a clean rasterization — feeding it a 16x16 source would produce a
    # blurry 256 entry.
    master = render(256)

    ico_path = HERE / "tracker.ico"
    master.save(
        ico_path,
        format="ICO",
        sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    print(f"wrote {ico_path}  ({ico_path.stat().st_size} bytes)")

    fav_path = REPO / "ui" / "public" / "favicon.ico"
    fav_path.parent.mkdir(parents=True, exist_ok=True)
    # favicon: 16/32/48 — keeps it small for the web.
    master.save(
        fav_path,
        format="ICO",
        sizes=[(16, 16), (32, 32), (48, 48)],
    )
    print(f"wrote {fav_path}  ({fav_path.stat().st_size} bytes)")

    # Drop a 256 PNG preview alongside the SVG so reviewers can eyeball it.
    preview = HERE / "tracker_preview_256.png"
    master.save(preview, format="PNG")
    print(f"wrote {preview}  ({preview.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
