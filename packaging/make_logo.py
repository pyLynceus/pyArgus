"""Draw the pyArgus mark and derive every icon size from it.

Argus Panoptes's hundred eyes ended up on the peacock's tail, and a
lidar cloud is nothing but eyes -- so the mark is a gold eye-spot
inside peacock-teal rings, each ring carrying its own small eyes
(returns), on pine ink. Unlike pyLynceus's converter this script
DRAWS the 1024 source too, so the whole brand regenerates from code:

    .venv/Scripts/python.exe packaging/make_logo.py

Needs Pillow (install ad hoc; it is not a project dependency).
"""

import math
from pathlib import Path

from PIL import Image, ImageDraw

INK = (22, 40, 30, 255)        # pine
TEAL = (46, 125, 110, 255)     # peacock
GOLD = (217, 164, 65, 255)     # the eye-spot
PAPER = (242, 244, 240, 255)

SIZES = [(16, 16), (24, 24), (32, 32), (48, 48),
         (64, 64), (128, 128), (256, 256)]


def draw_mark(size=1024):
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    art = ImageDraw.Draw(image)
    center = size / 2

    def circle(radius, fill=None, outline=None, width=1):
        box = [center - radius, center - radius,
               center + radius, center + radius]
        art.ellipse(box, fill=fill, outline=outline, width=width)

    circle(size * 0.48, fill=INK)
    # scan rings, each studded with its eyes
    for ring, count in ((0.40, 24), (0.31, 16), (0.22, 10)):
        radius = size * ring
        circle(radius, outline=TEAL, width=max(2, size // 128))
        for k in range(count):
            angle = 2 * math.pi * k / count
            ex = center + radius * math.cos(angle)
            ey = center + radius * math.sin(angle)
            eye = size * 0.018
            art.ellipse([ex - eye, ey - eye, ex + eye, ey + eye],
                        fill=PAPER)
    # the eye-spot: gold iris, ink pupil, paper glint
    circle(size * 0.13, fill=GOLD)
    circle(size * 0.06, fill=INK)
    glint = size * 0.02
    art.ellipse([center + size * 0.02 - glint, center - size * 0.04 - glint,
                 center + size * 0.02 + glint, center - size * 0.04 + glint],
                fill=PAPER)
    return image


def main():
    assets = Path(__file__).resolve().parents[1] / "pyargus" / "assets"
    assets.mkdir(exist_ok=True)
    mark = draw_mark(1024)
    mark.save(assets / "pyargus-icon-1024.png")
    mark.resize((256, 256), Image.LANCZOS).save(
        assets / "pyargus-icon-256.png")
    mark.resize((256, 256), Image.LANCZOS).save(
        assets / "pyArgus.ico", format="ICO", sizes=SIZES)
    print(f"wrote mark + ico into {assets}")


if __name__ == "__main__":
    main()
