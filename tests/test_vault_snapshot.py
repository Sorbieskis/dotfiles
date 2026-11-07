"""Hermetic tests for bin/vault-snapshot (M9 P2, widened by M11 P1): the read-only vault snapshot claude.ai reads from.

Each test builds a vault git repo whose `refs/remotes/origin/main` is the "pushed" state, runs the real
script into a scratch output dir and checks the published tree itself. Real gitleaks is used where the
guarantee is the scan (skipped if the binary is missing); failure paths use stubs. Secret fixtures are
assembled at runtime and never whole in git.

Run: python3 -m unittest discover -s tests
"""

import importlib.machinery
import importlib.util
import json
import os
import re
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import unittest
import uuid

sys.dont_write_bytecode = True

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCRIPT = os.path.join(ROOT, "bin", "vault-snapshot")
GITLEAKS = os.environ.get("GITLEAKS_BIN") or "/home/dima/.local/share/mise/installs/aqua-gitleaks-gitleaks/8.30.1/gitleaks"
CONFIG = os.path.join(ROOT, "vault", "gitleaks.toml")

GIT_ENV = {
    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid",
    "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
}


def load_script():
    loader = importlib.machinery.SourceFileLoader("vault_snapshot_under_test", SCRIPT)
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


VS = load_script()  # the closed enums (TEXT_TYPES, BINARY_MAGICS, SCOPE) are read from the code, not a hand table
PDFTOTEXT = "/usr/bin/pdftotext"


def sandbox_works():
    try:
        p = subprocess.run(["systemd-run", "--user", "--pipe", "--wait", "--collect", "-p", "PrivateNetwork=yes", "true"],
                           capture_output=True, timeout=30)
        return p.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


needs_sandbox = unittest.skipUnless(os.access(PDFTOTEXT, os.X_OK) and sandbox_works(), "pdftotext or systemd-run --user missing")


def gen_name(sha, scope=2):
    return f"gen-{sha}-s{scope}"


def make_pdf(pages):
    """A minimal hand-written PDF (Helvetica, one text line per page), built at runtime."""
    n = len(pages)
    kids = " ".join(f"{4 + 2 * i} 0 R" for i in range(n))
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>",
            f"<< /Type /Pages /Kids [{kids}] /Count {n} >>".encode(),
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    for i, text in enumerate(pages):
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {5 + 2 * i} 0 R "
                    f"/Resources << /Font << /F1 3 0 R >> >> >>".encode())
        stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
        objs.append(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
    out = bytearray(b"%PDF-1.4\n")
    offs = []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += f"{i} 0 obj\n".encode() + o + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    for o in offs:
        out += f"{o:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True,
                          text=True, env={**os.environ, **GIT_ENV}).stdout.strip()


def secret():
    """A gitleaks-positive GitHub token assembled here, never whole in git."""
    return "".join(["gh", "p_", "R7x2KqL9mZ4v", "B8nC1dF5gH3j", "T6wY0sA2eU9p"])


def stub(path, body):
    with open(path, "w") as f:
        f.write("#!/bin/sh\n" + body + "\n")
    os.chmod(path, 0o755)
    return path


