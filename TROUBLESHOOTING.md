# Troubleshooting

Start with `python3 scripts/gen.py doctor`. It checks everything below that can be checked
without spending a render, and prints the fix for each problem it finds.

- **`failed to spawn code-mode host ... codex-code-mode-host`**: `image_gen` routes through a
  helper binary that must sit **beside** the `codex` binary on PATH. If `codex` on PATH is a
  symlink, the helper needs its own symlink in the same directory. It lives in
  `/Applications/ChatGPT.app/Contents/Resources/` with the macOS desktop app, or
  `~/.codex/packages/standalone/current/bin/` for the standalone install. `doctor` prints
  the exact `ln -sf` command for your machine.
- **`not supported when using Codex with a ChatGPT account`**: the account's plan does not
  serve that model. Report it; never pick another model.
- **`codex finished but produced no image`**: codex declined or misread the request. Its last
  message is in the error. Rephrase the prompt and run again.
- **`codex exec timed out`**: run it once more. If it times out twice, report it.
- **`no free codex slot`**: other renders held all 3 slots for the whole budget. Run it again
  when they finish, or in the background with `GEN_TIMEOUT=1200`.
- **`already being rendered by another gen.py run`**: two renders aimed at the same file.
  Run `dest` again for a fresh name.
- **`already exists`**: the destination is taken. Run `dest` for a fresh name, or pass
  `--force` when the user wants it replaced.
- **No contact sheet for variants**: Pillow is not installed for the `python3` that runs the
  script. `doctor` prints the install command. Each variant still renders.

## Settings

| Variable | Default | What it does |
| --- | --- | --- |
| `GPT_IMAGE_DIR` | `~/Pictures/gpt-image-2` | Where images land outside a listed project |
| `GEN_TIMEOUT` | `540` | Seconds for a whole `gen.py run`, waiting included |
| `GEN_CONCURRENCY` | `3` | Renders running at once across every `gen.py` process |
| `CODEX_HOME` | `~/.codex` | Codex's own folder, where it saves renders |
| `XDG_CONFIG_HOME` | `~/.config` | Parent of the `gpt-image-2/` config folder |
