#!/usr/bin/env python3
# s2chitni & Claude (AI-generated)
"""Tests of dora_soc.py, the checks of DORA's Chipyard driver (dora/Makefile).

Everything here is synthetic and lives in a temporary directory under
``TMPDIR``: small git repositories stand in for ``DORA_ROOT``, Chipyard (with
a gitlink pinning ``generators/dora``) and ``generators/dora``, a hand-made
``DORA_OUT`` (manifest, interchange stub, cells, header) stands in for a
``static_hycube.build --soc`` render, and a hand-written CHIRRTL module for
the SoC's. No DORA checkout, JVM or simulator is needed. Run: ``make -C <this
dir> test``.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
TOOL = HERE / "dora_soc.py"

GIT_ID = ["-c", "user.name=dora-soc-test", "-c", "user.email=dora-soc-test@invalid"]


def _run_tool(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(TOOL), *args], capture_output=True, text=True, timeout=120
    )


def _git(directory: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *GIT_ID, "-C", str(directory), *args],
        capture_output=True,
        text=True,
        check=True,
        timeout=120,
    )
    return result.stdout.strip()


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Repos:
    """A DORA-like repository with two commits, and a Chipyard-like repository
    whose ``generators/dora`` is a clone of it at the first commit, pinned there
    by a committed gitlink."""

    def __init__(self, root: Path) -> None:
        self.origin = root / "dora"
        self.origin.mkdir()
        _git(self.origin, "init", "-q", "-b", "main")
        (self.origin / "scripts").mkdir()
        (self.origin / "scripts" / "dora-run").write_text("#!/bin/sh\n")
        build = self.origin / "examples" / "architectures" / "static_hycube"
        build.mkdir(parents=True)
        (build / "build.py").write_text("# build\n")
        (self.origin / "dora.chisel").mkdir()
        (self.origin / "dora.chisel" / "A.scala").write_text("object A\n")
        (self.origin / ".gitignore").write_text("ignored/\n")
        _git(self.origin, "add", "-A")
        _git(self.origin, "commit", "-q", "-m", "first")
        self.first = _git(self.origin, "rev-parse", "HEAD")
        (self.origin / "README").write_text("second\n")
        _git(self.origin, "add", "-A")
        _git(self.origin, "commit", "-q", "-m", "second")
        self.second = _git(self.origin, "rev-parse", "HEAD")
        # Chipyard's generators/dora, at the first commit.
        self.chipyard = root / "chipyard"
        (self.chipyard / "generators").mkdir(parents=True)
        self.submodule = self.chipyard / "generators" / "dora"
        _git(root, "clone", "-q", str(self.origin), str(self.submodule))
        _git(self.submodule, "checkout", "-q", self.first)
        _git(self.chipyard, "init", "-q", "-b", "main")
        (self.chipyard / "build.sbt").write_text("// chipyard\n")
        _git(self.chipyard, "add", "build.sbt")
        self.stage_pin(self.first)
        _git(self.chipyard, "commit", "-q", "-m", "pin generators/dora")

    def stage_pin(self, commit: str) -> None:
        """Stage the gitlink generators/dora -> ``commit`` in Chipyard."""
        _git(
            self.chipyard,
            "update-index",
            "--add",
            "--cacheinfo",
            f"160000,{commit},generators/dora",
        )

    def bump_pin(self, commit: str, *, commit_it: bool) -> None:
        """Check ``commit`` out in generators/dora and stage (and commit) the pin."""
        _git(self.submodule, "checkout", "-q", commit)
        self.stage_pin(commit)
        if commit_it:
            _git(self.chipyard, "commit", "-q", "-m", "bump generators/dora")

    def root_at(self, commit: str, name: str) -> Path:
        """A clean clone of the repository at ``commit`` (a DORA_ROOT)."""
        clone = self.origin.parent / name
        _git(self.origin.parent, "clone", "-q", str(self.origin), str(clone))
        _git(clone, "checkout", "-q", commit)
        return clone


class CheckRootTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="dora-soc-test-", dir=os.environ.get("TMPDIR"))
        self.addCleanup(self.tmp.cleanup)
        self.repos = Repos(Path(self.tmp.name))

    def check(self, root: Path, *extra: str) -> subprocess.CompletedProcess[str]:
        return _run_tool(
            "check-root",
            "--dora-root",
            str(root),
            "--submodule",
            str(self.repos.submodule),
            "--chipyard-root",
            str(self.repos.chipyard),
            *extra,
        )

    def assertRefused(self, result: subprocess.CompletedProcess[str], *needles: str) -> None:
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        for needle in needles:
            self.assertIn(needle, result.stderr)

    def test_same_commit_and_clean_passes(self) -> None:
        root = self.repos.root_at(self.repos.first, "root")
        result = self.check(root)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("matches generators/dora", result.stdout)
        self.assertNotIn("DEVELOPMENT OVERRIDE", result.stderr)

    def test_other_commit_is_refused(self) -> None:
        root = self.repos.root_at(self.repos.second, "root")
        self.assertRefused(self.check(root), "different commits", self.repos.second, self.repos.first)

    def test_committed_pin_bump_passes(self) -> None:
        self.repos.bump_pin(self.repos.second, commit_it=True)
        root = self.repos.root_at(self.repos.second, "root")
        result = self.check(root)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"matches generators/dora {self.repos.second}", result.stdout)

    def test_checkout_without_a_pin_bump_is_refused(self) -> None:
        # generators/dora and DORA_ROOT agree, but Chipyard still pins the first commit.
        _git(self.repos.submodule, "checkout", "-q", self.repos.second)
        root = self.repos.root_at(self.repos.second, "root")
        result = self.check(root)
        self.assertRefused(result, f"Chipyard's HEAD pins it to {self.repos.first}", "commit the pin bump")
        self.assertNotIn("different commits", result.stderr)
        dev = self.check(root, "--allow-dev")
        self.assertEqual(dev.returncode, 0, dev.stderr)
        self.assertIn("DEVELOPMENT OVERRIDE", dev.stderr)
        self.assertIn("Chipyard's HEAD pins it to", dev.stderr)

    def test_staged_pin_bump_is_refused(self) -> None:
        self.repos.bump_pin(self.repos.second, commit_it=False)
        root = self.repos.root_at(self.repos.second, "root")
        self.assertRefused(
            self.check(root),
            f"a pin bump of generators/dora to {self.repos.second} is staged but not committed",
            f"Chipyard's HEAD pins it to {self.repos.first}",
        )

    def test_chipyard_root_without_git_is_refused(self) -> None:
        root = self.repos.root_at(self.repos.first, "root")
        bare = Path(self.tmp.name) / "not-chipyard"
        (bare / "generators").mkdir(parents=True)
        result = _run_tool(
            "check-root",
            "--dora-root",
            str(root),
            "--submodule",
            str(self.repos.submodule),
            "--chipyard-root",
            str(bare),
            "--allow-dev",
        )
        self.assertRefused(result, "is not a git checkout")

    def test_modified_tracked_file_is_refused(self) -> None:
        root = self.repos.root_at(self.repos.first, "root")
        (root / "dora.chisel" / "A.scala").write_text("object A { val x = 1 }\n")
        self.assertRefused(self.check(root), "uncommitted or untracked", "dora.chisel/A.scala")

    def test_untracked_file_is_refused(self) -> None:
        root = self.repos.root_at(self.repos.first, "root")
        (root / "new_template.sv").write_text("module m; endmodule\n")
        self.assertRefused(self.check(root), "new_template.sv")

    def test_ignored_file_is_not_dirt(self) -> None:
        root = self.repos.root_at(self.repos.first, "root")
        (root / "ignored").mkdir()
        (root / "ignored" / "scratch").write_text("x\n")
        self.assertEqual(self.check(root).returncode, 0)

    def test_dirty_glue_in_the_submodule_is_refused(self) -> None:
        root = self.repos.root_at(self.repos.first, "root")
        (self.repos.submodule / "dora.chisel" / "A.scala").write_text("object A // synced\n")
        self.assertRefused(self.check(root), "generators/dora has uncommitted dora.chisel/")

    def test_development_override_warns_and_passes(self) -> None:
        root = self.repos.root_at(self.repos.second, "root")
        (root / "untracked.txt").write_text("x\n")
        result = self.check(root, "--allow-dev")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("DORA_GEN_ALLOW_DEV=1: DEVELOPMENT OVERRIDE", result.stderr)
        self.assertIn("different commits", result.stderr)
        self.assertIn("untracked.txt", result.stderr)
        self.assertIn("DOES NOT match", result.stdout)

    def test_missing_root_is_refused_even_with_the_override(self) -> None:
        missing = Path(self.tmp.name) / "no-such-dora"
        for extra in ((), ("--allow-dev",)):
            self.assertRefused(self.check(missing, *extra), "does not exist")

    def test_relative_root_is_refused(self) -> None:
        self.assertRefused(self.check(Path("dora")), "absolute")

    def test_submodule_as_root_is_refused(self) -> None:
        self.assertRefused(self.check(self.repos.submodule, "--allow-dev"), "nested submodules")

    def test_subdirectory_of_a_checkout_is_refused(self) -> None:
        root = self.repos.root_at(self.repos.first, "root")
        self.assertRefused(self.check(root / "dora.chisel"), "not the top of its checkout")

    def test_non_dora_checkout_is_refused(self) -> None:
        other = Path(self.tmp.name) / "other"
        other.mkdir()
        _git(other, "init", "-q")
        self.assertRefused(self.check(other, "--allow-dev"), "is it a DORA checkout")

    def test_uninitialized_submodule_is_refused(self) -> None:
        root = self.repos.root_at(self.repos.first, "root")
        empty = self.repos.chipyard / "generators" / "empty"
        empty.mkdir()
        result = _run_tool(
            "check-root",
            "--dora-root",
            str(root),
            "--submodule",
            str(empty),
            "--chipyard-root",
            str(self.repos.chipyard),
            "--allow-dev",
        )
        self.assertRefused(result, "is not initialized")


class Render:
    """A synthetic DORA_OUT with a manifest that matches its files."""

    def __init__(self, out: Path, producer_sha: str) -> None:
        self.out = out
        (out / "hdl" / "cells").mkdir(parents=True)
        (out / "sw").mkdir()
        for width in (1, 32):
            (out / "hdl" / "cells" / f"dora_comb_cut_w{width}.sv").write_text(
                f"module dora_comb_cut_w{width}(); endmodule\n"
            )
        (out / "sw" / "dora_hycube_array.h").write_text("/* header */\n")
        (out / "sw" / "k3_mem_axpy.bin").write_bytes(b"\x01\x02")
        (out / "sw" / "k3_mem_axpy.json").write_text('{"writes":[[5,1,128,7]]}\n')
        self.doc: dict[str, Any] = {
            "schema": {"name": "dora.static_hycube.soc", "version": 1},
            "top": "hycube_array",
            "module_prefix": "dora_hycube_array_",
            "header_name": "dora_hycube_array.h",
            "hardware_digest": "sha256:" + "a" * 64,
            "k3": {"skipped": None, "run_cycles": 42, "last_write_cycle": 28, "mem_writes": 24},
            "producer": {"dora_git_sha": producer_sha, "dirty": False},
        }
        self.write_interchange()
        self.write()

    def write_interchange(self) -> None:
        cells = [
            {
                "module": f"dora_comb_cut_w{width}",
                "width": width,
                "sv": f"cells/dora_comb_cut_w{width}.sv",
                "sha256": _sha(self.out / "hdl" / "cells" / f"dora_comb_cut_w{width}.sv"),
            }
            for width in (1, 32)
        ]
        (self.out / "hdl" / "hycube_array.dnl.json").write_text(json.dumps({"cells": cells}) + "\n")

    def write(self) -> None:
        paths = {
            "interchange": "hdl/hycube_array.dnl.json",
            "header": "sw/dora_hycube_array.h",
            "cell_w1": "hdl/cells/dora_comb_cut_w1.sv",
            "cell_w32": "hdl/cells/dora_comb_cut_w32.sv",
            "k3_image": "sw/k3_mem_axpy.bin",
            "k3_reference": "sw/k3_mem_axpy.json",
        }
        self.doc["files"] = {
            key: {"path": rel, "sha256": _sha(self.out / rel)} for key, rel in paths.items()
        }
        (self.out / "soc.json").write_text(json.dumps(self.doc, sort_keys=True) + "\n")


class ManifestTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="dora-soc-test-", dir=os.environ.get("TMPDIR"))
        self.addCleanup(self.tmp.cleanup)
        self.repos = Repos(Path(self.tmp.name))
        self.render = Render(Path(self.tmp.name) / "out", self.repos.first)

    def verify(self, *extra: str) -> subprocess.CompletedProcess[str]:
        return _run_tool(
            "verify",
            "--out",
            str(self.render.out),
            "--top",
            "hycube_array",
            "--submodule",
            str(self.repos.submodule),
            "--chipyard-root",
            str(self.repos.chipyard),
            *extra,
        )

    def assertRefused(self, result: subprocess.CompletedProcess[str], needle: str) -> None:
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn(needle, result.stderr)

    def test_consistent_render_passes(self) -> None:
        result = self.verify()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("every file matches soc.json", result.stdout)

    def test_edited_file_is_refused(self) -> None:
        (self.render.out / "sw" / "dora_hycube_array.h").write_text("/* edited */\n")
        self.assertRefused(self.verify(), "changed after the render")

    def test_missing_manifest_is_refused(self) -> None:
        (self.render.out / "soc.json").unlink()
        self.assertRefused(self.verify("--allow-dev"), "not a complete DORA --soc render")

    def test_missing_file_is_refused(self) -> None:
        (self.render.out / "sw" / "k3_mem_axpy.bin").unlink()
        self.assertRefused(self.verify(), "does not exist")

    def test_stray_cell_is_refused(self) -> None:
        (self.render.out / "hdl" / "cells" / "dora_comb_cut_w8.sv").write_text("stale\n")
        self.assertRefused(self.verify(), "render DORA_OUT again")

    def test_cell_not_in_the_interchange_is_refused(self) -> None:
        cell = self.render.out / "hdl" / "cells" / "dora_comb_cut_w1.sv"
        cell.write_text("module dora_comb_cut_w1(input x); endmodule\n")
        self.render.write()  # the manifest follows, the interchange does not
        self.assertRefused(self.verify(), "cells[].sha256")

    def test_escaping_path_is_refused(self) -> None:
        self.render.doc["files"]["k3_image"]["path"] = "../out/sw/k3_mem_axpy.bin"
        (self.render.out / "soc.json").write_text(json.dumps(self.render.doc) + "\n")
        self.assertRefused(self.verify(), "relative path inside DORA_OUT")

    def test_other_schema_is_refused(self) -> None:
        self.render.doc["schema"]["version"] = 2
        self.render.write()
        self.assertRefused(self.verify(), "this driver reads")

    def test_other_top_is_refused(self) -> None:
        result = _run_tool("verify", "--out", str(self.render.out), "--top", "other_top")
        self.assertRefused(result, "expects 'other_top'")

    def test_skipped_kernel_is_refused(self) -> None:
        self.render.doc["k3"] = {"skipped": "K3 needs at least 4x3 PEs"}
        self.render.write()
        self.assertRefused(self.verify(), "no K3 kernel: K3 needs at least 4x3 PEs")

    def test_producer_at_another_commit_is_refused(self) -> None:
        self.render.doc["producer"]["dora_git_sha"] = self.repos.second
        self.render.write()
        self.assertRefused(self.verify(), "was rendered by DORA")

    def test_producer_at_an_uncommitted_pin_is_refused(self) -> None:
        # The render and generators/dora agree, but Chipyard's HEAD pins the first commit.
        _git(self.repos.submodule, "checkout", "-q", self.repos.second)
        self.render.doc["producer"]["dora_git_sha"] = self.repos.second
        self.render.write()
        self.assertRefused(self.verify(), "commit the pin bump")
        self.repos.bump_pin(self.repos.second, commit_it=True)
        result = self.verify()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_submodule_without_chipyard_root_is_refused(self) -> None:
        result = _run_tool(
            "verify", "--out", str(self.render.out), "--submodule", str(self.repos.submodule)
        )
        self.assertRefused(result, "needs --chipyard-root")

    def test_dirty_producer_is_refused_and_the_override_warns(self) -> None:
        self.render.doc["producer"]["dirty"] = True
        self.render.write()
        self.assertRefused(self.verify(), "dirty=True")
        result = self.verify("--allow-dev")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("DEVELOPMENT OVERRIDE of the DORA_OUT producer check", result.stderr)

    def test_structural_checks_need_no_submodule(self) -> None:
        self.render.doc["producer"]["dirty"] = True
        self.render.write()
        result = _run_tool("verify", "--out", str(self.render.out))
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_relative_out_is_refused(self) -> None:
        self.assertRefused(_run_tool("verify", "--out", "out"), "absolute")

    def test_get_values(self) -> None:
        out = str(self.render.out)
        self.assertEqual(_run_tool("get", "--out", out, "module_prefix").stdout.strip(), "dora_hycube_array_")
        self.assertEqual(
            _run_tool("get", "--out", out, "interchange").stdout.strip(),
            str((self.render.out / "hdl" / "hycube_array.dnl.json").resolve()),
        )
        cells = _run_tool("get", "--out", out, "cells").stdout.split()
        self.assertEqual([Path(c).name for c in cells], ["dora_comb_cut_w1.sv", "dora_comb_cut_w32.sv"])


class StampTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="dora-soc-test-", dir=os.environ.get("TMPDIR"))
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.render = Render(root / "out", "0" * 40)
        self.stamp = root / "stamps" / "Config.stamp"

    def write_stamp(self, out: Path) -> subprocess.CompletedProcess[str]:
        result = _run_tool("stamp", "--out", str(out), "--stamp", str(self.stamp))
        self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def age_stamp(self) -> float:
        old = time.time() - 3600
        os.utime(self.stamp, (old, old))
        return self.stamp.stat().st_mtime

    def test_rewritten_only_when_the_fabric_changes(self) -> None:
        self.assertIn("rewritten", self.write_stamp(self.render.out).stdout)
        content = self.stamp.read_text()
        self.assertIn(str((self.render.out / "hdl" / "hycube_array.dnl.json").resolve()), content)
        self.assertIn("cells/dora_comb_cut_w32.sv", content)
        before = self.age_stamp()
        self.assertIn("unchanged", self.write_stamp(self.render.out).stdout)
        self.assertEqual(self.stamp.stat().st_mtime, before)
        # A new cell body (a new render) rewrites it.
        cell = self.render.out / "hdl" / "cells" / "dora_comb_cut_w1.sv"
        cell.write_text("module dora_comb_cut_w1(input a); endmodule\n")
        self.render.write_interchange()
        self.render.write()
        self.assertIn("rewritten", self.write_stamp(self.render.out).stdout)
        self.assertGreater(self.stamp.stat().st_mtime, before)

    def test_another_render_with_the_same_content_rewrites_it(self) -> None:
        self.write_stamp(self.render.out)
        before = self.age_stamp()
        other = Render(Path(self.tmp.name) / "other", "0" * 40)
        self.assertIn("rewritten", self.write_stamp(other.out).stdout)
        self.assertGreater(self.stamp.stat().st_mtime, before)

    def test_check_accepts_only_a_soc_generated_after_this_fabric(self) -> None:
        generated = Path(self.tmp.name) / "soc.fir"
        check = ("stamp", "--out", str(self.render.out), "--stamp", str(self.stamp), "--check", str(generated))
        missing = _run_tool(*check)
        self.assertEqual(missing.returncode, 1)
        self.assertIn("names another fabric or is missing", missing.stderr)
        self.write_stamp(self.render.out)
        self.age_stamp()
        generated.write_text("circuit\n")
        self.assertEqual(_run_tool(*check).returncode, 0)
        old = self.stamp.stat().st_mtime - 60
        os.utime(generated, (old, old))
        stale = _run_tool(*check)
        self.assertEqual(stale.returncode, 1)
        self.assertIn("older than the fabric stamp", stale.stderr)
        other = Render(Path(self.tmp.name) / "other", "0" * 40)
        self.write_stamp(other.out)
        switched = _run_tool(*check)
        self.assertEqual(switched.returncode, 1)
        self.assertIn("names another fabric", switched.stderr)


def _wiring_interchange() -> dict[str, Any]:
    """A two-memory-port fabric's top ports and roles, as the interchange has them."""
    ports = [
        ("clk_i", "in", "clock"),
        ("prog_clk_i", "in", "prog.clock"),
        ("reset_i", "in", "reset"),
        ("en_i", "in", "enable"),
        ("prog_rst_i", "in", "prog.reset"),
        ("prog_done_i", "in", "prog.done"),
        ("prog_we_i", "in", "scan.we_in"),
        ("prog_din_i", "in", "scan.din"),
        ("prog_dout_o", "out", "scan.dout"),
        ("prog_we_o", "out", "scan.we_out"),
        ("ipin_0", "in", "io.in"),
        ("opin_0", "out", "io.out"),
    ]
    roles: dict[str, dict[str, Any]] = {name: {"role": role} for name, _, role in ports}
    top_ports = [{"n": name, "d": d, "w": 1, "k": "data"} for name, d, _ in ports]
    for port in (0, 1):
        for name, d, role in (
            (f"addr_to_ram_{port}", "out", "mem.addr"),
            (f"data_to_ram_{port}", "out", "mem.wdata"),
            (f"ram_we_{port}", "out", "mem.we"),
            (f"data_from_ram_{port}", "in", "mem.rdata"),
        ):
            roles[name] = {"role": role, "port": port}
            top_ports.append({"n": name, "d": d, "w": 32, "k": "data"})
    return {
        "top": "fab",
        "modules": [{"name": "fab", "ports": top_ports}],
        "integration": {"roles": roles},
    }