def tree(root):
    """All published file paths, relative, excluding the stamp."""
    out = set()
    for d, _, files in os.walk(root):
        for n in files:
            rel = os.path.relpath(os.path.join(d, n), root)
            if rel != "SNAPSHOT.md":
                out.add(rel)
    return out


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(dir="/tmp")  # the extractor sandbox hides /home: stubs must live in /tmp
        self.addCleanup(self._tmp.cleanup)
        self.root = self._tmp.name
        self.vault = os.path.join(self.root, "vault")
        self.out = os.path.join(self.root, "out")  # scratch output, never ~/.cache/vault-snapshot
        git(self.root, "init", "-q", "-b", "main", self.vault)
        self.gl_ok = stub(os.path.join(self.root, "gl-ok"), "exit 0")

    def put(self, rel, text="note\n"):
        p = os.path.join(self.vault, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as f:
            f.write(text)

    def putb(self, rel, data):
        p = os.path.join(self.vault, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as f:
            f.write(data)

    def link(self, rel, target):
        p = os.path.join(self.vault, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        os.symlink(target, p)

    def commit(self, push=True):
        git(self.vault, "add", "-A")
        git(self.vault, "commit", "-q", "--allow-empty", "-m", "c")
        if push:
            git(self.vault, "update-ref", "refs/remotes/origin/main", "HEAD")
        return git(self.vault, "rev-parse", "HEAD")

    def run_snapshot(self, gitleaks=None, config=True, script=None, **extra):
        env = {**os.environ, **GIT_ENV, "VAULT_DIR": self.vault, "SNAPSHOT_DIR": self.out,
               "GITLEAKS_BIN": gitleaks or self.gl_ok, "GITLEAKS_CONFIG": CONFIG if config else "/nonexistent.toml"}
        env.update(extra)
        return subprocess.run([script or SCRIPT], capture_output=True, text=True, env=env, timeout=120)

    def current(self):
        return os.path.join(self.out, "current")

    def published(self):
        return tree(os.path.join(self.out, "current"))

    def vault_files(self):
        """Published vault files, without the .text/ sidecars."""
        return {p for p in self.published() if not p.startswith(".text/")}

    def stamp(self):
        with open(os.path.join(self.current(), "SNAPSHOT.md")) as f:
            return f.read()

    def read_published(self, rel):
        with open(os.path.join(self.current(), rel), "rb") as f:
            return f.read()

    def gens(self):
        return sorted(n for n in os.listdir(self.out) if n.startswith("gen-"))


class ScopeTests(Base):
    def test_every_top_folder_and_root_file_is_published_and_hidden_ones_are_not(self):
        keep = ["1_projects/p/a.md", "2_areas/x/b.md", "4_resources/c.md", "1_projects/p/engineering/plans/m1.md",
                "3_personal/d.md", "2_areas/finances/e.md", "belle/f.md", "journal/g.md", "5_archive/h.md",
                "0_inbox/i.md", "0_inbox/claude-ai/j.md", "excalidraw/k.md", "CLAUDE.md", "Untitled 1.md",
                "1_projects/belle_masters_2027/l.md", "2_areas/x/Journal.md"]
        deny = [".obsidian/m.md", ".trash/n.md", ".stversions/o.md", "1_projects/oikoumene/sources/.corpus/p.md"]
        for rel in keep + deny:
            self.put(rel)
        self.commit()
        r = self.run_snapshot()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.published(), set(keep))

    def test_kept_types_are_published_and_any_other_type_is_dropped_and_counted_other_type(self):
        keep = [f"1_projects/p/t.{e}" for e in VS.TEXT_TYPES] + [f"2_areas/i.{e}" for e in ("png", "jpg", "jpeg", "webp", "gif")]
        keep += ["1_projects/p/CAPS.PNG", "1_projects/p/doc.pdf"]
        drop = ["1_projects/p/a.xlsx", "1_projects/p/b.canvas", "1_projects/p/noext", "1_projects/p/c.md.bak",
                "1_projects/p/d.docx", "1_projects/p/e.py", "1_projects/p/bad\nname.md"]
        for rel in keep:
            if rel.endswith(".pdf"):
                self.putb(rel, make_pdf(["x"]))
            elif rel.lower().endswith(("png", "jpg", "jpeg", "webp", "gif")):
                self.putb(rel, b"\x89not-really-an-image")
            else:
                self.put(rel, "plain text\n")
        for rel in drop:
            self.put(rel)
        self.commit()
        r = self.run_snapshot()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.vault_files(), set(keep))
        self.assertIn(f"other-type {len(drop)},", self.stamp())

    def test_hidden_files_and_folders_inside_any_folder_are_dropped(self):
        for rel in ["1_projects/p/a.md", "1_projects/p/.review-record/r.md", "1_projects/p/.hidden.md", "2_areas/.obsidian/o.md",
                    "3_personal/.private/q.md"]:
            self.put(rel)
        self.commit()
        self.assertEqual(self.run_snapshot().returncode, 0)
        self.assertEqual(self.published(), {"1_projects/p/a.md"})

    def test_names_with_spaces_and_unicode_survive(self):
        self.put("1_projects/p/Plan v2 \u2014 \u0436.md", "x\n")
        self.commit()
        self.assertEqual(self.run_snapshot().returncode, 0)
        self.assertEqual(self.published(), {"1_projects/p/Plan v2 \u2014 \u0436.md"})


class MachineOutputTests(Base):
    def test_the_p3_machine_output_paths_are_excluded_and_their_neighbours_are_not(self):
        drop = ["1_projects/p/pull-log/a.md", "1_projects/p/pull-log/deep/b.md", "1_projects/q/landings/c.md",
                "1_projects/p/engineering/jobs/d.md", "1_projects/p/engineering/seat/e.md",
                "1_projects/p/engineering/seat/x/y/f.md", "1_projects/p/agent-ledger.md", "1_projects/p/agent-ledger-2026.md"]
        keep = ["1_projects/p/engineering/plans/m1.md", "1_projects/p/engineering/jobs-notes.md", "1_projects/p/current.md",
                "1_projects/p/notes/pull-log.md", "1_projects/p/landing-page.md", "2_areas/pull-log/z.md"]
        for rel in drop + keep:
            self.put(rel)
        self.commit()
        self.assertEqual(self.run_snapshot().returncode, 0)
        self.assertEqual(self.published(), set(keep))


class OversizeTests(Base):
    def test_text_over_5_mb_and_binaries_over_25_mb_are_dropped_and_counted_oversize(self):  # I11
        self.put("1_projects/p/ok.md")
        self.put("1_projects/p/exact.md", "x" * 5_000_000)
        self.put("1_projects/p/big.md", "x" * 5_000_001)
        self.putb("1_projects/p/exact.png", b"\0" * 25_000_000)
        self.putb("1_projects/p/big.png", b"\0" * 25_000_001)
        self.commit()
        self.assertEqual(self.run_snapshot().returncode, 0)
        self.assertEqual(self.published(), {"1_projects/p/ok.md", "1_projects/p/exact.md", "1_projects/p/exact.png"})
        self.assertIn("oversize 2,", self.stamp())
        self.assertRegex(self.stamp(), r"(?m)^dropped: 2$")


class PushedOnlyTests(Base):
    def test_only_origin_main_is_published_never_local_commits_or_the_work_tree(self):
        self.put("1_projects/p/pushed.md", "v1 pushed\n")
        sha = self.commit()
        self.put("1_projects/p/pushed.md", "v2 LOCAL\n")
        self.put("1_projects/p/local-only.md")
        self.commit(push=False)  # committed, not pushed
        self.put("1_projects/p/dirty.md")  # not even committed
        r = self.run_snapshot()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.published(), {"1_projects/p/pushed.md"})
        with open(os.path.join(self.current(), "1_projects/p/pushed.md")) as f:
            self.assertEqual(f.read(), "v1 pushed\n")
        with open(os.path.join(self.current(), "SNAPSHOT.md")) as f:
            self.assertRegex(f.read(), rf"(?m)^sha: {sha}$")

    def test_no_origin_main_publishes_nothing_and_fails(self):
        self.put("1_projects/p/a.md")
        self.commit(push=False)
        r = self.run_snapshot()
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse(os.path.lexists(self.current()))

    def test_symlinks_in_the_tree_are_not_published(self):
        self.put("1_projects/p/real.md", "real\n")
        self.put("3_personal/diary.md", "now published as itself\n")
        self.link("1_projects/p/alias.md", "real.md")
        self.link("1_projects/p/leak.md", "../../3_personal/diary.md")
        self.link("1_projects/p/dirlink", "../../3_personal")
        self.commit()
        self.assertEqual(self.run_snapshot().returncode, 0)
        self.assertEqual(self.published(), {"1_projects/p/real.md", "3_personal/diary.md"})
        for d, _, files in os.walk(self.current()):
            for n in files + _:
                self.assertFalse(os.path.islink(os.path.join(d, n)), n)

    def test_the_stamp_has_sha_utc_time_and_counts(self):
        for rel in ["1_projects/p/a.md", "1_projects/p/b.md", "1_projects/p/pull-log/c.md", "1_projects/p/.x/d.md"]:
            self.put(rel)
        sha = self.commit()
        self.assertEqual(self.run_snapshot().returncode, 0)
        with open(os.path.join(self.current(), "SNAPSHOT.md")) as f:
            text = f.read()
        self.assertRegex(text, rf"(?m)^sha: {sha}$")
        self.assertRegex(text, r"(?m)^generated: \d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        self.assertRegex(text, r"(?m)^scope: 2$")
        self.assertRegex(text, r"(?m)^files: 2$")
        self.assertRegex(text, r"(?m)^dropped: 2$")
        for k in ("machine-output", "hidden", "symlinks", "oversize", "other-type", "fake-binary", "secrets", "pdf-notext"):
            self.assertRegex(text, rf"dropped_detail: .*\b{k} \d")
        self.assertNotIn("personal-name", text)

    def test_published_modes_let_the_container_user_read_them(self):
        self.put("1_projects/p/a.md")
        self.commit()
        self.assertEqual(self.run_snapshot().returncode, 0)
        gen = os.path.join(self.out, self.gens()[0])
        self.assertEqual(stat.S_IMODE(os.stat(gen).st_mode), 0o755)
        self.assertEqual(stat.S_IMODE(os.stat(os.path.join(gen, "1_projects/p/a.md")).st_mode), 0o644)
        self.assertEqual(stat.S_IMODE(os.stat(os.path.join(gen, "1_projects/p")).st_mode), 0o755)


@unittest.skipUnless(os.access(GITLEAKS, os.X_OK), "gitleaks missing")
class SecretScanTests(Base):
    def test_a_file_with_a_credential_is_dropped_and_nothing_else_is(self):
        self.put("1_projects/p/clean.md", "nothing secret here\n")
        self.put("1_projects/p/leaky.md", f"token = {secret()}\n")
        self.put("2_areas/clean2.md", "also fine\n")
        self.commit()
        r = self.run_snapshot(gitleaks=GITLEAKS)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.published(), {"1_projects/p/clean.md", "2_areas/clean2.md"})
        for d, _, files in os.walk(self.out):  # the secret is nowhere under the output, stamp included
            for n in files:
                with open(os.path.join(d, n), errors="replace") as f:
                    self.assertNotIn(secret(), f.read(), n)
        with open(os.path.join(self.current(), "SNAPSHOT.md")) as f:
            self.assertRegex(f.read(), r"(?m)^dropped: 1$")
        self.assertNotIn(secret(), r.stdout + r.stderr)

    def test_a_credential_in_the_file_name_is_dropped_too(self):
        self.put("1_projects/p/clean.md")
        self.put(f"1_projects/p/{secret()}.md", "x\n")
        self.commit()
        r = self.run_snapshot(gitleaks=GITLEAKS)
        # either the name is flagged and dropped, or gitleaks does not scan names: then it must still publish no secret in content
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("1_projects/p/clean.md", self.published())

    def test_gitleaks_inline_allow_comment_does_not_exempt_a_file(self):
        self.put("1_projects/p/sneaky.md", f"token = {secret()}  # gitleaks:allow\n")
        self.put("1_projects/p/clean.md")
        self.commit()
        self.assertEqual(self.run_snapshot(gitleaks=GITLEAKS).returncode, 0)
        self.assertEqual(self.published(), {"1_projects/p/clean.md"})


