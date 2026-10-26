# gpt-image-2 for Claude Code

**Claude can't make images. Codex can, on the ChatGPT plan you already pay for.**

A Claude Code skill that lets Claude generate and edit images with OpenAI's gpt-image-2 by
driving the Codex CLI. Ask for a photo, a mockup, a texture or an edit to an existing file.
Claude writes the prompt, runs the render, looks at the result and tells you where it
landed.

No `OPENAI_API_KEY`. Renders count against your ChatGPT subscription's Codex usage.

| `make me a hero shot of a matte black mug on a concrete bench, morning light, 3:2` | `now make it a glossy forest-green glaze, keep everything else` |
| --- | --- |
| ![A matte black mug on a concrete bench in morning light](docs/matte-black-mug.jpg) | ![The same mug, now glossy green, everything else unchanged](docs/mug-green-glaze.jpg) |

Both images came out of this skill in about 40 seconds each, unretouched apart from resizing
for this page.

## What it does

- **Generate** from a written brief.
- **Edit** an existing image, or combine several reference images.
- **Variants**: up to 6 renders of one brief, plus a labelled contact sheet.
- **Queues safely**: only 3 renders run at once across every session, so parallel requests
  wait their turn instead of timing out.
- **Logs every render** to `gpt-image-log.jsonl` next to the image: prompt, sources, size,
  Codex thread id and C2PA provenance, so you can remake or trace any asset.
- **Per-project output folders**: renders land in your project's image folder when you're
  working inside it, and `~/Pictures/gpt-image-2/` otherwise.

Where the chat renders markdown images you see the image inline; in the terminal you get
its path.

## Where it works

Anywhere Claude Code runs on your own machine: the terminal, the **Code** tab of the Claude
desktop app (local sessions), and the VS Code and JetBrains extensions. It does not work in
claude.ai chat or Cowork, which run in Anthropic's cloud where your Codex login isn't.

## Requirements

- macOS or Linux.
- [Codex CLI](https://github.com/openai/codex), signed in with a ChatGPT account
  (`codex login`).
- Python 3.9+.
- Optional: [Pillow](https://pypi.org/project/pillow/) for variant contact sheets and image
  checks, and `exiftool` for C2PA provenance in the log. Everything else works without
  them.

## Install

As a plugin, so you get fixes with `/plugin update`:

```
/plugin install gpt-image-2 --marketplace petersindex/gpt-image-2-claudecode
```

On Claude Code before 2.1.275, add the marketplace first:

```
/plugin marketplace add petersindex/gpt-image-2-claudecode
/plugin install gpt-image-2@petersindex
```

Or as a plain skill:

```bash
git clone https://github.com/petersindex/gpt-image-2-claudecode ~/.claude/skills/gpt-image-2
```

Then check your setup. This renders nothing and prints the fix for anything missing:

```bash
python3 ~/.claude/skills/gpt-image-2/scripts/gen.py doctor
```

(For the plugin install, Claude can run it for you: ask it to "run the gpt-image-2 doctor".)

Start a new Claude Code session and ask for an image.

### Optional: project output folders

Create `~/.config/gpt-image-2/projects.json` and map each project root to the folder its
images belong in:

```json
{
  "~/code/my-app": "brand/generated"
}
```

A folder named `generated/` gets its own `.gitignore`, so raw renders never get committed.

### Optional: your own rules

Anything in `~/.config/gpt-image-2/LOCAL.md` is read every time the skill runs and wins over
the defaults: house style, naming, where finished assets go. It lives outside the skill, so
updates never overwrite it.

## Good to know

- **It depends on Codex internals.** Where Codex saves images and how `image_gen` is wired
  are not documented APIs. A Codex update can break this. If it does, open an issue.
- **gpt-image-2 only.** Codex's built-in tool has no model choice, and the skill refuses to
  fall back to older image models.
- **Transparent backgrounds** are done with a chroma key and Codex's own
  `remove_chroma_key.py`, not a model switch.
- **How it finds the image**: `codex exec --json` reports a thread id, and Codex saves that
  run's render under `$CODEX_HOME/generated_images/<thread_id>/`. The script reads it from
  there, so it never guesses by "newest file". Codex runs in a read-only sandbox.

Errors and settings: [TROUBLESHOOTING.md](TROUBLESHOOTING.md).

## Contributing

Issues and pull requests are welcome; questions and show-and-tell go in
[Discussions](https://github.com/petersindex/gpt-image-2-claudecode/discussions). See
[CONTRIBUTING.md](CONTRIBUTING.md). Changes are listed in [CHANGELOG.md](CHANGELOG.md).

## Licence

MIT. An independent project, not affiliated with or endorsed by OpenAI or Anthropic.
gpt-image-2, ChatGPT and Codex are OpenAI's; Claude and Claude Code are Anthropic's.
