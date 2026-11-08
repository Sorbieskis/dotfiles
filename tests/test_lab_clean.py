"""Hermetic tests for bin/lab-clean: the only docker removal a seat is allowed (settings allow rule).

A fake `docker` on PATH serves a JSON world and logs every call; nothing here touches real docker.
Each case names the guarantee it pins; the boundary cases (non-lab, other slug, in-use, prod) are the point.

Run: python3 -m unittest discover -s tests
"""

import importlib.machinery
import importlib.util
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(os.path.dirname(HERE), "bin", "lab-clean")

FAKE_DOCKER = r'''#!/usr/bin/env python3
import json, os, sys
w = json.load(open(os.environ["FAKE_DOCKER_WORLD"]))
a = sys.argv[1:]
with open(os.environ["FAKE_DOCKER_LOG"], "a") as f:
    f.write(json.dumps(a) + "\n")
if a[:2] == ["container", "ls"]:
    print("\n".join(c["id"] for c in w["containers"]))
elif a[:2] == ["container", "inspect"]:
    ids = a[2:]
    seen = [json.loads(l) for l in open(os.environ["FAKE_DOCKER_LOG"]) if l.strip()]
    out = []
    for c in w["containers"]:
        if c["id"] in ids:
            n = sum(1 for x in seen if x[:2] == ["container", "inspect"] and c["id"] in x)
            tier = "" if (c["id"] in w.get("flip", []) and n >= 2) else c.get("tier", "")
            name = "other" if (c["id"] in w.get("rename", []) and n >= 2) else c["name"]
            out.append({"Id": c["id"], "Name": "/" + name, "Image": c["image"], "Config": {"Labels": {"tier": tier}}})
    print(json.dumps(out))
elif a[:2] == ["image", "ls"]:
    for i in w["images"]:
        print(f'{i["id"]}\t{i["repo"]}\t{i["tag"]}')
elif a[:2] == ["image", "inspect"]:
    print(" ".join(w.get("digests", {}).get(a[-1], [])))
elif a[0] in ("rm", "rmi"):
    pass
else:
    sys.exit("fake docker: unexpected " + repr(a))
'''

WORLD = {
    "containers": [
        {"id": "c1" * 32, "name": "lab-m11-p4-echo", "tier": "lab", "image": "sha256:img-echo"},
        {"id": "c2" * 32, "name": "lab-m11-p4-caddy", "tier": "lab", "image": "sha256:img-final"},
        # same name shape, wrong tier: must survive
        {"id": "c3" * 32, "name": "lab-m11-prodlook", "tier": "prod", "image": "sha256:img-prod"},
        {"id": "c4" * 32, "name": "lab-m11-nolabel", "tier": "", "image": "sha256:img-prod"},
        # tier=lab, other slugs / no dash after the slug: must survive
        {"id": "c5" * 32, "name": "lab-m110-x", "tier": "lab", "image": "sha256:img-other"},
        {"id": "c6" * 32, "name": "lab-m1-x", "tier": "lab", "image": "sha256:img-other"},
        {"id": "c7" * 32, "name": "lab-m11", "tier": "lab", "image": "sha256:img-other"},
        {"id": "c8" * 32, "name": "caddy", "tier": "", "image": "sha256:img-prod"},
        {"id": "c9" * 32, "name": "x-lab-m11-p4", "tier": "lab", "image": "sha256:img-other"},
    ],
    "images": [
        {"id": "sha256:img-final", "repo": "vault-door", "tag": "m11-final"},
        {"id": "sha256:img-m11", "repo": "vault-door", "tag": "m11"},
        {"id": "sha256:img-labtag", "repo": "scratch", "tag": "lab-m11-x"},
        {"id": "sha256:img-m118", "repo": "vault-door", "tag": "m118-x"},
        {"id": "sha256:img-m1", "repo": "vault-door", "tag": "m1-x"},
        {"id": "sha256:img-latest", "repo": "vault-door", "tag": "latest"},
        {"id": "sha256:img-none", "repo": "<none>", "tag": "<none>"},
        {"id": "sha256:img-used", "repo": "vault-door", "tag": "m11-used"},
        {"id": "sha256:img-hot", "repo": "someone/app", "tag": "m11-hot"},
        {"id": "sha256:img-mirror", "repo": "mirror", "tag": "m11-dig"},
        {"id": "sha256:img-pin", "repo": "pinned", "tag": "m11-pin"},
        {"id": "sha256:img-other", "repo": "vault-door", "tag": "m12-final"},
    ],
    "flip": [],
    "digests": {"sha256:img-mirror": ["mirror@sha256:" + "d" * 64]},
}
# img-used is also run by a surviving container
WORLD["containers"].append({"id": "ca" * 32, "name": "vault-door", "tier": "prod", "image": "sha256:img-used"})

