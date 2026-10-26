"""Tests for scripts/gen.py, driven through its command line against a fake codex.

Run with:  python3 -m unittest discover -s tests
"""

import json
import os
import shutil
import site
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
GEN = REPO / "scripts" / "gen.py"
FAKE = Path(__file__).resolve().parent / "fake_codex.py"


class Sandbox:
    """A throwaway HOME with a fake codex on PATH."""

    def __init__(self):
        self.root = Path(os.path.realpath(tempfile.mkdtemp(prefix="gen-test-")))
        self.home = self.root / "home"
        self.bin = self.root / "bin"
        self.home.mkdir()
        self.bin.mkdir()
        codex = self.bin / "codex"
        codex.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{FAKE}" "$@"\n')
        codex.chmod(0o755)
        self.log = self.root / "codex-calls.jsonl"
        self.env = {
            k: v for k, v in os.environ.items()
            if k not in ("CODEX_HOME", "GPT_IMAGE_DIR", "XDG_CONFIG_HOME",
                         "GEN_TIMEOUT", "GEN_CONCURRENCY") and not k.startswith("FAKE_CODEX")
        }
        self.env.update({
            "HOME": str(self.home),
            "PATH": f"{self.bin}{os.pathsep}{os.environ['PATH']}",
            "TMPDIR": str(self.root / "tmp"),
            "FAKE_CODEX_LOG": str(self.log),
            # Keep the real user site-packages visible despite the new HOME, so a Pillow
            # installed with pip --user is still found.
            "PYTHONUSERBASE": site.getuserbase(),
        })
        (self.root / "tmp").mkdir()

    def projects(self, mapping):
        config = self.home / ".config" / "gpt-image-2"
        config.mkdir(parents=True, exist_ok=True)
        (config / "projects.json").write_text(json.dumps(mapping))

    def gen(self, *args, cwd=None, python_flags=(), timeout=60, **env):
        return subprocess.run(
            [sys.executable, *python_flags, str(GEN), *args],
            cwd=cwd or self.home, env={**self.env, **env},
            capture_output=True, text=True, timeout=timeout,
        )

    def spawn(self, *args, **env):
        return subprocess.Popen(
            [sys.executable, str(GEN), *args], cwd=self.home, env={**self.env, **env},
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )

    def codex_calls(self):
        if not self.log.exists():
            return []
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def cleanup(self):
        shutil.rmtree(self.root, ignore_errors=True)


class GenTest(unittest.TestCase):
    def setUp(self):
        self.s = Sandbox()
        self.addCleanup(self.s.cleanup)

    def lines(self, result):
        return [Path(line) for line in result.stdout.splitlines()]


class DestTest(GenTest):
    def test_inside_nested_projects_the_deepest_root_wins(self):
        app = self.s.home / "code" / "app"
        (app / "src").mkdir(parents=True)
        self.s.projects({"~/code": "outer/generated", "~/code/app": "inner/generated"})

        r = self.s.gen("dest", "mug", cwd=app / "src")

        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.lines(r), [app / "inner" / "generated" / "mug.png"])

    def test_outside_projects_images_go_to_pictures_not_tmp(self):
        r = self.s.gen("dest", "mug")

        self.assertEqual(self.lines(r), [self.s.home / "Pictures" / "gpt-image-2" / "mug.png"])

    def test_gpt_image_dir_overrides_the_default_folder(self):
        r = self.s.gen("dest", "mug", GPT_IMAGE_DIR=str(self.s.root / "renders"))

        self.assertEqual(self.lines(r), [self.s.root / "renders" / "mug.png"])

    def test_a_slug_cannot_escape_the_folder(self):
        r = self.s.gen("dest", "../../Matte Black Mug!")

        self.assertEqual(self.lines(r),
                         [self.s.home / "Pictures" / "gpt-image-2" / "matte-black-mug.png"])