class ScopeVersionTests(Base):
    """R1: the generation key carries the scope version, so a script change rebuilds at an unchanged sha."""

    def test_a_scope_bump_republishes_at_an_unchanged_sha_and_the_same_scope_does_not(self):
        self.put("1_projects/p/a.md")
        sha = self.commit()
        self.assertEqual(self.run_snapshot(SNAPSHOT_SCOPE="1").returncode, 0)
        self.assertEqual(os.readlink(self.current()), gen_name(sha, 1))
        r = self.run_snapshot()  # scope 2, same sha
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("already current", r.stdout)
        self.assertEqual(os.readlink(self.current()), gen_name(sha, 2))
        self.assertRegex(self.stamp(), r"(?m)^scope: 2$")
        self.assertEqual(self.gens(), sorted([gen_name(sha, 1), gen_name(sha, 2)]))
        r = self.run_snapshot(gitleaks=stub(os.path.join(self.root, "gl-boom"), "exit 2"))  # same sha, same scope
        self.assertEqual(r.returncode, 0)
        self.assertIn("already current", r.stdout)

    def test_the_pre_m11_generation_key_without_a_scope_is_rebuilt(self):
        self.put("1_projects/p/a.md")
        sha = self.commit()
        old = os.path.join(self.out, f"gen-{sha}")
        os.makedirs(old)
        with open(os.path.join(old, "SNAPSHOT.md"), "w") as f:
            f.write("# vault snapshot\n")
        os.symlink(f"gen-{sha}", self.current())
        r = self.run_snapshot()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(os.readlink(self.current()), gen_name(sha))


