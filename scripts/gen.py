#!/usr/bin/env python3
"""Generate or edit images with gpt-image-2 through `codex exec`, billed to ChatGPT.

  gen.py dest <slug> [--variants N]
      Print the next free destination path for <slug>. Inside a project listed in
      ~/.config/gpt-image-2/projects.json it is that project's image folder, otherwise
      $GPT_IMAGE_DIR, default ~/Pictures/gpt-image-2/.

  gen.py run --out PATH --prompt TEXT [--edit SRC ...] [--variants N] [--force]
      Render, verify, copy to PATH, append to gpt-image-log.jsonl beside it.
      With --variants N, writes <stem>-v1..vN.png and, with Pillow, a contact sheet at
      PATH. At most GEN_CONCURRENCY renders (default 3) run at once across every gen.py
      process; GEN_TIMEOUT (default 540 s) is the budget for the whole run.

  gen.py doctor
      Check codex, its login, its helper binary and the optional extras. Renders nothing.

Exit 0 on success, 1 on failure, 2 when only some variants succeeded. Final paths go to
stdout, one per line. Diagnostics go to stderr.
"""

import argparse
import datetime
import fcntl
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

# Where images land outside a listed project. /tmp would be wiped on reboot.
DEFAULT_OUT = Path(os.environ.get("GPT_IMAGE_DIR") or Path.home() / "Pictures" / "gpt-image-2").expanduser()
# codex's working directory, also holds the lock files. Per-user on macOS.
SCRATCH = Path(tempfile.gettempdir()) / "gpt-image-2"
CODEX_HOME = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex").expanduser()
GENERATED_IMAGES = CODEX_HOME / "generated_images"
# Wall-clock budget for one gen.py run, waiting for a slot included. 540 s fits under the
# Bash tool's 600 s ceiling; raise it for background runs.
BUDGET = int(os.environ.get("GEN_TIMEOUT", 540))
# Renders a subscription runs at once. Extra ones queue inside codex and time out, so
# every gen.py process on the machine shares this many slots.
CONCURRENCY = max(1, int(os.environ.get("GEN_CONCURRENCY", 3)))
LOG_NAME = "gpt-image-log.jsonl"
MAX_VARIANTS = 6

# Optional map of project roots to the folder generated images belong in, e.g.
# {"~/code/my-app": "brand/generated"}. It lives outside the skill folder so a plugin
# update or a fresh clone never wipes it.
CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "gpt-image-2"
PROJECTS_FILE = CONFIG_DIR / "projects.json"


def fail(msg, code=1):
    print(f"gen.py: {msg}", file=sys.stderr)
    sys.exit(code)


def load_projects():
    if not PROJECTS_FILE.exists():
        return {}
    try:
        raw = json.loads(PROJECTS_FILE.read_text())
    except json.JSONDecodeError as e:
        fail(f"{PROJECTS_FILE} is not valid JSON: {e}")
    if not isinstance(raw, dict):
        fail(f"{PROJECTS_FILE} must be an object of project root to image folder")
    return {os.path.realpath(os.path.expanduser(root)): sub for root, sub in raw.items()}


def dest_dir(cwd):
    cwd = os.path.realpath(cwd)
    # Longest root first, so a project nested inside another listed root wins.
    for root, sub in sorted(load_projects().items(), key=lambda kv: -len(kv[0])):
        if cwd == root or cwd.startswith(root + os.sep):
            return Path(root) / os.path.expanduser(sub)
    return Path(os.path.realpath(DEFAULT_OUT))


def canon(path):
    """One spelling per file, so checks and locks agree on what "the same path" is."""
    return Path(os.path.realpath(os.path.expanduser(path)))


def variant_path(out, i):
    return out.with_name(f"{out.stem}-v{i}{out.suffix}")