class RunTest(GenTest):
    def out(self, name="mug.png"):
        return self.s.home / "Pictures" / "gpt-image-2" / name

    def test_render_lands_at_out_and_is_logged(self):
        r = self.s.gen("run", "--out", str(self.out()), "--prompt", "a mug")

        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.lines(r), [self.out()])
        self.assertTrue(self.out().read_bytes().startswith(b"\x89PNG"))
        record = json.loads((self.out().parent / "gpt-image-log.jsonl").read_text())
        self.assertEqual((record["file"], record["prompt"]), ("mug.png", "a mug"))

    def test_codex_home_is_honoured(self):
        codex_home = self.s.root / "elsewhere"

        r = self.s.gen("run", "--out", str(self.out()), "--prompt", "a mug",
                       CODEX_HOME=str(codex_home))

        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(str(codex_home) in
                        json.loads((self.out().parent / "gpt-image-log.jsonl").read_text())["codex_original"])

    def test_codex_runs_read_only(self):
        self.s.gen("run", "--out", str(self.out()), "--prompt", "a mug")

        argv = self.s.codex_calls()[0]["argv"]
        self.assertEqual(argv[argv.index("-s") + 1], "read-only")

    def test_edit_sources_are_attached_and_the_prompt_comes_last(self):
        a, b = self.s.root / "a.png", self.s.root / "b.png"
        a.write_bytes(b"\x89PNG\r\n\x1a\n")
        b.write_bytes(b"\x89PNG\r\n\x1a\n")

        r = self.s.gen("run", "--out", str(self.out()), "--prompt", "blend them",
                       "--edit", str(a), "--edit", str(b))

        self.assertEqual(r.returncode, 0, r.stderr)
        argv = self.s.codex_calls()[0]["argv"]
        self.assertEqual([argv[i + 1] for i, v in enumerate(argv) if v == "-i"], [str(a), str(b)])
        self.assertEqual(argv[-2], "--")
        self.assertIn("blend them", argv[-1])

    def test_no_image_is_a_clear_failure(self):
        r = self.s.gen("run", "--out", str(self.out()), "--prompt", "a mug",
                       FAKE_CODEX_NO_IMAGE="1")

        self.assertEqual(r.returncode, 1)
        self.assertIn("produced no image", r.stderr)
        self.assertIn("I can't make that.", r.stderr)
        self.assertFalse(self.out().exists())


class ConcurrencyTest(GenTest):
    """Only a few renders run at once on a subscription; extra ones must wait, not pile in."""

    def setUp(self):
        super().setUp()
        self.running = self.s.root / "running"
        self.running.mkdir()
        self.knobs = {"FAKE_CODEX_RUNNING": str(self.running), "FAKE_CODEX_SLEEP": "0.6",
                      "GEN_CONCURRENCY": "2"}

    def peak(self):
        return max(int(n) for n in self.running.with_suffix(".peaks").read_text().split())

    def out(self, name):
        return str(self.s.home / "Pictures" / "gpt-image-2" / name)

    def test_variants_never_exceed_the_cap(self):
        r = self.s.gen("run", "--out", self.out("mug.png"), "--prompt", "a mug",
                       "--variants", "5", **self.knobs)

        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len(self.s.codex_calls()), 5)
        self.assertEqual(self.peak(), 2)

    def test_separate_runs_share_the_cap(self):
        procs = [self.s.spawn("run", "--out", self.out(f"{n}.png"), "--prompt", n,
                              "--variants", "2", **self.knobs) for n in ("cup", "jug")]
        for p in procs:
            _, err = p.communicate(timeout=60)
            self.assertEqual(p.returncode, 0, err)

        self.assertEqual(len(self.s.codex_calls()), 4)
        self.assertEqual(self.peak(), 2)

    def test_gen_timeout_is_one_budget_for_the_whole_run(self):
        r = self.s.gen("run", "--out", self.out("mug.png"), "--prompt", "a mug",
                       "--variants", "3", GEN_TIMEOUT="2",
                       **{**self.knobs, "GEN_CONCURRENCY": "1", "FAKE_CODEX_SLEEP": "1.2"})

        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertEqual(len(self.lines(r)), 2)  # the sheet plus the one variant that fit
        self.assertIn("no free codex slot", r.stderr)


