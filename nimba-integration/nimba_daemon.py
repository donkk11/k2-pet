#!/usr/bin/env python3.11
"""
NIMBA — System-Wide Hotkey Daemon
───────────────────────────────────────────────────────────────────────────────
Runs in the background on your Mac. Works in ANY app — VS Code, Chrome,
Notion, Pages, Terminal, anywhere.

THREE MODES (all triggered without leaving your current app):

  ⌥Space  (hold Alt + Space)
  ─────────────────────────────────────────────────────
  DICTATION MODE
  Hold the keys → speak → release → Whisper transcribes →
  text types itself into whatever app your cursor is in.
  No AI, no latency. Pure speech-to-text, everywhere.

  Double-tap Fn  (tap Fn twice within 0.4s)
  ─────────────────────────────────────────────────────
  SMART MODE — auto-detects context:

  • Text is highlighted anywhere →  READ-ALOUD MODE
    Copies highlighted text → Kokoro reads it in natural voice.
    Works in Chrome, PDF, VS Code, Word, anywhere.

  • Nothing highlighted → AI MODE
    Hold mic open → speak → Ollama thinks →
    Kokoro speaks the answer aloud.

REQUIREMENTS (run INSTALL_DAEMON.command first):
  pip3.11 install pynput sounddevice numpy scipy pyperclip

PERMISSIONS (one-time, macOS will prompt):
  System Settings → Privacy & Security → Accessibility → add Terminal (or your IDE)
  System Settings → Privacy & Security → Microphone → add Terminal

START:
  python3.11 nimba_daemon.py
  (START_NIMBA.command does this automatically)
───────────────────────────────────────────────────────────────────────────────
"""

import sys
import os
import time
import json
import threading
import subprocess
import tempfile
import traceback
import urllib.request
import urllib.error

# ── CONFIG ────────────────────────────────────────────────────────────────────
NIMBA_URL        = 'http://127.0.0.1:7788'
KOKORO_URL       = 'http://127.0.0.1:8880'
WHISPER_WS_URL   = 'ws://127.0.0.1:8765'

# Same speech-to-text engine + model as the Nkama Coach live mic (whisper.cpp,
# Metal GPU, small.en). Replaces the old openai-whisper "base" subprocess as the
# primary path -- see transcribe() below. Swap the model file here to upgrade
# (ggml-medium.en.bin is already downloaded next to it).
WHISPER_CPP_MODEL = os.path.expanduser('~/.cache/hyperframes/whisper/models/ggml-small.en.bin')
WHISPER_CPP_CLI   = '/opt/homebrew/bin/whisper-cli'
# Neutral priming sentence: measured on real clips to give proper punctuation/
# capitals (matters when dictating into apps) and fewer wrong-word guesses.
# Known side effect (reproduced on pure noise): whisper can echo it back, so
# _transcribe_whispercpp() strips any echo of this exact text from the result.
WHISPER_CPP_PROMPT = 'This is a sentence, with proper punctuation.'

RECORD_SECONDS   = 30        # hard max for push-to-talk (safety cap)
SAMPLE_RATE      = 16000      # Hz — Whisper target rate
RECORD_RATE      = 44100      # Hz — MacBook Air native rate (CoreAudio rejects 16kHz)
CHANNELS         = 1
FN_DOUBLE_TAP_MS = 400        # max ms between two Fn taps to count as double
KOKORO_VOICE     = 'am_echo'
KOKORO_SPEED     = 1.1  # default read speed (Nkama 2026-08-18)
# Shared by overlay /voice POST and active read prefetch (same object — mid-read updates work)
_READ_VOICE_BOX  = {'id': 'am_echo'}

def set_kokoro_voice(voice: str) -> str:
    """Single writer for overlay / Reader voice selection (avoid __main__ drift)."""
    global KOKORO_VOICE
    v = (voice or '').strip() or 'am_echo'
    # Strip accidental kokoro: prefix from some UIs
    if v.startswith('kokoro:'):
        v = v[len('kokoro:'):]
    KOKORO_VOICE = v
    _READ_VOICE_BOX['id'] = v
    return KOKORO_VOICE


def resolve_read_voice() -> str:
    """Voice for a new read / synth call. Prefer live Nimba selection, then overlay pin."""
    global KOKORO_VOICE
    server_v = ''
    try:
        server_v = (get_active_voice() or '').strip()
    except Exception:
        server_v = ''
    if server_v.startswith('kokoro:'):
        server_v = server_v[len('kokoro:'):]
    # Prefer server selection when present (fixes dropdown Sarah not sticking)
    if server_v:
        return set_kokoro_voice(server_v)
    return set_kokoro_voice(KOKORO_VOICE or 'am_echo')

# Natural Voice Pipeline — breath gaps for ⌥⌘C / ⌥⌘Ç read-aloud
# Shared rules with nkama_voice_studio_v2/NATURAL_VOICE_PIPELINE.md
# Real silence between units (not fake breath samples).
# Values are at 1.0× speed; runtime scales gap ≈ base/speed so faster speech
# does not leave "dead air" that feels twice as long.
#
# FLOW SET (2026-08-02) — “perfect” for long-form read-aloud, not max pause:
#   0.6s after *every* chunk makes a book feel sticky / hesitant (adds ~0.45s
#   × hundreds of segments → minutes of dead air). Humans leave ~120–280ms
#   between sentences when narrating; paragraphs get a clearer breath.
#   Tuned for Kokoro + XTTS chunk joins (no robot zero-gap, no lecture drag).
NATURAL_GAP_S_PHRASE = 0.18   # normal sentence → next (~180 ms) — continuous flow
NATURAL_GAP_S_LONG   = 0.26   # long line ending .!? (~260 ms) — slight weight
NATURAL_GAP_S_PARA   = 0.40   # paragraph break (~400 ms) — real breath, still moving
# Overlay speed buttons (must match HTML + changeSpeed map)
OVERLAY_SPEEDS = (0.8, 0.9, 1.0, 1.1, 1.2, 1.3, 1.5)

# ── IMPORTS (with helpful errors) ────────────────────────────────────────────
def _require(pkg, install_name=None):
    try:
        return __import__(pkg)
    except ImportError:
        name = install_name or pkg
        print(f'[Nimba Daemon] ✗ Missing: {pkg}')
        print(f'[Nimba Daemon]   Fix: pip3.11 install {name}')
        print(f'[Nimba Daemon]   Or run: INSTALL_DAEMON.command')
        sys.exit(1)

pynput      = _require('pynput')
sounddevice = _require('sounddevice')
np          = _require('numpy')
pyperclip   = _require('pyperclip')

from pynput import keyboard
from pynput.keyboard import Key, Controller as KbController

kbctl = KbController()

# ── STATE ─────────────────────────────────────────────────────────────────────
_fn_last_tap     = 0.0          # timestamp of last Fn tap
_fn_lock         = threading.Lock()
_recording       = False        # prevent overlapping recordings
_speaking        = False        # Kokoro is currently speaking
_record_lock     = threading.Lock()
_alt_held        = False        # track ⌥ (Option/Alt) state
_space_held      = False        # track Space state
_dictation_start = 0.0          # when ⌥Space hold began

# ── READ-ALOUD STATE ──────────────────────────────────────────────────────────
_is_reading      = False        # True while read-aloud is active
_is_paused       = False        # True when paused mid-reading
_pause_event     = threading.Event()  # set = play, clear = pause
_reading_lock    = threading.Lock()
_afplay_proc     = None         # current afplay subprocess (killable)
_overlay_proc    = None         # Chrome overlay window process
_read_sentences  = []           # sentences currently being read
_read_index      = 0            # current sentence index
_seek_index      = -1           # -1 = no seek requested, >=0 = jump to this index
_overlay_port    = 8881         # tiny HTTP server for overlay comms
_overlay_error   = None         # set when TTS fails — shown as banner in overlay

# Initialise pause event to "playing" state
_pause_event.set()

# ── CLIPBOARD HELPERS ─────────────────────────────────────────────────────────
def get_clipboard() -> str:
    """Return current clipboard content."""
    try:
        return pyperclip.paste() or ''
    except Exception:
        return ''

def set_clipboard(text: str):
    try:
        pyperclip.copy(text)
    except Exception as e:
        print(f'[Nimba Daemon] clipboard write failed: {e}')

def copy_selection() -> str:
    """
    Copy currently highlighted text to clipboard and return it.
    Simulates Cmd+C then reads clipboard.
    """
    prev = get_clipboard()
    # Temporarily clear so we can detect if anything was copied
    set_clipboard('\x00')
    time.sleep(0.05)

    with kbctl.pressed(Key.cmd):
        kbctl.tap('c')
    time.sleep(0.12)  # give app time to update clipboard

    result = get_clipboard()
    if result == '\x00':
        # Nothing was selected — restore previous clipboard
        set_clipboard(prev)
        return ''
    return result.strip()

def type_text(text: str):
    """
    Inject text into the currently focused app via clipboard paste.
    More reliable than key-by-key typing for unicode and speed.
    """
    prev = get_clipboard()
    set_clipboard(text)
    time.sleep(0.05)
    with kbctl.pressed(Key.cmd):
        kbctl.tap('v')
    time.sleep(0.1)
    set_clipboard(prev)  # restore clipboard

# ── AUDIO RECORDING ───────────────────────────────────────────────────────────

# Push-to-talk stop signal — set when key is released → process the audio
_ptt_stop = threading.Event()
# Push-to-talk cancel signal — set to discard audio and free the mic immediately
# Triggered by: Escape key, second ⌥⌘Fn press, or 60s auto-timeout
_ptt_cancel = threading.Event()

def record_push_to_talk(max_seconds=RECORD_SECONDS) -> bytes:
    """
    Record from microphone until _ptt_stop (key released → process)
    or _ptt_cancel (Escape / second press → discard) or max_seconds timeout.
    Returns WAV bytes on success, or b'' if cancelled / nothing recorded.
    """
    import scipy.io.wavfile as wav
    import io

    frames     = []
    chunk_size = int(RECORD_RATE * 0.05)  # 50ms chunks at native 44100 Hz

    def callback(indata, frame_count, time_info, status):
        frames.append(indata.copy())

    _ptt_stop.clear()
    _ptt_cancel.clear()
    max_chunks = int(max_seconds * RECORD_RATE / chunk_size)

    # Auto-detect best input device — avoids PaErrorCode -9986 on macOS
    try:
        dev_info = sounddevice.query_devices(kind='input')
        input_device = dev_info.get('index', None)
    except Exception:
        input_device = None

    with sounddevice.InputStream(
        samplerate=RECORD_RATE,   # record at 44100 Hz (MacBook Air native)
        channels=CHANNELS,
        dtype='float32',
        blocksize=chunk_size,
        device=input_device,
        callback=callback,
    ):
        for _ in range(max_chunks):
            time.sleep(0.05)
            if _ptt_cancel.is_set():
                return b''   # cancelled — discard audio, free mic
            if _ptt_stop.is_set():
                break        # key released — process audio

    if not frames:
        return b''

    audio = np.concatenate(frames, axis=0)

    # Resample from 44100 Hz → 16000 Hz for Whisper
    from scipy.signal import resample_poly
    audio_resampled = resample_poly(audio, up=160, down=441)  # 16000/44100 = 160/441
    audio_int16 = (np.clip(audio_resampled, -1.0, 1.0) * 32767).astype(np.int16)

    buf = io.BytesIO()
    wav.write(buf, SAMPLE_RATE, audio_int16)   # write at 16000 Hz for Whisper
    return buf.getvalue()


def record_until_silence(max_seconds=10, silence_thresh=0.01, silence_dur=1.5) -> bytes:
    """
    Record from microphone until silence or max_seconds.
    Used for Fn double-tap AI mode (no key to hold).
    Returns WAV bytes (16kHz mono).
    """
    import scipy.io.wavfile as wav
    import io

    frames        = []
    silence_count = 0
    chunk_size    = int(RECORD_RATE * 0.05)  # 50ms chunks at native 44100 Hz
    silence_limit = int(silence_dur / 0.05)  # number of 50ms chunks of silence

    def callback(indata, frame_count, time_info, status):
        nonlocal silence_count
        frames.append(indata.copy())
        rms = float(np.sqrt(np.mean(indata ** 2)))
        if rms < silence_thresh:
            silence_count += 1
        else:
            silence_count = 0

    max_chunks = int(max_seconds * RECORD_RATE / chunk_size)

    # Auto-detect best input device — avoids PaErrorCode -9986 on macOS
    try:
        dev_info = sounddevice.query_devices(kind='input')
        input_device = dev_info.get('index', None)
    except Exception:
        input_device = None

    with sounddevice.InputStream(
        samplerate=RECORD_RATE,   # record at 44100 Hz (MacBook Air native)
        channels=CHANNELS,
        dtype='float32',
        blocksize=chunk_size,
        device=input_device,
        callback=callback,
    ):
        for _ in range(max_chunks):
            time.sleep(0.05)
            if silence_count >= silence_limit and len(frames) > 10:
                break

    if not frames:
        return b''

    audio = np.concatenate(frames, axis=0)

    # Resample from 44100 Hz → 16000 Hz for Whisper
    from scipy.signal import resample_poly
    audio_resampled = resample_poly(audio, up=160, down=441)  # 16000/44100 = 160/441
    audio_int16 = (np.clip(audio_resampled, -1.0, 1.0) * 32767).astype(np.int16)

    buf = io.BytesIO()
    wav.write(buf, SAMPLE_RATE, audio_int16)   # write at 16000 Hz for Whisper
    return buf.getvalue()