def slugify(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "image"


def has_pillow():
    try:
        import PIL  # noqa: F401
        return True
    except ImportError:
        return False


def cmd_dest(args):
    d = dest_dir(os.getcwd())
    slug = slugify(args.slug)
    n = 1
    while True:
        name = slug if n == 1 else f"{slug}-{n}"
        p = d / f"{name}.png"
        variants = [variant_path(p, i) for i in range(1, args.variants + 1)]
        if not any(t.exists() or in_flight(t) for t in [p] + variants):
            # Without Pillow there is no contact sheet, so offer each variant instead.
            for line in variants if args.variants > 1 and not has_pillow() else [p]:
                print(line)
            return
        n += 1


def prepare_dir(d):
    d.mkdir(parents=True, exist_ok=True)
    # A generated/ folder inside a repo ignores itself, so raw renders never get committed.
    if d.name == "generated" and not (d / ".gitignore").exists():
        (d / ".gitignore").write_text("*\n")


def build_prompt(prompt, edits):
    tail = (
        " Produce exactly one image. Do not copy, move, or post-process the file."
        " When the image exists, reply with the single word DONE."
    )
    if not edits:
        return f"Use the image_gen tool to generate: {prompt}.{tail}"
    if len(edits) == 1:
        return f"Use the image_gen tool to edit the attached image ({edits[0]}): {prompt}.{tail}"
    refs = ", ".join(edits)
    return (f"Use the image_gen tool with the attached reference images ({refs}): "
            f"{prompt}.{tail}")


def acquire_slot(deadline):
    """Lock one of CONCURRENCY slot files, shared by every gen.py process. Returns the
    open file (closing it frees the slot), or None if none came free before deadline.
    The OS drops the lock if the process dies, so a crash never leaks a slot."""
    SCRATCH.mkdir(parents=True, exist_ok=True)
    while True:
        for i in range(CONCURRENCY):
            f = open(SCRATCH / f"slot-{i}.lock", "w")
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return f
            except BlockingIOError:
                f.close()
        if time.monotonic() >= deadline:
            return None
        time.sleep(0.25)


def claim(path):
    """Lock path for this process's lifetime so no other gen.py renders to it meanwhile.
    Returns the lock (keep it referenced), or None if another run holds it."""
    SCRATCH.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha1(str(path).encode()).hexdigest()[:16]
    f = open(SCRATCH / f"claim-{key}.lock", "w")
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return f
    except BlockingIOError:
        f.close()
        return None


def in_flight(path):
    lock = claim(path)
    if lock is None:
        return True
    lock.close()
    return False


def run_codex(text, edits, timeout):
    """Run one codex exec. Returns (thread_id, last agent message, error lines)."""
    # read-only: image_gen saves through codex itself, so the agent never needs to write.
    # Edit sources are attached with -i so the model sees them, not just their paths.
    cmd = ["codex", "exec", "--json", "--skip-git-repo-check", "-s", "read-only"]
    for e in edits:
        cmd += ["-i", e]
    cmd += ["--", text]
    # Own process group, so a timeout also kills the helpers codex spawns.
    proc = subprocess.Popen(cmd, cwd=SCRATCH, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, start_new_session=True)
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, 9)
        proc.communicate()
        return None, None, [f"codex exec timed out after {BUDGET}s (GEN_TIMEOUT)"]

    thread_id, last_msg, errors = None, None, []
    for line in stdout.splitlines():
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        kind = ev.get("type", "")
        if kind == "thread.started":
            thread_id = ev.get("thread_id")
        elif kind in ("error", "turn.failed"):
            errors.append(json.dumps(ev)[:500])
        elif kind == "item.completed" and ev.get("item", {}).get("type") == "agent_message":
            last_msg = ev["item"].get("text")
    if proc.returncode != 0:
        errors.append(f"codex exited {proc.returncode}")
        errors += stderr.strip().splitlines()[-5:]
    return thread_id, last_msg, errors


def image_info(path):
    """Return (width, height) for a valid image, or raise."""
    try:
        from PIL import Image
    except ImportError:
        with open(path, "rb") as f:
            if f.read(8) != b"\x89PNG\r\n\x1a\n":
                raise ValueError("not a PNG")
        return None, None
    with Image.open(path) as im:
        im.verify()
    with Image.open(path) as im:
        return im.size


def provenance(path):
    if not shutil.which("exiftool"):
        return {}
    try:
        out = subprocess.run(["exiftool", "-j", "-a", "-G1", str(path)],
                             capture_output=True, text=True, timeout=30).stdout
        meta = json.loads(out)[0]
    except Exception:
        return {}
    return {k.split(":", 1)[-1]: v for k, v in meta.items()
            if k.startswith("CBOR:") and ("Agent" in k or "Generator" in k) and "Icon" not in k}


def codex_version():
    try:
        return subprocess.run(["codex", "--version"], capture_output=True,
                              text=True, timeout=30).stdout.strip()
    except Exception:
        return None


