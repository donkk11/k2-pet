# Nimba daemon, with K2 pet speaking events

`nimba_daemon.py` is a copy of Nimba's system-wide hotkey daemon
(`~/Documents/openklaw/nimba/nimba_daemon.py`) after one change: it now tells the
K2 pet when Nimba starts and stops speaking, so Gentleman KK can do his TED-style
presenter animation while a voice is playing. `pet-tts-events.patch` is that change
alone: 24 added lines, none removed or altered.

## What it sends

A small helper, `pet_tts('started' | 'ended')`, POSTs to the pet server:

    POST http://127.0.0.1:3043/ingest
    {"method": "nimba/tts.started"}      /      {"method": "nimba/tts.ended"}

It runs on its own thread with a 0.5 s timeout and swallows every error, so a
missing or stopped pet can never delay or break audio.

## Where it fires

| Moment | Event |
|---|---|
| Read-aloud starts (⌥⌘C and the other read modes) | started |
| Read-aloud finishes, errors, or is stopped | ended |
| Read-aloud paused / resumed | ended / started |
| A spoken answer (not a read-aloud sentence) starts / ends | started / ended |

Read-aloud sentences report once per session, not per sentence, so the pet does
not flicker between sentences.

## Status, stated plainly

- Verified: the file compiles under python3.11; the diff against the working file
  is additions only; the helper, run against the live pet server, moves the pet to
  `speaking` on started and releases it on ended, and returns in under 1 ms.
- Not verified end to end: pressing ⌥⌘C on selected text and watching the pet react.
  At the time of writing macOS had dropped Python's Accessibility / Input Monitoring
  trust after a restart (the daemon logs "This process is not trusted!"), so the
  hotkey itself was not firing. That is a macOS permission, not this change.
  Re-grant it (System Settings -> Privacy & Security), then test.

## Use

Copy it over Nimba's file (keep a backup), then restart the daemon:

    cp nimba_daemon.py ~/Documents/openklaw/nimba/nimba_daemon.py
    cd ~/Documents/openklaw/nimba && python3.11 nimba_daemon.py
