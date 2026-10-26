# Contributing

Issues and pull requests are welcome. For questions, prompt tips or images you made, use
[Discussions](https://github.com/petersindex/gpt-image-2-claudecode/discussions).

## Reporting a problem

Run `python3 scripts/gen.py doctor` and paste its output into the bug report. It checks the
whole setup and renders nothing.

## Changing the code

- `scripts/gen.py` is one file on the Python 3.9+ standard library. Keep it that way: no
  required dependencies, so installing stays one command. Pillow and exiftool stay optional.
- Every change in behaviour comes with a test in `tests/test_gen.py`. The tests run `gen.py`
  as a command against `tests/fake_codex.py`, so they cost no renders:

  ```bash
  python3 -m unittest discover -s tests
  ```

- If you change how codex is called, also run one real render and say so in the pull
  request. The fake codex can't tell you whether the real one still behaves.
- macOS and Linux only for now (the script uses `fcntl` locks).
- CI runs the tests on macOS and Linux with Python 3.9 and 3.13.

## Writing the docs

`SKILL.md` is read by Claude on every run, so keep it short and put rare cases in
`TROUBLESHOOTING.md`. `README.md` is for people. The changelog describes what users notice,
in plain English.
