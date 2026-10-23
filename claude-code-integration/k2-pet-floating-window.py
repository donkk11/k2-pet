#!/usr/bin/env python3
"""A small, borderless, always-on-top floating window showing a K2 pet companion.

Usage:
  python3 k2-pet-floating-window.py <url> <title>
  python3 k2-pet-floating-window.py http://127.0.0.1:3042 "K2 — Nimba"
  python3 k2-pet-floating-window.py http://127.0.0.1:3043 "K2 — Claude Code"

Real, tested (macOS): pywebview's on_top=True keeps this above other windows.
frameless=True removes the title bar so it reads as a small companion, not an app window.

Real bug found and fixed on macOS: pywebview 6.2.1's cocoa backend only calls
setOpaque_(False) for transparent=True, but never actually sets the NSWindow's
backgroundColor to clear -- so the window keeps painting its default background,
which is exactly the faint visible box you'd see. Fixed directly below via the
window's real native NSWindow reference, not by patching the library.

Windows: everything below this point that touches AppKit/pyobjc/Cocoa is
macOS-only and guarded behind `IS_MAC` -- none of it exists on Windows, and the
modules themselves don't import there. The base webview.create_window() call
(frameless/on_top/resizable/transparent/easy_drag) is pywebview's own
cross-platform API and should work unmodified on its Windows backend, but this
has NOT been run on a real Windows machine by whoever wrote this -- unlike the
macOS behavior above, which was. Treat the Windows path as an untested first
cut: if something looks wrong (window chrome still visible, click-through not
working, etc.), that's expected until someone actually runs it there and reports
back what's broken.
"""
import json
import platform
import re
import subprocess
import sys
from pathlib import Path
import webview

IS_MAC = platform.system() == "Darwin"

if IS_MAC:
    from PyObjCTools import AppHelper
    import AppKit
    from webview.platforms.cocoa import BrowserView

url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:3042"
title = sys.argv[2] if len(sys.argv) > 2 else "K2 Pet"

# KK's bug report (2026-10-09): shrinking the window, then having it "reset to
# default and go big again" -- real cause, confirmed by grepping this whole file
# and companion.js for every resize() call: nothing here is state-driven (no code
# resizes on "finished" or any other pet state). The window simply has no memory of
# its own size across a process restart -- every fresh launch starts at the
# hardcoded WIDTH/HEIGHT default below, which is exactly what happens on every
# redeploy during active development (today's actual trigger), and would happen
# just as much from a crash, a reboot, or KK re-running the launcher by hand.
# Keyed by port (parsed from url) so Nimba's pet (3042) and Claude Code's (3043)
# remember their own sizes independently, not shared.
_port_match = re.search(r":(\d+)", url)
_SIZE_FILE = Path.home() / f".k2-pet-size-{_port_match.group(1) if _port_match else 'default'}.json"


def _load_saved_size(default_w, default_h):
    try:
        data = json.loads(_SIZE_FILE.read_text())
        w, h = int(data["w"]), int(data["h"])
        if 150 <= w <= 600 and 180 <= h <= 900:  # sane bounds, same as resize()'s own clamp
            return w, h
    except Exception:
        pass
    return default_w, default_h


def _save_size(w, h):
    try:
        _SIZE_FILE.write_text(json.dumps({"w": w, "h": h}))
    except Exception as e:
        print(f"[k2-pet] couldn't save window size (non-fatal): {e}")


WIDTH, HEIGHT = _load_saved_size(260, 400)