# ── WHISPER TRANSCRIPTION ─────────────────────────────────────────────────────
def _transcribe_whispercpp(wav_bytes: bytes):
    """
    Same engine as the Nkama Coach live mic: whisper.cpp + small.en on Metal.
    Input is the 16 kHz mono int16 WAV the record_* functions already produce.

    Returns the cleaned text ('' if it heard nothing), or None if the engine
    itself is unavailable/failed -- so the caller can tell "silence" (stop here)
    from "broken" (try the slower fallbacks).
    """
    import re as _re
    if not (os.path.exists(WHISPER_CPP_CLI) and os.path.exists(WHISPER_CPP_MODEL)):
        print('[Nimba Daemon] whisper.cpp not available — falling back', flush=True)
        return None
    tmp = None
    try:
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as f:
            f.write(wav_bytes)
            tmp = f.name
        out = subprocess.run(
            [WHISPER_CPP_CLI, '-m', WHISPER_CPP_MODEL, '-f', tmp, '-nt', '-np',
             '--prompt', WHISPER_CPP_PROMPT],
            capture_output=True, text=True, timeout=30,
        )
        if out.returncode != 0:
            print(f'[Nimba Daemon] whisper.cpp exit {out.returncode}: {out.stderr[-200:]}', flush=True)
            return None
        # whisper-cli prints diagnostics around the transcript; keep only transcript lines
        diag = ('main:', 'whisper_', 'ggml_', 'load_backend', 'system_info')
        lines = [l.strip() for l in out.stdout.splitlines() if l.strip()]
        raw = ' '.join(l for l in lines if not l.lower().startswith(diag))
        raw = raw.replace(WHISPER_CPP_PROMPT, '')   # drop prompt echo (hallucination on noise)
        # Same clean-up the old path used: noise tokens, trailing dot on a pause
        raw = _re.sub(r'\[.*?\]|\(.*?\)', '', raw)
        raw = _re.sub(r'[\.…]+$', '', raw.strip())
        return _re.sub(r'\s{2,}', ' ', raw).strip()
    except Exception as e:
        print(f'[Nimba Daemon] whisper.cpp failed: {e}', flush=True)
        return None
    finally:
        if tmp:
            try:
                os.unlink(tmp)
            except OSError:
                pass


def transcribe(wav_bytes: bytes) -> str:
    """
    Primary: whisper.cpp small.en (same as the Nkama Coach). If that engine is
    unavailable, fall back to the old whisper_server WebSocket, then to the
    openai-whisper "base" subprocess.
    """
    if not wav_bytes:
        return ''

    cpp = _transcribe_whispercpp(wav_bytes)
    if cpp is not None:
        return cpp

    # Try whisper_server WebSocket first
    try:
        import websocket  # websocket-client
        ws = websocket.create_connection(WHISPER_WS_URL, timeout=5)
        ws.send_binary(wav_bytes)
        result = json.loads(ws.recv())
        ws.close()
        text = result.get('text', '').strip()
        if text:
            return text
    except Exception:
        pass  # fall through to local whisper

    # Fallback: local whisper subprocess (uses "small" model, same as whisper_server)
    try:
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as f:
            f.write(wav_bytes)
            tmp = f.name
        result = subprocess.run(
            ['python3.11', '-m', 'whisper', tmp,
             '--model', 'base', '--language', 'en',  # 2026-06: base = faster PTT
             '--condition_on_previous_text', 'False',
             '--temperature', '0',
             '--output_format', 'txt', '--output_dir', os.path.dirname(tmp)],
            capture_output=True, timeout=45
        )
        txt_path = tmp.replace('.wav', '.txt')
        if os.path.exists(txt_path):
            raw  = open(txt_path).read().strip()
            # Same clean-up as whisper_server: strip trailing dot, noise tokens
            import re as _re
            raw  = _re.sub(r'\[.*?\]|\(.*?\)', '', raw)
            text = _re.sub(r'[\.…]+$', '', raw).strip()
            os.unlink(txt_path)
        else:
            text = ''
        os.unlink(tmp)
        return text
    except Exception as e:
        print(f'[Nimba Daemon] whisper fallback failed: {e}')
        return ''

# ── KOKORO TTS ────────────────────────────────────────────────────────────────
_SPANISH_VOICE_PREFIXES = ('e',)  # ef_dora, em_alex, em_santa — same convention as kokoro_server.py

def _is_spanish_voice(voice: str) -> bool:
    v = (voice or '').strip()
    if v.startswith('kokoro:'):
        v = v[len('kokoro:'):]
    return v[:1] in _SPANISH_VOICE_PREFIXES


_SPANISH_STOPWORDS = {
    'que', 'el', 'la', 'los', 'las', 'de', 'del', 'y', 'es', 'en', 'un', 'una',
    'unos', 'unas', 'para', 'con', 'no', 'se', 'su', 'sus', 'por', 'mas', 'más',
    'como', 'pero', 'le', 'les', 'ya', 'este', 'esta', 'estos', 'estas', 'entre',
    'cuando', 'muy', 'sin', 'sobre', 'tambien', 'también', 'hasta', 'hay', 'donde',
    'mientras', 'quien', 'desde', 'yo', 'tu', 'tú', 'el', 'ella', 'nosotros',
    'porque', 'si', 'sí', 'al', 'lo', 'ser', 'esta', 'todo', 'todos', 'nos',
}


def _looks_spanish(text: str) -> bool:
    """Cheap, no-dependency Spanish detector for the read-aloud auto-voice-switch.

    Real bug found 2026-08-31: selecting genuine Spanish text and hitting the
    read-aloud hotkey still read it with whatever voice happened to be last
    active on the server (commonly the English default, am_echo) -- nothing
    in that path ever looked at the selected text's language. This gives the
    hotkey path a real signal to auto-switch on, instead of requiring the
    user to open the reader UI and change the voice picker first.

    Two independent signals so short accent-free Spanish ("el sol es bueno")
    isn't missed, and short English text with one stray accented loanword
    ("café latte") isn't falsely flagged:
      1. Spanish-exclusive punctuation/letters (¿ ¡ ñ) -- near-zero false positive rate.
      2. Density of common Spanish stopwords as whole words.
    """
    import re
    if not text:
        return False
    sample = text[:1000]
    if re.search(r'[¿¡ñÑ]', sample):
        return True
    words = re.findall(r"[a-záéíóúüñ]+", sample.lower())
    if len(words) < 4:
        return False
    hits = sum(1 for w in words if w in _SPANISH_STOPWORDS)
    return hits / len(words) >= 0.25


def clean_for_tts(text: str, voice: str = '') -> str:
    """
    Prepare text for Kokoro TTS — convert symbols to spoken words, strip
    anything G2P can't handle. Goal: zero skipped words.
    """
    import re

    # Remove URLs entirely (they're unreadable)
    text = re.sub(r'https?://\S+', '', text)
    text = re.sub(r'www\.\S+', '', text)

    # Unwrap markdown bold/italic/code — keep the inner text
    text = re.sub(r'\*{1,3}(.*?)\*{1,3}', r'\1', text)
    text = re.sub(r'`{1,3}(.*?)`{1,3}', r'\1', text)
    text = re.sub(r'_{1,2}(.*?)_{1,2}', r'\1', text)

    # Remove markdown headers — keep text
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)

    # Convert symbols to spoken words BEFORE stripping non-ASCII
    replacements = [
        ('→', ' to '),       ('←', ' back '),      ('↑', ' up '),
        ('↓', ' down '),     ('≈', ' approximately '), ('≠', ' not equal to '),
        ('≤', ' less than or equal to '), ('≥', ' greater than or equal to '),
        ('×', ' times '),    ('÷', ' divided by '), ('√', ' root of '),
        ('∞', ' infinity '), ('∑', ' sum of '),     ('∆', ' change in '),
        ('π', ' pi '),       ('°', ' degrees '),    ('±', ' plus or minus '),
        ('⌥', ' Option '),   ('⌘', ' Command '),    ('⌃', ' Control '),
        ('⇧', ' Shift '),    ('↵', ' Enter '),      ('⌫', ' Delete '),
        ('&', ' and '),      ('%', ' percent '),    ('@', ' at '),
        ('#', ' number '),   ('$', ' dollars '),    ('€', ' euros '),
        ('£', ' pounds '),   ('₦', ' naira '),      ('¥', ' yen '),
        ('+', ' plus '),
        ('•', ' '),          ('·', ' '),             ('◦', ' '),
        ('–', ', '),         ('—', ', '),            ('―', ', '),
        ('…', '... '),
        ('|', ' '),          ('\\', ' '),            ('/', ' '),
        ('"', '"'),          ('"', '"'),
        (''', "'"),          (''', "'"),
        ('«', '"'),          ('»', '"'),
    ]
    for sym, word in replacements:
        text = text.replace(sym, word)

    # Expand common abbreviations that Kokoro mispronounces or skips
    abbrevs = [
        (r'\be\.g\.', 'for example'),
        (r'\bi\.e\.', 'that is'),
        (r'\betc\.', 'et cetera'),
        (r'\bvs\.', 'versus'),
        (r'\bDr\.', 'Doctor'),
        (r'\bMr\.', 'Mister'),
        (r'\bMrs\.', 'Missus'),
        (r'\bMs\.', 'Miss'),
        (r'\bProf\.', 'Professor'),
        (r'\bSt\.', 'Saint'),
        (r'\bAve\.', 'Avenue'),
        (r'\bBlvd\.', 'Boulevard'),
        (r'\bno\.', 'number'),
        (r'\bNov\.', 'November'),
        (r'\bDec\.', 'December'),
        (r'\bJan\.', 'January'),
        (r'\bFeb\.', 'February'),
        (r'\bAug\.', 'August'),
        (r'\bSept\.', 'September'),
        (r'\bOct\.', 'October'),
    ]
    for pattern, replacement in abbrevs:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)

    # Strip any remaining non-ASCII (Kokoro G2P silently skips these) --
    # EXCEPT for a Spanish voice, where accented letters/ñ/¿/¡ are not junk
    # to discard, they're the actual language. Blanket-stripping them here
    # was a real bug: it turned "¿Cómo estás?" into " C mo est s ", which is
    # why Spanish voices sounded like broken English rather than Spanish
    # (found 2026-08-30, root-caused by testing this exact regex against the
    # Spanish voice ids already registered in voices.json: ef_dora, em_alex,
    # em_santa).
    if _is_spanish_voice(voice):
        text = re.sub(r'[^\x00-\x7Fáéíóúüñ'
                       r'ÁÉÍÓÚÜÑ¿¡]+', ' ', text)
    else:
        text = re.sub(r'[^\x00-\x7F]+', ' ', text)

    # ── Phonetic substitutions — proper nouns Kokoro mispronounces or skips ──
    # Applied AFTER non-ASCII strip so we're working with plain ASCII only.
    # Format: (exact_word_regex, phonetic_spelling)
    phonetics = [
        # Product names
        (r'\bNimba\b',      'Nimbah'),
        (r'\bNIMBA\b',      'Nimbah'),
        (r'\bKokoro\b',     'Koh-koh-roh'),
        (r'\bOllama\b',     'Oh-lah-mah'),
        (r'\bGemma\b',      'Jemmah'),
        (r'\bWhisper\b',    'Wissper'),
        (r'\bLoRA\b',       'Loh-rah'),
        (r'\bGGUF\b',       'gee-guf'),
        (r'\bMLX\b',        'em-el-ex'),
        (r'\bLLM\b',        'L-L-M'),
        (r'\bLLMs\b',       'L-L-Ems'),
        (r'\bAPI\b',        'A-P-I'),
        # African names
        (r'\bDangote\b',    'Dan-goh-tay'),
        (r'\bNairobi\b',    'Nai-roh-bee'),
        (r'\bCasablanca\b', 'Cah-sah-blahn-kah'),
        (r'\bNGX\b',        'N-G-X'),
        (r'\bJSE\b',        'J-S-E'),
        (r'\bNSE\b',        'N-S-E'),
        (r'\bCBN\b',        'C-B-N'),
        (r'\bNGN\b',        'Nigerian Naira'),
        (r'\bKES\b',        'Kenyan Shilling'),
        (r'\bZAR\b',        'South African Rand'),
        (r'\bEGP\b',        'Egyptian Pound'),
        (r'\bMAD\b',        'Moroccan Dirham'),
        # Person name
        (r'\bKK\b',         'Kay Kay'),
    ]
    for pattern, phonetic in phonetics:
        text = re.sub(pattern, phonetic, text)

    # Preserve natural pauses: ; : and dashes become commas so Kokoro breathes
    # there instead of them being stripped (Reader v3, 2026-07-14)
    text = re.sub(r'\s*[;:]\s*', ', ', text)
    text = re.sub(r'\s*[—–]\s*|\s+-\s+', ', ', text)

    # Clean up punctuation clutter
    text = re.sub(r'[^\w\s.,!?\'"()\-]', ' ', text)  # keep only readable chars
    text = re.sub(r'\.{3,}', '... ', text)             # normalise ellipsis
    text = re.sub(r'\s+', ' ', text).strip()           # collapse whitespace

    return text


def pet_tts(event: str):
    """Tell the K2 pet when Nimba starts/stops speaking ('started' | 'ended').
    Fire-and-forget on its own thread: a missing pet must never delay or break audio."""
    def _post():
        try:
            urllib.request.urlopen(urllib.request.Request(
                'http://127.0.0.1:3043/ingest',
                data=json.dumps({'method': f'nimba/tts.{event}'}).encode(),
                headers={'Content-Type': 'application/json'}), timeout=0.5)
        except Exception:
            pass
    threading.Thread(target=_post, daemon=True).start()


def stop_reading():
    """Kill afplay and clear reading state. Toggle stops here."""
    global _afplay_proc, _is_reading, _speaking, _is_paused
    _is_reading = False
    _is_paused  = False
    _speaking   = False
    _pause_event.set()  # unblock any waiting pause so thread can exit
    proc = _afplay_proc
    if proc and proc.poll() is None:
        try: proc.kill()
        except Exception: pass
    _afplay_proc = None
    overlay_update(-1, '')
    pet_tts('ended')


