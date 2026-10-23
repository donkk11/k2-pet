import math
import os
import textwrap
from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(__file__)
OUT_BLUEPRINT = os.path.join(ROOT, "k2-pet-blueprint-v2.png")
OUT_SCHEMATIC = os.path.join(ROOT, "k2-pet-interaction-schematic.png")
W, H = 2600, 1800
BG = "#08131f"
GRID = "#142b3e"
PANEL = "#0d2234"
PANEL2 = "#102b40"
WHITE = "#f5fbff"
MUTED = "#b5cfda"
CYAN = "#79e6ff"
GOLD = "#ffd47e"
ORANGE = "#ffae78"
GREEN = "#75e6a7"
RED = "#ff8e91"


def font(size, bold=False):
    candidates = [
        "/System/Library/Fonts/SFNSMono.ttf",
        "/System/Library/Fonts/Menlo.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    ]
    for path in candidates:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


TITLE = font(46, True)
SUB = font(21)
ZONE = font(25, True)
LABEL = font(18, True)
BODY = font(19)
SMALL = font(16)
TINY = font(14)


class Audit:
    """Tracks drawn text and asserts that independent text blocks do not collide."""
    def __init__(self, draw):
        self.d = draw
        self.texts = []

    def text(self, xy, value, f, fill, anchor="la", name="text", spacing=5, align="left"):
        bb = self.d.multiline_textbbox(xy, value, font=f, anchor=anchor, spacing=spacing, align=align)
        # generous padding is part of the audited bbox, not merely visual decoration
        padded = (bb[0] - 12, bb[1] - 10, bb[2] + 12, bb[3] + 10)
        self.texts.append((name, padded))
        self.d.multiline_text(xy, value, font=f, fill=fill, anchor=anchor, spacing=spacing, align=align)
        return padded

    def assert_no_text_collisions(self):
        failures = []
        for i, (n1, a) in enumerate(self.texts):
            for n2, b in self.texts[i + 1:]:
                if a[0] < b[2] and a[2] > b[0] and a[1] < b[3] and a[3] > b[1]:
                    failures.append((n1, n2, a, b))
        if failures:
            raise AssertionError("text bbox collisions: " + repr(failures[:5]))


def base(title, subtitle, sheet, footer=True):
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)
    for x in range(0, W + 1, 65): d.line((x, 0, x, H), fill=GRID, width=1)
    for y in range(0, H + 1, 65): d.line((0, y, W, y), fill=GRID, width=1)
    a = Audit(d)
    a.text((86, 50), title, TITLE, WHITE, name="title")
    a.text((88, 112), subtitle, SUB, CYAN, name="subtitle")
    a.text((2510, 58), "REV 2026-10-10", LABEL, GOLD, anchor="ra", name="revision")
    d.line((86, 155, 2510, 155), fill=CYAN, width=2)
    if footer:
        a.text((86, 1735), "LOCAL-ONLY K2 PET · REAL SOURCE NAMES · NO INVENTED SESSION TITLES", TINY, MUTED, name="footer")
        a.text((2510, 1735), sheet, TINY, GOLD, anchor="ra", name="sheet")
    return im, d, a


def wrap(s, width):
    return "\n".join(textwrap.wrap(s, width=width, break_long_words=False, break_on_hyphens=False))


def card(d, a, x, y, w, h, kicker, title, body, accent=CYAN, size=BODY):
    d.rounded_rectangle((x, y, x + w, y + h), radius=22, fill=PANEL, outline=accent, width=3)
    a.text((x + 26, y + 24), kicker.upper(), LABEL, GOLD, name=f"{title}-kicker")
    a.text((x + 26, y + 65), title, ZONE, WHITE, name=f"{title}-title")
    d.line((x + 26, y + 112, x + w - 26, y + 112), fill=GRID, width=2)
    a.text((x + 28, y + 140), wrap(body, max(30, int((w - 56) / (size.size * .60)))), size, MUTED,
           name=f"{title}-body", spacing=8)