if IS_MAC:
    # Real fix, not a config tweak: pywebview's WindowHost is a plain NSWindow, and the
    # private _setPreventsActivation selector on a plain NSWindow was proven (live test,
    # zero errors logged from a poll-based drag that never even started) to block mouse
    # event delivery outright, not just window activation. The actual Apple-sanctioned
    # mechanism for "floats everywhere, never steals focus, still clickable" is an NSPanel
    # with NSWindowStyleMaskNonactivatingPanel -- what Spotlight, Alfred, and Codex's own
    # Electron pet window (via Chromium's own panel support) all use. pywebview never
    # creates an NSPanel, so this replaces its WindowHost class before the real window is
    # built. canBecomeKeyWindow keeps pywebview's own designed behavior (driven by the
    # `focus` flag it already sets), so typing into the compose box still works.
    class NonActivatingPanelHost(AppKit.NSPanel):
        def canBecomeKeyWindow(self):
            return self.focus

        def canBecomeMainWindow(self):
            return False

    BrowserView.WindowHost = NonActivatingPanelHost

    # Real fix for "reach the top of the screen like Codex's pet does", second attempt.
    # The first attempt replaced pywebview's whole mouseDragged_ (the method that fires
    # mid-drag, on every mouse-move, and is what feeds the DOM's own pointermove events)
    # to fix a real, confirmed bug in its vertical clamp. Confirmed live, by KK, that this
    # broke the drag-to-run animation -- even though the horizontal math was untouched,
    # replacing that exact method changed something about the mouse-event pipeline JS
    # depends on to see real pointermove events during a drag. Real lesson: don't touch the
    # event-delivery path just to fix a position number.
    # This version never touches mouseDragged_ at all. windowDidMove_ is a NOTIFICATION
    # that fires AFTER a move already happened -- outside the live mouse-event pipeline
    # entirely -- so it can correct the window's position without going anywhere near
    # whatever timing/dispatch JS's pointermove listener depends on.
    _TOP_OVERSHOOT = 20  # px the window's own top may go past the screen's true top
    _original_window_did_move = BrowserView.WindowDelegate.windowDidMove_

    def _patched_window_did_move(self, notification):
        _original_window_did_move(self, notification)  # preserve pywebview's own real behavior (fires events.moved)
        try:
            inst = BrowserView.get_instance('window', notification.object())
            if not inst:
                return
            win = inst.window
            frame = win.frame()
            screen_frame = win.screen().frame()
            screen_top = screen_frame.origin.y + screen_frame.size.height
            max_origin_y = screen_top - frame.size.height + _TOP_OVERSHOOT
            if frame.origin.y > max_origin_y:
                # Re-entrant: this setFrameOrigin_ will itself fire windowDidMove_ again,
                # but with origin.y already at max_origin_y the condition above is then
                # false, so it terminates after exactly one real correction.
                win.setFrameOrigin_(AppKit.NSMakePoint(frame.origin.x, max_origin_y))
        except Exception as e:
            print(f"[k2-pet] windowDidMove top-clamp failed (non-fatal): {e}")

    BrowserView.WindowDelegate.windowDidMove_ = _patched_window_did_move

    # KK's bug report (2026-10-09): switching Spaces (3-finger swipe) away from the
    # pet mid-type, then back, leaves the compose box open and visibly showing what
    # he already typed, but further keystrokes do nothing -- can't add text, can't
    # delete it either. Real, documented behavior of a NSWindowStyleMaskNonactivating
    # Panel + embedded WKWebView: the panel can still become key (canBecomeKeyWindow
    # returns self.focus, which defaults True here -- never explicitly set otherwise)
    # and DOES regain key status on click, but WKWebView's own internal first-responder
    # state doesn't always re-sync with it after the app was backgrounded by a Space
    # switch -- the DOM-level focus/cursor can look fine while actual keyboard events
    # from the OS never reach the webview's text input layer at all.
    # Additive only, like windowDidMove_ above: this is a notification Cocoa already
    # sends and nothing here currently handles, so it can't regress the drag/click-
    # through behavior the comment above warns about (that regression came from
    # replacing mouseDragged_, a method genuinely already in the live event pipeline --
    # this isn't that). NOT independently reproduced here (no second real macOS Space
    # to test an actual 3-finger swipe against) -- reasoned from the real `focus`
    # default and the documented NSPanel/WKWebView quirk, not verified end to end.
    # Please test this for real after the restart and say if it's not fixed.
    def _window_did_become_key(self, notification):
        try:
            inst = BrowserView.get_instance('window', notification.object())
            if inst and inst.window and inst.webview:
                inst.window.makeFirstResponder_(inst.webview)
        except Exception as e:
            print(f"[k2-pet] windowDidBecomeKey refocus failed (non-fatal): {e}")

    BrowserView.WindowDelegate.windowDidBecomeKey_ = _window_did_become_key


class Api:
    def __init__(self):
        # Real fix for "click-through doesn't fit his body": the page reports the
        # ACTUAL on-screen box of whatever's currently visible (character + floor,
        # unioned), in window-local top-down pixels, every time the pose changes or the
        # window resizes. Replaces the earlier fixed-percentage approximation, which
        # couldn't work since every pose has a different real rendered size.
        self.hot_rect = None  # (left, top, width, height), window-local, top-down

    def update_hot_rect(self, left, top, width, height):
        self.hot_rect = (left, top, width, height)

    def resize(self, delta):
        """Called from the page's own +/- buttons -- grows/shrinks the real window
        by delta px on both axes, keeping the same aspect ratio, clamped to sane bounds.

        Width floor: 120 -> 150 -> 170 (KK's bug reports, 2026-10-09, now three
        rounds). Latest: #btn-tasks (the running-tasks picker) made 8 real buttons,
        measured live at 167px content span -- fixed proactively this time, in the
        same commit that added the button, matched to companion.html's #chrome
        min-width (same change, same commit)."""
        w = max(170, min(600, window.width + delta))
        h = max(180, min(900, window.height + int(delta * HEIGHT / WIDTH)))
        window.resize(w, h)
        _save_size(w, h)  # KK's ask: stays this size across a restart, not just this session

    def focus_claude_code(self):
        """Real, boring, reliable: bring the actual Claude Code app forward. macOS uses
        a standard 'activate' command. Windows has no equivalent wired up yet -- untested,
        no pywin32 dependency added speculatively -- so this is a no-op there for now
        rather than a guess that might do the wrong thing."""
        if not IS_MAC:
            return
        try:
            subprocess.run(["osascript", "-e", 'tell application "Claude" to activate'],
                            timeout=3, check=False)
        except Exception as e:
            print(f"[k2-pet] focus_claude_code failed (non-fatal): {e}")


