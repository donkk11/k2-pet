# Build your own K2 pet character — real prompts, any image AI

This project's code can't generate images. This is the actual workaround: real prompts,
grounded in the exact parameters the two working characters (Gentleman KK, K2 Nkama) were
really built with — not guessed — that you paste into any image-generating AI you already
have access to (ChatGPT/DALL-E, Midjourney, Gemini, etc.). The output feeds directly into
`build_character.py`, which does the real, automated extraction work.

## Why 11 separate prompts, not one

The real pipeline that built Gentleman KK and K2 Nkama never generated one giant sheet in a
single shot — it generated one pose-strip at a time, feeding the FIRST result back in as a
reference image for every later prompt so the character stays consistent. Asking any image AI
for one perfect 88-cell grid in one pass is not something today's tools do reliably; asking for
one strip at a time, with a reference image, is.

**Already have a loose sheet from one general prompt instead?** That's the realistic case —
most people won't run 11 separate prompts. Don't throw it away: `detect_poses.py` finds each
individual pose automatically (proven on three real, very different sheets — a flat-green-alpha
one, a solid-black-background one, and a solid-green-background one), builds a numbered contact
sheet, and `assemble_from_poses.py` turns a `{state: [pose numbers]}` mapping into the exact
strip format below. Missing poses (no dedicated "review" gesture, only one running direction,
etc.) are real and fine — `build_character.py` only requires `idle`; everything else is optional
and the pet just won't have that specific animation rather than faking it.

## Two real ways to get the image — text description vs. a reference sheet

**Method A — the precise prompts below.** Describe the character in words (Step 0), then run
the 11 per-pose prompts one at a time, each with the previous result attached as a reference
image. Most control over exact content per pose, most separate steps, most typing.

**Method B — paste a reference sheet instead of describing the format in words.** This is the
faster, more realistic path for most people, and it's real, not theoretical — three of this
project's characters (Einstein, Basketball Kid, Bruce Lee) were built this exact way.
`samples/example-format-sheet.webp` is a real sprite sheet already in this repo (idle, two
running directions, a wave, jump/action poses, a ready stance, an active pose). Attach it
**and** a reference photo or clear description of the character you actually want to any image
AI that supports multiple image attachments (ChatGPT, Gemini, Midjourney with multiple image
prompts, etc.), then prompt:

```
Using the exact same sprite-sheet format, layout, and pose types as the first attached
image (idle standing poses, two running-direction cycles, a greeting wave, a jump/action
sequence, a ready/fighting stance, and an active pose using an object), generate an
equivalent sprite sheet for the character shown in the second attached image. Keep it in
that same style: a single flat solid-color background across the whole sheet (not per-cell),
consistent character scale and camera angle in every pose, one pose type per row.
```

**The real tradeoff between them:** Method A, followed precisely, can skip straight to
`build_character.py` — no assignment step needed, since you already know exactly which file is
which pose. Method B is faster to get an image back, but the AI decides its own grid and pose
count (like all three real examples above), so it always needs the adapter
(`detect_poses.py` + `assemble_from_poses.py`) and someone looking at the contact sheet to say
which numbers are which pose — real semantic work Method A avoids by being precise up front.

## Step 0 — describe your character once

Fill this in and keep it handy — you'll paste it into every prompt below.

```
CHARACTER: [name], a [age/build] [description] with [hair/face details], wearing
[outfit description, be specific about colors/materials]. Personality: [2-3 traits].
```

## The real technical contract (do not change these numbers)

- **Cell size: exactly 192×208 pixels** per pose, no exceptions — this is what every part of
  the extraction pipeline assumes.