def pause_reading():
    """Pause: kill current afplay, remember position, block the read loop."""
    global _afplay_proc, _is_paused, _speaking
    if not _is_reading or _is_paused:
        return
    _is_paused = True
    _speaking  = False
    _pause_event.clear()  # read loop will block here after current sentence
    proc = _afplay_proc
    if proc and proc.poll() is None:
        try: proc.kill()
        except Exception: pass
    _afplay_proc = None
    print('[Nimba Daemon] ⏸ Paused', flush=True)
    pet_tts('ended')


def resume_reading():
    """Resume: unblock the read loop so it continues from next sentence."""
    global _is_paused
    if not _is_paused:
        return
    _is_paused = False
    _pause_event.set()  # unblocks the waiting read loop
    print('[Nimba Daemon] ▶ Resumed', flush=True)
    pet_tts('started')


def seek_reading(index: int):
    """
    Jump to a specific sentence index.
    Kills current afplay, sets _seek_index so the read loop jumps there.
    """
    global _afplay_proc, _seek_index, _is_paused
    if not _is_reading:
        return
    if index < 0 or index >= len(_read_sentences):
        return

    # Resume if paused
    if _is_paused:
        _is_paused = False
        _pause_event.set()

    _seek_index = index
    proc = _afplay_proc
    if proc and proc.poll() is None:
        try: proc.kill()
        except Exception: pass
    _afplay_proc = None
    print(f'[Nimba Daemon] ⏩ Seek to sentence {index}', flush=True)


def overlay_update(index: int, sentence: str):
    """Tell the overlay which sentence is being read (non-blocking)."""
    try:
        payload = json.dumps({'index': index, 'sentence': sentence,
                              'total': len(_read_sentences)}).encode()
        req = urllib.request.Request(
            f'http://127.0.0.1:{_overlay_port}/update',
            data=payload,
            headers={'Content-Type': 'application/json'},
            method='POST',
        )
        urllib.request.urlopen(req, timeout=1)
    except Exception:
        pass  # overlay may not be open yet — silently ignore


def overlay_audio_start(index: int, wav: bytes, sentence: str):
    """Publish this sentence's real audio length + start time so the overlay
    can run word-level karaoke highlighting. Falls back to a length estimate
    when the WAV can't be parsed (the overlay then still tracks words)."""
    dur = 0.0
    try:
        import io as _io, wave as _wave
        with _wave.open(_io.BytesIO(wav), 'rb') as _w:
            dur = _w.getnframes() / float(_w.getframerate())
    except Exception:
        sp = max(0.5, min(2.0, float(KOKORO_SPEED) or 1.0))
        dur = max(0.5, len(sentence) / (15.0 * sp))
    try:
        payload = json.dumps({'index': index, 'total': len(_read_sentences),
                              'audio_dur': round(dur, 3),
                              'audio_t0': time.time()}).encode()
        req = urllib.request.Request(
            f'http://127.0.0.1:{_overlay_port}/update',
            data=payload,
            headers={'Content-Type': 'application/json'},
            method='POST',
        )
        urllib.request.urlopen(req, timeout=1)
    except Exception:
        pass


def get_active_voice() -> str:
    """
    Fetch the currently selected voice from the Nimba server.
    The browser pushes its voice selection to /api/voice whenever the user changes it.
    Falls back to local KOKORO_VOICE if server is unreachable.
    """
    try:
        req = urllib.request.Request(f'{NIMBA_URL}/api/voice', method='GET')
        with urllib.request.urlopen(req, timeout=1) as resp:
            data = json.loads(resp.read())
            return data.get('voice', KOKORO_VOICE)
    except Exception:
        return KOKORO_VOICE


def _fetch_tts_wav(text: str, voice: str, speed: float, tries: int = 3) -> bytes | None:
    """Fetch WAV for one sentence. ALWAYS uses the locked `voice` — never swap mid-read.

    Retries the SAME voice on transient failures (model still loading / busy).
    Does NOT fall back to Echo/Michael/browser — that was the audible voice switch.
    """
    voice = (voice or KOKORO_VOICE or 'am_echo').strip()
    cleaned = clean_for_tts(text, voice)
    if not cleaned:
        return None
    speed = float(speed if speed is not None else KOKORO_SPEED) or 1.1
    last_err = None

    for attempt in range(1, max(1, tries) + 1):
        try:
            payload = json.dumps({
                'text': cleaned,
                'voice': voice,
                'speed': speed,
            }).encode()

            # Prefer Nimba router (XTTS + Kokoro). Same voice id every attempt.
            try:
                req = urllib.request.Request(
                    f'{NIMBA_URL}/api/speak',
                    data=payload,
                    headers={'Content-Type': 'application/json'},
                    method='POST',
                )
                with urllib.request.urlopen(req, timeout=90) as resp:
                    data = resp.read()
                    if data and len(data) > 100:
                        return data
                    last_err = 'empty/short response from /api/speak'
            except Exception as e:
                last_err = e
                err_l = str(e).lower()
                # If Nimba is down and voice is a plain Kokoro id, hit Kokoro direct
                # with THE SAME voice — never substitute am_echo for am_michael.
                if any(x in err_l for x in ('connection refused', 'urlopen error', 'errno 61')):
                    if voice.startswith('xtts:') or voice == 'kk':
                        # Need Nimba for cloned / kk-kokoro path
                        raise
                    print(
                        f'[Nimba Daemon] ↩ Nimba down — Kokoro direct voice={voice} '
                        f'(attempt {attempt}/{tries})',
                        flush=True,
                    )
                    req2 = urllib.request.Request(
                        f'{KOKORO_URL}/speak',
                        data=payload,
                        headers={'Content-Type': 'application/json'},
                        method='POST',
                    )
                    with urllib.request.urlopen(req2, timeout=60) as resp2:
                        data = resp2.read()
                        if data and len(data) > 100:
                            return data
                        last_err = 'empty/short response from Kokoro direct'
                else:
                    raise

        except Exception as e:
            last_err = e
            print(
                f'[Nimba Daemon] TTS retry {attempt}/{tries} voice={voice}: {e}',
                flush=True,
            )
            time.sleep(0.35 * attempt)  # model-still-loading / lock contention

    print(
        f'[Nimba Daemon] ✗ TTS gave up voice={voice} after {tries} tries: {last_err}',
        flush=True,
    )
    return None


def speak_kokoro(text: str, sentence_index: int = -1, locked_voice: str | None = None):
    """
    Send text to TTS → play WAV via killable afplay.
    `locked_voice` freezes the session voice so we never switch mid-read.
    No macOS say / browser TTS fallback (that was the voice jump).
    """
    global _speaking, _afplay_proc
    if not text:
        return

    voice = locked_voice or KOKORO_VOICE or get_active_voice()
    text = clean_for_tts(text, voice)
    if not text:
        return

    if not _is_reading and sentence_index >= 0:
        return  # reading was cancelled before this sentence started

    _speaking = True
    if sentence_index < 0:
        pet_tts('started')  # a spoken answer; read-aloud sentences report once per session instead
    tmp = None
    try:
        wav_bytes = _fetch_tts_wav(text, voice, KOKORO_SPEED, tries=3)
        if not wav_bytes:
            raise RuntimeError(f'No audio for voice={voice} (kept same voice; no switch)')

        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as f:
            f.write(wav_bytes)
            tmp = f.name

        # Store process handle so stop_reading() can kill it mid-play
        _afplay_proc = subprocess.Popen(['afplay', tmp])
        _afplay_proc.wait()
        _afplay_proc = None

    except Exception as e:
        global _overlay_error
        err_str = str(e)
        print(f'[Nimba Daemon] ✗ TTS failed: {e}', flush=True)
        _overlay_error = f'⚠ Audio error ({voice}): {err_str[:100]}'
        _afplay_proc = None
    finally:
        _speaking = False
        if sentence_index < 0:
            pet_tts('ended')
        if tmp and os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except Exception:
                pass


def speak_async(text: str):
    """Speak without blocking the hotkey listener."""
    threading.Thread(target=speak_kokoro, args=(text,), daemon=True).start()


def natural_gap_s(sentence: str, speed: float | None = None) -> float:
    """Seconds of silence after a spoken unit (human breath, not robot join).

    At 1.0×: phrase ~0.15s, long ~0.22s. Scaled by 1/speed so 1.5× speech
    still feels tight; 0.8× still has room to breathe.
    """
    if not sentence or sentence == '\x00PARA\x00':
        return 0.0
    s = sentence.strip()
    base = NATURAL_GAP_S_LONG if (s.endswith(('.', '!', '?')) and len(s) > 80) else NATURAL_GAP_S_PHRASE
    sp = float(speed if speed is not None else KOKORO_SPEED) or 1.0
    sp = max(0.5, min(2.0, sp))
    return max(0.06, base / sp)


def split_sentences(text: str) -> list:
    """
    Split text into speakable sentence chunks.
    Avoids splitting on abbreviation dots (Dr., e.g., vs., etc.)
    Returns a list of non-empty strings.
    """
    import re

    # First clean the text so abbreviations are already expanded
    text = clean_for_tts(text)

    # Split on paragraph breaks first
    paragraphs = re.split(r'\n\s*\n', text)

    result = []
    # Pattern: split after . ! ? only when followed by space+capital letter
    # This avoids splitting "Dr. Smith", "e.g. this", "3.5 GHz", etc.
    sent_split = re.compile(r'(?<=[.!?])\s+(?=[A-Z"\'(])')

    for para_idx, para in enumerate(paragraphs):
        para = para.strip()
        if not para:
            continue
        # Insert paragraph-break marker between paragraphs (not before the first)
        if para_idx > 0 and result:
            result.append('\x00PARA\x00')  # sentinel: pause longer here
        parts = sent_split.split(para)
        for p in parts:
            p = p.strip()
            if len(p) > 2:  # skip single-char fragments
                result.append(p)

    if not result:
        result = [text] if text.strip() else []

    # Hard-split any chunk longer than 280 chars.
    # Prefer breaking at natural punctuation; if none found, break at word boundary.
    # 280 chars ≈ 2 seconds of Kokoro audio — fast and gap-free.
    SOFT_MAX = 240  # break here at punctuation if possible
    HARD_MAX = 280  # always break here regardless

    final = []
    for chunk in result:
        if len(chunk) <= HARD_MAX:
            final.append(chunk)
            continue
        words = chunk.split()
        current = []
        length  = 0
        for w in words:
            current.append(w)
            length += len(w) + 1
            at_punct = bool(w) and w[-1] in '.,!?;:'
            if (at_punct and length >= SOFT_MAX) or length >= HARD_MAX:
                final.append(' '.join(current).strip())
                current = []
                length  = 0
        if current:
            final.append(' '.join(current).strip())

    return [c for c in final if c]

# ── READER v3: structure-aware parsing (2026-07-14) ──────────────────────────
# The screen shows a faithful "photocopy" of what was copied (verbatim, with
# headings/lists/quotes/code rendered as a real document) while the SPOKEN text
# is the cleaned/phonetic version. Display and speech are separate tracks.

def _split_display_sentences(text: str) -> list:
    """Sentence-split RAW text (no TTS cleaning) — same boundaries as before:
    after .!? followed by space+capital/quote, hard-break past 280 chars."""
    import re
    sent_split = re.compile(r'(?<=[.!?])\s+(?=[A-Z"\'(])')
    SOFT_MAX, HARD_MAX = 240, 280
    out = []
    for p in sent_split.split(text.strip()):
        p = p.strip()
        if not p:
            continue
        if len(p) <= HARD_MAX:
            out.append(p)
            continue
        words, cur, ln = p.split(), [], 0
        for w in words:
            cur.append(w); ln += len(w) + 1
            if (w and w[-1] in '.,!?;:' and ln >= SOFT_MAX) or ln >= HARD_MAX:
                out.append(' '.join(cur).strip()); cur, ln = [], 0
        if cur:
            out.append(' '.join(cur).strip())
    return [s for s in out if s]


def parse_blocks(text: str) -> list:
    """Detect the structure of pasted text (markdown-ish) → list of blocks:
    {'t': 'h1'|'h2'|'h3'|'li'|'oli'|'quote'|'code'|'p', 'text': str}"""
    import re
    lines = text.replace('\r\n', '\n').split('\n')
    blocks, para, in_code, code_buf = [], [], False, []

    def flush_para():
        if para:
            blocks.append({'t': 'p', 'text': ' '.join(para).strip()})
            para.clear()

    for line in lines:
        stripped = line.strip()
        if stripped.startswith('```'):
            if in_code:
                blocks.append({'t': 'code', 'text': '\n'.join(code_buf)})
                code_buf, in_code = [], False
            else:
                flush_para(); in_code = True
            continue
        if in_code:
            code_buf.append(line)
            continue
        if not stripped:
            flush_para()
            continue
        m = re.match(r'^(#{1,6})\s+(.*)', stripped)
        if m:
            flush_para()
            lvl = min(len(m.group(1)), 3)
            blocks.append({'t': f'h{lvl}', 'text': m.group(2).strip()})
            continue
        m = re.match(r'^[-*•]\s+(.*)', stripped)
        if m:
            flush_para()
            blocks.append({'t': 'li', 'text': m.group(1).strip()})
            continue
        m = re.match(r'^(\d+[.)])\s+(.*)', stripped)
        if m:
            flush_para()
            blocks.append({'t': 'oli', 'text': stripped})
            continue
        if stripped.startswith('>'):
            flush_para()
            blocks.append({'t': 'quote', 'text': stripped.lstrip('> ').strip()})
            continue
        para.append(stripped)
    if in_code and code_buf:
        blocks.append({'t': 'code', 'text': '\n'.join(code_buf)})
    flush_para()
    return blocks