api = Api()
window = webview.create_window(
    title,
    url,
    width=WIDTH,
    height=HEIGHT,
    x=40,
    y=60,
    frameless=True,
    on_top=True,
    resizable=True,
    min_size=(170, 180),  # matches resize()'s own floor above -- same bar-overflow fix
    easy_drag=True,
    transparent=True,
    js_api=api,
)

if IS_MAC:
    def _start_passthrough_monitor():
        """Real click-through, the same way Codex's does it conceptually (their
        setIgnoreMouseEvents(true, {forward:true})) -- but built on a technique already
        proven stable in this exact codebase (the drag fix's NSEvent.mouseLocation()
        polling), since plain AppKit's ignoresMouseEvents has no "still forward movement"
        mode: if it were left on, the window would stop receiving events entirely and could
        never detect the cursor approaching to turn itself back on. Polling from outside
        sidesteps that -- global cursor position is readable regardless of the window's own
        interactivity state."""
        try:
            native = BrowserView.instances[window.uid].window

            def _tick(_elapsed):
                try:
                    loc = AppKit.NSEvent.mouseLocation()
                    f = native.frame()
                    if api.hot_rect is None:
                        # No report yet (page just loaded) -- fail open to the whole
                        # window rather than leave him briefly unclickable.
                        inside = (f.origin.x <= loc.x <= f.origin.x + f.size.width and
                                  f.origin.y <= loc.y <= f.origin.y + f.size.height)
                    else:
                        # hot_rect is window-local, top-down (browser convention). Convert
                        # to screen coordinates, which are bottom-up on macOS.
                        left, top, w, h = api.hot_rect
                        x_min = f.origin.x + left
                        x_max = x_min + w
                        y_max = f.origin.y + f.size.height - top
                        y_min = y_max - h
                        inside = x_min <= loc.x <= x_max and y_min <= loc.y <= y_max

                    if native.ignoresMouseEvents() == inside:
                        native.setIgnoresMouseEvents_(not inside)
                except Exception as e:
                    print(f"[k2-pet] passthrough tick failed (non-fatal): {e}")
                AppHelper.callLater(0.08, _tick, 0)

            _tick(0)
        except Exception as e:
            print(f"[k2-pet] passthrough monitor failed to start (non-fatal): {e}")


    def _apply_native_window_fixes():
        try:
            native = BrowserView.instances[window.uid].window
            # Belt-and-suspenders re-assertion of pywebview's own transparent=True path
            # (setOpaque_/backgroundColor), in case a page reload ever resets it.
            native.setBackgroundColor_(AppKit.NSColor.clearColor())
            native.setOpaque_(False)
            native.setHasShadow_(False)

            # Real bug, confirmed by reading pywebview's cocoa.py: it never calls
            # setCollectionBehavior_, so a new NSWindow only ever joins the one macOS
            # Space it was created on -- that's exactly why this only appeared over
            # Claude Code instead of everywhere, unlike the real (Electron-based) Codex
            # pet. Calling setCollectionBehavior_ synchronously from inside this
            # events.shown callback reliably hard-crashed the window (SIGTRAP,
            # reproduced 3/3) -- that callback isn't a safe place for a second
            # AppKit call. Scheduling it via AppHelper.callAfter (pywebview's own
            # main-run-loop dispatcher, already used internally by pywebview itself)
            # instead of calling it inline fixes this: verified stable across repeated
            # runs with no crash.
            def _set_collection_behavior():
                try:
                    CAN_JOIN_ALL_SPACES = 1 << 0
                    FULLSCREEN_AUXILIARY = 1 << 8
                    NONACTIVATING_PANEL = 1 << 7  # NSWindowStyleMaskNonactivatingPanel
                    native.setCollectionBehavior_(CAN_JOIN_ALL_SPACES | FULLSCREEN_AUXILIARY)
                    AppKit.NSApp().setActivationPolicy_(AppKit.NSApplicationActivationPolicyAccessory)
                    # The window is already an NSPanel (see NonActivatingPanelHost above), but
                    # the actual "don't activate the app when clicked" behavior comes from this
                    # style-mask bit -- Apple's real, supported mechanism, unlike the private
                    # preventsActivation property that blocked clicks outright when tried on a
                    # plain NSWindow.
                    native.setStyleMask_(native.styleMask() | NONACTIVATING_PANEL)
                    native.setHidesOnDeactivate_(False)
                except Exception as e2:
                    print(f"[k2-pet] collectionBehavior/activation-policy fix failed (non-fatal): {e2}")

            AppHelper.callAfter(_set_collection_behavior)
            AppHelper.callAfter(_start_passthrough_monitor)
        except Exception as e:
            print(f"[k2-pet] native window fix failed (non-fatal): {e}")


    window.events.shown += _apply_native_window_fixes

webview.start()
