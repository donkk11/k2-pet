import os
import textwrap
from PIL import Image, ImageDraw, ImageFont


OUT = os.path.join(os.path.dirname(__file__), "k2-pet-blueprint.png")
W, H = 2400, 1600
NAVY, PANEL, GRID = "#0a1929", "#0d2238", "#153958"
CYAN, WHITE, MUTED = "#7fe8ff", "#f2fbff", "#a8cfdb"
YELLOW, ORANGE = "#ffe59a", "#ffbc7a"


def font(size, bold=False):
    path = "/System/Library/Fonts/SFNSMono.ttf"
    if bold:
        path = "/System/Library/Fonts/SFNSMono.ttf"
    return ImageFont.truetype(path, size)


def wrap(s, width):
    return "\n".join(textwrap.wrap(s, width=width, break_long_words=False))


im = Image.new("RGB", (W, H), NAVY)
d = ImageDraw.Draw(im)

# Blueprint drafting grid.
for x in range(0, W + 1, 60):
    d.line((x, 0, x, H), fill=GRID, width=1)
for y in range(0, H + 1, 60):
    d.line((0, y, W, y), fill=GRID, width=1)

title_f, sub_f, zone_f = font(42, True), font(18), font(22, True)
body_f = font(15)
small_f = font(14)
label_f = font(14)

d.text((85, 45), "K2 PET -- SYSTEM BLUEPRINT", font=title_f, fill=WHITE)
d.text((85, 98), "FULL ARCHITECTURE / LOCAL MACOS COMPANION / ENGINEERING SCHEMATIC", font=sub_f, fill=CYAN)
d.text((2315, 48), "AS OF 2026-10-10", font=font(20), fill=YELLOW, anchor="ra")
d.line((85, 130, 2315, 130), fill=CYAN, width=2)


def box(x, y, w, h, layer, title, body, size=15):
    d.rounded_rectangle((x, y, x + w, y + h), radius=18, fill=PANEL, outline=CYAN, width=3)
    d.text((x + 22, y + 17), f"LAYER {layer}", font=font(16, True), fill=YELLOW)
    d.text((x + 150, y + 17), title, font=zone_f, fill=WHITE)
    d.line((x + 22, y + 58, x + w - 22, y + 58), fill=GRID, width=2)
    d.multiline_text((x + 24, y + 76), wrap(body, 48), font=font(size), fill=MUTED, spacing=6)


box(85, 185, 665, 550, "1", "Claude Code classic hooks",
    "GLOBAL ~/.claude/settings.json\n\nEVENTS: UserPromptSubmit / PreToolUse / PostToolUse / PostToolUseFailure / PermissionRequest / Stop / StopFailure / Notification\n\n→ claude-code-integration/k2-pet-claude-code-emit.sh\n\nstdin JSON: hook_event_name, transcript_path, cwd, tool_name, message\nextract_last_result reads the real last assistant message from transcript JSONL\nPOST tagged events to server.mjs /ingest; every event carries real session cwd\n\nAlso shells directly to macOS say for short Done. / Hit a problem. / notification-text cues.", 14)

box(865, 185, 665, 550, "2", "k2-pet-mod / inside Claude Code",
    "Claude Code Mod; global install via CLAUDE_CODE_PLUGIN_DIRS\n\nPolls GET /state every 700ms → live Pane inside Claude Code\nPolls GET /pending-prompt every 700ms\n→ Claude Code own $.prompt.submit() when text is queued\nPOST /prompt-delivered with $.session.cwd() once it wins\n\nNATIVE TURN.COMPLETE\n$.audio.play → bundled audio/done.aiff or audio/problem.aiff\n(direct; no server dependency for this audio path)", 15)

box(1645, 185, 670, 550, "3", "server.mjs / CENTRAL HUB",
    "Node · port 3043 · serves companion.html/js/assets\n\nK2StateMapper: 16 states — idle, working, executing, editing, searching, tool-use, checking, permission, question, finished, interrupted, problem, listening, speaking, reading, attention\n\nMap task registry keyed by real session cwd: label / state / hasResult / resultText (multi-task fix)\nlastResultText global-most-recent cache · pendingPrompt queue · lastDelivery record\n\nspeakText(): speechGeneration cancels stale in-flight requests; activeSpeechProcess + isPaused drive real SIGSTOP/SIGCONT pause/resume\n\nAPI: POST /ingest · GET /events · GET /state · POST /speak-last · POST /speak-pause · POST /speak-resume · POST /speak-task · GET /voices · POST /set-voice · POST /submit-prompt · GET /pending-prompt · POST /prompt-delivered · GET /last-delivery · GET /tasks", 13)

box(85, 850, 665, 550, "4", "companion.html + companion.js / FLOATING UI",
    "Actual rendered companion window UI\n\nPet sprite + floor bar: character picker · hide · write/compose · speaker (idle / pause / resume icon states) · voice picker · tasks picker · shrink/grow\n\nStatus card has live breathing-glow animation while in progress\nCompose box POSTs typed text to /submit-prompt\nVoice picker: GET /voices + POST /set-voice\nTasks picker: GET /tasks + POST /speak-task with chosen cwd\nEventSource against /events drives all live rendering", 15)

box(865, 850, 665, 550, "5", "k2-pet-floating-window.py / NATIVE HOST",
    "Python + pywebview · macOS\n\nNon-activating NSPanel\nframeless · always-on-top\nreal click-through via mouse-position polling\n\nLoads companion.html from server.mjs\n\nPersists its own window size to disk so it survives restarts.", 16)

