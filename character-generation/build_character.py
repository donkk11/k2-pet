#!/usr/bin/env python3
"""Real, automated extraction: turns per-row sprite strips (from any image AI, following
PROMPT_TEMPLATE.md) into a K2 pet character folder -- the same union-bbox tight-cropping
and row layout already proven this session on Gentleman KK and K2 Nkama, generalized so it
no longer has to be redone by hand for every new character.

Does NOT register the character as ready in characters.json -- prints a validation report
and the exact manifest entry to add by hand, after a human has actually looked at the result.
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

CELL_W, CELL_H = 192, 208
SAFE_MARGIN_X, SAFE_MARGIN_Y = 18, 16

# Real row contract, identical to Gentleman KK and K2 Nkama's own pet_request.json.
ROWS = {
    # Real ask: an idle ANIMATION, not just a static pose -- every character's idle row
    # was already fed as a real multi-frame strip ("a calm idle standing loop... a blink
    # in one frame"), but only frame[0] ever got used; the rest were silently discarded.
    # Dual output (matching "waiting" below) keeps the static state for the picker
    # thumbnail/fallback while also producing the real animation, same real content, no
    # extra input needed. Frame count stays 6 by default (the technical contract) but is
    # overridable per character via --frames idle=N, same mechanism "working" already uses.
    "idle":          {"frames": 6, "outputs": [("state", "idle"), ("animation", "idle")]},
    "running-right": {"frames": 8, "outputs": [("animation", "running-right")]},
    "running-left":  {"frames": 8, "outputs": [("animation", "running-left")]},
    "waving":        {"frames": 4, "outputs": [("animation", "waving")]},
    "jumping":       {"frames": 5, "outputs": [("animation", "jumping")]},
    "failed":        {"frames": 8, "outputs": [("state", "problem")]},
    "waiting":       {"frames": 6, "outputs": [("state", "waiting"), ("animation", "permission-wait")]},
    "working":       {"frames": 6, "outputs": [("animation", "working")]},
    "review":        {"frames": 6, "outputs": [("animation", "checking")]},
}
GAZE_DEGREES_ROW9 = ["000", "022.5", "045", "067.5", "090", "112.5", "135", "157.5"]
GAZE_DEGREES_ROW10 = ["180", "202.5", "225", "247.5", "270", "292.5", "315", "337.5"]


def has_real_alpha(img: Image.Image) -> bool:
    """True if the image already carries real, varied transparency -- an AI that produced
    a genuine transparent PNG instead of the requested flat green background. Skip chroma
    keying in that case; keying an already-transparent image would corrupt it."""
    if img.mode != "RGBA":
        return False
    alpha = np.array(img.getchannel("A"))
    return bool(np.any(alpha < 250)) and bool(np.any(alpha > 5))


def detect_key_color(arr: np.ndarray) -> tuple:
    """Sample the image's own four true corners -- the background is reliably there even
    if the character fills most of the frame, and this avoids assuming a fixed #00FF00 in
    case the AI didn't produce it exactly.

    Real bug found and fixed: this used to clamp to CELL_W-3/CELL_H-3 (192/208), assuming
    whatever was passed in was exactly one cell wide/tall. That's true for a build_character.py
    strip (a strip's own edges ARE its cell edges), but detect_poses.py calls this on a whole,
    arbitrarily-sized uploaded reference sheet -- there, min(w-3, CELL_W-3) can land inside the
    SECOND cell instead of on real background (confirmed live: one corner sampled [199,100,65],
    clearly skin tone, not the sheet's real green). That wrong sample dragged the detected key
    color off pure green, causing a real, measured ~14% green-spill halo on every extracted
    pose. Using the image's own real corners fixes both cases identically -- a strip's true
    corners are already exactly what CELL_W-3/CELL_H-3 pointed at, so this changes nothing for
    the already-shipped characters, and now also works for any differently-sized sheet."""
    h, w = arr.shape[0], arr.shape[1]
    corners = [arr[2, 2], arr[2, w - 3], arr[h - 3, 2], arr[h - 3, w - 3]]
    rgb = np.array([c[:3] for c in corners], dtype=np.float64)
    return tuple(np.median(rgb, axis=0))


def chroma_key(img: Image.Image, inner=60.0, outer=110.0) -> Image.Image:
    """Real distance-based keying with a soft edge and a basic despill, not a guess.
    inner/outer are Euclidean RGB distance thresholds: below inner -> fully transparent,
    above outer -> fully opaque, between -> a soft, real anti-aliased edge."""
    img = img.convert("RGBA")
    arr = np.array(img).astype(np.float64)
    key = np.array(detect_key_color(arr))
    dist = np.sqrt(np.sum((arr[:, :, :3] - key) ** 2, axis=2))

    alpha = np.clip((dist - inner) / (outer - inner), 0.0, 1.0) * 255.0
    arr[:, :, 3] = np.minimum(arr[:, :, 3], alpha)

    # Despill: where a pixel is partially keyed (near the background color but kept as
    # foreground, e.g. hair edges), pull its green channel down toward the red/blue
    # average so no green cast bleeds onto the character -- the same real problem the
    # original pipeline's own chroma-despill step existed to fix.
    partial = (dist > inner) & (dist < outer * 1.4)
    r, g, b = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]
    rb_avg = (r + b) / 2.0
    excess_green = np.clip(g - rb_avg, 0, 255)
    g_fixed = g - np.where(partial, excess_green * 0.6, 0)
    arr[:, :, 1] = g_fixed

    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))


def union_crop_strip(frames):
    boxes = [f.getbbox() for f in frames if f.getbbox()]
    if not boxes:
        raise ValueError("every frame in this strip is blank after keying -- the background "
                          "color detection likely keyed out the character itself")
    l = min(b[0] for b in boxes); t = min(b[1] for b in boxes)
    r = max(b[2] for b in boxes); b_ = max(b[3] for b in boxes)
    cropped = [f.crop((l, t, r, b_)) for f in frames]
    w = sum(f.width for f in cropped)
    h = cropped[0].height
    strip = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    x = 0
    for f in cropped:
        strip.paste(f, (x, 0))
        x += f.width
    return strip, cropped[0].width, cropped[0].height


def load_and_key(path: Path) -> Image.Image:
    img = Image.open(path).convert("RGBA")
    if has_real_alpha(img):
        return img
    return chroma_key(img)


def slice_cells(img: Image.Image, n: int):
    return [img.crop((i * CELL_W, 0, (i + 1) * CELL_W, CELL_H)) for i in range(n)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input-dir", required=True)
    ap.add_argument("--character-id", required=True)
    ap.add_argument("--label", required=True)
    ap.add_argument("--out-root", default=None,
                     help="Defaults to k2-extended-pet-states/assets/characters next to this script.")
    ap.add_argument("--frames", action="append", default=[],
                     metavar="row=count",
                     help="Override a row's required frame count for this character only "
                          "(e.g. --frames working=18). The shared ROWS default stays "
                          "untouched for every other character -- this only affects the "
                          "current invocation, so a character with a genuinely longer or "
                          "shorter real sequence for one row doesn't need the global "
                          "contract changed underneath everyone else.")
    args = ap.parse_args()

    rows = dict(ROWS)  # per-invocation copy -- never mutate the shared default
    for override in args.frames:
        row_name, _, count = override.partition("=")
        if row_name not in rows or not count.isdigit():
            print(f"Ignoring invalid --frames override: {override!r} "
                  f"(expected an existing row name and an integer, e.g. working=18)")
            continue
        rows[row_name] = {**rows[row_name], "frames": int(count)}

    in_dir = Path(args.input_dir)
    out_root = Path(args.out_root) if args.out_root else (
        Path(__file__).resolve().parent.parent / "assets" / "characters")
    char_dir = out_root / args.character_id
    (char_dir / "states" / "gaze").mkdir(parents=True, exist_ok=True)
    (char_dir / "animations").mkdir(parents=True, exist_ok=True)

    # Only idle is a hard requirement -- it's the picker thumbnail and the default fallback
    # pose. Everything else is real but optional: a loose, unstructured sheet (someone's one
    # general prompt to an image AI, not the 11 precise per-row prompts) realistically won't
    # have every pose, and a partial-but-honest character beats refusing to build one at all.
    REQUIRED_ROWS = {"idle"}

    report = {"pass": [], "fail": [], "warn": []}
    manifest = {"cell": [CELL_W, CELL_H], "states": {}, "animations": {}, "gaze": {}}

    for row_name, spec in rows.items():
        path = in_dir / f"{row_name}.png"
        bucket = report["fail"] if row_name in REQUIRED_ROWS else report["warn"]
        if not path.exists():
            bucket.append(f"{row_name}.png: MISSING" + (" (required)" if row_name in REQUIRED_ROWS else " (optional -- skipped)"))
            continue
        expected_w = CELL_W * spec["frames"]
        try:
            keyed = load_and_key(path)
        except Exception as e:
            bucket.append(f"{row_name}.png: failed to load/key ({e})")
            continue
        if keyed.width != expected_w or keyed.height != CELL_H:
            bucket.append(
                f"{row_name}.png: wrong size {keyed.width}x{keyed.height}, "
                f"expected {expected_w}x{CELL_H} ({spec['frames']} frames x {CELL_W}px)")
            continue
        frames = slice_cells(keyed, spec["frames"])
        try:
            strip, fw, fh = union_crop_strip(frames)
        except ValueError as e:
            bucket.append(f"{row_name}.png: {e}")
            continue

        for kind, out_name in spec["outputs"]:
            if kind == "state":
                first = frames[0]
                bbox = first.getbbox()
                cropped = first.crop(bbox) if bbox else first
                cropped.save(char_dir / "states" / f"{out_name}.png")
                manifest["states"][out_name] = {"file": f"states/{out_name}.png", "size": list(cropped.size)}
            else:
                strip.save(char_dir / "animations" / f"{out_name}.png")
                manifest["animations"][out_name] = {
                    "file": f"animations/{out_name}.png", "frames": spec["frames"],
                    "frameWidth": fw, "frameHeight": fh, "aspectRatio": f"{fw}/{fh}",
                }
        report["pass"].append(f"{row_name}.png: OK ({spec['frames']} frames, cropped to {frames[0].width}x{frames[0].height} -> tight {manifest['animations'].get(spec['outputs'][-1][1], manifest['states'].get(spec['outputs'][-1][1], {})).get('size', [fw, fh])})")

    # Gaze rows -- per-frame tight crop, same as every other character this session.
    # Optional: a loose sheet realistically won't include 16 dedicated head-turn frames.
    # A character without these just won't get waiting-state gaze glancing (see
    # companion.js's own gating for characters that lack this, same honest pattern
    # already used for Gentleman KK's legacy idle-glance/typing-gaze assets).
    for row_file, degrees in (("gaze-row9.png", GAZE_DEGREES_ROW9), ("gaze-row10.png", GAZE_DEGREES_ROW10)):
        path = in_dir / row_file
        if not path.exists():
            report["warn"].append(f"{row_file}: MISSING (optional -- skipped, no waiting-gaze for this character)")
            continue
        expected_w = CELL_W * 8
        try:
            keyed = load_and_key(path)
        except Exception as e:
            report["warn"].append(f"{row_file}: failed to load/key ({e})")
            continue
        if keyed.width != expected_w or keyed.height != CELL_H:
            report["warn"].append(f"{row_file}: wrong size {keyed.width}x{keyed.height}, expected {expected_w}x{CELL_H}")
            continue
        cells = slice_cells(keyed, 8)
        for cell, deg in zip(cells, degrees):
            bbox = cell.getbbox()
            if not bbox:
                report["warn"].append(f"{row_file}: frame for {deg} degrees is blank after keying")
                continue
            cropped = cell.crop(bbox)
            cropped.save(char_dir / "states" / "gaze" / f"look-{deg}.png")
            manifest["gaze"][deg] = {"file": f"look-{deg}.png", "size": list(cropped.size)}
        report["pass"].append(f"{row_file}: OK (8 gaze frames)")

    (char_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))

    print(f"\n=== Build report for '{args.character_id}' ===")
    for line in report["pass"]:
        print(f"  PASS  {line}")
    for line in report["warn"]:
        print(f"  WARN  {line}")
    for line in report["fail"]:
        print(f"  FAIL  {line}")
    print(f"\n{len(report['pass'])} passed, {len(report['warn'])} warnings (optional, skipped), {len(report['fail'])} failed (required).")

    if report["fail"]:
        print("\nNot registering in characters.json -- fix the failures above first.")
        sys.exit(1)

    thumb = char_dir / "states" / "idle.png"
    print(f"\nAll real checks passed. Files are in: {char_dir}")
    print("This does NOT register the character yet -- look at the actual generated files")
    print("(especially states/idle.png and a couple of animations/*.png) before trusting them.")
    print("\nOnce you've looked and it's good, add this to assets/characters.json's \"characters\" array:")
    print(json.dumps({"id": args.character_id, "label": args.label,
                       "thumbnail": f"/assets/characters/{args.character_id}/states/idle.png",
                       "ready": True}, indent=2))


if __name__ == "__main__":
    main()