def build_reading(text: str):
    """→ (overlay_blocks, display_list, speak_list). The three stay index-aligned:
    speak_list drives TTS (with \\x00PARA\\x00 pauses between blocks), overlay
    blocks carry [global_index, verbatim_display] pairs for the document view."""
    blocks_in = parse_blocks(text)
    overlay_blocks, display, speak = [], [], []
    for b in blocks_in:
        if not b['text'].strip():
            continue
        if display:                          # pause between blocks
            display.append('\x00PARA\x00')
            speak.append('\x00PARA\x00')
        if b['t'] == 'code':
            idx = len(display)
            n = b['text'].count('\n') + 1
            display.append(b['text'])
            speak.append(f'Code block, {n} line{"s" if n != 1 else ""}.')
            overlay_blocks.append({'t': 'code', 'segs': [[idx, b['text']]]})
            continue
        segs = []
        for s in _split_display_sentences(b['text']):
            idx = len(display)
            display.append(s)
            speak.append(s)                  # cleaned later by clean_for_tts in prefetch
            segs.append([idx, s])
        if segs:
            overlay_blocks.append({'t': b['t'], 'segs': segs})
    return overlay_blocks, display, speak


# ── NIMBA AI QUERY ────────────────────────────────────────────────────────────
def ask_nimba(message: str) -> str:
    """POST to Nimba's /api/browse and return the reply text."""
    try:
        payload = json.dumps({'message': message, 'history': []}).encode()
        req = urllib.request.Request(
            f'{NIMBA_URL}/api/browse',
            data=payload,
            headers={'Content-Type': 'application/json'},
            method='POST',
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read())
        return data.get('reply', '').strip()
    except Exception as e:
        return f'I could not reach Nimba right now. {e}'

# ── NOTIFICATION (macOS) ──────────────────────────────────────────────────────
def notify(title: str, message: str):
    """Show a macOS notification bubble."""
    try:
        script = f'display notification "{message}" with title "{title}"'
        subprocess.run(['osascript', '-e', script], check=False,
                       capture_output=True)
    except Exception:
        pass

# ── MODE IMPLEMENTATIONS ──────────────────────────────────────────────────────

def run_dictation_mode():
    """
    ⌥Space — Push-to-talk: hold = mic open, release = transcribe → type.
    """
    global _recording
    with _record_lock:
        if _recording:
            return
        _recording = True

    try:
        notify('Nimba 🎙', 'Hold ⌥Space and speak… release to transcribe')
        print('[Nimba Daemon] 🎙 Dictation — mic open (release ⌥ to stop)')

        # record_push_to_talk waits until _ptt_stop is set (⌥ released)
        wav = record_push_to_talk()
        if not wav:
            notify('Nimba', 'Nothing heard')
            return

        notify('Nimba ⏳', 'Transcribing…')
        print('[Nimba Daemon] ⏳ Transcribing...')
        text = transcribe(wav)
        if not text:
            notify('Nimba', 'Could not transcribe')
            return

        print(f'[Nimba Daemon] ✏️  Typing: {text[:60]}')
        notify('Nimba ✏️', text[:60])
        type_text(text)

    except Exception as e:
        print(f'[Nimba Daemon] dictation error: {e}')
        traceback.print_exc()
    finally:
        _recording = False


def open_reader_overlay(sentences: list, blocks: list = None):
    """
    Open the floating reader overlay in Chrome app mode.
    Sends the display sentences plus the structured blocks (Reader v3)
    so the overlay renders a real document, not a flat list.
    """
    global _overlay_proc
    # Close any existing overlay
    if _overlay_proc and _overlay_proc.poll() is None:
        try:
            _overlay_proc.terminate()
        except Exception:
            pass

    # Build URL with sentence data via the overlay server
    try:
        payload = json.dumps({'sentences': sentences, 'blocks': blocks or [],
                              'voice': KOKORO_VOICE}).encode()
        req = urllib.request.Request(
            f'http://127.0.0.1:{_overlay_port}/load',
            data=payload,
            headers={'Content-Type': 'application/json'},
            method='POST',
        )
        urllib.request.urlopen(req, timeout=2)
    except Exception:
        pass  # overlay server handles this

    overlay_url = f'http://127.0.0.1:{_overlay_port}/'

    # ── Open a proper app-mode popup window ───────────────────────────────────
    # We call the browser BINARY directly rather than using `open -a`.
    # When Chrome is already running, `open -a --args` talks to it via Apple
    # Events and silently drops the --app flag, opening a plain background tab.
    # Calling the binary directly makes Chrome's existing process create a real
    # app-mode window that comes to the front.
    browser_bins = [
        '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
        '/Applications/Brave Browser.app/Contents/MacOS/Brave Browser',
        '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge',
    ]
    for binary in browser_bins:
        if os.path.exists(binary):
            try:
                _overlay_proc = subprocess.Popen([
                    binary,
                    f'--app={overlay_url}',
                    '--window-size=900,680',
                    '--window-position=60,60',
                    '--no-first-run',
                    '--disable-extensions',
                    '--disable-background-mode',
                ])
            except Exception as e:
                print(f'[Nimba Daemon] Overlay open error: {e}')
            break


def run_read_aloud_mode():
    """
    ⌥⌘C — Read highlighted text aloud using Kokoro, sentence by sentence.

    TOGGLE behavior:
      • If not reading → copy selection, open overlay, start reading
      • If already reading → stop immediately (kill afplay)
    """
    global _is_reading, _read_sentences, _read_index, _recording, _seek_index, _is_paused, _afplay_proc, _speaking, _overlay_error
    _overlay_error = None   # clear any previous error banner

    # ── TOGGLE: stop if already reading ───────────────────────────────────────
    with _reading_lock:
        if _is_reading:
            print('[Nimba Daemon] 📖 Read-aloud: STOPPED by user')
            notify('Nimba', 'Reading stopped')
            stop_reading()
            return

    # ── NOT reading → start ───────────────────────────────────────────────────
    with _record_lock:
        if _recording:
            return
        _recording = True

    try:
        selected = copy_selection()
        if not selected or len(selected) < 2:
            notify('Nimba', 'No text selected — highlight text first')
            print('[Nimba Daemon] 📖 Read-aloud: no text selected')
            return

        # Reader v3: display (verbatim document) and speech (cleaned) are
        # separate, index-aligned tracks — the overlay shows a photocopy of
        # what was copied, never the TTS-phonetic text.
        overlay_blocks, display_list, sentences = build_reading(selected)
        if not sentences:
            return

        _read_sentences = sentences
        _read_index     = 0

        with _reading_lock:
            _is_reading = True
        pet_tts('started')

        print(f'[Nimba Daemon] 📖 Reading {len(sentences)} sentence(s): {selected[:60]}…')
        notify('Nimba 📖', f'Reading {len(sentences)} sentence{"s" if len(sentences)>1 else ""}…')

        # Open the floating overlay (background — keeps source app focused)
        open_reader_overlay(display_list, overlay_blocks)

        # ── Voice for this read (stability + picker must both work) ─────────
        # Use module _READ_VOICE_BOX so overlay /voice POST updates the same
        # object mid-read (old bug: closed-over 'am_echo' ignored Sarah).
        # "No mid-read swap" = never silent-fallback to a different id on error.
        resolve_read_voice()
        voice_box = _READ_VOICE_BOX

        # Auto-switch to a Spanish voice when the selection is Spanish and the
        # resolved voice isn't already Spanish or a cloned voice (never override
        # a deliberately-picked xtts: clone). See _looks_spanish() for why.
        current_id = voice_box['id'] or ''
        if _looks_spanish(selected) and not _is_spanish_voice(current_id) and not current_id.startswith('xtts:'):
            set_kokoro_voice('ef_dora')
            print(f'[Nimba Daemon] 🇪🇸 Selection detected as Spanish → voice → ef_dora', flush=True)

        print(f'[Nimba Daemon] 🔒 Session voice: {voice_box["id"]}', flush=True)

        def prefetch_audio(text):
            """Fetch WAV for one sentence — current voice_box (picker-aware)."""
            if not text or not _is_reading or text == '\x00PARA\x00':
                return None
            return _fetch_tts_wav(text, voice_box['id'], KOKORO_SPEED, tries=3)

        # Prefetch with bounded workers — Kokoro holds a global lock; stampeding
        # every sentence at once caused timeouts → failed segments → audible jumps.
        prefetch_cache   = {}  # idx → wav bytes (or None on failure)
        prefetch_events  = {}  # idx → Event, .set() when synthesis is done
        prefetch_started = set()
        _prefetch_sem = threading.Semaphore(2)  # max 2 in-flight synths

        def _do_prefetch(text, idx):
            with _prefetch_sem:
                if not _is_reading:
                    prefetch_cache[idx] = None
                else:
                    prefetch_cache[idx] = prefetch_audio(text)
            prefetch_events[idx].set()

        def _start_prefetch(idx):
            """Kick off synthesis for idx exactly once."""
            if idx in prefetch_started or idx >= len(sentences):
                return
            prefetch_started.add(idx)
            prefetch_events[idx] = threading.Event()
            threading.Thread(
                target=lambda t=sentences[idx], i=idx: _do_prefetch(t, i),
                daemon=True,
            ).start()

        def _wait_for(idx):
            """Block until synthesis for idx is done; return wav bytes or None."""
            _start_prefetch(idx)
            # Look-ahead: keep next 2 warming
            _start_prefetch(idx + 1)
            _start_prefetch(idx + 2)
            prefetch_events[idx].wait(timeout=120)
            return prefetch_cache.get(idx)

        def _reset_prefetch():
            """Called on seek — drop stale results (threads still run, harmless)."""
            prefetch_cache.clear()
            prefetch_events.clear()
            prefetch_started.clear()

        def _breath_after(spoken: str, idx: int):
            """Insert natural silence after a unit. PARA owns paragraph pauses —
            do not stack phrase gap + para gap. Gap scales with KOKORO_SPEED."""
            if not _is_reading or _is_paused:
                return
            nxt = sentences[idx + 1] if idx + 1 < len(sentences) else None
            if nxt is None:
                return
            if nxt == '\x00PARA\x00':
                return  # PARA step sleeps NATURAL_GAP_S_PARA
            if spoken == '\x00PARA\x00':
                return  # already slept at PARA step
            gap = natural_gap_s(spoken, KOKORO_SPEED)
            if gap > 0:
                time.sleep(gap)

        # Warm first few only (bounded queue fills the rest as we read)
        for _pi, _ps in enumerate(sentences[:3]):
            if _ps != '\x00PARA\x00':
                _start_prefetch(_pi)

        print(
            f'[Nimba Daemon] 📖 Natural gaps: phrase={NATURAL_GAP_S_PHRASE}s '
            f'long={NATURAL_GAP_S_LONG}s para={NATURAL_GAP_S_PARA}s · voice={voice_box["id"]}',
            flush=True,
        )

        # ── Read sentence by sentence — supports pause, resume, seek ─────────
        i = 0
        while i < len(sentences):
            if not _is_reading:
                break

            # ── Handle seek ───────────────────────────────────────────────
            if _seek_index >= 0:
                i = _seek_index
                _seek_index = -1
                _reset_prefetch()
                _start_prefetch(i)          # pre-warm the jumped-to sentence

            sentence = sentences[i]

            # ── Wait if paused ────────────────────────────────────────────
            if _is_paused:
                print(f'[Nimba Daemon] ⏸ Paused at sentence {i+1}', flush=True)
                _pause_event.wait()
                if not _is_reading:
                    break
                if _seek_index >= 0:
                    i = _seek_index
                    _seek_index = -1
                    _reset_prefetch()
                    _start_prefetch(i)
                    sentence = sentences[i]

            _read_index = i
            overlay_update(i, sentence)
            print(f'[Nimba Daemon]   [{i+1}/{len(sentences)}] {sentence[:70]}')

            # ── Wait for this sentence's WAV (already synthesising in parallel)
            wav = _wait_for(i)

            # ── Paragraph break sentinel — natural para breath, no audio ──
            if sentence == '\x00PARA\x00':
                if _is_reading and not _is_paused:
                    sp = max(0.5, min(2.0, float(KOKORO_SPEED) or 1.0))
                    time.sleep(max(0.10, NATURAL_GAP_S_PARA / sp))
                i += 1
                continue

            # ── Play (picker voice; never silent-fallback to another id) ───
            if wav and _is_reading and not _is_paused:
                _speaking = True
                tmp = None
                try:
                    import tempfile as _tf
                    with _tf.NamedTemporaryFile(suffix='.wav', delete=False) as f:
                        f.write(wav)
                        tmp = f.name
                    overlay_audio_start(i, wav, sentence)
                    _afplay_proc = subprocess.Popen(['afplay', tmp])
                    _afplay_proc.wait()
                    _afplay_proc = None
                    # Natural breath between sentences (not after last / before PARA)
                    _breath_after(sentence, i)
                except Exception:
                    speak_kokoro(sentence, sentence_index=i, locked_voice=voice_box['id'])
                finally:
                    _speaking = False
                    if tmp and os.path.exists(tmp):
                        try: os.unlink(tmp)
                        except: pass
            elif _is_reading and not _is_paused:
                # synthesis failed — retry SAME picker voice (never swap to Echo)
                speak_kokoro(sentence, sentence_index=i, locked_voice=voice_box['id'])
                _breath_after(sentence, i)

            # ── After playing: check for seek before advancing ────────────
            if _seek_index >= 0:
                i = _seek_index
                _seek_index = -1
                _reset_prefetch()
                _start_prefetch(i)
            elif _is_reading and not _is_paused:
                i += 1

        # Done
        if _is_reading:
            overlay_update(-1, '')  # signal overlay: finished
            notify('Nimba', 'Done reading')

        with _reading_lock:
            _is_reading = False
        pet_tts('ended')

    except Exception as e:
        print(f'[Nimba Daemon] read-aloud error: {e}')
        traceback.print_exc()
        with _reading_lock:
            _is_reading = False
        pet_tts('ended')
    finally:
        _recording = False