box(1645, 850, 670, 550, "6", "VOICE BACKENDS / REAL PRIORITY",
    "server.mjs speech engine calls these in order:\n\n1  Kokoro-82M — nimba/kokoro_server.py\n   port 8880 · Apple MLX/GPU · REAL DEFAULT\n   12 voices incl. KK cloned-speed voice am_kk\n\n2  macOS say — instant fallback if Kokoro unreachable\n\n3  XTTS v2 — nimba/xtts_server.py\n   port 8883 · PyTorch/CPU · true voice clone\n   slow (30–50s) · opt-in third option, not default", 15)


def arrow(start, end, label, color=CYAN, dashed=False, label_xy=None, size=13):
    x1, y1 = start; x2, y2 = end
    if dashed:
        # Short dash segments keep the drafting style legible.
        import math
        dist = math.hypot(x2 - x1, y2 - y1)
        for i in range(0, int(dist), 22):
            t1, t2 = i / dist, min((i + 11) / dist, 1)
            d.line((x1 + (x2 - x1) * t1, y1 + (y2 - y1) * t1,
                    x1 + (x2 - x1) * t2, y1 + (y2 - y1) * t2), fill=color, width=3)
    else:
        d.line((x1, y1, x2, y2), fill=color, width=3)
    import math
    angle = math.atan2(y2 - y1, x2 - x1)
    size_a = 18
    p1 = (x2, y2)
    p2 = (x2 - size_a * math.cos(angle - 0.45), y2 - size_a * math.sin(angle - 0.45))
    p3 = (x2 - size_a * math.cos(angle + 0.45), y2 - size_a * math.sin(angle + 0.45))
    d.polygon([p1, p2, p3], fill=color)
    if label_xy is None:
        label_xy = ((x1 + x2) // 2, (y1 + y2) // 2)
    tx, ty = label_xy
    lines = wrap(label, max(24, int(42 - len(label) / 8)))
    bb = d.multiline_textbbox((tx, ty), lines, font=font(size), spacing=3, anchor="mm")
    pad = 5
    d.rounded_rectangle((bb[0] - pad, bb[1] - pad, bb[2] + pad, bb[3] + pad), radius=5, fill=NAVY)
    d.multiline_text((tx, ty), lines, font=font(size), fill=color, spacing=3, anchor="mm", align="center")


def routed_arrow(points, label, color=CYAN, label_xy=None, size=13):
    for a, b in zip(points, points[1:]):
        d.line((a[0], a[1], b[0], b[1]), fill=color, width=3)
    x1, y1 = points[-2]
    x2, y2 = points[-1]
    import math
    angle = math.atan2(y2 - y1, x2 - x1)
    size_a = 18
    p1 = (x2, y2)
    p2 = (x2 - size_a * math.cos(angle - 0.45), y2 - size_a * math.sin(angle - 0.45))
    p3 = (x2 - size_a * math.cos(angle + 0.45), y2 - size_a * math.sin(angle + 0.45))
    d.polygon([p1, p2, p3], fill=color)
    if label_xy is None:
        label_xy = ((points[0][0] + points[-1][0]) // 2, (points[0][1] + points[-1][1]) // 2)
    tx, ty = label_xy
    lines = wrap(label, max(24, int(42 - len(label) / 8)))
    bb = d.multiline_textbbox((tx, ty), lines, font=font(size), spacing=3, anchor="mm")
    d.rounded_rectangle((bb[0] - 5, bb[1] - 5, bb[2] + 5, bb[3] + 5), radius=5, fill=NAVY)
    d.multiline_text((tx, ty), lines, font=font(size), fill=color, spacing=3, anchor="mm", align="center")


# Inter-zone flows, each label names the actual payload or endpoint.
routed_arrow([(750, 300), (790, 155), (1600, 155), (1645, 300)],
             "tagged hook events + real session cwd\nPOST /ingest", label_xy=(1195, 155), size=14)
arrow((1530, 315), (1645, 315), "GET /state\nGET /pending-prompt", label_xy=(1585, 270), size=13)
arrow((1645, 500), (1530, 500), "POST /prompt-delivered\n+ $.session.cwd()", label_xy=(1585, 555), size=13)
arrow((1080, 660), (1370, 660), "native turn.complete → $.audio.play", color=ORANGE, dashed=True, label_xy=(1225, 705), size=12)
arrow((1940, 735), (390, 850), "GET /events (SSE)\nstate + live events", label_xy=(1200, 790), size=13)
arrow((700, 850), (1830, 735), "POST /submit-prompt · GET /voices\nPOST /set-voice · GET /tasks · POST /speak-task\nPOST /speak-last · /speak-pause · /speak-resume", color=YELLOW, label_xy=(1200, 910), size=11)
arrow((2050, 735), (1200, 850), "serves companion.html/js/assets", color=ORANGE, dashed=True, label_xy=(1690, 770), size=12)
arrow((2070, 735), (2070, 850), "speech text / voice selection", label_xy=(2200, 790), size=12)

# Footer/title block.
d.text((85, 1460), "DATA PLANE: local-only process graph · arrows are labeled with real payloads/endpoints · no remote service", font=small_f, fill=MUTED)
d.text((2315, 1460), "SHEET K2-01   REV 2026.10", font=small_f, fill=YELLOW, anchor="ra")
d.rectangle((85, 1505, 2315, 1570), outline=CYAN, width=2)
d.line((1900, 1505, 1900, 1570), fill=CYAN, width=2)
d.text((1930, 1525), "K2 PET / SYSTEM BLUEPRINT", font=small_f, fill=WHITE)
d.text((2285, 1525), "MACOS · NODE · PYTHON · 3043", font=small_f, fill=CYAN, anchor="ra")

im.save(OUT, format="PNG", optimize=True)
print(OUT)