@needs_sandbox
class PdfTextTests(Base):
    PDF = "1_projects/p/doc.pdf"

    def sidecar(self, rel=None):
        return ".text/" + (rel or self.PDF) + ".txt"

    def test_a_pdf_gets_a_text_sidecar_with_a_fixed_first_line_and_form_feed_page_breaks(self):
        self.putb(self.PDF, make_pdf(["alpha page", "beta page"]))
        self.commit()
        r = self.run_snapshot()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(self.PDF, self.published())
        text = self.read_published(self.sidecar()).decode()
        self.assertTrue(text.startswith(f"# pdf text of {self.PDF}\n"), text[:80])
        pages = text.split("\n", 1)[1].split("\f")
        self.assertEqual(len(pages), 3)  # pdftotext ends every page with \f
        self.assertIn("alpha page", pages[0])
        self.assertIn("beta page", pages[1])
        self.assertIn("pdf-notext 0", self.stamp())

    def test_a_failed_extraction_keeps_the_pdf_without_a_sidecar_and_counts_pdf_notext(self):
        self.putb(self.PDF, make_pdf(["x"]))
        self.put("1_projects/p/a.md")
        self.commit()
        r = self.run_snapshot(PDFTOTEXT_BIN=stub(os.path.join(self.root, "pt-fail"), "exit 1"))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.published(), {self.PDF, "1_projects/p/a.md"})
        self.assertIn("pdf-notext 1", self.stamp())
        self.assertRegex(self.stamp(), r"(?m)^dropped: 0$")  # a kept PDF is not a drop

    def test_an_extractor_that_exceeds_its_time_or_memory_limit_leaves_the_pdf_without_a_sidecar_and_the_run_publishes(self):
        self.putb(self.PDF, make_pdf(["x"]))
        self.put("1_projects/p/a.md")
        self.commit()
        slow = stub(os.path.join(self.root, "pt-slow"), "sleep 30")
        fat = os.path.join(self.root, "pt-fat")
        with open(fat, "w") as f:
            f.write("#!/usr/bin/python3\nb = b'x' * (300 << 20)\nprint(len(b))\n")
        os.chmod(fat, 0o755)
        for name, bin_, extra in (("time", slow, dict(EXTRACT_SECONDS="3")), ("memory", fat, dict(EXTRACT_MEMORY="64M"))):
            with self.subTest(name):
                shutil.rmtree(self.out, ignore_errors=True)
                r = self.run_snapshot(PDFTOTEXT_BIN=bin_, **extra)
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertEqual(self.published(), {self.PDF, "1_projects/p/a.md"})
                self.assertIn("pdf-notext 1", self.stamp())

    def test_the_extractor_cannot_open_a_socket_reach_loopback_or_write_outside_its_pipes(self):
        srv = socket.socket()
        srv.bind(("127.0.0.1", 0))
        srv.listen(5)
        port = srv.getsockname()[1]
        self.addCleanup(srv.close)
        probe = os.path.join(self.root, "pt-probe")
        tag = uuid.uuid4().hex  # per-run names: a confinement failure leaves files, which are removed below
        victims = [os.path.join(self.root, "escaped.txt"), os.path.expanduser(f"~/.m11-snapshot-probe-{tag}"),
                   f"/var/tmp/.m11-snapshot-probe-{tag}"]
        for v in victims:
            self.assertFalse(os.path.exists(v), v)  # absent before the run
            self.addCleanup(lambda v=v: os.path.exists(v) and os.unlink(v))
        with open(probe, "w") as f:
            f.write(f"""#!/usr/bin/python3
import socket
def t(name, fn):
    try:
        fn()
        print(name + ": BAD")
    except OSError:
        print(name + ": refused")
def conn():
    s = socket.socket(); s.settimeout(2); s.connect(("127.0.0.1", {port}))
def write(path):
    def w():
        open(path, "w").write("x")
    return w
t("inet", lambda: socket.socket(socket.AF_INET, socket.SOCK_STREAM))
t("inet6", lambda: socket.socket(socket.AF_INET6, socket.SOCK_STREAM))
t("loopback", conn)
""" + "".join(f't("write{i}", write({v!r}))\n' for i, v in enumerate(victims)))
        os.chmod(probe, 0o755)
        self.putb(self.PDF, make_pdf(["x"]))
        self.commit()
        r = self.run_snapshot(PDFTOTEXT_BIN=probe)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = self.read_published(self.sidecar()).decode()
        self.assertEqual(out.count(": refused"), 3 + len(victims), out)
        self.assertNotIn("BAD", out)
        srv.settimeout(0.2)
        with self.assertRaises(OSError):
            srv.accept()
        for v in victims:
            self.assertFalse(os.path.exists(v), v)


