#!/usr/bin/env python3
"""Generate or edit images with gpt-image-2 through `codex exec`, billed to ChatGPT.

  gen.py dest <slug> [--variants N]
      Print the next free destination path for <slug>. Inside a project listed in
      projects.json it is that project's image folder, otherwise /tmp/gpt-image-2/.

  gen.py run --out PATH --prompt TEXT [--edit SRC ...] [--variants N] [--force]
      Render, verify, copy to PATH, append to gpt-image-log.jsonl beside it.
      With --variants N, writes <stem>-v1..vN.png and a contact sheet at PATH.

Exit 0 on success, 1 on failure, 2 when only some variants succeeded. Final paths go to
stdout, one per line. Diagnostics go to stderr.
"""

import argparse
import datetime
import json
import os
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

WORKDIR = Path("/tmp/gpt-image-2")
GENERATED_IMAGES = Path.home() / ".codex" / "generated_images"
CODEX_TIMEOUT = int(os.environ.get("GEN_TIMEOUT", 540))  # under the Bash tool's 600 s ceiling; raise GEN_TIMEOUT for background queues
LOG_NAME = "gpt-image-log.jsonl"
MAX_VARIANTS = 6

# Optional map of project roots to the folder generated images belong in, kept beside
# SKILL.md. See projects.example.json.
PROJECTS_FILE = Path(__file__).resolve().parent.parent / "projects.json"


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
    return {os.path.realpath(os.path.expanduser(root)): sub for root, sub in raw.items()}


def dest_dir(cwd):
    cwd = os.path.realpath(cwd)
    for root, sub in load_projects().items():
        if cwd == root or cwd.startswith(root + os.sep):
            return Path(root) / sub
    return WORKDIR


def variant_path(out, i):
    return out.with_name(f"{out.stem}-v{i}{out.suffix}")


def cmd_dest(args):
    d = dest_dir(os.getcwd())
    n = 1
    while True:
        name = args.slug if n == 1 else f"{args.slug}-{n}"
        p = d / f"{name}.png"
        taken = [p] + [variant_path(p, i) for i in range(1, args.variants + 1)]
        if not any(t.exists() for t in taken):
            print(p)
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
        return f"Use the image_gen tool to edit {edits[0]}: {prompt}.{tail}"
    refs = ", ".join(edits)
    return f"Use the image_gen tool with these reference images: {refs}. {prompt}.{tail}"


def run_codex(text):
    """Run one codex exec. Returns (thread_id, last agent message, error lines)."""
    WORKDIR.mkdir(parents=True, exist_ok=True)
    cmd = ["codex", "exec", "--json", "--skip-git-repo-check", "-s", "workspace-write", text]
    try:
        proc = subprocess.run(
            cmd, cwd=WORKDIR, stdin=subprocess.DEVNULL, capture_output=True,
            text=True, timeout=CODEX_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return None, None, [f"codex exec timed out after {CODEX_TIMEOUT}s"]

    thread_id, last_msg, errors = None, None, []
    for line in proc.stdout.splitlines():
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
        errors += proc.stderr.strip().splitlines()[-5:]
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


def render_one(out, prompt, edits, force):
    """Render one image to out. Returns (ok, log record or error text)."""
    if out.exists() and not force:
        return False, f"{out} already exists (pass --force to overwrite)"
    thread_id, last_msg, errors = run_codex(build_prompt(prompt, edits))
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
    out = Path(args.out).expanduser().resolve()
    if out.suffix.lower() != ".png":
        fail("--out must end in .png")
    edits = [str(Path(e).expanduser().resolve()) for e in args.edit or []]
    for e in edits:
        if not Path(e).is_file():
            fail(f"edit source not found: {e}")

    if args.variants <= 1:
        ok, result = render_one(out, args.prompt, edits, args.force)
        if not ok:
            fail(result)
        append_log(out.parent, [result])
        print(out)
        return

    if args.variants > MAX_VARIANTS:
        fail(f"--variants is capped at {MAX_VARIANTS}")
    if out.exists() and not args.force:
        fail(f"{out} already exists (pass --force to overwrite)")
    targets = [variant_path(out, i) for i in range(1, args.variants + 1)]
    with ThreadPoolExecutor(len(targets)) as pool:
        results = list(pool.map(lambda t: render_one(t, args.prompt, edits, args.force), targets))

    done = [t for t, (ok, _) in zip(targets, results) if ok]
    for t, (ok, r) in zip(targets, results):
        if not ok:
            print(f"gen.py: {t.name} failed: {r}", file=sys.stderr)
    if not done:
        fail("every variant failed")
    append_log(out.parent, [r for ok, r in results if ok])
    contact_sheet(done, out)
    print(out)
    for t in done:
        print(t)
    if len(done) < len(targets):
        sys.exit(2)


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

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
