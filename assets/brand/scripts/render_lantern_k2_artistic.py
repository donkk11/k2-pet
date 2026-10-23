#!/usr/bin/env python3
"""Render artistic K2 lantern/mark fusions and real-size previews.

The source mark is sampled at runtime so this asset remains tied to the real
brand file rather than a guessed orange. All output is RGBA PNG with a clear
background; the glow is baked into the artwork, ready for the existing CSS
drop-shadow/glass treatment around #peek.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont


ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "assets" / "brand"
SOURCE = OUT / "lantern-mark.png"
SIZE = 1024
SCALE = 4


def sampled_brand_color() -> tuple[int, int, int]:
    im = Image.open(SOURCE).convert("RGBA")
    pixels = [tuple(rgb) for *rgb, alpha in im.getdata() if alpha > 240]
    # The real mark is intentionally flat; most-common opaque pixel is the
    # authoritative hue and makes a future brand refresh propagate here.
    from collections import Counter

    return Counter(pixels).most_common(1)[0][0]


BRAND = sampled_brand_color()  # currently (232, 93, 38), #e85d26
CLAUDE = (217, 119, 87)  # public/companion.html --accent for Claude Code
# Warm light derived from the actual flat lantern hue, not a guessed orange.
HIGHLIGHT = tuple(round((BRAND[i] + (255, 214, 133)[i]) / 2) for i in range(3))
INK = (42, 18, 14)
FONT_PATH = "/System/Library/Fonts/Supplemental/Arial Black.ttf"


def rgba(color, alpha=255):
    return (*color, alpha)


def layer() -> Image.Image:
    return Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))


def polygon(draw, pts, fill):
    draw.polygon([(int(x), int(y)) for x, y in pts], fill=fill)


def rounded(draw, box, radius, fill, outline=None, width=1):
    draw.rounded_rectangle(tuple(map(int, box)), radius=int(radius), fill=fill, outline=outline, width=width)


def add_glow(base: Image.Image, mask: Image.Image, color=CLAUDE, blur=26, alpha=130):
    glow = Image.new("RGBA", base.size, rgba(color, 0))
    glow.putalpha(mask.filter(ImageFilter.GaussianBlur(blur)).point(lambda p: p * alpha // 255))
    base.alpha_composite(glow)


def add_light_streak(base: Image.Image, box, color=HIGHLIGHT, blur=12, alpha=180):
    m = Image.new("L", base.size, 0)
    d = ImageDraw.Draw(m)
    d.rounded_rectangle(box, radius=box[3] - box[1], fill=alpha)
    l = Image.new("RGBA", base.size, rgba(color, 0))
    l.putalpha(m.filter(ImageFilter.GaussianBlur(blur)))
    base.alpha_composite(l)


def k2_mask(font_size=270, tracking=0):
    """Rasterize the real K2 glyphs; never approximate either character with polygons."""
    font = ImageFont.truetype(FONT_PATH, font_size)
    probe = Image.new("L", (1600, 500), 0)
    pd = ImageDraw.Draw(probe)
    bbox = pd.textbbox((0, 0), "K2", font=font, stroke_width=0)
    w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    mask = Image.new("L", (w + 24, h + 24), 0)
    md = ImageDraw.Draw(mask)
    md.text((12 - bbox[0], 12 - bbox[1]), "K2", font=font, fill=255,
            stroke_width=0)
    return mask


def place_k2(base: Image.Image, color, panel, font_size=270, inset=(0, 0), glow=False, stretch_y=1.0):
    """Place a genuine font-rendered K2 inside the panel and optionally glow it."""
    mask = k2_mask(font_size)
    x0, y0, x1, y1 = map(int, panel)
    max_w, max_h = x1 - x0 - 34, y1 - y0 - 34
    scale = min(max_w / mask.width, max_h / mask.height, 1.0)
    if scale != 1:
        mask = mask.resize((round(mask.width * scale), round(mask.height * scale)), Image.Resampling.LANCZOS)
    if stretch_y != 1.0:
        mask = mask.resize((mask.width, round(mask.height * stretch_y)), Image.Resampling.LANCZOS)
    x = x0 + (x1 - x0 - mask.width) // 2 + inset[0]
    y = y0 + (y1 - y0 - mask.height) // 2 + inset[1]
    if glow:
        glow_layer = Image.new("RGBA", base.size, rgba(color, 0))
        glow_mask = Image.new("L", base.size, 0)
        glow_mask.paste(mask, (x, y))
        glow_layer.putalpha(glow_mask.filter(ImageFilter.GaussianBlur(18)).point(lambda p: p * 150 // 255))
        base.alpha_composite(glow_layer)
    glyph = Image.new("RGBA", base.size, rgba(color, 0))
    full_mask = Image.new("L", base.size, 0)
    full_mask.paste(mask, (x, y))
    glyph.putalpha(full_mask)
    base.alpha_composite(glyph)


def v3_shell(im: Image.Image, compact=False):
    """A clean lantern shell whose panel gives the real K2 font enough room."""
    d = ImageDraw.Draw(im)
    m = Image.new("L", im.size, 0)
    ImageDraw.Draw(m).ellipse((275, 170, 750, 850), fill=220)
    add_glow(im, m, CLAUDE, 44, 110)
    lantern_shell(d, compact=compact)


def candidate_v3_a() -> Image.Image:
    """Arial Black K2 as a warm-glow cutout in the lantern glass."""
    im = layer()
    v3_shell(im)
    d = ImageDraw.Draw(im)
    # A dark bezel makes the two real letterforms read as one designed window.
    rounded(d, (342, 330, 682, 760), 28, rgba(INK, 255))
    rounded(d, (356, 344, 668, 746), 22, rgba((104, 42, 28), 255))
    place_k2(im, HIGHLIGHT, (356, 344, 668, 746), font_size=500, glow=True, stretch_y=1.55)
    d.line((330, 770, 694, 770), fill=rgba(HIGHLIGHT, 220), width=14)
    polygon(d, [(342, 790), (682, 790), (635, 850), (389, 850)], rgba(CLAUDE, 255))
    return im


def candidate_v3_b() -> Image.Image:
    """Arial Black K2 punched through a bright panel, with the lantern color as ink."""
    im = layer()
    v3_shell(im, compact=True)
    d = ImageDraw.Draw(im)
    rounded(d, (334, 326, 690, 764), 28, rgba(HIGHLIGHT, 255))
    # The mask is rendered directly as the dark negative, so the 2 remains
    # crisp even when the surrounding orange shell is reduced to 22px.
    place_k2(im, INK, (350, 342, 674, 748), font_size=500, glow=False, stretch_y=1.55)
    d.line((333, 770, 691, 770), fill=rgba(HIGHLIGHT, 220), width=14)
    polygon(d, [(348, 790), (676, 790), (640, 850), (384, 850)], rgba(CLAUDE, 255))
    return im


def candidate_v3_c() -> Image.Image:
    """A high-contrast typographic beacon: real K2 sits in a dark glass aperture."""
    im = layer()
    v3_shell(im)
    d = ImageDraw.Draw(im)
    rounded(d, (334, 326, 690, 764), 30, rgba(INK, 255))
    # The dark glass is deliberately high contrast at icon size; the warm
    # lantern shell still wraps the aperture so this is not a flat label.
    rounded(d, (350, 342, 674, 748), 22, rgba(INK, 255))
    place_k2(im, HIGHLIGHT, (350, 342, 674, 748), font_size=500, glow=True, stretch_y=1.55)
    d.line((330, 770, 694, 770), fill=rgba(HIGHLIGHT, 220), width=14)
    polygon(d, [(342, 790), (682, 790), (635, 850), (389, 850)], rgba(CLAUDE, 255))
    return im


def crop_to_art(im: Image.Image) -> Image.Image:
    bbox = im.getchannel("A").getbbox()
    if not bbox:
        return im
    # Keep a little transparent breathing room for the 22px glyph.
    x0, y0, x1, y1 = bbox
    pad = 20
    return im.crop((max(0, x0 - pad), max(0, y0 - pad), min(SIZE, x1 + pad), min(SIZE, y1 + pad)))


def finish(im: Image.Image, name: str, preview=True):
    # All artwork is kept on a 1024 transparent canvas for predictable CSS fit.
    canvas = layer()
    art = crop_to_art(im)
    fit = min(860 / art.width, 860 / art.height)
    art = art.resize((round(art.width * fit), round(art.height * fit)), Image.Resampling.LANCZOS)
    canvas.alpha_composite(art, ((SIZE - art.width) // 2, (SIZE - art.height) // 2))
    path = OUT / f"{name}.png"
    canvas.save(path)
    for px in (44, 22):
        small = canvas.resize((px, px), Image.Resampling.LANCZOS)
        small.save(OUT / f"{name}-preview-{px}.png")
    return path


def candidate_a() -> Image.Image:
    """The lantern body becomes one continuous, readable 2-shaped ribbon."""
    im = layer()
    d = ImageDraw.Draw(im)
    # halo from the lower lamp and the top power-line seam
    m = Image.new("L", im.size, 0)
    md = ImageDraw.Draw(m)
    md.ellipse((260, 235, 765, 855), fill=210)
    add_glow(im, m, CLAUDE, 48, 115)

    # K2-ish shoulder and handle: the upper loop is also the top of the 2.
    rounded(d, (355, 135, 670, 210), 34, rgba(CLAUDE, 255))
    rounded(d, (385, 158, 640, 195), 18, rgba(INK, 255))
    d.line((512, 180, 512, 245), fill=rgba(CLAUDE, 255), width=26)

    # A single thick stroke traces a lantern roof, curls across the glass, and
    # resolves into a 2. At small size the negative triangular window remains.
    polygon(d, [(300, 300), (410, 244), (614, 244), (724, 300), (685, 355),
                (625, 318), (399, 318), (339, 355)], rgba(CLAUDE, 255))
    rounded(d, (315, 310, 709, 770), 86, rgba(CLAUDE, 255))
    # Carve the 2-shaped light channel through the lantern body.
    polygon(d, [(382, 420), (431, 375), (585, 375), (645, 420), (645, 505),
                (404, 620), (404, 681), (645, 681), (645, 742), (350, 742),
                (350, 579), (586, 470), (586, 429), (575, 420), (443, 420),
                (424, 438), (424, 500), (382, 500)], rgba(INK, 255))
    # Bright inner light reinforces “lantern”, while the cutout still reads 2.
    rounded(d, (445, 445, 568, 620), 36, rgba(HIGHLIGHT, 225))
    polygon(d, [(451, 578), (560, 510), (560, 597), (451, 650)], rgba(CLAUDE, 235))
    # Tech seam and grounding cap.
    d.line((330, 790, 694, 790), fill=rgba(HIGHLIGHT, 210), width=14)
    polygon(d, [(342, 805), (682, 805), (635, 862), (389, 862)], rgba(CLAUDE, 255))
    return im


def candidate_b() -> Image.Image:
    """A compact lantern vessel with an unmistakable K2 glyph in its light."""
    im = layer()
    d = ImageDraw.Draw(im)
    m = Image.new("L", im.size, 0)
    md = ImageDraw.Draw(m)
    md.ellipse((295, 185, 730, 835), fill=225)
    add_glow(im, m, CLAUDE, 40, 120)
    # Floating geometric handle / crown.
    d.arc((360, 98, 664, 320), 180, 360, fill=rgba(CLAUDE, 255), width=34)
    d.line((382, 214, 642, 214), fill=rgba(CLAUDE, 255), width=26)
    # Lantern roof and faceted side rails.
    polygon(d, [(310, 320), (512, 240), (714, 320), (674, 370), (350, 370)], rgba(CLAUDE, 255))
    polygon(d, [(306, 335), (351, 369), (351, 744), (300, 690)], rgba(CLAUDE, 245))
    polygon(d, [(718, 335), (673, 369), (673, 744), (724, 690)], rgba(CLAUDE, 245))
    rounded(d, (342, 350, 682, 770), 34, rgba(INK, 255))
    # Warm glass panel, with a bold K2 cut into it rather than pasted beside it.
    rounded(d, (382, 390, 642, 711), 22, rgba(HIGHLIGHT, 238))
    rounded(d, (410, 418, 445, 676), 14, rgba(CLAUDE, 255))
    d.line((438, 545, 586, 427), fill=rgba(CLAUDE, 255), width=34)
    d.line((438, 545, 592, 674), fill=rgba(CLAUDE, 255), width=34)
    # The diagonal K stroke continues as the 2's top hook and lower sweep.
    d.line((560, 420, 614, 464, 614, 515), fill=rgba(CLAUDE, 255), width=32, joint="curve")
    d.line((614, 515, 500, 615, 500, 672, 616, 672), fill=rgba(CLAUDE, 255), width=32, joint="curve")
    # Inner light seam: one vivid vertical axis survives at 22px.
    add_light_streak(im, (492, 408, 526, 688), HIGHLIGHT, 15, 160)
    d.line((333, 790, 691, 790), fill=rgba(HIGHLIGHT, 210), width=13)
    polygon(d, [(348, 805), (676, 805), (640, 862), (384, 862)], rgba(CLAUDE, 255))
    return im


def candidate_c() -> Image.Image:
    """An artistic flame-mark fusion: the flame is a cutout 2 inside a lantern."""
    im = layer()
    d = ImageDraw.Draw(im)
    m = Image.new("L", im.size, 0)
    md = ImageDraw.Draw(m)
    md.ellipse((300, 200, 730, 825), fill=220)
    add_glow(im, m, CLAUDE, 42, 115)
    # Minimal cage: the negative space is part of the mark.
    d.line((365, 270, 659, 270), fill=rgba(CLAUDE, 255), width=30)
    d.line((365, 270, 323, 368, 347, 745), fill=rgba(CLAUDE, 255), width=30, joint="curve")
    d.line((659, 270, 701, 368, 677, 745), fill=rgba(CLAUDE, 255), width=30, joint="curve")
    d.line((347, 745, 677, 745), fill=rgba(CLAUDE, 255), width=30)
    # 2-shaped flame, deliberately separated from the cage so it reads at icon size.
    flame = [(512, 335), (579, 422), (622, 491), (611, 561), (575, 603),
             (531, 635), (609, 635), (609, 690), (416, 690), (416, 617),
             (536, 515), (555, 480), (542, 446), (512, 414), (484, 452),
             (478, 496), (438, 496), (435, 439)]
    polygon(d, flame, rgba(CLAUDE, 255))
    # Inner flame cut makes the 2's counter and catches a warm highlight.
    polygon(d, [(512, 435), (548, 480), (538, 510), (494, 556), (494, 590),
                (548, 542), (568, 510), (557, 472)], rgba(HIGHLIGHT, 245))
    d.line((378, 790, 646, 790), fill=rgba(HIGHLIGHT, 210), width=13)
    polygon(d, [(390, 805), (634, 805), (605, 858), (419, 858)], rgba(CLAUDE, 255))
    return im


# --- Round 2: deliberately reduced K2 monograms ---------------------------
# These variants use filled, heavy geometry instead of the first round's
# separate thin glyph strokes.  The outer lantern remains a single bold vessel
# so the mark can be judged at actual button size.

def lantern_shell(d: ImageDraw.ImageDraw, compact=False):
    """Draw the shared, simple lantern silhouette and warm glass panel."""
    if compact:
        crown = (390, 122, 634, 270)
        body = (320, 300, 704, 790)
        panel = (372, 372, 652, 710)
    else:
        crown = (365, 112, 659, 270)
        body = (300, 290, 724, 800)
        panel = (362, 365, 662, 726)
    d.arc(crown, 180, 360, fill=rgba(CLAUDE, 255), width=38)
    d.line((crown[0] + 22, 214, crown[2] - 22, 214), fill=rgba(CLAUDE, 255), width=28)
    polygon(d, [(body[0] + 10, 330), (512, 250), (body[2] - 10, 330),
                (body[2] - 52, 384), (body[0] + 52, 384)], rgba(CLAUDE, 255))
    rounded(d, body, 58, rgba(INK, 255))
    rounded(d, panel, 24, rgba(HIGHLIGHT, 242))
    d.line((body[0] + 30, 770, body[2] - 30, 770), fill=rgba(HIGHLIGHT, 220), width=14)
    polygon(d, [(body[0] + 42, 790), (body[2] - 42, 790),
                (body[2] - 78, 850), (body[0] + 78, 850)], rgba(CLAUDE, 255))


def candidate_v2_a() -> Image.Image:
    """One continuous belt-buckle stroke: K stem/arms flow into a squared 2."""
    im = layer()
    d = ImageDraw.Draw(im)
    m = Image.new("L", im.size, 0)
    ImageDraw.Draw(m).ellipse((275, 170, 750, 850), fill=220)
    add_glow(im, m, CLAUDE, 44, 110)
    lantern_shell(d)
    # A single connected monogram. The K's upper arm is the 2's top hook;
    # the lower arm becomes its diagonal return. Wide geometry is intentional.
    pts = [(414, 420), (414, 668), (470, 668), (470, 566),
           (584, 430), (620, 430), (620, 478), (486, 588),
           (486, 628), (620, 628), (620, 684), (414, 684)]
    polygon(d, pts, rgba(CLAUDE, 255))
    polygon(d, [(470, 528), (470, 420), (414, 420), (414, 484)], rgba(CLAUDE, 255))
    # Make the two diagonal K arms unmistakable without introducing detail.
    polygon(d, [(454, 512), (574, 420), (608, 420), (608, 454), (478, 555)], rgba(CLAUDE, 255))
    polygon(d, [(454, 552), (478, 524), (608, 650), (608, 684), (574, 684)], rgba(CLAUDE, 255))
    return im


def candidate_v2_b() -> Image.Image:
    """Two interlocking slabs: a very bold K locks into a blocky 2."""
    im = layer()
    d = ImageDraw.Draw(im)
    m = Image.new("L", im.size, 0)
    ImageDraw.Draw(m).ellipse((275, 170, 750, 850), fill=220)
    add_glow(im, m, CLAUDE, 44, 110)
    lantern_shell(d, compact=True)
    # K slab: one vertical and two diagonals, all the same substantial weight.
    rounded(d, (405, 412, 468, 681), 20, rgba(CLAUDE, 255))
    polygon(d, [(450, 510), (574, 412), (622, 412), (622, 465),
                (493, 566), (622, 650), (622, 690), (570, 690), (450, 584)], rgba(CLAUDE, 255))
    # 2 is a single squared ribbon, sharing the K's upper diagonal at its start.
    polygon(d, [(548, 412), (622, 412), (622, 465), (492, 568),
                (492, 625), (622, 625), (622, 685), (440, 685),
                (440, 546)], rgba(INK, 255))
    # Reassert the 2's bright top and foot so it survives downsampling.
    rounded(d, (548, 412, 622, 466), 18, rgba(CLAUDE, 255))
    rounded(d, (492, 625, 622, 685), 18, rgba(CLAUDE, 255))
    return im


def candidate_v2_c() -> Image.Image:
    """A cutout monogram: the K is a left rail and the 2 is its hooked negative."""
    im = layer()
    d = ImageDraw.Draw(im)
    m = Image.new("L", im.size, 0)
    ImageDraw.Draw(m).ellipse((275, 170, 750, 850), fill=220)
    add_glow(im, m, CLAUDE, 44, 110)
    lantern_shell(d)
    # Bright monogram mass, intentionally almost a single silhouette.
    rounded(d, (400, 412, 466, 688), 20, rgba(CLAUDE, 255))
    polygon(d, [(446, 520), (560, 412), (624, 412), (624, 466),
                (505, 568), (624, 650), (624, 688), (563, 688), (446, 584)], rgba(CLAUDE, 255))
    # Carve one large, angular counter: the remaining bright shape reads K,
    # while the outer contour reads 2 rather than a generic flame.
    polygon(d, [(510, 470), (562, 430), (590, 430), (590, 451),
                (486, 544), (486, 585), (590, 651), (590, 668),
                (558, 668), (510, 630), (448, 583), (448, 551)], rgba(HIGHLIGHT, 242))
    return im


def candidate_v2_d() -> Image.Image:
    """High-contrast side-by-side K2 lockup, sharing one center spine."""
    im = layer()
    d = ImageDraw.Draw(im)
    m = Image.new("L", im.size, 0)
    ImageDraw.Draw(m).ellipse((275, 170, 750, 850), fill=220)
    add_glow(im, m, CLAUDE, 44, 110)
    lantern_shell(d, compact=True)
    # The outer body is quieter here so the actual K2 silhouette owns the
    # 22px read. Both characters are built from broad filled polygons.
    k = rgba(CLAUDE, 255)
    # shared spine + K's two arms
    rounded(d, (395, 408, 458, 690), 19, k)
    polygon(d, [(438, 522), (535, 410), (585, 410), (585, 458),
                (475, 560), (585, 646), (585, 690), (535, 690), (438, 585)], k)
    # 2 shares the K's upper-right shoulder and is kept as one chunky ribbon.
    polygon(d, [(535, 410), (624, 410), (624, 463), (507, 558),
                (507, 624), (624, 624), (624, 690), (455, 690),
                (455, 570)], k)
    # Restore a single dark counter between the letters; it separates K from 2
    # without adding any fine internal linework.
    polygon(d, [(505, 488), (544, 456), (544, 520), (486, 570),
                (486, 612), (455, 612), (455, 570)], rgba(INK, 255))
    return im


def candidate_v2_e() -> Image.Image:
    """The same single-silhouette lockup as D, inverted for maximum contrast."""
    im = layer()
    d = ImageDraw.Draw(im)
    m = Image.new("L", im.size, 0)
    ImageDraw.Draw(m).ellipse((275, 170, 750, 850), fill=220)
    add_glow(im, m, CLAUDE, 44, 110)
    lantern_shell(d, compact=True)
    k = rgba(INK, 255)
    rounded(d, (395, 408, 458, 690), 19, k)
    polygon(d, [(438, 522), (535, 410), (585, 410), (585, 458),
                (475, 560), (585, 646), (585, 690), (535, 690), (438, 585)], k)
    polygon(d, [(535, 410), (624, 410), (624, 463), (507, 558),
                (507, 624), (624, 624), (624, 690), (455, 690),
                (455, 570)], k)
    # A single bright counter keeps the interlock visible without fine detail.
    polygon(d, [(505, 488), (544, 456), (544, 520), (486, 570),
                (486, 612), (455, 612), (455, 570)], rgba(HIGHLIGHT, 242))
    return im


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    candidates = {
        "lantern-k2-artistic-candidate-a": candidate_a(),
        "lantern-k2-artistic-candidate-b": candidate_b(),
        "lantern-k2-artistic-candidate-c": candidate_c(),
    }
    for name, im in candidates.items():
        finish(im, name)

    v2_candidates = {
        "lantern-k2-artistic-v2-candidate-a": candidate_v2_a(),
        "lantern-k2-artistic-v2-candidate-b": candidate_v2_b(),
        "lantern-k2-artistic-v2-candidate-c": candidate_v2_c(),
        "lantern-k2-artistic-v2-candidate-d": candidate_v2_d(),
        "lantern-k2-artistic-v2-candidate-e": candidate_v2_e(),
    }
    for name, im in v2_candidates.items():
        finish(im, name)
    v3_candidates = {
        "lantern-k2-artistic-v3-candidate-a": candidate_v3_a(),
        "lantern-k2-artistic-v3-candidate-b": candidate_v3_b(),
        "lantern-k2-artistic-v3-candidate-c": candidate_v3_c(),
    }
    for name, im in v3_candidates.items():
        finish(im, name)
    # Candidate A is the selected ship asset: its continuous body/ribbon keeps a
    # clear lantern silhouette and a clear 2 at 22px; B's K2 panel turns noisy,
    # while C reads as a 2 but loses the K2 relationship.
    finish(candidates["lantern-k2-artistic-candidate-a"], "lantern-k2-artistic")
    print(f"Sampled source lantern color: #{BRAND[0]:02x}{BRAND[1]:02x}{BRAND[2]:02x}")
    print("Round 1 recommended: lantern-k2-artistic (candidate A)")
    print("Round 2 outputs: " + ", ".join(sorted(v2_candidates)))
    print("Round 3 outputs: " + ", ".join(sorted(v3_candidates)))
    for p in sorted(OUT.glob("lantern-k2-artistic*.png")):
        print(p)


if __name__ == "__main__":
    main()