@needs_sandbox
@unittest.skipUnless(os.access(GITLEAKS, os.X_OK), "gitleaks missing")
class PdfSecretTests(Base):
    PDF = "1_projects/p/doc.pdf"

    def test_a_credential_in_a_pdfs_text_drops_the_pdf_and_its_sidecar_and_nothing_else(self):
        self.putb(self.PDF, make_pdf([f"token = {secret()}"]))
        self.putb("1_projects/p/clean.pdf", make_pdf(["nothing secret"]))
        self.commit()
        r = self.run_snapshot(gitleaks=GITLEAKS)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.published(), {"1_projects/p/clean.pdf", ".text/1_projects/p/clean.pdf.txt"})
        self.assertRegex(self.stamp(), r"(?m)^dropped: 1$")
        self.assertIn("secrets 1", self.stamp())
        for d, _, files in os.walk(self.out):
            for n in files:
                with open(os.path.join(d, n), errors="replace") as f:
                    self.assertNotIn(secret(), f.read(), n)

    def test_a_sidecar_whose_extracted_text_starts_with_pdf_magic_is_still_scanned(self):
        self.putb(self.PDF, make_pdf(["x"]))
        stubbed = stub(os.path.join(self.root, "pt-magic"), f"printf '%s\\n' '%PDF-1.4 token = {secret()}'")
        self.commit()
        r = self.run_snapshot(gitleaks=GITLEAKS, PDFTOTEXT_BIN=stubbed)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.published(), set())