WIRING_FIR = """FIRRTL version 4.1.0
circuit TestHarness :
  module dora_x_fab : @[Fab.scala 1:1]
    input clk_i : Clock
  module DoraShellController : @[DoraShellController.scala 1:1]
    input clock : Clock
  module DoraFabricTL : @[DoraFabricTL.scala 56:9]
    input clock : Clock
    inst fabric of dora_x_fab @[DoraFabricTL.scala 71:24]
    inst shell of DoraShellController @[DoraFabricTL.scala 79:23]
    connect shell.clock, clock
    connect fabric.ipin_0, UInt<1>(0h0) @[DoraFabricTL.scala 100:60]
    connect fabric.clk_i, clock @[DoraFabricTL.scala 93:60]
    connect fabric.reset_i, shell.io.fabric.reset @[DoraFabricTL.scala 94:60]
    connect fabric.en_i, shell.io.fabric.en @[DoraFabricTL.scala 96:60]
    connect fabric.data_from_ram_0, shell.io.fabric.mem[0].rdata @[DoraFabricTL.scala 101:60]
    connect fabric.data_from_ram_1, shell.io.fabric.mem[1].rdata @[DoraFabricTL.scala 101:60]
    connect fabric.prog_clk_i, clock @[DoraFabricTL.scala 93:60]
    connect fabric.prog_rst_i, shell.io.fabric.progRst @[DoraFabricTL.scala 95:60]
    connect fabric.prog_done_i, shell.io.fabric.progDone @[DoraFabricTL.scala 97:60]
    connect fabric.prog_we_i, shell.io.fabric.progWe @[DoraFabricTL.scala 98:60]
    connect fabric.prog_din_i, shell.io.fabric.progDin @[DoraFabricTL.scala 99:60]
    connect shell.io.fabric.mem[0].addr, fabric.addr_to_ram_0 @[DoraFabricTL.scala 109:17]
    connect shell.io.fabric.mem[0].wdata, fabric.data_to_ram_0 @[DoraFabricTL.scala 110:18]
    node _shell_io_fabric_mem_0_we_T = bits(fabric.ram_we_0, 0, 0) @[DoraFabricTL.scala 111:29]
    connect shell.io.fabric.mem[0].we, _shell_io_fabric_mem_0_we_T @[DoraFabricTL.scala 111:15]
    connect shell.io.fabric.mem[1].addr, fabric.addr_to_ram_1 @[DoraFabricTL.scala 109:17]
    connect shell.io.fabric.mem[1].wdata, fabric.data_to_ram_1 @[DoraFabricTL.scala 110:18]
    node _shell_io_fabric_mem_1_we_T = bits(fabric.ram_we_1, 0, 0) @[DoraFabricTL.scala 111:29]
    connect shell.io.fabric.mem[1].we, _shell_io_fabric_mem_1_we_T @[DoraFabricTL.scala 111:15]
    connect shell.io.host.scanCtrl.valid, UInt<1>(0h0) @[DoraShellRegisters.scala 47:25]
  module Other :
    input clock : Clock
"""


