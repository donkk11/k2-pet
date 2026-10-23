# K2 — a floating desktop companion for Claude Code

A small, borderless, always-on-top pet that sits next to a Claude Code session
and reacts to what's happening in it (idle, running, waiting for permission,
working, etc.). Runs entirely locally — a Node server plus a Python-driven
native window, no cloud dependency, no data leaves your machine.

![Gentleman KK — idle, working, checking, waiting for permission, problem, finished](media/gentleman-states.png)

**[▶ Watch the pet running](https://github.com/donkk11/k2-pet/releases/download/v1.0.0/k2-nkama-pet-story_2026-09-19_23-03-46.mp4)** (44s)

## Install

macOS, with **Node 18+** and **Python 3.9+** already installed:

```bash
git clone https://github.com/donkk11/k2-pet.git
cd k2-pet
bash install.sh
```

That's it. The installer checks your machine, installs the two Python
dependencies, runs a smoke test, and asks whether to connect it to Claude Code
(optional — it backs up `~/.claude/settings.json` first, and
`bash install.sh --uninstall` removes every trace). Use `--dry-run` to see what
it would do without changing anything. Full detail in [`INSTALL.md`](INSTALL.md).

Then: `bash scripts/run.sh` to start, `bash scripts/stop.sh` to stop.

The pet is not Claude-specific — anything can drive it by POSTing JSON events
to `http://127.0.0.1:3043/ingest`. See `nimba-integration/` for a worked example
of wiring it to a completely different tool.

## Build your own pet

The point isn't to use mine. Claude can't generate images, so there's a real
pipeline for making your own character from a reference sheet — the prompt to
feed an image model, then the scripts that cut the result into pose states:

**[`character-generation/PROMPT_TEMPLATE.md`](character-generation/PROMPT_TEMPLATE.md)**

Drop the result in `assets/characters/<your-pet>/` and the pet picks it up.
`blueprint/` has the interaction schematic if you want to understand how the
states connect before you draw anything.

## What's in this folder

- `public/companion.html` + `public/companion.js` — the pet's UI
- `assets/` — character sprite sheets (Gentleman KK, K2 Nkama, Einstein,
  Bruce Lee, BBALL)
- `claude-code-integration/` — the floating-window script and the autostart
  hook that runs it when a Claude Code session begins
- `character-generation/` — the real, separate pipeline for building a new
  character from a reference sheet (see `character-generation/PROMPT_TEMPLATE.md`)
  — a manual, creative process, not part of installing the app itself
- `scripts/` — run, stop and doctor scripts used by the installer

## Internal dev tooling (not the product)

`src/server.mjs` also has an `--record` flag and a `src/app-server-recorder.mjs`
companion used during development to capture and replay real session traces —
these are debugging aids for working on the state-mapping logic itself, not
something installing or running the pet needs. If you're just here to get the
companion running, ignore this section entirely — the Install section above is all you need.