@unittest.skipUnless(os.access(GITLEAKS, os.X_OK), "gitleaks missing")
class NoFileTypeIsPublishedUnscannedTests(Base):
    """R3: gitleaks dir skips by extension, by directory and by content sniff; the scan copies are neutral-named."""

    def test_every_published_text_type_with_a_planted_secret_is_dropped(self):
        for e in VS.TEXT_TYPES:
            self.put(f"1_projects/p/s.{e}", f"<svg><text>token = {secret()}</text></svg>\n" if e == "svg" else f"token = {secret()}\n")
        self.put("1_projects/p/clean.md")
        self.commit()
        r = self.run_snapshot(gitleaks=GITLEAKS)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.published(), {"1_projects/p/clean.md"})
        self.assertIn(f"secrets {len(VS.TEXT_TYPES) }", self.stamp())
        self.assertIn("svg", VS.TEXT_TYPES)

    def test_a_secret_under_node_modules_is_dropped(self):
        self.put("1_projects/p/node_modules/x.md", f"token = {secret()}\n")
        self.put("1_projects/p/a/node_modules/deep/y.txt", f"token = {secret()}\n")
        self.put("1_projects/p/clean.md")
        self.commit()
        self.assertEqual(self.run_snapshot(gitleaks=GITLEAKS).returncode, 0)
        self.assertEqual(self.published(), {"1_projects/p/clean.md"})

    def test_a_text_file_that_starts_with_a_binary_magic_is_dropped_fake_binary_and_never_published(self):
        for i, (off, magic) in enumerate(VS.BINARY_MAGICS):
            self.putb(f"1_projects/p/m{i}.txt", b" " * off + magic + f" token = {secret()}\n".encode())
        self.put("1_projects/p/clean.md")
        self.commit()
        self.assertEqual(self.run_snapshot(gitleaks=GITLEAKS).returncode, 0)
        self.assertEqual(self.published(), {"1_projects/p/clean.md"})
        self.assertIn(f"fake-binary {len(VS.BINARY_MAGICS)},", self.stamp())

    def test_a_text_file_with_a_nul_or_invalid_utf8_is_dropped_fake_binary(self):
        self.putb("1_projects/p/utf16.md", "hello\n".encode("utf-16"))
        self.putb("1_projects/p/latin1.txt", "caf\xe9\n".encode("latin-1"))
        self.putb("1_projects/p/nul.csv", b"a,b\0c\n")
        self.put("1_projects/p/clean.md")
        self.commit()
        self.assertEqual(self.run_snapshot(gitleaks=GITLEAKS).returncode, 0)
        self.assertEqual(self.published(), {"1_projects/p/clean.md"})
        self.assertIn("fake-binary 3,", self.stamp())

    def test_the_scan_copy_first_line_alone_keeps_gitleaks_from_skipping_a_binary_looking_file(self):
        # I7: with the magic list emptied (the head check is hygiene), a `%PDF-`-headed .txt holding a token is still
        # dropped, because every scan copy starts with the fixed `# scan copy` line and gitleaks sniffs that, not the file
        src = open(SCRIPT).read()
        patched = re.sub(r"(?s)\nBINARY_MAGICS = \(.*?\n\)\n", "\nBINARY_MAGICS = ()\n", src, count=1)
        self.assertNotEqual(patched, src)
        script = os.path.join(self.root, "vault-snapshot-no-magics")
        with open(script, "w") as f:
            f.write(patched)
        os.chmod(script, 0o755)
        self.putb("1_projects/p/fake.txt", b"%PDF-1.4 token = " + secret().encode() + b"\n")
        self.put("1_projects/p/clean.md")
        self.commit()
        r = self.run_snapshot(gitleaks=GITLEAKS, script=script)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.published(), {"1_projects/p/clean.md"})
        self.assertIn("secrets 1,", self.stamp())