def run_ai_mode():
    """
    Fn Fn — Speak a question, Nimba answers aloud via Kokoro.
    """
    global _recording
    with _record_lock:
        if _recording:
            return
        _recording = True

    try:
        notify('Nimba 🤖', 'Listening… ask me anything')
        print('[Nimba Daemon] 🤖 AI mode — listening')

        wav = record_until_silence()
        if not wav:
            notify('Nimba', 'Nothing heard')
            return

        notify('Nimba ⏳', 'Thinking…')
        question = transcribe(wav)
        if not question:
            notify('Nimba', 'Could not hear question')
            return

        print(f'[Nimba Daemon] ❓ Question: {question}')
        notify('Nimba 💭', question[:60])

        reply = ask_nimba(question)
        print(f'[Nimba Daemon] 💬 Reply: {reply[:80]}')
        notify('Nimba 💬', reply[:80])
        speak_async(reply)

    except Exception as e:
        print(f'[Nimba Daemon] AI mode error: {e}')
        traceback.print_exc()
    finally:
        _recording = False


PTT_MAX_SECONDS  = 60   # auto-cancel after 60s — never leaves mic stuck open
PTT_WARN_SECONDS = 50   # warn user at 50s so they know timeout is coming


def run_ai_mode_ptt():
    """
    ⌥⌘Fn — WhisperFlow-style push-to-talk AI mode.

    HOLD   ⌥⌘Fn  = mic opens instantly.
    RELEASE Fn    = mic closes, transcribes, Nimba replies.
    ESCAPE        = cancel immediately — mic freed, nothing sent.
    ⌥⌘Fn again   = cancel if already recording.
    60s timeout   = auto-cancel so mic is never left stuck open.
    """
    global _recording
    with _record_lock:
        if _recording:
            # Already recording — treat second ⌥⌘Fn press as cancel
            print('[Nimba Daemon] 🎙 PTT: second press → CANCELLED', flush=True)
            _ptt_cancel.set()
            return
        _recording = True

    # ── 60-second watchdog — auto-cancels to free mic ─────────────────────────
    def _watchdog():
        for i in range(PTT_MAX_SECONDS * 10):   # check every 100ms
            time.sleep(0.1)
            if not _recording or _ptt_stop.is_set() or _ptt_cancel.is_set():
                return
            elapsed = (i + 1) / 10
            if elapsed >= PTT_WARN_SECONDS and int(elapsed * 10) % 50 == 0:
                notify('Nimba ⚠', f'Mic auto-closing in {PTT_MAX_SECONDS - int(elapsed)}s — press Escape to cancel now')
        # Timeout reached — force cancel
        if _recording:
            print('[Nimba Daemon] 🎙 PTT: 60s timeout — auto-cancelling, freeing mic', flush=True)
            notify('Nimba', 'Mic timeout — cancelled. Press ⌥⌘Fn to try again.')
            _ptt_cancel.set()

    threading.Thread(target=_watchdog, daemon=True).start()

    try:
        notify('Nimba 🎙', 'Mic open — release Fn to send  |  Escape to cancel')
        print('[Nimba Daemon] 🎙 PTT: mic open (Escape or ⌥⌘Fn again to cancel)…', flush=True)

        wav_bytes = record_push_to_talk(max_seconds=PTT_MAX_SECONDS)

        # Cancelled (Escape, second press, or timeout) → free mic silently
        if _ptt_cancel.is_set():
            print('[Nimba Daemon] 🎙 PTT: cancelled — mic released', flush=True)
            notify('Nimba', 'Mic cancelled — nothing sent')
            return

        if not wav_bytes:
            notify('Nimba', 'Nothing captured')
            return

        notify('Nimba ⏳', 'Thinking…')
        question = transcribe(wav_bytes)
        if not question or len(question.strip()) < 2:
            notify('Nimba', 'Could not make out what you said — try again')
            return

        print(f'[Nimba Daemon] ❓ "{question}"', flush=True)
        notify('Nimba 💭', question[:80])

        reply = ask_nimba(question)
        if not reply:
            notify('Nimba', 'No reply from AI')
            return

        print(f'[Nimba Daemon] 💬 "{reply[:80]}"', flush=True)
        notify('Nimba 💬', reply[:80])
        speak_async(reply)

    except Exception as e:
        print(f'[Nimba Daemon] PTT error: {e}', flush=True)
        _ptt_cancel.set()   # ensure mic is freed on any exception
        traceback.print_exc()
    finally:
        _recording = False


def run_smart_fn_mode():
    """Fn Fn — now routes directly to AI mode."""
    run_ai_mode()


# ── SCREEN + REGION READ MODES ────────────────────────────────────────────────

NIMBA_DIR  = os.path.dirname(os.path.abspath(__file__))
OCR_SCRIPT = os.path.join(NIMBA_DIR, 'codex_ocr.swift')


def _ocr_image(img_path: str) -> str:
    """Run Apple Vision OCR on an image file. Returns extracted text."""
    result = subprocess.run(
        ['swift', OCR_SCRIPT, img_path],
        capture_output=True, text=True, timeout=20
    )
    return result.stdout.strip()



def run_screen_read_mode():
    """
    ⌥⌘0 — Full screen OCR → speak aloud.
    Press again while reading to STOP immediately.
    """
    global _is_reading

    # ── TOGGLE: already reading → STOP ───────────────────────────────────────
    if _is_reading or _speaking:
        print('[Nimba Daemon] 👁 Screen-read: STOPPED by user', flush=True)
        notify('Nimba', 'Reading stopped')
        stop_reading()
        return

    print('[Nimba Daemon] 👁 Screen-read triggered (⌥⌘0)', flush=True)
    notify('Nimba 👁', 'Reading your screen…')

    try:
        payload = json.dumps({'question': ''}).encode()
        req = urllib.request.Request(
            f'{NIMBA_URL}/api/read-screen',
            data=payload,
            headers={'Content-Type': 'application/json'},
            method='POST',
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())

        reply = data.get('reply') or data.get('text') or ''
        if not reply or len(reply.strip()) < 5:
            notify('Nimba', 'No readable text found on screen')
            return

        print(f'[Nimba Daemon] 👁 Screen-read: {len(reply)} chars', flush=True)
        notify('Nimba 👁', reply[:60] + ('…' if len(reply) > 60 else ''))
        speak_async(reply)

    except Exception as e:
        print(f'[Nimba Daemon] 👁 Screen-read error: {e}', flush=True)
        notify('Nimba', f'Screen read failed: {e}')


def speak_async(text: str):
    """Speak text without blocking the hotkey listener."""
    threading.Thread(target=speak_kokoro, args=(text,), daemon=True).start()


def run_region_read_mode():
    """
    ⌥⌘9 — Drag to select any area of the screen (including video frames).
    OCR runs on that area → text copied to clipboard AND spoken aloud.
    Press ⌥⌘0 while speaking to stop the reading.
    """
    tmp_img = f'/tmp/nimba_region_{int(time.time())}.png'
    print('[Nimba Daemon] 👁 Region-select triggered (⌥⌘9)', flush=True)
    notify('Nimba 👁', 'Drag to select — release to read…')

    try:
        # -i interactive, -s rectangular drag only (no window picker)
        result = subprocess.run(
            ['screencapture', '-i', '-s', tmp_img],
            capture_output=True, timeout=60
        )

        # User hit Escape — file won't exist
        if result.returncode != 0 or not os.path.exists(tmp_img):
            print('[Nimba Daemon] 👁 Region-select cancelled', flush=True)
            return

        text = _ocr_image(tmp_img)

        if not text or len(text.strip()) < 2:
            notify('Nimba', 'No text found in that area — try a bigger selection')
            return

        # 1. Copy to clipboard so they can paste anywhere
        subprocess.run(['pbcopy'], input=text.encode(), check=True)

        # 2. Speak it aloud (press ⌥⌘0 to stop mid-read)
        char_count = len(text.strip())
        notify('Nimba 👁', f'Reading {char_count} chars — ⌥⌘0 to stop')
        print(f'[Nimba Daemon] 👁 Region: {char_count} chars — copied + speaking', flush=True)
        speak_async(text.strip())

    except subprocess.TimeoutExpired:
        notify('Nimba', 'Timed out — try again')
    except Exception as e:
        print(f'[Nimba Daemon] 👁 Region OCR error: {e}', flush=True)
        notify('Nimba', f'Region read failed: {e}')
    finally:
        try:
            os.unlink(tmp_img)
        except Exception:
            pass


# ── HOTKEY LISTENER ───────────────────────────────────────────────────────────

# Track modifier key state
_alt_pressed         = False
_cmd_pressed         = False
_space_pressed       = False
_alt_space_triggered = False  # guard — only trigger once per hold

# ── ⌥⌘ timing window ─────────────────────────────────────────────────────────
# When a number key is pressed BEFORE Cmd is registered (happens on many
# keyboards), we store the vk and timestamp. When Cmd then fires within
# 500 ms, we still trigger the correct action.
_last_alt_vk      = None   # vk of last key pressed while alt was held
_last_alt_vk_time = 0.0    # time.time() when that key was pressed

def on_press(key):
    global _alt_pressed, _cmd_pressed, _space_pressed, _alt_space_triggered
    global _fn_last_tap, _last_alt_vk, _last_alt_vk_time, _recording

    # ── ESCAPE = cancel PTT mic immediately ───────────────────────────────────
    # If mic is open (PTT recording in progress), Escape frees it instantly.
    # Does nothing if PTT is not active.
    if key == Key.esc and _recording:
        print('[Nimba Daemon] 🎙 Escape pressed — mic CANCELLED', flush=True)
        _ptt_cancel.set()
        _ptt_stop.set()
        notify('Nimba', 'Mic cancelled — nothing sent')
        return

    # ── DEBUG: log key when alt is held so we can see what Space looks like ──
    if _alt_pressed:
        char = getattr(key, 'char', None)
        vk   = getattr(key, 'vk', None)
        print(f'[Nimba Daemon] key with alt held: {key!r}  char={char!r}  vk={vk!r}', flush=True)

    # ── Track ⌥ (Option/Alt) ─────────────────────────────────────────────────
    if key in (Key.alt, Key.alt_l, Key.alt_r):
        _alt_pressed = True
        return  # modifier only

    # ── Track ⌘ (Command) ────────────────────────────────────────────────────
    if key in (Key.cmd, Key.cmd_l, Key.cmd_r):
        _cmd_pressed = True
        # ── Timing-window check: did the user press 0 or 9 BEFORE Cmd? ───────
        # (common on Spanish/European keyboards where the number key fires first)
        if _alt_pressed:
            _now = time.time()
            if _now - _last_alt_vk_time < 0.5:   # 500 ms window
                if _last_alt_vk == 29:            # 0 key → full screen read
                    threading.Thread(target=run_screen_read_mode, daemon=True).start()
                elif _last_alt_vk == 25:          # 9 key → region select
                    threading.Thread(target=run_region_read_mode, daemon=True).start()
        return  # modifier only

    _char = getattr(key, 'char', None)
    _vk   = getattr(key, 'vk',   None)

    # Record every key pressed while Alt is held so the timing window works
    if _alt_pressed and _vk is not None:
        _last_alt_vk      = _vk
        _last_alt_vk_time = time.time()

    # ── ⌥⌘C → Read-aloud ─────────────────────────────────────────────────────
    # macOS sends '©' (U+00A9) for ⌥⌘C on most keyboards. The produced char
    # changes with the active layout (ES/US/ABC), so ALSO match the physical
    # keys by key code like ⌥⌘0/⌥⌘9 do: vk 8 = C, vk 42 = the Ç key on ISO.
    if (_char in ('©', '£', '}', 'c') or _vk in (8, 42)) and _alt_pressed and _cmd_pressed:
        threading.Thread(target=run_read_aloud_mode, daemon=True).start()
        return

    # ── ⌥⌘0 → Screen read (full screen) — press again to STOP ───────────────
    # Use vk=29 (the physical 0 key) — works regardless of keyboard layout.
    # Also match common chars ('≠','º','ø') as belt-and-suspenders.
    if _alt_pressed and _cmd_pressed and (_vk == 29 or _char in ('≠', 'º', 'ø')):
        threading.Thread(target=run_screen_read_mode, daemon=True).start()
        return

    # ── ⌥⌘9 → Region-select OCR → copy + speak ───────────────────────────────
    # Use vk=25 (the physical 9 key).
    # Also match common chars ('"','ª','·') as fallback.
    if _alt_pressed and _cmd_pressed and (_vk == 25 or _char in ('"', 'ª', '·')):
        threading.Thread(target=run_region_read_mode, daemon=True).start()
        return

    # ── ⌥Space → Dictation (push-to-talk) ────────────────────────────────────
    # On macOS, Option+Space produces a non-breaking space (\xa0 / U+00A0)
    # rather than Key.space. We check both for compatibility.
    _is_space = (
        key == Key.space or
        (_char is not None and _char in (' ', ' ', ' '))
    )
    if _is_space and _alt_pressed and not _cmd_pressed and not _alt_space_triggered:
        _alt_space_triggered = True
        _space_pressed = True
        print('[Nimba Daemon] \U0001f3d9 ⌥Space detected — starting dictation', flush=True)
        threading.Thread(target=run_dictation_mode, daemon=True).start()