- **Background: solid, flat, pure green (#00FF00)**, no gradient, no shadow cast onto it.
  (Real characters used green-screen chroma-key, not "transparent PNG" — most image AIs can't
  reliably produce clean alpha edges, but nearly all of them can produce a flat green
  background, which `build_character.py` keys out for real afterward.)

  **If you've been told to ask for "transparent background" or a checkerboard preview
  instead — don't.** That advice sounds reasonable but isn't grounded in what these tools
  actually do: a chat-based image generator (ChatGPT/DALL-E, Midjourney, Gemini) has no real
  alpha channel to paint into. Ask one for "transparent" and it either ignores you, or -- worse
  -- draws an actual picture of a grey-and-white checkerboard pattern as solid pixels, since
  that's what transparency looks like in its training data. That's harder to remove
  programmatically than a flat color, not easier: a checkerboard is a busy, multi-tone pattern,
  not a single hue a distance-based chroma key can threshold against. Confirmed directly,
  twice, in this project: `samples/example-format-sheet.webp` (the sheet that really built
  Einstein, Basketball Kid, and Bruce Lee) measures as solid `RGB(3,250,5)`, and a completely
  different character built from a plain white-background sheet worked identically with zero
  code changes. The real requirement is "one flat, solid color, no pattern" -- green is just
  the traditional choice (unlikely to clash with skin or clothing tones), not a hard technical
  requirement.

  **The one real exception**: if you have an actual way to produce a genuinely
  alpha-transparent PNG — not by asking a chat image AI for one (see above), but from a
  real editing tool, an export pipeline, or any process that writes real per-pixel alpha —
  that's the ideal input, better than a flat color, and this pipeline already supports it
  directly: `build_character.py`'s own `has_real_alpha()` check looks for genuine alpha
  variation (not a uniform 255 everywhere) and skips chroma-keying entirely when it finds
  it, using your real alpha as-is. The real, checkable bar for "is this actually
  transparent, not a picture of transparency": open it in Python and confirm
  `Image.open(path).convert("RGBA")`'s alpha channel is **not** uniformly 255 — background
  pixels should read close to alpha=0, not alpha=255 with a grey-and-white pattern painted
  into the RGB channels. If you can't verify that, assume it's a checkerboard picture, not
  real alpha, and use the flat-color path above instead.
- **Style**: "Stylized 3D toy mascot with smooth rounded forms, simple materials, clear
  silhouette, no photoreal complexity. Compact human proportions, face and glasses/features
  readable at 192×208, clean silhouette, no text or logos except one small approved chest
  mark, no detached effects." (This exact style contract is what both real characters used.)
- **Margins**: keep the character inside an 18px horizontal / 16px vertical safe margin per
  cell — nothing should touch the cell edge.
- **Identity lock**: every prompt after the first must say "the exact same character as the
  reference image — same face, same outfit, same proportions, same colors" and should attach
  your first successful generation as a reference/edit-image input if your tool supports that
  (most current ones do: image-to-image, "edit this image," or a reference-image parameter).

## Step 1 — the identity/idle prompt (generate this first, save the result as your reference)

```
[YOUR CHARACTER DESCRIPTION FROM STEP 0].
Generate a horizontal sprite sheet: 6 frames side by side, each frame exactly 192x208 pixels
(total image 1152x208), on a solid flat pure green (#00FF00) background with no shadow.
Style: stylized 3D toy mascot, smooth rounded forms, simple materials, clear silhouette,
compact human proportions, face readable at this size, no text except one small approved
chest mark. Content: a calm idle standing loop -- neutral standing pose, subtle breathing/
weight-shift variation, a blink in one frame. Character stays centered, same scale, same
camera angle (straight-on, full body) in every frame. Keep an 18px horizontal / 16px vertical
margin inside each 192x208 cell -- nothing touches the cell edge.
```

## Naming: the state matters, not the literal content

Each row below is named for *when the app shows it* (`working`, `waiting`, `jumping`...),
not for one fixed action. Gentleman KK's `working` is a laptop scene because that's what
he does at a desk — but that's a choice for that character, not a requirement of the
`working` slot itself. Pick real content that fits *your* character's identity for the
same moment: a basketball character's `working` can be a real dribble-to-dunk sequence
(shipped: `bball`, `basketball-player`) instead of a laptop; its `waiting` can be spinning
a ball on one finger instead of a thumbs-up. What has to stay fixed is *when* the app
shows that row (still mid-task, waiting for permission, etc.) and its real frame count —
the story you tell in those frames is yours to design per character.

## Step 2 — the rest of the poses (use your Step 1 result as the reference image each time)

For each block below: attach your saved Step 1 image as a reference, then paste the prompt.

**running-right.png** (8 frames, 1536×208 total)
```
The exact same character as the reference image -- same face, same outfit, same proportions,
same colors. Horizontal sprite sheet: 8 frames, each exactly 192x208px (total 1536x208), solid
flat pure green (#00FF00) background. Content: a rightward running/movement loop, full body,
same camera angle and scale as the reference. 18px/16px safe margins per cell.
```

**running-left.png** (8 frames, 1536×208 total) — same prompt as above, "leftward" instead of "rightward."

**waving.png** (4 frames, 768×208 total)
```
The exact same character as the reference image. Horizontal sprite sheet: 4 frames, each
exactly 192x208px (total 768x208), solid flat pure green (#00FF00) background. Content: a
friendly greeting wave -- arm raised and waving at the camera, 1-2 idle frames before/after.
Same camera angle and scale as the reference. 18px/16px safe margins per cell.
```

**jumping.png** (5 frames, 960×208 total)
```
The exact same character as the reference image. Horizontal sprite sheet: 5 frames, each
exactly 192x208px (total 960x208), solid flat pure green (#00FF00) background. Content: a
playful jump/celebration arc -- crouch, launch, peak with arms up, landing. Same camera angle
and scale as the reference. 18px/16px safe margins per cell.
```

**failed.png** (8 frames, 1536×208 total)
```
The exact same character as the reference image. Horizontal sprite sheet: 8 frames, each
exactly 192x208px (total 1536x208), solid flat pure green (#00FF00) background. Content: a
disappointed/blocked reaction -- shoulders drop, a discouraged gesture, resetting back toward
neutral by the last frame. Same camera angle and scale as the reference. 18px/16px safe
margins per cell.
```

**waiting.png** (6 frames, 1152×208 total)
```
The exact same character as the reference image. Horizontal sprite sheet: 6 frames, each
exactly 192x208px (total 1152x208), solid flat pure green (#00FF00) background. Content: an
"acknowledging, please wait" loop -- a thumbs-up or reassuring gesture, patient standing pose.
Same camera angle and scale as the reference. 18px/16px safe margins per cell.
```

**working.png** (6 frames, 1152×208 total)
```
The exact same character as the reference image. Horizontal sprite sheet: 6 frames, each
exactly 192x208px (total 1152x208), solid flat pure green (#00FF00) background. Content:
sitting cross-legged on the ground with an open laptop, actively typing/working, small head
movements between frames. Same camera angle and scale as the reference. 18px/16px safe margins
per cell.
```

**review.png** (6 frames, 1152×208 total)
```
The exact same character as the reference image. Horizontal sprite sheet: 6 frames, each
exactly 192x208px (total 1152x208), solid flat pure green (#00FF00) background. Content:
inspecting/reviewing something closely -- holding a magnifying glass up, examining, a
satisfied nod by the last frame. Same camera angle and scale as the reference. 18px/16px safe
margins per cell.
```

**gaze-row9.png** (8 frames, 1536×208 total) -- the first 8 of 16 real look-directions
```
The exact same character as the reference image, in its neutral idle standing pose (do not
change the body pose). Horizontal sprite sheet: 8 frames, each exactly 192x208px (total
1536x208), solid flat pure green (#00FF00) background. Content: ONLY the head/eyes turn
between frames, body stays still and centered. Frame 1: looking straight up. Frame 2: up and
slightly right. Frame 3: up-right diagonal. Frame 4: right and slightly up. Frame 5: looking
straight right. Frame 6: right and slightly down. Frame 7: down-right diagonal. Frame 8: down
and slightly right. Smooth clockwise progression from up to down-right. Same camera angle and
scale as the reference. 18px/16px safe margins per cell.
```

**gaze-row10.png** (8 frames, 1536×208 total) -- the remaining 8 of 16 real look-directions
```
The exact same character as the reference image, in its neutral idle standing pose (do not
change the body pose). Horizontal sprite sheet: 8 frames, each exactly 192x208px (total
1536x208), solid flat pure green (#00FF00) background. Content: ONLY the head/eyes turn
between frames, body stays still and centered. Frame 1: looking straight down. Frame 2: down
and slightly left. Frame 3: down-left diagonal. Frame 4: left and slightly down. Frame 5:
looking straight left. Frame 6: left and slightly up. Frame 7: up-left diagonal. Frame 8: up
and slightly left. Smooth clockwise progression continuing from down to up-left. Same camera
angle and scale as the reference. 18px/16px safe margins per cell.
```

## Step 3 — save your files with these exact names

Put all 9 files in one folder:

```
idle.png  running-right.png  running-left.png  waving.png  jumping.png
failed.png  waiting.png  working.png  review.png  gaze-row9.png  gaze-row10.png
```

## Step 4 — run the real extraction

One-time setup (this needs numpy/scipy/Pillow, separate from the core pet's own
`pywebview`/`pyobjc` dependencies since not everyone needs to build a character):

```bash
pip3 install -r k2-extended-pet-states/character-generation/requirements.txt
```

```bash
python3 k2-extended-pet-states/character-generation/build_character.py \
  --input-dir /path/to/your/saved/images \
  --character-id my-character \
  --label "My Character"
```

It validates every file's real dimensions, keys out the green background for real (not
guessed), tight-crops every strip, extracts all 16 real gaze frames, and prints a clear
pass/fail report — it does **not** silently register the character as ready. Read the report,
look at the generated contact sheet, and only then add it to `characters.json` yourself (the
script tells you the exact line to add).

## Known real limitation

Image AIs are not perfectly consistent across separate generations even with a reference image
— expect some outfit/proportion drift between strips, especially on cheaper or less
steerable models. That's a real limitation of today's image-gen tools, not something this
pipeline can paper over. Regenerate any strip that drifted before running the extraction.
