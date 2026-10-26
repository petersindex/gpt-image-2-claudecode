---
name: gpt-image-2
description: Generate or edit a raster image with OpenAI's gpt-image-2 through the Codex CLI, billed to the ChatGPT subscription rather than an API key. Use whenever the user asks for a photo, illustration, mockup, texture, marketing visual, or an edit to an existing image file, including when they name gpt-image-2, GPT Image 2, or ChatGPT image generation. Not for SVG, charts, diagrams, or anything better written as code.
---

# gpt-image-2

Claude has no image generation of its own. Codex does, through its built-in `image_gen`
tool, and it bills the ChatGPT subscription with no `OPENAI_API_KEY`. `scripts/gen.py`
is the bridge: it runs `codex exec`, finds the exact PNG that run made, checks it, copies
it to the destination and logs it. Always go through the script, never raw `codex exec`.

```bash
G=~/.claude/skills/gpt-image-2/scripts/gen.py
```

## 1. Pick the destination

```bash
python3 -I $G dest <short-slug-of-the-subject>        # add --variants N for a set
```

It prints the next free path. Inside a project listed in `projects.json` (beside this
file, see `projects.example.json`) that is `<project>/<image folder>/<slug>.png`; anywhere
else, `/tmp/gpt-image-2/`. A folder named `generated/` ignores itself in git, so raw
renders never get committed: when one ships, move it into the project's real asset folder.
Use a different path only when the user names one. Never ask the user for a path.

## 2. Announce the image, then render

Tell the user the destination path in the same message that launches the render, so they
know where it will land:

```markdown
![orange traffic cone](/tmp/gpt-image-2/orange-traffic-cone.png)
```

One line per image, never repeated after the command finishes.

```bash
python3 -I $G run --out <DEST> --prompt "<PROMPT>"
```

**Set the Bash timeout to 600000 ms.** A render takes a few minutes and the script gives up
cleanly at 540 s, before Bash would kill it.

Then `Read` the destination to see the result before describing it. Never describe an
image you have not looked at.

## Edit an existing image

```bash
python3 -I $G run --out <DEST> --edit /abs/path/in.png \
  --prompt "Change only <X>. Keep <Y> and <Z> unchanged"
```

Name the invariants. An edit prompt that only says what to change tends to come back with
the rest redrawn. Repeat `--edit` to pass several reference images.

## Variants

When the user wants options, render a set and show one contact sheet:

```bash
python3 -I $G dest <slug> --variants 4
python3 -I $G run --out <DEST> --variants 4 --prompt "<PROMPT>"
```

This writes `<slug>-v1.png` to `<slug>-v4.png` in parallel, plus a labelled contact sheet
at `<DEST>`. Announce only `<DEST>`. Capped at 6. The contact sheet needs Pillow. Exit code
2 means some variants failed: the sheet shows the ones that worked and stderr names the
rest.

For several **different** images, run separate `gen.py run` calls in parallel, one Bash call
each with its own destination. Serialising them multiplies a multi-minute wait.

## Writing the prompt

The built-in tool takes no size, quality or model arguments. Everything goes in the
prompt, so write it like a brief to a photographer or illustrator:

1. **Subject.** What it is, specifically. "A matte black ceramic mug", not "a mug".
2. **Composition.** Framing, angle, where the subject sits, what is in the background.
3. **Light.** Time of day, direction, softness. This does more for realism than any style
   word.
4. **Style or medium.** Photo (lens, depth of field), 3D render, flat illustration,
   watercolour. One style, not a stack of them.
5. **Text in the image.** Exact words in quotes, plus where they sit. Keep it short.
6. **Shape.** Say the aspect ratio in words: "square", "3:2 landscape", "9:16 portrait".
7. **Exclusions.** What must not appear: "no text", "no people", "no logos".

Do not pad a clear request with adjectives. Add detail only where the user left a gap that
would change the image.

## Model rule

`gpt-image-2` only. Never accept a fallback to `gpt-image-1.5`, `gpt-image-1`, or
`gpt-image-1-mini`, not even for native transparency, the one capability that tempts it.

At the time of writing (October 2026, codex-cli 0.163.0), GPT Image 2.5
(`gpt-image-2.5-sunburst`, `gpt-image-2.5-flare`) cannot be selected on this route. The
built-in `image_gen` schema has no model field, Codex hardcodes `gpt-image-2`, and the
backend rewrites any requested model (openai/codex issue #43965). The image's C2PA data only
says `ChatGPT` / `gpt-image`, so it cannot tell 2 from 2.5 either. 2.5 is only reachable
through the paid Images API with an `OPENAI_API_KEY`. Never claim an image came from 2.5.

For a transparent background: generate on a flat chroma-key background, then strip it with
the helper Codex ships in its bundled imagegen skill,
`~/.codex/skills/.system/imagegen/scripts/remove_chroma_key.py`. If that file is missing or
fails, say so and stop rather than switching models.

## The log

Every render appends one line to `gpt-image-log.jsonl` in the destination folder: prompt,
mode, sources, size, codex thread id, the original under `~/.codex/generated_images/`, the
codex version, and the C2PA software agent fields. Use it to remake an asset or recover a
prompt. If the C2PA version ever changes from plain `gpt-image`, that is the first sign the
served model changed.

## How the script finds the image

`codex exec --json` emits a `thread.started` event whose `thread_id` is the folder name the
render lands in: `~/.codex/generated_images/<thread_id>/`. The script reads it from there,
so it never guesses by modification time and never depends on codex copying the file.
(Asking codex to copy fails silently outside its working directory: exit 0, no path.)

## When it fails

The script exits non-zero and says why on stderr. Report that, do not paper over it.

- `failed to spawn code-mode host ... codex-code-mode-host`: `image_gen` routes through a
  helper binary that must sit **beside** the `codex` binary being run. If `codex` on PATH is
  a symlink, the helper needs its own symlink in the same directory. Find where
  `codex-code-mode-host` lives (`/Applications/ChatGPT.app/Contents/Resources/` on macOS
  with the desktop app, or `~/.codex/packages/standalone/current/bin/` for the standalone
  install) and link it next to `codex`:
  ```bash
  ln -sf <dir>/codex-code-mode-host "$(dirname "$(command -v codex)")/codex-code-mode-host"
  ```
- `not supported when using Codex with a ChatGPT account`: the account's plan does not
  serve that model. Report it, do not silently pick another.
- `codex finished but produced no image`: codex declined or misread the request. Its last
  message is in the error. Rephrase the prompt and run again.
- `timed out after 540s`: run it once more. If it times out twice, report it.
- **Only about 3 renders run at once** on a subscription (observed October 2026). Extra
  jobs wait in codex's queue, and the 540 s clock includes that wait, so a 4th-at-once job
  usually times out. Batch 3 at a time. For a background queue that must wait its turn, set
  `GEN_TIMEOUT=1200` in the environment (only outside a foreground Bash call).
