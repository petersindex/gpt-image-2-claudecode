---
name: gpt-image-2
description: Generate or edit a raster image with OpenAI's gpt-image-2 through the Codex CLI, billed to the ChatGPT subscription rather than an API key. Use whenever the user asks for a photo, illustration, mockup, texture, marketing visual, or an edit to an existing image file, including when they name gpt-image-2, GPT Image 2, or ChatGPT image generation. Not for SVG, charts, diagrams, or anything better written as code.
---

# gpt-image-2

Claude has no image generation of its own. Codex does, through its built-in `image_gen`
tool, billed to the ChatGPT subscription with no `OPENAI_API_KEY`. `scripts/gen.py` is the
bridge: it runs `codex exec`, finds the exact PNG that run made, checks it, copies it to the
destination and logs it. Every render goes through the script.

`gen.py` sits in this skill's base directory (Claude Code names it when the skill loads):

```bash
G="<this skill's base directory>/scripts/gen.py"
```

If `~/.config/gpt-image-2/LOCAL.md` exists, read it now. It holds this user's own rules and
overrides anything below.

## 1. Pick the destination

```bash
python3 "$G" dest <short-slug-of-the-subject>        # add --variants N for a set
```

It prints one or more free paths. Inside a project listed in
`~/.config/gpt-image-2/projects.json` that is the project's image folder; anywhere else,
`$GPT_IMAGE_DIR`, default `~/Pictures/gpt-image-2/`. A folder named `generated/` ignores
itself in git, so raw renders stay out of commits until one is moved into the project's real
asset folder. Use another path only when the user names one; otherwise take what `dest`
prints.

## 2. Announce, then render

In the same message that launches the render, write one markdown image line for **every**
path `dest` printed, so the user knows where each will land (apps that render markdown
images show it once the file exists):

```markdown
![orange traffic cone](/Users/you/Pictures/gpt-image-2/orange-traffic-cone.png)
```

Write each line once; after the command finishes, refer to the image in words.

```bash
python3 "$G" run --out <DEST> --prompt "<PROMPT>"
```

**Set the Bash timeout to 600000 ms.** A render takes a few minutes; the script stops
cleanly at 540 s (`GEN_TIMEOUT`), before Bash would kill it.

The step is done when you have `Read` every path the script printed and looked at it.
Describe only what you saw.

## Edit an existing image

```bash
python3 "$G" run --out <DEST> --edit /abs/path/in.png \
  --prompt "Change only <X>. Keep <Y> and <Z> unchanged"
```

Name the invariants: an edit prompt that only says what to change tends to come back with
the rest redrawn. Repeat `--edit` to pass several reference images.

## Variants

When the user wants options, render a set:

```bash
python3 "$G" dest <slug> --variants 3
python3 "$G" run --out <DEST> --variants 3 --prompt "<PROMPT>"
```

This writes `<slug>-v1.png` onwards, plus a labelled contact sheet at `<DEST>` when Pillow
is installed. Without Pillow, `dest` and `run` print each variant instead of the sheet;
announce and show whatever they print. Capped at 6. Exit code 2 means some variants failed:
stdout lists the ones that worked, stderr names the rest.

Only 3 renders run at once, shared across every `gen.py` on the machine; the rest wait, and
the wait counts against the 540 s budget. Up to 3 variants fit one foreground call. For 4 to
6, run the command with `run_in_background` and `GEN_TIMEOUT=1200` in front of it.

For several **different** images, run separate `gen.py run` calls in parallel, one Bash call
each with its own destination. The shared limit queues them safely.

## Writing the prompt

The built-in tool takes no size, quality or model arguments. Everything goes in the prompt,
so write it like a brief to a photographer or illustrator:

1. **Subject.** What it is, specifically. "A matte black ceramic mug", not "a mug".
2. **Composition.** Framing, angle, where the subject sits, what is in the background.
3. **Light.** Time of day, direction, softness. This does more for realism than any style
   word.
4. **Style or medium.** Photo (lens, depth of field), 3D render, flat illustration,
   watercolour. One style.
5. **Text in the image.** Exact words in quotes, plus where they sit. Keep it short.
6. **Shape.** The aspect ratio in words: "square", "3:2 landscape", "9:16 portrait".
7. **Exclusions.** What must not appear: "no text", "no people", "no logos".

Keep a clear request as the user wrote it; add detail only where a gap would change the
image.

## Model rule

`gpt-image-2` only. If Codex offers `gpt-image-1.5`, `gpt-image-1` or `gpt-image-1-mini`,
refuse it, even for native transparency.

For a transparent background, generate on a flat chroma-key background, then strip it with
the helper Codex ships, `$CODEX_HOME/skills/.system/imagegen/scripts/remove_chroma_key.py`
(`CODEX_HOME` defaults to `~/.codex`). If that file is missing or fails, say so and stop.

GPT Image 2.5 cannot be selected on this route (checked October 2026, codex-cli 0.163.0;
openai/codex issue #43965), and the image's C2PA data cannot tell 2 from 2.5. Never claim an
image came from 2.5.

## The log

Every render appends one line to `gpt-image-log.jsonl` in the destination folder: prompt,
mode, sources, size, codex thread id, the original under `$CODEX_HOME/generated_images/`, the
codex version, and the C2PA fields. Use it to remake an asset or recover a prompt. If the
C2PA version ever changes from plain `gpt-image`, tell the user: the served model may have
changed.

## When it fails

The script exits non-zero and says why on stderr. Report that message as it is. Run
`python3 "$G" doctor` for a setup check that renders nothing, then look the error up in
[TROUBLESHOOTING.md](TROUBLESHOOTING.md).