class FailClosedTests(Base):
    def first_generation(self):
        self.put("1_projects/p/old.md", "old\n")
        old = self.commit()
        self.assertEqual(self.run_snapshot().returncode, 0)
        self.assertEqual(os.readlink(self.current()), gen_name(old))
        return old

    def assert_old_kept(self, old):
        self.assertEqual(os.readlink(self.current()), gen_name(old))
        self.assertEqual(self.gens(), [gen_name(old)])
        self.assertEqual(self.published(), {"1_projects/p/old.md"})
        self.assertEqual([n for n in os.listdir(self.out) if n not in (gen_name(old), "current", ".lock")], [])  # no build leftovers

    def test_gitleaks_error_publishes_nothing_and_keeps_the_old_current(self):
        old = self.first_generation()
        self.put("1_projects/p/new.md")
        self.commit()
        r = self.run_snapshot(gitleaks=stub(os.path.join(self.root, "gl-err"), "exit 2"))
        self.assertNotEqual(r.returncode, 0)
        self.assert_old_kept(old)

    def test_gitleaks_missing_publishes_nothing_and_keeps_the_old_current(self):
        old = self.first_generation()
        self.put("1_projects/p/new.md")
        self.commit()
        r = self.run_snapshot(gitleaks=os.path.join(self.root, "no-such-gitleaks"))
        self.assertNotEqual(r.returncode, 0)
        self.assert_old_kept(old)

    def test_gitleaks_config_unreadable_fails_closed(self):
        old = self.first_generation()
        self.put("1_projects/p/new.md")
        self.commit()
        r = self.run_snapshot(config=False)
        self.assertNotEqual(r.returncode, 0)
        self.assert_old_kept(old)

    def test_exit_1_without_a_readable_report_is_an_error_not_a_hit(self):
        # gitleaks also exits 1 on a bad config: no report must never read as "all files dropped, publish"
        old = self.first_generation()
        self.put("1_projects/p/new.md")
        self.commit()
        r = self.run_snapshot(gitleaks=stub(os.path.join(self.root, "gl-1"), "exit 1"))
        self.assertNotEqual(r.returncode, 0)
        self.assert_old_kept(old)

    def test_a_rescan_that_still_finds_a_hit_publishes_nothing(self):
        # first call reports a hit on a.md, the second still exits 1: dropping did not make it clean
        old = self.first_generation()
        self.put("1_projects/p/new.md")
        self.commit()
        body = ('rp=""; while [ $# -gt 0 ]; do [ "$1" = "--report-path" ] && rp="$2"; shift; done\n'
                'echo \'[{"File":"0.txt","RuleID":"x"}]\' > "$rp"; exit 1')  # a scan copy: it can be dropped, the rescan still hits
        r = self.run_snapshot(gitleaks=stub(os.path.join(self.root, "gl-stuck"), body))
        self.assertNotEqual(r.returncode, 0)
        self.assert_old_kept(old)

    def test_exit_1_with_an_empty_report_is_an_error_not_a_hit(self):
        old = self.first_generation()
        self.put("1_projects/p/new.md")
        self.commit()
        body = ('rp=""; while [ $# -gt 0 ]; do [ "$1" = "--report-path" ] && rp="$2"; shift; done\n'
                'echo "[]" > "$rp"; exit 1')
        r = self.run_snapshot(gitleaks=stub(os.path.join(self.root, "gl-empty"), body))
        self.assertNotEqual(r.returncode, 0)
        self.assert_old_kept(old)

    def test_a_report_naming_a_file_outside_the_generation_deletes_nothing_there(self):
        # first call: report a file outside (exit 1); second call: exit 0, so only the path check can stop the delete
        old = self.first_generation()
        self.put("1_projects/p/new.md")
        self.commit()
        victim = os.path.join(self.root, "victim.md")
        with open(victim, "w") as f:
            f.write("must survive\n")
        flag = os.path.join(self.root, "called-once")
        body = ('rp=""; while [ $# -gt 0 ]; do [ "$1" = "--report-path" ] && rp="$2"; shift; done\n'
                f'if [ -e {flag} ]; then exit 0; fi; touch {flag}\n'
                f'echo \'[{{"File":"{victim}","RuleID":"x"}}]\' > "$rp"; exit 1')
        r = self.run_snapshot(gitleaks=stub(os.path.join(self.root, "gl-victim"), body))
        self.assertNotEqual(r.returncode, 0)
        self.assertTrue(os.path.exists(victim))
        self.assert_old_kept(old)

    def test_a_report_naming_a_path_outside_the_generation_is_an_error(self):
        old = self.first_generation()
        self.put("1_projects/p/new.md")
        self.commit()
        body = ('rp=""; while [ $# -gt 0 ]; do [ "$1" = "--report-path" ] && rp="$2"; shift; done\n'
                'echo \'[{"File":"/etc/passwd","RuleID":"x"}]\' > "$rp"; exit 1')
        r = self.run_snapshot(gitleaks=stub(os.path.join(self.root, "gl-out"), body))
        self.assertNotEqual(r.returncode, 0)
        self.assert_old_kept(old)