def render_one(out, prompt, edits, deadline):
    """Render one image to out. Returns (ok, log record or error text)."""
    slot = acquire_slot(deadline)
    remaining = deadline - time.monotonic()
    if slot is None or remaining <= 0:
        if slot:
            slot.close()
        return False, (f"no free codex slot within {BUDGET}s (GEN_TIMEOUT): other renders "
                       f"held all {CONCURRENCY}. Run it again, or in the background with a "
                       "higher GEN_TIMEOUT")
    with slot:
        thread_id, last_msg, errors = run_codex(build_prompt(prompt, edits), edits, remaining)
    if not thread_id:
        return False, "no thread id from codex. " + " | ".join(errors)

    candidates = sorted((GENERATED_IMAGES / thread_id).glob("*.png"),
                        key=lambda p: p.stat().st_mtime)
    if not candidates:
        detail = " | ".join(errors) or f"codex said: {last_msg!r}"
        return False, f"codex finished but produced no image (thread {thread_id}). {detail}"
    original = candidates[-1]

    try:
        width, height = image_info(original)
    except Exception as e:
        return False, f"{original} is not a valid image: {e}"

    prepare_dir(out.parent)
    shutil.copy2(original, out)
    return True, {
        "file": out.name,
        "mode": "edit" if edits else "generate",
        "prompt": prompt,
        "sources": edits,
        "width": width,
        "height": height,
        "thread_id": thread_id,
        "codex_original": str(original),
        "candidates": len(candidates),
        "c2pa": provenance(out),
    }