COMPOSE = "services:\n  a:\n    image: someone/app:1.0   # prod\n  b:\n    image: pinned@sha256:%s\n" % ("d" * 64)


def load():
    loader = importlib.machinery.SourceFileLoader("lab_clean", SCRIPT)
    spec = importlib.util.spec_from_loader("lab_clean", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        t = self.tmp.name
        os.mkdir(os.path.join(t, "bin"))
        fake = os.path.join(t, "bin", "docker")
        with open(fake, "w") as f:
            f.write(FAKE_DOCKER)
        os.chmod(fake, os.stat(fake).st_mode | stat.S_IXUSR)
        self.log = os.path.join(t, "log")
        open(self.log, "w").close()
        self.stacks = os.path.join(t, "stacks")
        os.makedirs(os.path.join(self.stacks, "app"))
        with open(os.path.join(self.stacks, "app", "docker-compose.yml"), "w") as f:
            f.write(COMPOSE)
        self.world(WORLD)
        self.env = dict(os.environ, PATH=os.path.join(t, "bin") + os.pathsep + os.environ["PATH"],
                        FAKE_DOCKER_WORLD=os.path.join(t, "world.json"), FAKE_DOCKER_LOG=self.log)

    def world(self, w):
        with open(os.path.join(self.tmp.name, "world.json"), "w") as f:
            json.dump(w, f)

    def calls(self):
        with open(self.log) as f:
            return [json.loads(l) for l in f if l.strip()]

    def removals(self):
        return [c for c in self.calls() if c[0] in ("rm", "rmi")]

    def run_main(self, *argv):
        """main() in-process with the fake docker first on PATH and the scratch compose dir."""
        mod = load()
        old = os.environ.copy()
        os.environ.update(self.env)
        import io, contextlib, pathlib
        buf, err = io.StringIO(), io.StringIO()
        try:
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(err):
                rc = mod.main(list(argv), stacks=pathlib.Path(self.stacks))
        finally:
            os.environ.clear()
            os.environ.update(old)
        return rc, buf.getvalue(), err.getvalue()


class Removal(Base):
    def test_dry_run_is_the_default_and_removes_nothing(self):
        rc, out, _ = self.run_main("m11")
        self.assertEqual(rc, 0)
        self.assertEqual(self.removals(), [])
        self.assertIn("container lab-m11-p4-echo", out)
        self.assertIn("image vault-door:m11-final", out)
        self.assertIn("would remove 2 container(s)", out)

    def test_explicit_dry_run_equals_default(self):
        self.assertEqual(self.run_main("m11"), self.run_main("m11", "--dry-run"))

    def test_yes_removes_exactly_the_labelled_slug_containers_by_full_id(self):
        rc, out, _ = self.run_main("m11", "--yes")
        self.assertEqual(rc, 0)
        rms = [c for c in self.removals() if c[0] == "rm"]
        self.assertEqual(sorted(rms), sorted([["rm", "-f", "c1" * 32], ["rm", "-f", "c2" * 32]]))
        self.assertIn("removed 2 container(s)", out)

    def test_yes_removes_only_slug_tagged_unused_unreferenced_images_and_never_forces(self):
        self.run_main("m11", "--yes")
        rmis = sorted(c for c in self.removals() if c[0] == "rmi")
        # m11-final is freed because its only container (lab-m11-p4-caddy) goes in the same run
        self.assertEqual(rmis, [["rmi", "scratch:lab-m11-x"], ["rmi", "vault-door:m11"], ["rmi", "vault-door:m11-final"]])

    def test_kept_images_say_why(self):
        _, out, _ = self.run_main("m11")
        self.assertIn("kept image vault-door:m11-used (in use by a container)", out)
        self.assertIn("kept image someone/app:m11-hot (repo is in a prod compose)", out)
        self.assertIn("kept image pinned:m11-pin (repo is in a prod compose)", out)
        self.assertIn("kept image mirror:m11-dig (a prod compose references it)", out)

    def test_a_slug_with_nothing_removes_nothing(self):
        rc, out, _ = self.run_main("m99", "--yes")
        self.assertEqual((rc, self.removals()), (0, []))
        self.assertIn("removed 0 container(s), 0 image(s)", out)


class Hostile(Base):
    def test_a_label_with_tabs_and_newlines_cannot_forge_a_container_row(self):
        w = json.loads(json.dumps(WORLD))
        forged = "x\tsha256:a\n" + "ee" * 32 + "\tlab-m11-zz\tlab"
        w["containers"].append({"id": "ab" * 32, "name": "evil", "tier": forged, "image": "sha256:img-other"})
        w["containers"].append({"id": "ee" * 32, "name": "caddy-prod", "tier": "", "image": "sha256:img-prod"})
        self.world(w)
        self.run_main("m11", "--yes")
        self.assertNotIn(["rm", "-f", "ee" * 32], self.removals())
        self.assertNotIn(["rm", "-f", "ab" * 32], self.removals())

    def test_a_container_that_changed_after_the_plan_is_not_removed(self):
        w = json.loads(json.dumps(WORLD))
        w["flip"] = ["c1" * 32]
        self.world(w)
        rc, _, err = self.run_main("m11", "--yes")
        self.assertEqual(rc, 1)
        self.assertIn("changed since the plan", err)
        self.assertNotIn(["rm", "-f", "c1" * 32], self.removals())


class Renamed(Base):
    def test_a_container_renamed_after_the_plan_is_not_removed(self):
        w = json.loads(json.dumps(WORLD))
        w["rename"] = ["c1" * 32]
        self.world(w)
        rc, _, err = self.run_main("m11", "--yes")
        self.assertEqual(rc, 1)
        self.assertNotIn(["rm", "-f", "c1" * 32], self.removals())


class Fail_closed(Base):
    def compose(self, name, body, sub="app"):
        d = os.path.join(self.stacks, sub)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, name), "w") as f:
            f.write(body)

    def test_unreadable_subdirectory_refuses(self):
        if os.geteuid() == 0:
            self.skipTest("root reads everything")
        self.compose("docker-compose.yml", "services: {}\n", sub="deep")
        d = os.path.join(self.stacks, "deep")
        os.chmod(d, 0)
        rc, _, err = self.run_main("m11", "--yes")
        os.chmod(d, 0o755)
        self.assertEqual(rc, 2)
        self.assertIn("cannot read", err)
        self.assertEqual(self.removals(), [])

    def test_image_forms_that_are_not_a_plain_scalar_refuse(self):
        for line in ("image: *base", "image: >-", '"image": thing:1', "{image: thing:1}", "image:", "image: ${R}:1", "image: reg.io/${R}:1"):
            with self.subTest(line=line):
                self.compose("extra.yaml", "services:\n  z:\n    %s\n" % line, sub="x")
                rc, _, err = self.run_main("m11", "--yes")
                self.assertEqual(rc, 2, line)
                self.assertEqual(self.removals(), [])

    def test_yaml_suffix_and_symlinked_stack_dirs_are_scanned(self):
        real = os.path.join(self.tmp.name, "real")
        os.makedirs(real)
        with open(os.path.join(real, "compose.yaml"), "w") as f:
            f.write("services:\n  a:\n    image: vault-door:1\n")
        os.symlink(real, os.path.join(self.stacks, "linked"))
        _, out, _ = self.run_main("m11")
        self.assertIn("kept image vault-door:m11-final (repo is in a prod compose)", out)

    def test_an_image_id_in_a_compose_file_keeps_the_image(self):
        self.compose("pin.yml", "# built as sha256:img-m11\n", sub="x")
        _, out, _ = self.run_main("m11")
        self.assertIn("kept image vault-door:m11 (a prod compose references it)", out)

    def test_registry_prefixes_do_not_hide_a_prod_repo(self):
        self.compose("p.yml", "services:\n  a:\n    image: docker.io/library/scratch:1\n", sub="x")
        _, out, _ = self.run_main("m11")
        self.assertIn("kept image scratch:lab-m11-x (repo is in a prod compose)", out)


    def test_unreadable_compose_refuses_image_removal_and_removes_nothing(self):
        if os.geteuid() == 0:
            self.skipTest("root reads everything")
        p = os.path.join(self.stacks, "app", "docker-compose.yml")
        os.chmod(p, 0)
        rc, _, err = self.run_main("m11", "--yes")
        os.chmod(p, 0o644)
        self.assertEqual(rc, 2)
        self.assertIn("cannot read", err)
        self.assertEqual(self.removals(), [])

    def test_docker_failure_is_reported_not_swallowed(self):
        os.remove(os.path.join(self.tmp.name, "world.json"))
        rc, _, err = self.run_main("m11", "--yes")
        self.assertNotEqual(rc, 0)
        self.assertEqual(self.removals(), [])