def on_release(key):
    global _alt_pressed, _cmd_pressed, _space_pressed, _alt_space_triggered

    if key in (Key.alt, Key.alt_l, Key.alt_r):
        _alt_pressed = False
        _alt_space_triggered = False
        # Signal push-to-talk stop — mic closes, transcription begins
        _ptt_stop.set()

    elif key in (Key.cmd, Key.cmd_l, Key.cmd_r):
        _cmd_pressed = False

    elif key == Key.space or (hasattr(key, 'char') and key.char in ('\xa0', ' ', ' ', ' ')):
        _space_pressed = False


def start_overlay_server():
    """
    Start a tiny HTTP server on port 8881 that:
      GET  /          → serve the overlay HTML
      POST /load      → store sentences for the overlay to display
      POST /update    → push current index to the overlay (polled by JS)
      GET  /state     → overlay polls this to get current reading state
    """
    from http.server import HTTPServer, BaseHTTPRequestHandler
    import urllib.parse

    overlay_state = {
        'sentences': [],
        'blocks': [],
        'index': -1,
        'total': 0,
        'voice': KOKORO_VOICE,
        'paused': False,
        'audio_dur': 0.0,   # real length (s) of the sentence now playing
        'audio_t0': 0.0,    # wall-clock epoch (s) when that audio started
    }

    OVERLAY_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Nimba Reader</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  /* ── Nkama / first-principles UI — dark, dense signal, no theater ── */
  :root {
    --bg: #07090c;
    --panel: #0e1218;
    --panel-2: #121820;
    --line: #1c2430;
    --text: #e8eef5;
    --dim: #7a8899;
    --mute: #4a5563;
    --accent: #3dffa8;
    --accent-dim: rgba(61,255,168,0.14);
    --accent-glow: rgba(61,255,168,0.28);
    --danger: #ff5c5c;
    --warn: #ffb020;
    --font: "SF Pro Text", -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
    --mono: "SF Mono", ui-monospace, Menlo, Consolas, monospace;
  }
  * { margin:0; padding:0; box-sizing:border-box; }
  body {
    background: var(--bg); color: var(--text);
    font-family: var(--font);
    font-size: 14px; height: 100vh;
    display: flex; flex-direction: column;
    user-select: text; overflow: hidden;
    background-image:
      radial-gradient(ellipse 80% 50% at 50% -20%, rgba(61,255,168,0.06), transparent 55%),
      linear-gradient(180deg, #0a0d12 0%, var(--bg) 40%);
  }
  #titlebar {
    background: rgba(14,18,24,0.92);
    backdrop-filter: blur(12px);
    padding: 10px 14px;
    display: flex; align-items: center; justify-content: space-between;
    border-bottom: 1px solid var(--line); flex-shrink: 0;
    -webkit-app-region: drag;
  }
  #titlebar .brand {
    display: flex; align-items: center; gap: 10px;
  }
  #titlebar .mark {
    width: 8px; height: 8px; border-radius: 50%;
    background: var(--accent);
    box-shadow: 0 0 12px var(--accent-glow);
  }
  #titlebar .titles { display: flex; flex-direction: column; gap: 1px; }
  #titlebar .name {
    font-size: 11px; font-weight: 700; letter-spacing: 0.14em;
    text-transform: uppercase; color: var(--text);
  }
  #titlebar .sub {
    font-size: 10px; color: var(--mute); letter-spacing: 0.04em;
    font-family: var(--mono);
  }
  #close-btn {
    -webkit-app-region: no-drag;
    background: transparent; border: 1px solid var(--line); color: var(--dim);
    width: 28px; height: 28px; border-radius: 8px;
    font-size: 14px; cursor: pointer; line-height: 1;
  }
  #close-btn:hover { color: var(--danger); border-color: var(--danger); }
  #progress-bar-wrap {
    height: 2px; background: var(--line); flex-shrink: 0; position: relative;
  }
  #progress-bar {
    height: 100%;
    background: linear-gradient(90deg, #1a9e68, var(--accent));
    width: 0%; transition: width 0.3s ease;
    box-shadow: 0 0 10px var(--accent-glow);
  }
  #reader {
    flex: 1; overflow-y: auto;
    padding: 36px clamp(18px, 6vw, 64px) 48px;
    scroll-behavior: smooth;
  }
  #doc { max-width: 68ch; margin: 0 auto; }
  .blk { margin: 0 0 1.1em; }
  .blk.p, .blk.li, .blk.oli, .blk.quote {
    font-family: "Iowan Old Style", Charter, Georgia, "Times New Roman", serif;
    font-size: 17.5px; line-height: 1.82; color: #c5d0dc;
  }
  .blk.h1, .blk.h2, .blk.h3 {
    font-family: var(--font);
    font-weight: 700; color: #f4f8fc; line-height: 1.28;
    margin-top: 1.5em; letter-spacing: -0.02em;
  }
  .blk.h1 { font-size: 26px; }
  .blk.h2 { font-size: 20px; }
  .blk.h3 { font-size: 16.5px; letter-spacing: 0.01em; color: #d7e2ee; }
  .blk.li, .blk.oli { padding-left: 1.4em; position: relative; margin-bottom: 0.5em; }
  .blk.li::before {
    content: ''; position: absolute; left: 0.35em; top: 0.65em;
    width: 5px; height: 5px; border-radius: 50%; background: var(--accent);
  }
  .blk.quote {
    border-left: 2px solid var(--accent); padding-left: 1em;
    color: #9aafc2; font-style: italic;
  }
  .blk.code {
    font-family: var(--mono);
    font-size: 12.5px; line-height: 1.55; color: #9fd4ff;
    background: #0a1018; border: 1px solid var(--line); border-radius: 10px;
    padding: 12px 14px; white-space: pre-wrap; overflow-x: auto;
  }
  .seg {
    cursor: pointer; border-radius: 4px;
    padding: 1px 2px; margin: -1px 0;
    transition: background 0.2s ease, color 0.2s ease, box-shadow 0.2s ease;
    box-decoration-break: clone; -webkit-box-decoration-break: clone;
  }
  .seg:hover { background: var(--accent-dim); }
  .seg.done { color: #4d5a68; }
  .seg.active {
    background: var(--accent-dim);
    color: #ffffff;
    box-shadow: 0 0 0 1px rgba(61,255,168,0.35), 0 0 20px rgba(61,255,168,0.12);
  }
  #hint {
    text-align: center; font-size: 10px; color: var(--mute);
    padding: 10px 0 0; user-select: none; font-family: var(--mono);
    letter-spacing: 0.03em;
  }
  #controls {
    background: rgba(14,18,24,0.96);
    border-top: 1px solid var(--line);
    padding: 10px 12px 12px;
    display: flex; flex-direction: column; gap: 8px;
    flex-shrink: 0;
  }
  #ctrl-row {
    display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
  }
  #status {
    flex: 1; min-width: 120px;
    font-size: 11px; color: var(--dim);
    font-family: var(--mono); letter-spacing: 0.02em;
  }
  #status .live { color: var(--accent); }
  #status .paused { color: var(--warn); }
  .ctrl-btn {
    background: var(--panel-2); border: 1px solid var(--line); color: var(--text);
    padding: 6px 11px; border-radius: 8px; font-size: 11px; cursor: pointer;
    font-family: var(--font); font-weight: 600;
    transition: background 0.15s, border-color 0.15s, color 0.15s;
  }
  .ctrl-btn:hover { background: #1a222d; border-color: #2a3545; }
  .ctrl-btn.primary {
    background: rgba(61,255,168,0.12); border-color: rgba(61,255,168,0.35); color: var(--accent);
  }
  .ctrl-btn.primary:hover { background: rgba(61,255,168,0.2); }
  .ctrl-btn.active-speed {
    background: var(--accent); border-color: var(--accent); color: #04140e;
  }
  .speed-row { display: inline-flex; flex-wrap: wrap; gap: 3px; align-items: center; }
  .speed-row .ctrl-btn {
    min-width: 2.6em; padding: 5px 7px; font-size: 10.5px;
    font-family: var(--mono); font-weight: 600;
  }
  #stop-btn { color: var(--danger); border-color: rgba(255,92,92,0.45); }
  #stop-btn:hover { background: rgba(255,92,92,0.1); }
  #voice-sel {
    background: var(--panel-2); border: 1px solid var(--line); color: var(--text);
    padding: 6px 8px; border-radius: 8px; font-size: 11px; cursor: pointer;
    font-family: var(--font); outline: none; max-width: 160px;
  }
  #voice-sel:focus { border-color: rgba(61,255,168,0.4); }
  .lbl {
    font-size: 9px; color: var(--mute); font-family: var(--mono);
    text-transform: uppercase; letter-spacing: 0.08em; margin-left: 2px;
  }
  #error-banner {
    display: none; background: rgba(255,92,92,0.08);
    border-bottom: 1px solid rgba(255,92,92,0.35);
    color: var(--danger); font-size: 12px; padding: 10px 14px;
    text-align: center; flex-shrink: 0; font-family: var(--mono);
  }
  #error-banner.visible { display: block; }
  optgroup { color: var(--dim); font-size: 10px; }
  option { color: var(--text); background: var(--panel); }
  ::-webkit-scrollbar { width: 8px; }
  ::-webkit-scrollbar-thumb { background: #243040; border-radius: 8px; }
  /* ══ STYLE 2 · Sentence + Word Dual Focus (Codex pick, 2026-10-02) ══ */
  :root {
    --bg:#0b1110; --panel:#121716; --panel-2:#17201d; --line:#26332d;
    --text:#edf4ef; --dim:#8c9b96; --mute:#5f6f68;
    --accent:#6ee7b7; --accent-2:#c5ffdf;
    --accent-dim:rgba(110,231,183,0.13); --accent-glow:rgba(110,231,183,0.30);
  }
  body { background-color: var(--bg); background-image: linear-gradient(145deg,#0b1110 0%,#17231f 54%,#0a0d0e 100%); }
  #titlebar { background: rgba(18,23,22,0.92); border-bottom-color: var(--line); }
  #titlebar .name { letter-spacing: 0.16em; color: var(--accent-2); }
  #progress-bar { background: linear-gradient(90deg,#2fa57a,var(--accent)); box-shadow: 0 0 10px var(--accent-glow); }
  .blk.p, .blk.li, .blk.oli, .blk.quote { font-family: var(--font); font-size: 18px; line-height: 1.85; color: #b9c6bf; }
  .blk.h1, .blk.h2, .blk.h3 { color: var(--text); }
  .blk.quote { border-left-color: var(--accent); color: #9fb0a8; }
  .blk.li::before { background: var(--accent); }
  .seg { padding: 3px 8px; margin: -3px 0; border-radius: 12px;
         box-decoration-break: slice; -webkit-box-decoration-break: slice; }
  .seg:hover { background: rgba(110,231,183,0.07); }
  .seg.done { color: #5f6f68; }
  .seg.active {
    background: #28443a; color: var(--text);
    box-shadow: inset 3px 0 0 var(--accent), 0 0 24px rgba(110,231,183,0.10);
  }
  .w { transition: color .12s ease, text-shadow .12s ease; }
  .seg:not(.active) .w { color: inherit; text-shadow: none; }
  .seg.active .w.past { color: #7d9087; }
  .seg.active .w.on { color: var(--accent-2); text-shadow: 0 0 14px rgba(110,231,183,.65); }
  #controls { background: rgba(16,20,19,0.96); border-top-color: var(--line); }
  .ctrl-btn.primary { background: rgba(110,231,183,0.12); border-color: rgba(110,231,183,0.45); color: var(--accent-2); }
  .ctrl-btn.primary:hover { background: rgba(110,231,183,0.2); }
  .ctrl-btn.active-speed { background: var(--accent); border-color: var(--accent); color: #07140f; }
  #voice-sel:focus { border-color: rgba(110,231,183,0.5); }
  ::-webkit-scrollbar-thumb { background: #2a3a33; }
</style>
</head>
<body>

<div id="titlebar">
  <div class="brand">
    <span class="mark" aria-hidden="true"></span>
    <div class="titles">
      <span class="name">Nimba Reader</span>
      <span class="sub">local · proof · voice</span>
    </div>
  </div>
  <button id="close-btn" onclick="stopAndClose()" title="Stop and close">✕</button>
</div>
<div id="error-banner"></div>
<div id="progress-bar-wrap"><div id="progress-bar"></div></div>

<div id="reader">
  <div id="doc"><div class="blk p">Loading…</div></div>
  <div id="hint">CLICK SENTENCE TO SEEK · HIGHLIGHT TEXT TO JUMP</div>
</div>

<div id="controls">
  <div id="ctrl-row">
    <div id="status">Ready</div>
    <button class="ctrl-btn primary" id="pause-btn" onclick="togglePause()">⏸ Pause</button>
    <button class="ctrl-btn" id="stop-btn" onclick="stopReading()">■ Stop</button>
    <span class="lbl">Voice</span>
    <select id="voice-sel" onchange="changeVoice(this.value)">
      <option value="am_echo">Echo (Male)</option>
    </select>
  </div>
  <div id="ctrl-row">
    <span class="lbl">Speed</span>
    <span class="speed-row">
      <button class="ctrl-btn" id="sp08" onclick="changeSpeed(0.8)">0.8×</button>
      <button class="ctrl-btn" id="sp09" onclick="changeSpeed(0.9)">0.9×</button>
      <button class="ctrl-btn" id="sp10" onclick="changeSpeed(1.0)">1.0×</button>
      <button class="ctrl-btn active-speed" id="sp11" onclick="changeSpeed(1.1)">1.1×</button>
      <button class="ctrl-btn" id="sp12" onclick="changeSpeed(1.2)">1.2×</button>
      <button class="ctrl-btn" id="sp13" onclick="changeSpeed(1.3)">1.3×</button>
      <button class="ctrl-btn" id="sp15" onclick="changeSpeed(1.5)">1.5×</button>
    </span>
  </div>
</div>

<script>
  let sentences = [];
  let blocks = [];
  let currentIndex = -1;
  let pollTimer = null;
  let currentSpeed = 1.1;
  let currentVoice = 'am_echo';

  // ── Load voices from overlay server (same origin — no CORS) ─
  async function loadVoices() {
    try {
      const r = await fetch('/voices');
      const data = await r.json();
      const sel = document.getElementById('voice-sel');
      sel.innerHTML = '';

      // Kokoro voices
      if (data.kokoro && data.kokoro.length) {
        const grp = document.createElement('optgroup');
        grp.label = 'Kokoro AI Voices';
        data.kokoro.forEach(v => {
          const o = document.createElement('option');
          o.value = v.id; o.textContent = v.label;
          grp.appendChild(o);
        });
        sel.appendChild(grp);
      }

      // Cloned voices
      if (data.cloned && data.cloned.length) {
        const grp = document.createElement('optgroup');
        grp.label = '🎤 My Cloned Voices';
        data.cloned.forEach(v => {
          const o = document.createElement('option');
          o.value = v.id; o.textContent = '🎤 ' + v.label;
          grp.appendChild(o);
        });
        sel.appendChild(grp);
      }

      // Restore current selection
      if (currentVoice) sel.value = currentVoice;
    } catch(e) { /* keep fallback */ }
  }

  // ── Show error banner ─────────────────────────────────────
  function showError(msg) {
    const banner = document.getElementById('error-banner');
    if (banner) {
      banner.textContent = msg;
      banner.classList.add('visible');
    }
  }

  // ── KARAOKE v1 (2026-10-02, Style 2 redesign) ────────────────
  // The daemon publishes each sentence's real audio length (audio_dur) and the
  // wall-clock moment playback began (audio_t0). Words in the active sentence
  // advance in proportion to their spoken weight (letters + punctuation pauses).
  let audioT0 = 0, audioDur = 0, kWords = [], kCum = [], kLast = -2;
  const K_LATENCY = 0.12;   // afplay start-up lag (s)
  function prepActiveWords(idx) {
    const el = document.getElementById('s-' + idx);
    kWords = el ? Array.from(el.querySelectorAll('.w')) : [];
    let acc = 0;
    kCum = kWords.map(w => {
      const t = w.textContent;
      acc += t.replace(/[^A-Za-z0-9À-ɏ]/g, '').length + 1;
      if (/[,;:]$/.test(t)) acc += 3;
      if (/[.!?]$/.test(t)) acc += 5;
      return acc;
    });
    kWords.forEach(w => w.classList.remove('on', 'past'));
    kLast = -2;
  }
  function kTick() {
    requestAnimationFrame(kTick);
    if (isPaused || !kWords.length || audioDur <= 0 || audioT0 <= 0) return;
    const f = Math.max(0, Math.min(1, (Date.now() / 1000 - audioT0 - K_LATENCY) / audioDur));
    const target = f * kCum[kCum.length - 1];
    let i = kCum.findIndex(c => c >= target);
    if (i < 0) i = kCum.length - 1;
    if (i === kLast) return;
    kLast = i;
    kWords.forEach((w, n) => { w.classList.toggle('past', n < i); w.classList.toggle('on', n === i); });
  }
  requestAnimationFrame(kTick);

  // ── Load initial state ────────────────────────────────────
  async function fetchState() {
    try {
      const r = await fetch('/state');
      const d = await r.json();

      // Show error if daemon set one (e.g. server not running)
      if (d.error) {
        showError(d.error);
        clearTimeout(pollTimer);
        return;
      }

      if (d.sentences && d.sentences.length && sentences.length === 0) {
        sentences = d.sentences;
        blocks = d.blocks || [];
        renderSentences();
        // Set current voice before loading so loadVoices restores the right option
        if (d.voice) currentVoice = d.voice;
        loadVoices();  // populate full voice list (Kokoro + cloned) from /voices
      }

      if (typeof d.audio_t0 !== 'undefined' && (d.audio_t0 !== audioT0 || d.audio_dur !== audioDur)) {
        audioT0 = d.audio_t0; audioDur = d.audio_dur || 0; kLast = -2;
      }
      if (d.index !== currentIndex) {
        currentIndex = d.index;
        updateHighlight(currentIndex, d.total);
      }

      // Reflect paused state from server
      if (typeof d.paused !== 'undefined') {
        const serverPaused = d.paused;
        const btn = document.getElementById('pause-btn');
        if (btn && serverPaused !== isPaused) {
          isPaused = serverPaused;
          btn.textContent = isPaused ? '▶ Resume' : '⏸ Pause';
        }
        if (serverPaused) {
          document.getElementById('status').innerHTML =
            '<span class="paused">PAUSED</span> · ' + (d.index+1) + ' / ' + d.total;
        }
      }

      if (d.index === -1 && sentences.length > 0) {
        document.getElementById('status').innerHTML = '<span class="live">DONE</span>';
        document.getElementById('progress-bar').style.width = '100%';
        clearTimeout(pollTimer);
        setTimeout(() => window.close(), 2000);
        return;
      }
    } catch(e) {}
    pollTimer = setTimeout(fetchState, 250);
  }

  // ── READER v3: render a real document — headings, lists, quotes, code —
  // with every sentence as a clickable karaoke span. A photocopy that reads.
  function renderSentences() {
    const doc = document.getElementById('doc');
    doc.innerHTML = '';

    const addSeg = (parent, idx, text) => {
      const span = document.createElement('span');
      span.className = 'seg';
      span.id = 's-' + idx;
      span.dataset.idx = idx;
      text.split(/(\s+)/).forEach(tok => {
        if (!tok) return;
        if (/^\s+$/.test(tok)) { span.appendChild(document.createTextNode(' ')); return; }
        const w = document.createElement('span');
        w.className = 'w';
        w.textContent = tok;
        span.appendChild(w);
      });
      span.title = 'Click to read from here';
      span.onclick = () => seekTo(idx);
      parent.appendChild(span);
      parent.appendChild(document.createTextNode(' '));
    };

    if (blocks && blocks.length) {
      blocks.forEach(b => {
        const div = document.createElement('div');
        div.className = 'blk ' + (b.t || 'p');
        (b.segs || []).forEach(([idx, text]) => addSeg(div, idx, text));
        doc.appendChild(div);
      });
    } else {
      // Fallback: flat sentence list (old payloads)
      sentences.forEach((s, i) => {
        if (s === '\x00PARA\x00') return;
        const div = document.createElement('div');
        div.className = 'blk p';
        addSeg(div, i, s);
        doc.appendChild(div);
      });
    }
  }

  function updateHighlight(idx, total) {
    document.querySelectorAll('.seg').forEach(el => {
      const i = parseInt(el.dataset.idx, 10);
      el.className = 'seg' + (i < idx ? ' done' : '');
    });
    if (idx >= 0 && idx < sentences.length) {
      const el = document.getElementById('s-' + idx);
      if (el) {
        el.className = 'seg active';
        el.scrollIntoView({ behavior: 'smooth', block: 'center' });
        prepActiveWords(idx);
      }
      const pct = total > 1 ? Math.round((idx / (total-1)) * 100) : 100;
      document.getElementById('progress-bar').style.width = pct + '%';
      if (!isPaused) {
        document.getElementById('status').innerHTML =
          '<span class="live">READING</span> · ' + (idx+1) + ' / ' + total;
      }
    }
  }

  // ── READER v3: select any text in the document → reading jumps there.
  // One surface: what you highlight is what it reads, highlighted in place.
  document.addEventListener('mouseup', () => {
    const sel = window.getSelection();
    if (!sel || sel.isCollapsed || !sel.toString().trim()) return;
    let node = sel.anchorNode;
    while (node && node !== document.body) {
      if (node.classList && node.classList.contains('seg')) {
        const idx = parseInt(node.dataset.idx, 10);
        if (!isNaN(idx) && idx !== currentIndex) seekTo(idx);
        return;
      }
      node = node.parentNode;
    }
  });

  async function stopReading() {
    clearTimeout(pollTimer);
    try { await fetch('/stop', { method: 'POST' }); } catch(e) {}
    window.close();
  }
  function stopAndClose() { stopReading(); }

  // Pause / Resume toggle
  let isPaused = false;
  async function togglePause() {
    const btn = document.getElementById('pause-btn');
    if (isPaused) {
      isPaused = false;
      btn.textContent = '⏸ Pause';
      btn.classList.add('primary');
      try { await fetch('/resume', { method: 'POST' }); } catch(e) {}
    } else {
      isPaused = true;
      btn.textContent = '▶ Resume';
      btn.classList.remove('primary');
      try { await fetch('/pause', { method: 'POST' }); } catch(e) {}
    }
  }

  // Seek — jump to sentence index
  async function seekTo(index) {
    isPaused = false;
    const btn = document.getElementById('pause-btn');
    if (btn) btn.textContent = '⏸ Pause';
    try {
      await fetch('/seek', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({index: index})
      });
    } catch(e) {}
  }

  // Speed — updates daemon immediately, highlights active button
  // Levels: 0.8 0.9 1.0 1.1 1.2 1.3 1.5 (fine control for natural storytelling)
  async function changeSpeed(s) {
    currentSpeed = s;
    const ids = ['sp08','sp09','sp10','sp11','sp12','sp13','sp15'];
    ids.forEach(id => {
      const el = document.getElementById(id);
      if (el) el.classList.remove('active-speed');
    });
    const map = {
      0.8: 'sp08', 0.9: 'sp09', 1.0: 'sp10', 1.1: 'sp11',
      1.2: 'sp12', 1.3: 'sp13', 1.5: 'sp15'
    };
    // float key safety (1.0 vs 1)
    const key = Math.round(s * 10) / 10;
    if (map[key]) {
      const el = document.getElementById(map[key]);
      if (el) el.classList.add('active-speed');
    }
    // Push to daemon — next synth + breath gaps use this rate
    try {
      await fetch('/speed', {
        method: 'POST',
        headers: {'Content-Type':'application/json'},
        body: JSON.stringify({speed: s})
      });
    } catch(e) {}
  }

  // Voice — pushes to daemon AND to Nimba server (so browser UI stays in sync)
  async function changeVoice(v) {
    currentVoice = v;
    try {
      // Update daemon
      await fetch('/voice', {
        method: 'POST',
        headers: {'Content-Type':'application/json'},
        body: JSON.stringify({voice: v})
      });
      // Update Nimba server so browser UI matches
      await fetch('http://127.0.0.1:7788/api/voice', {
        method: 'POST',
        headers: {'Content-Type':'application/json'},
        body: JSON.stringify({voice: v})
      });
    } catch(e) {}
  }

  fetchState();
</script>
</body>
</html>"""

    class OverlayHandler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args): pass

        def do_GET(self):
            path = urllib.parse.urlparse(self.path).path
            if path == '/':
                body = OVERLAY_HTML.encode()
                self.send_response(200)
                self.send_header('Content-Type', 'text/html')
                self.send_header('Content-Length', len(body))
                self.end_headers()
                self.wfile.write(body)
            elif path == '/state':
                state_copy = dict(overlay_state)
                state_copy['error'] = _overlay_error
                body = json.dumps(state_copy).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', len(body))
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(body)
            elif path == '/voices':
                # Read voices.json from the nimba folder — same origin, no CORS
                try:
                    voices_path = os.path.join(
                        os.path.dirname(os.path.abspath(__file__)), 'voices.json'
                    )
                    with open(voices_path) as _vf:
                        body = _vf.read().encode()
                except Exception:
                    body = b'{"kokoro":[],"cloned":[]}'
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', len(body))
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_response(404); self.end_headers()

        def do_POST(self):
            length = int(self.headers.get('Content-Length', 0))
            data = json.loads(self.rfile.read(length) or b'{}')
            path = urllib.parse.urlparse(self.path).path

            if path == '/load':
                overlay_state['sentences'] = data.get('sentences', [])
                overlay_state['blocks']    = data.get('blocks', [])
                overlay_state['index']     = 0
                overlay_state['total']     = len(overlay_state['sentences'])
                overlay_state['voice']     = data.get('voice', KOKORO_VOICE)
                overlay_state['speed']     = KOKORO_SPEED
            elif path == '/update':
                overlay_state['index']  = data.get('index', -1)
                overlay_state['total']  = data.get('total', 0)
                overlay_state['speed']  = KOKORO_SPEED
                overlay_state['paused'] = _is_paused
                overlay_state['audio_dur'] = float(data.get('audio_dur', 0.0) or 0.0)
                overlay_state['audio_t0']  = float(data.get('audio_t0', 0.0) or 0.0)
            elif path == '/stop':
                stop_reading()
            elif path == '/pause':
                pause_reading()
                overlay_state['paused'] = True
            elif path == '/resume':
                resume_reading()
                overlay_state['paused'] = False
            elif path == '/seek':
                idx = int(data.get('index', 0))
                seek_reading(idx)
                overlay_state['paused'] = False
            elif path == '/speed':
                import __main__
                new_speed = float(data.get('speed', 1.0))
                new_speed = max(0.5, min(2.0, new_speed))
                speed_changed = (new_speed != __main__.KOKORO_SPEED)
                __main__.KOKORO_SPEED = new_speed
                overlay_state['speed'] = new_speed
                print(f'[Nimba Daemon] Speed → {new_speed}× (breath gaps scale with rate)', flush=True)
                # BUG FIX (2026-07-18): every sentence is pre-synthesized in
                # parallel the instant reading starts, with speed baked into
                # each request. Without this, a mid-read speed change was
                # silently ignored — every remaining sentence kept playing at
                # the OLD speed because it was already synthesized/cached.
                # seek_reading() already knows how to drop stale cache and
                # re-synthesize from here — reuse it instead of duplicating.
                if speed_changed and _is_reading:
                    seek_reading(_read_index)
            elif path == '/voice':
                new_voice = str(data.get('voice', KOKORO_VOICE))
                old = KOKORO_VOICE
                set_kokoro_voice(new_voice)
                overlay_state['voice'] = KOKORO_VOICE
                voice_changed = (KOKORO_VOICE != old)
                print(f'[Nimba Daemon] Voice → {KOKORO_VOICE}', flush=True)
                # Drop pre-baked WAVs and re-synth from here at the NEW voice.
                if voice_changed and _is_reading:
                    seek_reading(_read_index)

            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(b'{"ok":true}')

        def do_OPTIONS(self):
            self.send_response(204)
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
            self.send_header('Access-Control-Allow-Headers', 'Content-Type')
            self.end_headers()

    server = HTTPServer(('127.0.0.1', _overlay_port), OverlayHandler)
    print(f'[Nimba Daemon] Overlay server on port {_overlay_port}', flush=True)
    server.serve_forever()


def make_fn_listener():
    """
    Fn key is special on macOS — pynput sees it as Key.cmd_r on Apple keyboards
    depending on firmware. We use a separate approach: monitor for the virtual
    key code 63 (Fn) via Quartz CGEvent if available, otherwise fall back to
    a keyboard shortcut the user can remap.
    """
    try:
        from Quartz import (
            CGEventTapCreate, kCGSessionEventTap,
            kCGHeadInsertEventTap, kCGEventTapOptionListenOnly,
            kCGEventFlagsChanged, CGEventGetFlags,
            CFMachPortCreateRunLoopSource, CFRunLoopGetCurrent,
            CFRunLoopAddSource, kCFRunLoopCommonModes,
            CFRunLoopRun, CGEventMaskBit,
        )
        NX_SECONDARYFNMASK = 0x00800000  # Fn modifier flag bit

        # Modifier flag constants
        kCGEventFlagMaskAlternate = 0x00080000  # ⌥ Option/Alt
        kCGEventFlagMaskCommand   = 0x00100000  # ⌘ Command

        # ⌥⌘Fn state: track whether PTT recording is in progress
        state = {'down': False, 'ptt_active': False}

        def fn_callback(proxy, etype, event, refcon):
            try:
                flags   = CGEventGetFlags(event)
                fn_now  = bool(flags & NX_SECONDARYFNMASK)
                alt_now = bool(flags & kCGEventFlagMaskAlternate)
                cmd_now = bool(flags & kCGEventFlagMaskCommand)

                if fn_now and not state['down']:
                    # ── FN KEY DOWN ──────────────────────────────────────────
                    state['down'] = True
                    if alt_now and cmd_now:
                        # ⌥⌘Fn pressed → open mic immediately (WhisperFlow style)
                        state['ptt_active'] = True
                        _ptt_stop.clear()
                        print('[Nimba Daemon] 🎙 ⌥⌘Fn DOWN — mic open, speak now…', flush=True)
                        threading.Thread(target=run_ai_mode_ptt, daemon=True).start()

                elif not fn_now and state['down']:
                    # ── FN KEY UP ────────────────────────────────────────────
                    state['down'] = False
                    if state['ptt_active']:
                        # Release → stop recording immediately, send to Nimba
                        state['ptt_active'] = False
                        _ptt_stop.set()
                        print('[Nimba Daemon] 🎙 ⌥⌘Fn UP — processing…', flush=True)

            except Exception:
                pass
            return event

        tap = CGEventTapCreate(
            kCGSessionEventTap,
            kCGHeadInsertEventTap,
            kCGEventTapOptionListenOnly,    # listen-only — fixes "wrong type" error
            CGEventMaskBit(kCGEventFlagsChanged),
            fn_callback,
            None,
        )
        if tap is None:
            raise RuntimeError('CGEventTap returned None — check Accessibility permission')

        src = CFMachPortCreateRunLoopSource(None, tap, 0)
        CFRunLoopAddSource(CFRunLoopGetCurrent(), src, kCFRunLoopCommonModes)
        print('[Nimba Daemon] ✓ Fn key listener active (Quartz — listen-only)')
        CFRunLoopRun()  # blocks — run in thread

    except Exception as e:
        print(f'[Nimba Daemon] ⚠ Quartz Fn listener failed: {e}')
        print('[Nimba Daemon]   Use ⌥⌘F as fallback for AI mode')
        # Fn listener failed — pynput handles ⌥F as fallback


def on_press_fallback(key):
    """
    Fallback if Quartz Fn tap isn't available:
    ⌥⌘F triggers AI mode (ask Nimba a question).
    """
    global _alt_pressed, _cmd_pressed
    try:
        # ⌥⌘F → AI mode fallback (ƒ is what ⌥F produces on Mac keyboards)
        if hasattr(key, 'char') and key.char in ('ƒ', 'f') and _alt_pressed and _cmd_pressed:
            threading.Thread(target=run_ai_mode, daemon=True).start()
    except Exception:
        pass


# ── STARTUP CHECKS ────────────────────────────────────────────────────────────
def check_accessibility():
    """Warn if Accessibility permission isn't granted."""
    try:
        from Quartz import AXIsProcessTrusted
        if not AXIsProcessTrusted():
            print()
            print('  ⚠  ACCESSIBILITY PERMISSION REQUIRED')
            print('  ─────────────────────────────────────────────────────')
            print('  Text injection and keyboard simulation need permission.')
            print('  1. Open: System Settings → Privacy & Security → Accessibility')
            print('  2. Add Terminal (or whichever app you run this from)')
            print('  3. Restart nimba_daemon.py')
            print()
    except Exception:
        pass  # Quartz not available — skip check


def check_nimba_server():
    try:
        urllib.request.urlopen(f'{NIMBA_URL}/api/status', timeout=3)
        print('[Nimba Daemon] ✓ Nimba server reachable')
    except Exception:
        print('[Nimba Daemon] ⚠ Nimba server not running — AI mode will fail')
        print(f'[Nimba Daemon]   Start it: node server.js  (or run START_NIMBA.command)')


def check_kokoro_server():
    try:
        resp = urllib.request.urlopen(f'{KOKORO_URL}/health', timeout=3)
        data = json.loads(resp.read())
        if data.get('ready'):
            print('[Nimba Daemon] ✓ Kokoro warm server ready')
        else:
            print('[Nimba Daemon] ⏳ Kokoro server loading model (will be ready in ~8s)')
    except Exception:
        print('[Nimba Daemon] ⚠ Kokoro server not running — hotkeys will be silent until it starts')
        print(f'[Nimba Daemon]   Kokoro starts automatically with START_NIMBA.command')


# ── WAKE WORD LISTENER ────────────────────────────────────────────────────────
# OFF by default — enabling it keeps the mic indicator lit permanently on macOS
# and can block Zoom/FaceTime/other apps from clean mic access.
#
# To enable, start the daemon with:  NIMBA_WAKE=1 python3.11 nimba_daemon.py
# or set _wake_word_enabled = True below before running.
#
# When enabled, the listener records short 1s bursts with a 0.3s gap between
# each burst so other apps have a window to grab the mic.

WAKE_WORDS         = ['nimba', 'hey nimba', 'ok nimba']
WAKE_CHUNK_SEC     = 1.0    # seconds captured per check
WAKE_GAP_SEC       = 0.3    # silence gap between captures — lets other apps grab mic
WAKE_ENERGY_THRESH = 0.012  # RMS below this = silence, skip Whisper entirely
WAKE_COOLDOWN_SEC  = 4.0    # wait after triggering before listening again

# Read from env var so user can enable without editing code
import os as _os
_wake_word_enabled = _os.environ.get('NIMBA_WAKE', '0').strip() == '1'


def _wake_word_listener():
    """
    Optional wake word thread — only runs when NIMBA_WAKE=1.
    Records short bursts (mic ON) then releases (mic OFF) in a loop.
    The gap lets Zoom/FaceTime/any other app access the mic cleanly.
    """
    import io
    import scipy.io.wavfile as wav

    WAKE_RECORD_RATE = 44100   # MacBook Air native rate
    chunk_samples    = int(WAKE_RECORD_RATE * WAKE_CHUNK_SEC)

    print('[Nimba Wake] 👂 Wake word ENABLED — mic will blink. Say "Hey Nimba".', flush=True)
    print('[Nimba Wake]    Note: mic indicator stays lit while wake word is on.', flush=True)
    print('[Nimba Wake]    To disable: restart daemon without NIMBA_WAKE=1', flush=True)

    while _wake_word_enabled:
        try:
            # Don't compete with active modes
            if _recording or _is_reading or _speaking:
                time.sleep(0.5)
                continue

            # ── Capture short burst at native 44100 Hz ────────────────────────
            audio = sounddevice.rec(
                chunk_samples, samplerate=WAKE_RECORD_RATE,
                channels=1, dtype='float32', blocking=True
            )
            # ── Release mic briefly (mic OFF) — other apps can grab it here ──
            time.sleep(WAKE_GAP_SEC)

            # Energy gate — skip whisper on silence
            rms = float(np.sqrt(np.mean(audio ** 2)))
            if rms < WAKE_ENERGY_THRESH:
                continue

            # Resample 44100 → 16000 Hz for Whisper
            from scipy.signal import resample_poly
            audio_16k   = resample_poly(audio, up=160, down=441)
            audio_int16 = (np.clip(audio_16k, -1, 1) * 32767).astype(np.int16)
            buf = io.BytesIO()
            wav.write(buf, 16000, audio_int16)
            text = transcribe(buf.getvalue()).lower().strip()

            if not text:
                continue

            if any(w in text for w in WAKE_WORDS):
                print(f'[Nimba Wake] 🎙 Wake word: "{text}"', flush=True)
                notify('Nimba 🎙', 'Listening…')
                threading.Thread(target=run_ai_mode_ptt, daemon=True).start()
                time.sleep(WAKE_COOLDOWN_SEC)

        except Exception as exc:
            if _wake_word_enabled:
                print(f'[Nimba Wake] ⚠ {exc}', flush=True)
            time.sleep(1)

    print('[Nimba Wake] Stopped.', flush=True)


# ── MAIN ──────────────────────────────────────────────────────────────────────
if __name__ == '__main__':

    # ── SELF-GUARD: kill any existing daemon copy before starting ─────────────
    # Prevents the "two voices" problem caused by running the daemon twice
    # (e.g. once from START_NIMBA.command and once manually from a terminal).
    import signal as _signal
    _my_pid = os.getpid()
    try:
        import subprocess as _sp
        _result = _sp.run(
            ['pgrep', '-f', 'nimba_daemon.py'],
            capture_output=True, text=True
        )
        for _pid_str in _result.stdout.strip().splitlines():
            _pid = int(_pid_str.strip())
            if _pid != _my_pid:
                print(f'[Nimba Daemon] Killing existing daemon (PID {_pid}) — only one allowed')
                try:
                    os.kill(_pid, _signal.SIGTERM)
                except Exception:
                    pass
    except Exception:
        pass

    print()
    print('  ┌──────────────────────────────────────────────────────┐')
    print('  │  NIMBA — System-Wide Hotkey Daemon                   │')
    print('  ├──────────────────────────────────────────────────────┤')
    print('  │  "Hey Nimba" / "Nimba"  → Wake word (always on)     │')
    print('  │  ⌥ ⌘ Fn                 → Ask Nimba (AI voice)      │')
    print('  │  ⌥ Space (hold+release) → Dictate anywhere          │')
    print('  │  ⌥ ⌘ C                  → Read selection aloud      │')
    print('  │  ⌥ ⌘ 0                  → Read full screen (OCR)    │')
    print('  │  ⌥ ⌘ 9                  → Select region → Copy+Read │')
    print('  └──────────────────────────────────────────────────────┘')
    print()

    check_accessibility()
    check_nimba_server()
    check_kokoro_server()

    # Start overlay HTTP server in background thread
    overlay_thread = threading.Thread(target=start_overlay_server, daemon=True)
    overlay_thread.start()

    print()
    print('[Nimba Daemon] Starting hotkey listeners…')

    # Start Fn listener in background thread (Quartz CFRunLoop blocks)
    fn_thread = threading.Thread(target=make_fn_listener, daemon=True)
    fn_thread.start()
    time.sleep(0.3)  # let Quartz initialise

    # Wake word — only start if explicitly enabled (keeps mic indicator off by default)
    if _wake_word_enabled:
        wake_thread = threading.Thread(target=_wake_word_listener, daemon=True)
        wake_thread.start()
    else:
        print('[Nimba Daemon] 💤 Wake word OFF (mic stays free). To enable: NIMBA_WAKE=1 python3.11 nimba_daemon.py')

    # Main pynput listener (⌥Space + ⌥F fallback)
    listener = keyboard.Listener(
        on_press=lambda key: (on_press(key), on_press_fallback(key)),
        on_release=on_release,
        suppress=False,   # don't swallow keys — just listen
    )
    listener.start()

    print('[Nimba Daemon] ✓ Ready. Hotkeys active system-wide.')
    if _wake_word_enabled:
        print('[Nimba Daemon]   "Hey Nimba" → Wake word (mic active — blink is normal)')
    else:
        print('[Nimba Daemon]   Wake word  OFF  (mic free — no blink)')
    print('[Nimba Daemon]   ⌥⌘Fn         → Ask Nimba (hold to speak, release to send)')
    print('[Nimba Daemon]   ⌥Space       → Dictate (speech to text)')
    print('[Nimba Daemon]   ⌥⌘C          → Read highlighted text aloud')
    print('[Nimba Daemon]   ⌥⌘0          → Read full screen (press again to STOP)')
    print('[Nimba Daemon]   ⌥⌘9          → Drag-select area → copy text to clipboard')
    print('[Nimba Daemon]   Ctrl+C to stop.')
    print()

    try:
        listener.join()
    except KeyboardInterrupt:
        print('\n[Nimba Daemon] Shutting down. Goodbye KK.')
        sys.exit(0)