def contact_sheet(paths, out):
    from PIL import Image, ImageDraw, ImageFont
    thumb_w, pad, label_h = 640, 24, 44
    thumbs = []
    for p in paths:
        with Image.open(p) as im:
            im = im.convert("RGB")
            h = round(im.height * thumb_w / im.width)
            thumbs.append((p, im.resize((thumb_w, h))))
    cols = 2 if len(thumbs) <= 4 else 3
    rows = -(-len(thumbs) // cols)
    cell_h = max(t.height for _, t in thumbs) + label_h
    sheet = Image.new("RGB", (cols * (thumb_w + pad) + pad, rows * (cell_h + pad) + pad), "white")
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default()
    for face in ("/System/Library/Fonts/Helvetica.ttc",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        try:
            font = ImageFont.truetype(face, 28)
            break
        except OSError:
            continue
    for i, (p, t) in enumerate(thumbs):
        x = pad + (i % cols) * (thumb_w + pad)
        y = pad + (i // cols) * (cell_h + pad)
        sheet.paste(t, (x, y))
        draw.text((x, y + t.height + 8), p.stem.rsplit("-", 1)[-1], fill="black", font=font)
    prepare_dir(out.parent)
    sheet.save(out)


def append_log(out_dir, records):
    stamp = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
    version = codex_version()
    with open(out_dir / LOG_NAME, "a") as f:
        for r in records:
            f.write(json.dumps({"time": stamp, "cwd": os.getcwd(), "codex": version, **r}) + "\n")


def cmd_run(args):
    deadline = time.monotonic() + BUDGET
    out = canon(args.out)
    if out.suffix.lower() != ".png":
        fail("--out must end in .png")
    edits = [str(canon(e)) for e in args.edit or []]
    for e in edits:
        if not Path(e).is_file():
            fail(f"edit source not found: {e}")
    if args.variants > MAX_VARIANTS:
        fail(f"--variants is capped at {MAX_VARIANTS}")

    targets = [out] if args.variants <= 1 else [variant_path(out, i) for i in range(1, args.variants + 1)]
    claims = []
    for t in dict.fromkeys(targets + [out]):
        lock = claim(t)
        if lock is None:
            fail(f"{t} is already being rendered by another gen.py run. Pick another name")
        claims.append(lock)
        if t.exists() and not args.force:
            fail(f"{t} already exists (pass --force to overwrite)")

    if len(targets) == 1:
        ok, result = render_one(out, args.prompt, edits, deadline)
        if not ok:
            fail(result)
        append_log(out.parent, [result])
        print(out)
        return

    with ThreadPoolExecutor(len(targets)) as pool:
        results = list(pool.map(lambda t: render_one(t, args.prompt, edits, deadline), targets))

    done = [t for t, (ok, _) in zip(targets, results) if ok]
    for t, (ok, r) in zip(targets, results):
        if not ok:
            print(f"gen.py: {t.name} failed: {r}", file=sys.stderr)
    if not done:
        fail("every variant failed")
    append_log(out.parent, [r for ok, r in results if ok])
    if has_pillow():
        contact_sheet(done, out)
        print(out)
    else:
        print("gen.py: Pillow is not installed, so no contact sheet. Show each variant.",
              file=sys.stderr)
    for t in done:
        print(t)
    if len(done) < len(targets):
        sys.exit(2)


def cmd_doctor(args):
    """Check the setup without spending a render. Exit 1 if anything would stop one."""
    failures = 0

    def report(level, msg):
        nonlocal failures
        failures += level == "FAIL"
        print(f"{level:<4}  {msg}")

    codex = shutil.which("codex")
    if not codex:
        report("FAIL", "codex is not on PATH. Install the Codex CLI: https://github.com/openai/codex")
    else:
        report("ok", f"{codex_version() or 'codex'} at {codex}")
        try:
            login = subprocess.run(["codex", "login", "status"], capture_output=True,
                                   text=True, timeout=30)
            logged_in = login.returncode == 0
        except Exception:
            logged_in = False
        if logged_in:
            report("ok", (login.stdout + login.stderr).strip() or "logged in")
        else:
            report("FAIL", "codex is not logged in. Run: codex login (sign in with ChatGPT)")

        # image_gen needs this helper beside the codex on PATH, even when that is a symlink.
        here = Path(codex).parent / "codex-code-mode-host"
        if here.exists():
            report("ok", f"codex-code-mode-host beside codex ({here.parent})")
        else:
            real = Path(os.path.realpath(codex)).parent / "codex-code-mode-host"
            source = real if real.exists() else Path("<dir holding codex-code-mode-host>")
            report("FAIL", "codex-code-mode-host is not beside codex, so image_gen cannot start. "
                           f"Fix: ln -sf '{source}' '{here}'")

    if GENERATED_IMAGES.parent.is_dir():
        report("ok", f"codex home {CODEX_HOME}")
    else:
        report("FAIL", f"codex home {CODEX_HOME} does not exist. Run codex once, or fix CODEX_HOME")

    if PROJECTS_FILE.exists():
        try:
            projects = json.loads(PROJECTS_FILE.read_text())
            if not isinstance(projects, dict):
                raise ValueError("expected an object of project root to image folder")
            report("ok", f"{PROJECTS_FILE} maps {len(projects)} project(s)")
            for root in projects:
                if not Path(os.path.expanduser(root)).is_dir():
                    report("warn", f"projects.json lists {root}, which does not exist")
        except ValueError as e:
            report("FAIL", f"{PROJECTS_FILE} is not valid: {e}")
    else:
        report("ok", f"no projects.json, images go to {DEFAULT_OUT}")

    if has_pillow():
        report("ok", "Pillow installed (contact sheets, image checks)")
    else:
        report("warn", f"Pillow not installed for {sys.executable}: variants come without a "
                       f"contact sheet. Fix: {sys.executable} -m pip install pillow")
    if shutil.which("exiftool"):
        report("ok", "exiftool installed (C2PA provenance in the log)")
    else:
        report("warn", "exiftool not installed: the log has no C2PA provenance")
    chroma = CODEX_HOME / "skills" / ".system" / "imagegen" / "scripts" / "remove_chroma_key.py"
    if not chroma.exists():
        report("warn", f"{chroma} missing: transparent backgrounds are unavailable")

    print("All set." if not failures else f"{failures} problem(s) will stop a render.")
    sys.exit(1 if failures else 0)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("dest", help="print the next free destination path")
    d.add_argument("slug")
    d.add_argument("--variants", type=int, default=1)
    d.set_defaults(func=cmd_dest)

    r = sub.add_parser("run", help="render an image")
    r.add_argument("--out", required=True)
    r.add_argument("--prompt", required=True)
    r.add_argument("--edit", action="append", help="source image to edit; repeat for references")
    r.add_argument("--variants", type=int, default=1)
    r.add_argument("--force", action="store_true")
    r.set_defaults(func=cmd_run)

    sub.add_parser("doctor", help="check the setup without rendering").set_defaults(func=cmd_doctor)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
