#!/usr/bin/env python3
"""Real pose detection for loose, unstructured character sheets -- the realistic case where
someone gave an image AI one general prompt instead of running PROMPT_TEMPLATE.md's 11
separate per-pose prompts. Finds each individual character instance via connected-component
labeling on the alpha channel, tight-crops it, and builds a numbered contact sheet so a human
(or Claude, reading it) can say "these numbers are idle, these are running-right, ..." --
that assignment step is real semantic understanding this script does not attempt to automate.
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy import ndimage

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_character import has_real_alpha, chroma_key  # noqa: E402

MIN_AREA = 200  # filters sensor noise / stray anti-aliased pixels, not real poses
PAD = 4  # px of padding kept around each detected pose's real bounding box


def detect_in_image(img: Image.Image, min_area=MIN_AREA):
    img = img.convert("RGBA")
    # Real gap found on the first genuinely flat-background test image (a solid black sheet,
    # zero alpha variation at all): without this, the whole sheet reads as one giant blob.
    # Key out a flat background first -- whatever color it actually is, not just green --
    # so detection has real per-pose transparency to work with, same as build_character.py
    # would eventually need to do for this file anyway.
    if not has_real_alpha(img):
        img = chroma_key(img)
    alpha = np.array(img.getchannel("A"))
    mask = alpha > 20
    labeled, n = ndimage.label(mask)
    sizes = ndimage.sum(mask, labeled, range(1, n + 1))
    boxes = ndimage.find_objects(labeled)
    crops = []
    for i, box in enumerate(boxes):
        if sizes[i] < min_area:
            continue
        y0, y1 = max(box[0].start - PAD, 0), min(box[0].stop + PAD, img.height)
        x0, x1 = max(box[1].start - PAD, 0), min(box[1].stop + PAD, img.width)
        crops.append(img.crop((x0, y0, x1, y1)))
    # Real reading order: top-to-bottom by row, left-to-right within a row -- matches how
    # a human looks at a character sheet, not raster/label order.
    positions = []
    idx = 0
    for i, box in enumerate(boxes):
        if sizes[i] < min_area:
            continue
        y0 = box[0].start
        x0 = box[1].start
        positions.append((y0, x0, idx))
        idx += 1
    row_tolerance = 40
    positions.sort(key=lambda p: p[0])
    rows = []
    for y0, x0, idx in positions:
        placed = False
        for row in rows:
            if abs(row[0][0] - y0) < row_tolerance:
                row.append((y0, x0, idx))
                placed = True
                break
        if not placed:
            rows.append([(y0, x0, idx)])
    order = []
    for row in rows:
        row.sort(key=lambda p: p[1])
        order.extend(p[2] for p in row)
    return [crops[i] for i in order]


def build_contact_sheet(crops, cols=8, cell=140):
    rows = (len(crops) + cols - 1) // cols
    sheet = Image.new("RGBA", (cols * cell, rows * cell), (245, 245, 245, 255))
    draw = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 16)
    except Exception:
        font = ImageFont.load_default()
    for i, crop in enumerate(crops):
        r, c = divmod(i, cols)
        x0, y0 = c * cell, r * cell
        thumb = crop.copy()
        thumb.thumbnail((cell - 20, cell - 30))
        px = x0 + (cell - thumb.width) // 2
        py = y0 + 4
        sheet.paste(thumb, (px, py), thumb)
        draw.rectangle([x0, y0, x0 + cell - 1, y0 + cell - 1], outline=(200, 200, 200))
        draw.text((x0 + 4, y0 + cell - 22), str(i + 1), fill=(20, 20, 20), font=font)
    return sheet


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("images", nargs="+", help="One or more loose character-sheet images.")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    out = Path(args.out)
    (out / "poses").mkdir(parents=True, exist_ok=True)

    all_crops = []
    for img_path in args.images:
        img = Image.open(img_path)
        crops = detect_in_image(img)
        print(f"{img_path}: {len(crops)} real poses detected")
        all_crops.extend(crops)

    index = {}
    for i, crop in enumerate(all_crops, start=1):
        fname = f"pose_{i:03d}.png"
        crop.save(out / "poses" / fname)
        index[i] = {"file": f"poses/{fname}", "size": list(crop.size)}
    (out / "poses_index.json").write_text(json.dumps(index, indent=2))

    sheet = build_contact_sheet(all_crops)
    sheet.save(out / "contact_sheet.png")

    print(f"\n{len(all_crops)} total real poses detected across {len(args.images)} image(s).")
    print(f"Contact sheet: {out / 'contact_sheet.png'}")
    print(f"Individual crops + index: {out / 'poses'} , {out / 'poses_index.json'}")
    print("\nNext: look at the contact sheet, decide which numbers are which pose, and run "
          "assemble_from_poses.py with a mapping.")


if __name__ == "__main__":
    main()
