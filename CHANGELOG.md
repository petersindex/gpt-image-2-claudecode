# Changelog

## 1.0.1 (26 October 2026)

- Works in the Claude desktop app even when it can't see your terminal's PATH: the skill now
  finds Codex (and exiftool) in the usual install folders on its own.
- `doctor` says where it found Codex.

## 1.0.0 (26 October 2026)

First public release.

- Ask Claude Code for an image and it writes the brief, renders it with gpt-image-2 through
  the Codex CLI, looks at the result and tells you where it saved it. No API key; it uses
  your ChatGPT plan.
- Edit an existing image, or combine several reference images.
- Ask for options and get up to 6 variants plus a labelled contact sheet.
- Run as many requests as you like: only 3 render at once and the rest wait their turn.
- Images go to `~/Pictures/gpt-image-2/`, or to each project's own image folder when you set
  one up.
- Every image is logged with its prompt, so you can remake or trace it later.
- `gen.py doctor` checks your setup in seconds without spending a render.
- Install as a Claude Code plugin, or clone it as a plain skill.