class WiringTest(unittest.TestCase):
    """``wiring``: the CHIRRTL around the fabric against the interchange's roles."""

    def setUp(self) -> None:
        sys.path.insert(0, str(HERE))
        self.addCleanup(sys.path.remove, str(HERE))
        import dora_soc

        self.problems = dora_soc.wiring_problems
        self.interchange = _wiring_interchange()

    def check(self, text: str) -> list[str]:
        problems, _ = self.problems(self.interchange, "dora_x_", text)
        return problems

    def test_the_shell_wiring_passes(self) -> None:
        problems, compared = self.problems(self.interchange, "dora_x_", WIRING_FIR)
        self.assertEqual(problems, [])
        self.assertEqual(compared, 11 + 2 * 3)  # 11 inputs, 3 shell inputs per port

    def mutated(self, old: str, new: str) -> list[str]:
        self.assertIn(old, WIRING_FIR)
        return self.check(WIRING_FIR.replace(old, new))

    def test_swapped_read_data_is_caught(self) -> None:
        problems = self.mutated(
            "connect fabric.data_from_ram_1, shell.io.fabric.mem[1].rdata",
            "connect fabric.data_from_ram_1, shell.io.fabric.mem[0].rdata",
        )
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("data_from_ram_1 (role mem.rdata) is driven by shell.io.fabric.mem[0].rdata", problems[0])

    def test_wrong_write_enable_is_caught(self) -> None:
        problems = self.mutated("bits(fabric.ram_we_1, 0, 0)", "bits(fabric.ram_we_0, 0, 0)")
        self.assertIn("shell.io.fabric.mem[1].we is driven by fabric.ram_we_0, expected fabric.ram_we_1", problems)

    def test_a_pad_not_tied_to_zero_is_caught(self) -> None:
        problems = self.mutated("connect fabric.ipin_0, UInt<1>(0h0)", "connect fabric.ipin_0, UInt<1>(0h1)")
        self.assertEqual(problems, ["fabric.ipin_0 (role io.in) is driven by UInt<1>(0h1), expected 0"])

    def test_a_missing_or_doubled_connection_is_caught(self) -> None:
        self.assertEqual(
            self.mutated("    connect fabric.prog_din_i, shell.io.fabric.progDin @[DoraFabricTL.scala 99:60]\n", ""),
            ["fabric.prog_din_i is connected 0 times, not once"],
        )
        doubled = WIRING_FIR.replace(
            "    connect fabric.en_i, shell.io.fabric.en",
            "    connect fabric.en_i, shell.io.fabric.reset\n    connect fabric.en_i, shell.io.fabric.en",
        )
        self.assertEqual(self.check(doubled), ["fabric.en_i is connected 2 times, not once"])

    def test_reading_another_output_is_caught(self) -> None:
        problems = self.mutated(
            "connect shell.io.fabric.mem[0].wdata, fabric.data_to_ram_0",
            "connect shell.io.fabric.mem[0].wdata, fabric.opin_0",
        )
        self.assertIn("shell.io.fabric.mem[0].wdata is driven by fabric.opin_0, expected fabric.data_to_ram_0", problems)
        self.assertIn(
            "fabric output opin_0 (role io.out) is read; the shell reads only the memory ports", problems
        )

    def test_the_fabric_must_be_instantiated_once(self) -> None:
        problems = self.check(WIRING_FIR.replace("inst fabric of dora_x_fab", "inst fabric of dora_y_fab"))
        self.assertEqual(len(problems), 1)
        self.assertIn("0 modules instantiate `fabric` of dora_x_fab", problems[0])

    def test_the_command_line_reads_the_render_and_the_fir(self) -> None:
        with tempfile.TemporaryDirectory(prefix="dora-soc-test-", dir=os.environ.get("TMPDIR")) as tmp:
            render = Render(Path(tmp) / "out", "0" * 40)
            interchange = render.out / "hdl" / "hycube_array.dnl.json"
            doc = json.loads(interchange.read_text())
            wiring = _wiring_interchange()
            wiring["modules"][0]["name"] = wiring["top"] = "hycube_array"
            doc.update(wiring)
            interchange.write_text(json.dumps(doc) + "\n")
            render.write()
            fir = Path(tmp) / "soc.fir"
            fir.write_text(WIRING_FIR.replace("dora_x_fab", "dora_hycube_array_hycube_array"))
            ok = _run_tool("wiring", "--out", str(render.out), "--firrtl", str(fir))
            self.assertEqual(ok.returncode, 0, ok.stderr)
            self.assertIn("17 connections compared", ok.stdout)
            fir.write_text(fir.read_text().replace("mem[1].rdata", "mem[0].rdata"))
            bad = _run_tool("wiring", "--out", str(render.out), "--firrtl", str(fir))
            self.assertEqual(bad.returncode, 1)
            self.assertIn("differs from the interchange's roles", bad.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