class SwapTests(Base):
    def test_current_is_a_relative_symlink_to_gen_sha_and_the_mounted_parent_is_never_renamed(self):
        self.put("1_projects/p/a.md")
        sha1 = self.commit()
        self.assertEqual(self.run_snapshot().returncode, 0)
        ino = os.stat(self.out).st_ino
        self.assertEqual(os.readlink(self.current()), gen_name(sha1))  # relative: valid inside a /snapshot mount
        self.put("1_projects/p/b.md")
        sha2 = self.commit()
        self.assertEqual(self.run_snapshot().returncode, 0)
        self.assertEqual(os.readlink(self.current()), gen_name(sha2))
        self.assertEqual(os.stat(self.out).st_ino, ino)
        self.assertNotIn("current.tmp", os.listdir(self.out))

    def test_a_reader_never_sees_current_missing_or_half_written_across_swaps(self):
        self.put("1_projects/p/a.md", "a\n")
        self.commit()
        self.assertEqual(self.run_snapshot().returncode, 0)
        stop, bad = threading.Event(), []

        def reader():
            while not stop.is_set():
                try:
                    with open(os.path.join(self.current(), "SNAPSHOT.md")) as f:
                        if not f.read().startswith("#"):
                            bad.append("content")
                    os.stat(os.path.join(self.current(), "1_projects/p/a.md"))
                except OSError as e:
                    bad.append(repr(e))

        t = threading.Thread(target=reader)
        t.start()
        try:
            for i in range(4):
                self.put(f"1_projects/p/n{i}.md")
                self.commit()
                self.assertEqual(self.run_snapshot().returncode, 0)
        finally:
            stop.set()
            t.join()
        self.assertEqual(bad, [])

    def test_two_generations_are_kept(self):
        shas = []
        for i in range(4):
            self.put(f"1_projects/p/n{i}.md")
            shas.append(self.commit())
            self.assertEqual(self.run_snapshot().returncode, 0)
        self.assertEqual(self.gens(), sorted(gen_name(s) for s in shas[-2:]))

    def test_an_unchanged_sha_republishes_nothing(self):
        self.put("1_projects/p/a.md")
        self.commit()
        self.assertEqual(self.run_snapshot().returncode, 0)
        stamp = os.lstat(self.current()).st_mtime_ns
        gen = os.path.join(self.out, self.gens()[0], "SNAPSHOT.md")
        before = os.stat(gen).st_mtime_ns
        self.assertEqual(self.run_snapshot(gitleaks=stub(os.path.join(self.root, "gl-boom"), "exit 2")).returncode, 0)
        self.assertEqual(os.stat(gen).st_mtime_ns, before)
        self.assertEqual(os.lstat(self.current()).st_mtime_ns, stamp)

    def test_stale_build_directories_from_a_killed_run_are_cleaned(self):
        os.makedirs(os.path.join(self.out, ".build-999"))
        self.put("1_projects/p/a.md")
        self.commit()
        self.assertEqual(self.run_snapshot().returncode, 0)
        self.assertFalse(any(n.startswith(".build") for n in os.listdir(self.out)))


class WiringTests(unittest.TestCase):
    def read(self, *p):
        with open(os.path.join(ROOT, *p)) as f:
            return f.read()

    def test_hourly_at_47_and_the_service_runs_the_installed_script(self):
        timer = self.read("systemd", "user", "vault-snapshot.timer")
        service = self.read("systemd", "user", "vault-snapshot.service")
        self.assertRegex(timer, r"(?m)^OnCalendar=\*:47(:00)?$")
        self.assertIn("timers.target", timer)
        self.assertRegex(service, r"(?m)^Type=oneshot$")
        self.assertRegex(service, r"(?m)^ExecStart=%h/\.local/bin/vault-snapshot$")
        self.assertRegex(service, r"(?m)^MemoryMax=")

    def test_install_enables_the_timer_and_links_the_script(self):
        install = self.read("install.sh")
        self.assertIn("vault-snapshot.timer", install)
        self.assertTrue(os.access(SCRIPT, os.X_OK))  # install.sh links every executable bin/*


if __name__ == "__main__":
    unittest.main()
