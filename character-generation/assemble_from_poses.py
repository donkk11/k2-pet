#!/usr/bin/env python3
"""Turns a human's (or Claude's) pose-number assignment into the exact per-row strip files
build_character.py expects. This is the real bridge between detect_poses.py's raw, irregularly
-sized crops and the pipeline's fixed 192x208-cell contract.

mapping.json format:
{
  "idle": [1, 2, 3, 4, 5, 6],
  "running-right": [9, 10, 11, 12, 13, 14, 15, 16],
  "running-left": {"mirror_of": "running-right"},
  "waving": [25, 26, 27, 27]
}
Frame counts must match each row's real required count (idle=6, running-right/left=8,
waving=4, jumping=5, failed=8, waiting=6, working=6, review=6, gaze-row9/10=8) -- repeat a
number to pad a short sequence; this script will not silently invent frames.
"""
import argparse
import json
from pathlib import Path

from PIL import Image, ImageOps

CELL_W, CELL_H = 192, 208
SAFE_W, SAFE_H = CELL_W - 2 * 18, CELL_H - 2 * 16

ROW_FRAME_COUNTS = {
    "idle": 6, "running-right": 8, "running-left": 8, "waving": 4, "jumping": 5,
    "failed": 8, "waiting": 6, "working": 6, "review": 6,
    "gaze-row9": 8, "gaze-row10": 8,
}


def normalize_to_cell(crop: Image.Image) -> Image.Image:
    """Scale a real, irregularly-sized detected pose to fit the safe area of a 192x208 cell,
    bottom-anchored and horizontally centered -- so frames line up the way a real atlas row
    already does, even though these crops came from independent, differently-scaled sources."""
    crop = crop.convert("RGBA")
    scale = min(SAFE_W / crop.width, SAFE_H / crop.height, 1.0)
    new_size = (max(1, round(crop.width * scale)), max(1, round(crop.height * scale)))
    resized = crop.resize(new_size, Image.LANCZOS)
    canvas = Image.new("RGBA", (CELL_W, CELL_H), (0, 0, 0, 0))
    x = (CELL_W - resized.width) // 2
    y = CELL_H - 16 - resized.height  # bottom-anchored inside the safe margin
    canvas.paste(resized, (x, max(0, y)), resized)
    return canvas


def build_strip(pose_files, poses_dir: Path) -> Image.Image:
    cells = [normalize_to_cell(Image.open(poses_dir / f"pose_{n:03d}.png")) for n in pose_files]
    strip = Image.new("RGBA", (CELL_W * len(cells), CELL_H), (0, 0, 0, 0))
    for i, cell in enumerate(cells):
        strip.paste(cell, (i * CELL_W, 0))
    return strip


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--poses-dir", required=True, help="Output dir from detect_poses.py (contains poses/ and poses_index.json).")
    ap.add_argument("--mapping", required=True)
    ap.add_argument("--out", required=True, help="Where to write the assembled *.png row files, ready for build_character.py --input-dir.")
    args = ap.parse_args()

    poses_dir = Path(args.poses_dir) / "poses"
    mapping = json.loads(Path(args.mapping).read_text())
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    built = {}
    deferred_mirrors = {}
    for row_name, value in mapping.items():
        if isinstance(value, dict) and "mirror_of" in value:
            deferred_mirrors[row_name] = value["mirror_of"]
            continue
        expected = ROW_FRAME_COUNTS.get(row_name)
        if expected is not None and len(value) != expected:
            print(f"SKIP {row_name}: mapping has {len(value)} frames, this row needs exactly {expected}")
            continue
        strip = build_strip(value, poses_dir)
        strip.save(out_dir / f"{row_name}.png")
        built[row_name] = strip
        print(f"built {row_name}.png -- {len(value)} frames from poses {value}")

    for row_name, source in deferred_mirrors.items():
        if source not in built:
            print(f"SKIP {row_name}: mirror_of '{source}' was not built")
            continue
        mirrored = ImageOps.mirror(built[source])
        mirrored.save(out_dir / f"{row_name}.png")
        print(f"built {row_name}.png -- real horizontal mirror of {source}.png (no independent frames available)")

    print(f"\nAssembled rows are in: {out_dir}")
    print("Next: python3 build_character.py --input-dir", out_dir)


if __name__ == "__main__":
    main()
