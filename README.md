# gpt-image-2 for Claude Code

**Claude can't make images. Codex can, on the ChatGPT plan you already pay for.**

A Claude Code skill that lets Claude generate and edit images with OpenAI's gpt-image-2 by
driving the Codex CLI. Ask for a photo, a mockup, a texture or an edit to an existing file,
and Claude writes the prompt, runs the render, checks the PNG and shows it to you.

No `OPENAI_API_KEY`. Renders count against your ChatGPT subscription's Codex usage.

```
> make me a hero shot of a matte black ceramic mug on a concrete bench, morning light, 3:2

![matte black mug](/tmp/gpt-image-2/matte-black-mug.png)
```

## What it does

- **Generate** from a written brief.
- **Edit** an existing image, or combine several reference images.
- **Variants**: up to 6 renders in parallel, plus a labelled contact sheet.
- **Finds the exact file** each run produced (by Codex thread id, never by "newest file").
- **Logs every render** to `gpt-image-log.jsonl` next to the image: prompt, sources, size,
  thread id and C2PA provenance, so you can remake or trace any asset.
- **Per-project output folders**: renders land in your project's image folder when you're
  working inside it, and `/tmp/gpt-image-2/` otherwise.

## Requirements

- [Codex CLI](https://github.com/openai/codex), signed in with a ChatGPT account
  (`codex login`).
- Python 3.9+.
- Optional: [Pillow](https://pypi.org/project/pillow/) for image validation and variant
  contact sheets, and `exiftool` for C2PA provenance in the log. The skill runs Python with
  `-I`, which skips user site-packages, so install Pillow where the system `python3` can see
  it.

## Install

```bash
git clone https://github.com/petersindex/gpt-image-2-claudecode ~/.claude/skills/gpt-image-2
```

Start a new Claude Code session. Ask for an image, or type `/gpt-image-2`.

### Optional: project output folders

Copy `projects.example.json` to `projects.json` in the same folder and map each project
root to the folder its images belong in:

```json
{
  "~/code/my-app": "brand/generated"
}
```

A folder named `generated/` gets its own `.gitignore`, so raw renders never get committed.

## Good to know

- **It depends on Codex internals.** Where Codex saves images and how `image_gen` is wired
  are not documented APIs. A Codex update can break this. If it does, open an issue.
- **gpt-image-2 only.** Codex's built-in tool has no model choice, and the skill refuses to
  fall back to older image models.
- **About 3 renders at once.** More than that queue up in Codex and tend to time out.
- **Transparent backgrounds** are done with a chroma key and Codex's own
  `remove_chroma_key.py`, not a model switch.

Troubleshooting for every known error is in [SKILL.md](SKILL.md#when-it-fails).

## Licence

MIT