class Arguments(Base):
    def cli(self, *argv):
        return subprocess.run([sys.executable, SCRIPT, *argv], capture_output=True, text=True, env=self.env)

    def test_bad_arguments_are_refused_before_docker_is_called(self):
        bad = ["2026", "2026-11", "door-widened", "m11-x", "m1x", "2026-1-x", "m" + "1" * 60, "2026-11-" + "x" * 60,
               "m11 caddy", "m11;ls", "m11&&ls", "$(id)", "m 11", "lab", "caddy", "M11", "m11/x", "m11*", "../m11",
               "m11--x", "-m11", "m11-", "", "m", "m11\n"]
        for a in bad:
            with self.subTest(arg=a):
                r = self.cli(a, "--yes")
                self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
                self.assertIn("lab-clean:", r.stderr)
        self.assertEqual(self.calls(), [])

    def test_slug_length_limit_is_60_inclusive(self):
        self.assertEqual(self.cli("2026-11-" + "x" * 52).returncode, 0)
        self.assertEqual(self.cli("2026-11-" + "x" * 53).returncode, 2)

    def test_a_second_name_is_refused(self):
        r = self.cli("m11", "m12", "--yes")
        self.assertEqual(r.returncode, 2)
        self.assertIn("one slug only", r.stderr)
        self.assertEqual(self.calls(), [])

    def test_unknown_options_and_conflicting_flags_are_refused(self):
        for argv in (["m11", "--force"], ["m11", "-f"], ["m11", "--yes", "--dry-run"], ["--yes"], []):
            with self.subTest(argv=argv):
                self.assertEqual(self.cli(*argv).returncode, 2)
        self.assertEqual(self.calls(), [])

    def test_cli_dry_run_end_to_end(self):
        r = self.cli("m11")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("would remove 2 container(s)", r.stdout)
        self.assertEqual(self.removals(), [])


if __name__ == "__main__":
    unittest.main()