def arrow(d, a, points, label, color=CYAN, label_xy=None, size=SMALL, dashed=False, name="arrow"):
    for p, q in zip(points, points[1:]):
        if dashed:
            dist = math.hypot(q[0] - p[0], q[1] - p[1])
            for i in range(0, max(1, int(dist)), 24):
                t1, t2 = i / dist, min((i + 12) / dist, 1)
                d.line((p[0] + (q[0] - p[0]) * t1, p[1] + (q[1] - p[1]) * t1,
                        p[0] + (q[0] - p[0]) * t2, p[1] + (q[1] - p[1]) * t2), fill=color, width=3)
        else:
            d.line((*p, *q), fill=color, width=3)
    p, q = points[-2], points[-1]
    ang = math.atan2(q[1] - p[1], q[0] - p[0])
    ah = 20
    d.polygon([(q[0], q[1]), (q[0] - ah * math.cos(ang - .45), q[1] - ah * math.sin(ang - .45)),
               (q[0] - ah * math.cos(ang + .45), q[1] - ah * math.sin(ang + .45))], fill=color)
    if label_xy is None: label_xy = ((points[0][0] + points[-1][0]) // 2, (points[0][1] + points[-1][1]) // 2)
    tx, ty = label_xy
    lines = wrap(label, max(18, int(52 - len(label) / 7)))
    bb = d.multiline_textbbox((tx, ty), lines, font=size, anchor="mm", spacing=5, align="center")
    d.rounded_rectangle((bb[0] - 15, bb[1] - 12, bb[2] + 15, bb[3] + 12), radius=8, fill=BG, outline=GRID, width=1)
    a.text((tx, ty), lines, size, color, anchor="mm", name=f"{name}-label", spacing=5, align="center")


def render_blueprint():
    im, d, a = base("K2 PET — SYSTEM / PROCESS BLUEPRINT V2",
                    "ACTUAL LOCAL MACOS PROCESS GRAPH · NODE :3043 · PYWEBVIEW / NSPANEL · REAL ENDPOINTS + EVENT PAYLOADS",
                    "SHEET K2-01")
    # Three rows leave explicit routing corridors for labels and arrows.
    card(d, a, 85, 220, 740, 520, "01", "Claude Code classic hooks",
         "~/.claude/settings.json invokes claude-code-integration/k2-pet-claude-code-emit.sh.\n\nREAL hook events: UserPromptSubmit · PreToolUse · PostToolUse · PostToolUseFailure · PermissionRequest · Stop · StopFailure · Notification.\n\npost() adds the real hook cwd to every JSON payload and POSTs it to /ingest. result/text reads the last assistant message from transcript JSONL.\n\nNotification posts pet/alert; PermissionRequest posts item/permissions/requestApproval (visual state only).", ORANGE)
    card(d, a, 930, 220, 740, 520, "02", "k2-pet-mod / inside Claude Code",
         "Loaded via CLAUDE_CODE_PLUGIN_DIRS.\n\nEvery 700ms: GET /state → K2 pane snapshot.\nEvery 700ms: GET /pending-prompt → $.prompt.submit({ text, asUser: true }) → $.session.cwd() → POST /prompt-delivered { cwd }.\n\nNative turn.complete plays bundled audio/done.aiff or audio/problem.aiff through $.audio.play — this path does not require the pet server.\n\nPane button: POST /speak-last.", GREEN)
    card(d, a, 1775, 220, 740, 520, "03", "src/server.mjs · CENTRAL HUB :3043",
         "K2StateMapper.ingest() maps real methods to state; SSE clients receive GET /events.\n\nTask registry: Map keyed by full session cwd → label, state, hasResult, resultText, updatedAt. label starts as cwd basename; client disambiguates collisions with the real parent folder.\n\nSpeech: activeSpeechProcess + isPaused; /speak-pause sends SIGSTOP and /speak-resume sends SIGCONT. speechGeneration rejects stale synthesis.\n\nHTTP: POST /ingest · GET /events · GET /state · GET /tasks · POST /speak-task · POST /speak-last · POST /speak-pause · POST /speak-resume · GET /voices · POST /set-voice · POST /submit-prompt · GET /pending-prompt · POST /prompt-delivered · GET /last-delivery.", CYAN, font(18))

    card(d, a, 85, 945, 740, 530, "04", "public/companion.html + companion.js",
         "Glass UI: backdrop-filter blur panels, always-visible glass deck, glowing glass #peek lantern while hidden.\n\nControls: #btn-character → #char-picker; #btn-text → #compose; #btn-speak; #btn-voice-select → #voice-picker; #btn-tasks → #task-picker; #btn-shrink / #btn-grow.\n\nEventSource('/events') renders state, caption, alertMessage, hasResult, isPaused.\n\nTask picker: GET /tasks; click selects cwd only; speaker then POST /speak-task { cwd }. No selection falls back to POST /speak-last.\n\nVoice picker: GET /voices then POST /set-voice. Compose: POST /submit-prompt.", GOLD, font(18))
    card(d, a, 930, 945, 740, 530, "05", "k2-pet-floating-window.py",
         "Python + pywebview native host. On macOS it replaces the host with an NSPanel / NSWindowStyleMaskNonactivatingPanel.\n\nframeless · always-on-top · transparent · easy_drag. Loads companion.html from the local Node server.\n\nEvery 80ms, AppHelper.callLater() compares NSEvent.mouseLocation() with the page-reported hot_rect and toggles setIgnoresMouseEvents_.\n\nNative resize persists ~/.k2-pet-size-<port>.json; default 260×400, clamped 170×180 to 600×900.", ORANGE)
    card(d, a, 1775, 945, 740, 530, "06", "Kokoro TTS :8880 + local audio",
         "server.mjs POSTs text to http://127.0.0.1:8880/speak using the selected Kokoro voice (default bf_emma). Returned WAV bytes are written to a temp file and played by afplay.\n\nOptional XTTS :8883 is selected only with K2_PET_NATURAL_VOICE=xtts; unreachable synthesis falls back to macOS say.\n\nThe same speakText() path is used by /speak-last and /speak-task, so pause/resume controls whichever activeSpeechProcess is actually running.", GREEN)

    # Labels occupy corridors only; each label is audited as a real bbox.
    arrow(d, a, [(825, 330), (875, 330), (875, 360), (930, 360)], "tagged hook payloads + cwd · POST /ingest", label_xy=(400, 790), color=ORANGE, size=TINY, name="hooks-server")
    arrow(d, a, [(1670, 410), (1720, 410), (1720, 410), (1775, 410)], "GET /state · /pending-prompt · /tasks · /voices", label_xy=(1100, 790), size=TINY, name="mod-server")
    arrow(d, a, [(1775, 565), (1720, 565), (1720, 565), (1670, 565)], "POST /prompt-delivered { cwd } · $.prompt.submit", label_xy=(1800, 790), color=GREEN, size=TINY, name="mod-return")
    arrow(d, a, [(825, 1120), (875, 1120), (875, 1120), (930, 1120)], "POST /submit-prompt · /speak-task · /speak-last · pause · resume", label_xy=(650, 880), color=GOLD, size=TINY, name="ui-server")
    arrow(d, a, [(1775, 1205), (1720, 1205), (1720, 1205), (1670, 1205)], "Kokoro POST /speak :8880 · WAV → afplay", label_xy=(1720, 1510), color=GREEN, size=TINY, name="server-tts")
    arrow(d, a, [(2145, 740), (2145, 895), (2145, 945)], "GET /events (SSE)\nstate + caption + alertMessage", label_xy=(2330, 840), size=TINY, name="sse-ui")
    arrow(d, a, [(1250, 740), (1250, 900), (1250, 945)], "native turn.complete · $.audio.play", label_xy=(1250, 880), color=ORANGE, size=TINY, dashed=True, name="native-audio")
    # Legend is isolated at the bottom, away from all title/arrow bboxes.
    d.rounded_rectangle((85, 1535, 2515, 1670), radius=16, fill=PANEL2, outline=CYAN, width=2)
    a.text((115, 1570), "TASK REGISTRY", LABEL, GOLD, name="legend-title")
    a.text((115, 1612), "full cwd key → basename label → client parent-folder disambiguation → selected cwd → /speak-task", SMALL, MUTED, name="legend-body")
    a.text((1500, 1570), "GLASS UI", LABEL, CYAN, name="legend-glass-title")
    a.text((1500, 1612), "backdrop-filter panels · always-visible deck · glowing #peek lantern", SMALL, MUTED, name="legend-glass-body")
    a.assert_no_text_collisions()
    im.save(OUT_BLUEPRINT, optimize=True)


def render_schematic():
    im, d, a = base("K2 PET — UI / INTERACTION SCHEMATIC",
                    "VERIFIED MENU_HANDOFF.md §7 TABLE TRANSLATED TO A REAL CONTROL → PANEL → ACTION → CONNECTION → FEEDBACK GRAPH",
                    "SHEET K2-02", footer=False)
    # Five columns with generous gutters. Every row is exactly one verified table row.
    xs = [85, 540, 995, 1450, 1950]
    ws = [390, 385, 390, 445, 565]
    heads = ["CONTROL", "PANEL", "ACTION", "REAL CONNECTION", "VISIBLE FEEDBACK"]
    for x, w, htxt in zip(xs, ws, heads):
        d.rounded_rectangle((x, 205, x + w, 280), radius=14, fill=PANEL2, outline=CYAN, width=2)
        a.text((x + 20, 242), htxt, LABEL, WHITE, anchor="lm", name=f"head-{htxt}")
    rows = [
        ("Write #btn-text", "Compose #compose", "type + Enter", "POST /submit-prompt → GET /pending-prompt → $.prompt.submit({ text, asUser: true }) → POST /prompt-delivered { cwd }", '"Sent to: <project>" or "Copied —" fallback text'),
        ("Speak #btn-speak", "(none)", "click; if reading, pause/resume", "/speak-last, /speak-pause, /speak-resume; selected task uses POST /speak-task { cwd }", "speaker ↔ pause ↔ resume icon; real activeSpeechProcess SIGSTOP/SIGCONT"),
        ("Choose voice #btn-voice-select", "Voice picker #voice-picker", "click a row", "GET /voices then POST /set-voice { voice }", "checkmark moves; mid-read audio restarts in new voice"),
        ("Running tasks #btn-tasks", "Tasks picker #task-picker", "click row selects; speaker plays", "GET /tasks → selected full cwd → POST /speak-task { cwd }; no selection → /speak-last", "selected checkmark; duplicate basename → real parent folder; speak icon starts read"),
        ("Character #btn-character", "Character picker #char-picker", "click a row", "localStorage key k2-character + location.reload()", "whole page reloads under new character"),
        ("Hide #btn-hide", "—", "click", "body.hidden class; #peek remains", "pet/deck vanish; glowing glass lantern appears"),
        ("Hook events", "Status card #status-card", "no button", "k2-pet-claude-code-emit.sh → POST /ingest → GET /events SSE", "label + caption + breathing glow while in progress"),
        ("Notification hook", "Alert bubble #alert-bubble", "no button", "pet/alert → POST /ingest", "dark amber bubble; self-expires in 9s"),
    ]
    y = 325
    rh = 156
    for i, row in enumerate(rows):
        fill = PANEL if i % 2 == 0 else PANEL2
        for x, w in zip(xs, ws): d.rounded_rectangle((x, y, x + w, y + rh), radius=14, fill=fill, outline=GRID, width=2)
        colors = [GOLD, CYAN, WHITE, GREEN, MUTED]
        names = ["control", "panel", "action", "connection", "feedback"]
        for (txt, x, w, col, name) in zip(row, xs, ws, colors, names):
            wrapped = wrap(txt, max(20, int((w - 36) / 10.8)))
            a.text((x + 18, y + 22), wrapped, BODY if name != "connection" else SMALL, col,
                   name=f"row{i}-{name}", spacing=7)
        y += rh + 18

    # Separate callout for shrink/grow, explicitly covered by the handoff inventory.
    d.rounded_rectangle((85, 1710, 2515, 1780), radius=14, fill=PANEL2, outline=CYAN, width=2)
    a.text((110, 1745), "SHRINK / GROW  #btn-shrink / #btn-grow", LABEL, GOLD, anchor="lm", name="resize-control")
    a.text((780, 1745), "native window.resize() via pywebview → persisted size; no CSS zoom / transform scaling", SMALL, MUTED, anchor="lm", name="resize-action")
    a.text((2210, 1745), "170×180 … 600×900", SMALL, CYAN, anchor="lm", name="resize-range")
    a.assert_no_text_collisions()
    im.save(OUT_SCHEMATIC, optimize=True)


if __name__ == "__main__":
    render_blueprint()
    render_schematic()
    print(OUT_BLUEPRINT)
    print(OUT_SCHEMATIC)