class InFlightTest(GenTest):
    """A destination is claimed for the whole render, not only once the file exists."""

    def setUp(self):
        super().setUp()
        self.out = self.s.home / "Pictures" / "gpt-image-2" / "mug.png"
        self.first = self.s.spawn("run", "--out", str(self.out), "--prompt", "a mug",
                                  FAKE_CODEX_SLEEP="2")
        self.addCleanup(self.first.communicate)
        for _ in range(100):  # wait until the first render is under way
            if self.s.codex_calls():
                break
            import time
            time.sleep(0.05)

    def test_a_second_run_to_the_same_file_fails_fast(self):
        r = self.s.gen("run", "--out", str(self.out), "--prompt", "another mug", timeout=1.5)

        self.assertEqual(r.returncode, 1)
        self.assertIn("already being rendered", r.stderr)

    def test_dest_skips_a_name_that_is_being_rendered(self):
        r = self.s.gen("dest", "mug")

        self.assertEqual(self.lines(r), [self.out.with_name("mug-2.png")])


class DoctorTest(GenTest):
    def setUp(self):
        super().setUp()
        host = self.s.bin / "codex-code-mode-host"
        host.write_text("#!/bin/sh\n")
        host.chmod(0o755)
        (self.s.home / ".codex").mkdir()

    def test_a_working_setup_passes(self):
        r = self.s.gen("doctor")

        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("FAIL", r.stdout)

    def test_a_missing_helper_fails_with_the_fix(self):
        (self.s.bin / "codex-code-mode-host").unlink()

        r = self.s.gen("doctor")

        self.assertEqual(r.returncode, 1)
        self.assertIn("codex-code-mode-host", r.stdout)
        self.assertIn("ln -sf", r.stdout)

    def test_a_logged_out_codex_fails(self):
        r = self.s.gen("doctor", FAKE_CODEX_LOGGED_OUT="1")

        self.assertEqual(r.returncode, 1)
        self.assertIn("codex login", r.stdout)

    def test_no_codex_on_path_fails(self):
        r = self.s.gen("doctor", PATH="/usr/bin:/bin")

        self.assertEqual(r.returncode, 1)
        self.assertIn("codex is not on PATH", r.stdout)

    def test_a_broken_projects_file_fails(self):
        config = self.s.home / ".config" / "gpt-image-2"
        config.mkdir(parents=True)
        (config / "projects.json").write_text("{nope")

        r = self.s.gen("doctor")

        self.assertEqual(r.returncode, 1)
        self.assertIn("projects.json", r.stdout)


def has_pillow(*python_flags):
    return subprocess.run([sys.executable, *python_flags, "-c", "import PIL"],
                          capture_output=True).returncode == 0


NO_PILLOW = ("-S",)  # no site-packages, so no Pillow


@unittest.skipIf(has_pillow(*NO_PILLOW), "this Python finds Pillow even with -S")
class WithoutPillowTest(GenTest):
    def test_dest_offers_each_variant_instead_of_a_sheet(self):
        r = self.s.gen("dest", "mug", "--variants", "3", python_flags=NO_PILLOW)

        folder = self.s.home / "Pictures" / "gpt-image-2"
        self.assertEqual(self.lines(r), [folder / f"mug-v{i}.png" for i in (1, 2, 3)])

    def test_variants_still_render_and_print_every_file(self):
        out = self.s.home / "Pictures" / "gpt-image-2" / "mug.png"

        r = self.s.gen("run", "--out", str(out), "--prompt", "a mug", "--variants", "3",
                       python_flags=NO_PILLOW)

        self.assertEqual(r.returncode, 0, r.stderr)
        variants = [out.with_name(f"mug-v{i}.png") for i in (1, 2, 3)]
        self.assertEqual(self.lines(r), variants)
        self.assertTrue(all(v.exists() for v in variants))
        self.assertFalse(out.exists())
        self.assertIn("Pillow", r.stderr)


@unittest.skipUnless(has_pillow(), "Pillow not installed")
class WithPillowTest(GenTest):
    def test_variants_come_with_a_contact_sheet_listed_first(self):
        out = self.s.home / "Pictures" / "gpt-image-2" / "mug.png"
        self.assertEqual(self.lines(self.s.gen("dest", "mug", "--variants", "2")), [out])

        r = self.s.gen("run", "--out", str(out), "--prompt", "a mug", "--variants", "2")

        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.lines(r), [out, out.with_name("mug-v1.png"), out.with_name("mug-v2.png")])
        from PIL import Image
        with Image.open(out) as sheet:
            self.assertGreater(sheet.width, 64 * 2)


if __name__ == "__main__":
    unittest.main()
