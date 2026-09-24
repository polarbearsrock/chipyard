#!/usr/bin/env python3
# s2chitni & Claude (AI-generated)
"""Checks and helpers for DORA's Chipyard driver (``dora/Makefile``).

DORA's Chisel pilot (step 5) renders a static HyCUBE fabric with a separate,
full DORA checkout (``DORA_ROOT``) into ``DORA_OUT`` and elaborates it in
Chipyard with the ``dora.chisel`` classes compiled from ``generators/dora``.
This tool keeps the two consistent and gives the Makefile what it needs; it
uses only the Python standard library (Chipyard's conda Python) and never
imports DORA.

Subcommands:

``check-root``
    ``gen``'s precondition: ``DORA_ROOT`` is a DORA checkout (its top level,
    not ``generators/dora``) at the pinned commit, with a clean tree (``git
    status --porcelain`` empty, the rule DORA's interchange producer uses for
    ``dirty``), and ``generators/dora``'s ``dora.chisel/`` has no uncommitted
    change (``chipyard.jar`` is built from it). The pinned commit is the one
    Chipyard's ``HEAD`` records for ``generators/dora`` (the gitlink, ``git
    ls-tree HEAD``); ``generators/dora`` must be checked out at it, and no
    other pin may be staged, so the render is reproducible from a Chipyard
    commit. ``--allow-dev`` (``DORA_GEN_ALLOW_DEV=1``) turns the commit, pin
    and cleanness refusals into a loud warning for development; a missing or
    malformed checkout is refused either way.
``verify``
    ``DORA_OUT/soc.json``, the manifest ``static_hycube.build --soc`` writes:
    schema, top, files present with their SHA-256 (the interchange, header,
    cut cells, K3 image and reference), the cut cells equal to the
    interchange's ``cells[]`` and to ``hdl/cells/*.sv``, K3 present, and,
    with ``--submodule``, a producer that is the pinned commit (as above)
    and clean (``--allow-dev`` warns instead).
``stamp``
    The content stamp of the fabric for ``EXTRA_GENERATOR_REQS``: the
    interchange's absolute path and the SHA-256 of the interchange and cells,
    rewritten only when they change. make compares times, not contents, and
    Chipyard's build directory depends only on ``CONFIG``, so without it
    switching ``DORA_FABRIC`` to an older render would keep the old fabric.
    ``--check GENERATED`` instead checks that the stamp matches ``DORA_OUT``
    and is older than ``GENERATED`` (the SoC's FIRRTL), i.e. that the SoC was
    generated from this fabric.
``get``
    One value of the manifest, for the Makefile: ``module_prefix``, ``top``,
    ``interchange``, ``header`` or ``cells`` (absolute paths).
``mock-test``
    Builds ``tests/dora-static-hycube.c`` and ``tests/dora-runtime.c`` for the
    host against ``mock-shell.c`` (a model of the shell ABI) and runs it
    faithfully (it must print PASS) and with each injected fault (each must
    print FAIL).
``wiring``
    The shell-to-fabric wiring in the SoC's CHIRRTL (``--firrtl``, the
    ``.fir`` Chipyard's generator writes) against the interchange's
    ``integration.roles``: in the module that instantiates the fabric
    (``inst fabric of <module_prefix><top>``), every fabric input is
    connected once, from the source its role names (the shell's clock,
    ``shell.io.fabric.<signal>``, 0 for an IO pad, ``shell.io.fabric.mem[p]
    .rdata`` for memory port ``p``'s read data); every
    ``shell.io.fabric.mem[p]`` input is connected once, from port ``p``'s
    ``mem.addr``, ``mem.wdata`` and ``mem.we`` outputs; and no other fabric
    output is read. DORA's checker compares the fabric itself; this compares
    what surrounds it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any, NoReturn, Optional, Sequence

sys.dont_write_bytecode = True

SCHEMA = {"name": "dora.static_hycube.soc", "version": 1}
REQUIRED_FILES = ("interchange", "header", "k3_image", "k3_reference")
PASS_LINE = "DORA K3 mem_axpy: PASS"
FAIL_LINE = "DORA K3 mem_axpy: FAIL ("
DEV_VARIABLE = "DORA_GEN_ALLOW_DEV"


class DriverError(Exception):
    """A refusal, reported as ``dora_soc: error: ...`` with exit status 1."""


def _fail(message: str) -> NoReturn:
    raise DriverError(message)


def _git(directory: Path, *args: str) -> str:
    """Run git in ``directory``; its stdout, or DriverError."""
    try:
        result = subprocess.run(
            ["git", "-C", str(directory), *args],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        _fail(f"git {' '.join(args)} in {directory} failed: {exc}")
    if result.returncode != 0:
        _fail(
            f"git {' '.join(args)} in {directory} failed: "
            f"{result.stderr.strip() or result.stdout.strip()}"
        )
    return result.stdout


def _head(directory: Path, what: str) -> str:
    if not (directory / ".git").exists():
        _fail(f"{what} {directory} is not a git checkout (no .git)")
    return _git(directory, "rev-parse", "HEAD").strip()


def _dirty(directory: Path, *paths: str) -> list[str]:
    status = _git(directory, "status", "--porcelain", *(["--", *paths] if paths else []))
    return [line for line in status.splitlines() if line.strip()]


def _listing(lines: list[str], limit: int = 8) -> str:
    shown = [f"      {line}" for line in lines[:limit]]
    if len(lines) > limit:
        shown.append(f"      ... and {len(lines) - limit} more")
    return "\n".join(shown)


def _warn_dev(problems: list[str], what: str) -> None:
    bar = "*" * 78
    lines = [
        bar,
        f"* {DEV_VARIABLE}=1: DEVELOPMENT OVERRIDE of the {what} check.",
        "* The DORA render does NOT come from the commit generators/dora is pinned to:",
    ]
    for problem in problems:
        lines.extend(f"*   {line}" for line in problem.splitlines())
    lines.extend(
        [
            "* Nothing built from it is reproducible from the pins. Never use it as",
            "* evidence; DoraFabric's source-digest check still applies in the SoC.",
            bar,
        ]
    )
    print("\n".join(lines), file=sys.stderr)


def _refuse_or_warn(problems: list[str], allow_dev: bool, what: str, remedy: str) -> None:
    if not problems:
        return
    if allow_dev:
        _warn_dev(problems, what)
        return
    _fail(
        f"{what} check failed:\n  - "
        + "\n  - ".join(problems)
        + f"\n{remedy}\nFor development only, {DEV_VARIABLE}=1 downgrades this "
        "refusal to a warning."
    )


PIN_REMEDY = (
    "Render with the DORA commit Chipyard pins generators/dora to: commit DORA_ROOT's "
    "changes and check that commit out in both (bump the pin with "
    "`git -C generators/dora checkout <sha>`, `git add generators/dora` and a "
    "Chipyard commit, then rebuild chipyard.jar), or check out the pinned commit in "
    "DORA_ROOT and generators/dora."
)


def _gitlink(chipyard: Path, submodule: Path, *args: str) -> Optional[str]:
    """The commit a gitlink listing (``ls-tree HEAD`` or ``ls-files -s``) of
    Chipyard records for ``submodule``; None if it records none."""
    try:
        relative = submodule.resolve().relative_to(chipyard.resolve()).as_posix()
    except ValueError:
        _fail(f"{submodule} is not inside the Chipyard checkout {chipyard}")
    listing = _git(chipyard, *args, "--", relative).strip()
    if not listing:
        return None
    fields = listing.splitlines()[0].split()
    mode = fields[0]
    sha = fields[2] if args[0] == "ls-tree" else fields[1]
    if mode != "160000":
        _fail(f"Chipyard records {relative} as mode {mode}, not a submodule (gitlink)")
    return sha


def pin_problems(chipyard: Path, submodule: Path, head: str) -> list[str]:
    """Why ``submodule`` (checked out at ``head``) is not at the commit
    Chipyard's ``HEAD`` pins it to, or has another pin staged; empty if it is."""
    if not (chipyard / ".git").exists():
        _fail(f"CHIPYARD_ROOT {chipyard} is not a git checkout (no .git)")
    committed = _gitlink(chipyard, submodule, "ls-tree", "HEAD")
    staged = _gitlink(chipyard, submodule, "ls-files", "-s")
    problems = []
    if committed != head:
        problems.append(
            f"generators/dora is checked out at {head}, but Chipyard's HEAD pins it to "
            f"{committed} (the gitlink `git ls-tree HEAD generators/dora`); commit the "
            "pin bump"
        )
    if staged != committed:
        problems.append(
            f"a pin bump of generators/dora to {staged} is staged but not committed "
            f"(HEAD pins {committed})"
        )
    return problems


def check_root(dora_root: Path, submodule: Path, chipyard: Path, allow_dev: bool) -> None:
    """``gen``'s precondition; see the module docstring."""
    if not dora_root.is_absolute():
        _fail(f"DORA_ROOT={dora_root} must be an absolute path")
    if not dora_root.is_dir():
        _fail(
            f"DORA_ROOT={dora_root} does not exist: install a full DORA checkout "
            "outside Chipyard (git clone --recursive, then scripts/install -d) and "
            "point DORA_ROOT at it"
        )
    root = dora_root.resolve()
    if submodule.exists() and root == submodule.resolve():
        _fail(
            "DORA_ROOT is Chipyard's generators/dora, whose nested submodules are "
            "never initialized, so DORA's Python cannot run there; use a separate, "
            "full DORA checkout"
        )
    top = _git(root, "rev-parse", "--show-toplevel").strip()
    if Path(top).resolve() != root:
        _fail(f"DORA_ROOT={dora_root} is not the top of its checkout ({top})")
    for needed in ("scripts/dora-run", "examples/architectures/static_hycube/build.py"):
        if not (root / needed).is_file():
            _fail(f"DORA_ROOT={dora_root} has no {needed}; is it a DORA checkout?")
    if not (submodule / ".git").exists():
        _fail(
            f"{submodule} is not initialized: run "
            "`git submodule update --init generators/dora` in Chipyard"
        )

    root_head = _head(root, "DORA_ROOT")
    pin = _head(submodule, "generators/dora")
    problems = pin_problems(chipyard, submodule, pin)
    if root_head != pin:
        problems.append(
            f"DORA_ROOT is at {root_head}, generators/dora at {pin} (different commits)"
        )
    dirty = _dirty(root)
    if dirty:
        problems.append(
            f"DORA_ROOT has {len(dirty)} uncommitted or untracked paths:\n"
            + _listing(dirty)
        )
    glue = _dirty(submodule, "dora.chisel")
    if glue:
        problems.append(
            "generators/dora has uncommitted dora.chisel/ changes (chipyard.jar is "
            "built from them; scripts/dora-sync-glue.sh leaves them):\n" + _listing(glue)
        )
    _refuse_or_warn(problems, allow_dev, "DORA_ROOT", PIN_REMEDY)
    state = "matches" if not problems else "DOES NOT match (development override)"
    print(f"dora_soc: DORA_ROOT {root} at {root_head}: {state} generators/dora {pin}")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_json(path: Path, what: str) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        _fail(f"{what} {path} does not exist")
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        _fail(f"{what} {path} is not readable JSON: {exc}")


def _out_dir(value: Path) -> Path:
    if not value.is_absolute():
        _fail(f"DORA_OUT={value} must be an absolute path")
    if not value.is_dir():
        _fail(
            f"DORA_OUT={value} does not exist: render the fabric first "
            "(make -C generators/chipyard/src/test/resources/dora gen)"
        )
    return value.resolve()


def _relative_file(out: Path, key: str, entry: Any) -> tuple[Path, str]:
    if not isinstance(entry, dict) or set(entry) != {"path", "sha256"}:
        _fail(f"soc.json files.{key} must be an object with exactly path and sha256")
    rel = entry["path"]
    sha = entry["sha256"]
    if not isinstance(rel, str) or not isinstance(sha, str):
        _fail(f"soc.json files.{key}: path and sha256 must be strings")
    pure = PurePosixPath(rel)
    if not rel or pure.is_absolute() or ".." in pure.parts or "\\" in rel:
        _fail(f"soc.json files.{key}.path {rel!r} must be a relative path inside DORA_OUT")
    if not re.fullmatch(r"[0-9a-f]{64}", sha):
        _fail(f"soc.json files.{key}.sha256 {sha!r} is not a SHA-256")
    path = out / rel
    if not path.is_file():
        _fail(f"soc.json files.{key}: {path} does not exist")
    actual = _sha256(path)
    if actual != sha:
        _fail(
            f"{path} has sha256 {actual}, soc.json says {sha}: DORA_OUT was changed "
            "after the render; render it again"
        )
    return path, rel


class Manifest:
    """``DORA_OUT/soc.json``, verified against the files it names."""

    def __init__(self, out: Path, top: Optional[str] = None) -> None:
        self.out = _out_dir(out)
        if not (self.out / "soc.json").is_file():
            _fail(
                f"{self.out} has no soc.json: it is not a complete DORA --soc render "
                "(a failed gen removes it); run make gen"
            )
        doc = _load_json(self.out / "soc.json", "the SoC manifest")
        if not isinstance(doc, dict):
            _fail("soc.json must be a JSON object")
        self.doc = doc
        if doc.get("schema") != SCHEMA:
            _fail(f"soc.json schema is {doc.get('schema')!r}, this driver reads {SCHEMA!r}")
        self.top = doc.get("top")
        if not isinstance(self.top, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", self.top):
            _fail(f"soc.json top {self.top!r} is not a module name")
        if top is not None and self.top != top:
            _fail(f"DORA_OUT holds fabric {self.top!r}, the driver expects {top!r}")
        self.module_prefix = doc.get("module_prefix")
        if not isinstance(self.module_prefix, str) or not re.fullmatch(
            r"[A-Za-z_][A-Za-z0-9_]*", self.module_prefix
        ):
            _fail(f"soc.json module_prefix {self.module_prefix!r} is not a module-name prefix")

        files = doc.get("files")
        if not isinstance(files, dict):
            _fail("soc.json files must be an object")
        missing = [key for key in REQUIRED_FILES if key not in files]
        if missing:
            _fail(f"soc.json files lacks {', '.join(missing)}")
        unknown = [key for key in files if key not in REQUIRED_FILES and not key.startswith("cell_")]
        if unknown:
            _fail(f"soc.json files has unknown entries {', '.join(sorted(unknown))}")
        self.files = {key: _relative_file(self.out, key, entry) for key, entry in files.items()}

        interchange_rel = f"hdl/{self.top}.dnl.json"
        if self.files["interchange"][1] != interchange_rel:
            _fail(f"soc.json files.interchange is {self.files['interchange'][1]}, expected {interchange_rel}")
        header_name = doc.get("header_name")
        if header_name != f"dora_{self.top}.h" or self.files["header"][1] != f"sw/{header_name}":
            _fail(f"soc.json header {header_name!r} at {self.files['header'][1]} is not sw/dora_{self.top}.h")
        self.interchange = self.files["interchange"][0]
        self.header = self.files["header"][0]
        self.cells = sorted(path for key, (path, _) in self.files.items() if key.startswith("cell_"))
        self._check_cells()

        k3 = doc.get("k3")
        if not isinstance(k3, dict):
            _fail("soc.json k3 must be an object")
        if k3.get("skipped") is not None:
            _fail(f"DORA_OUT has no K3 kernel: {k3['skipped']}")
        self.k3 = k3
        producer = doc.get("producer")
        if not isinstance(producer, dict):
            _fail("soc.json producer must be an object")
        self.producer = producer

    def _check_cells(self) -> None:
        """The manifest's cells, hdl/cells/*.sv and the interchange's cells[] agree."""
        cell_dir = self.out / "hdl" / "cells"
        on_disk = sorted(cell_dir.glob("*.sv")) if cell_dir.is_dir() else []
        if [p.resolve() for p in on_disk] != [p.resolve() for p in self.cells]:
            _fail(
                f"{cell_dir} holds {[p.name for p in on_disk]}, soc.json names "
                f"{[p.name for p in self.cells]}; render DORA_OUT again into a clean directory"
            )
        doc = _load_json(self.interchange, "the interchange")
        cells = doc.get("cells") if isinstance(doc, dict) else None
        if not isinstance(cells, list):
            _fail(f"{self.interchange} has no cells list")
        declared = {}
        for cell in cells:
            if not isinstance(cell, dict) or not isinstance(cell.get("sv"), str):
                _fail(f"{self.interchange}: malformed cells[] entry {cell!r}")
            declared[(self.interchange.parent / cell["sv"]).resolve()] = cell.get("sha256")
        if sorted(declared) != [p.resolve() for p in self.cells]:
            _fail(
                f"the interchange's cells[] ({sorted(p.name for p in declared)}) are not "
                f"soc.json's ({[p.name for p in self.cells]})"
            )
        for path in self.cells:
            want = str(declared[path.resolve()]).removeprefix("sha256:")
            if _sha256(path) != want:
                _fail(f"{path} does not match the interchange's cells[].sha256")

    def check_producer(self, submodule: Path, chipyard: Path, allow_dev: bool) -> None:
        """The render's producer is the pinned commit (generators/dora's, and
        Chipyard's gitlink), from a clean tree."""
        pin = _head(submodule, "generators/dora")
        sha = self.producer.get("dora_git_sha")
        dirty = self.producer.get("dirty")
        problems = pin_problems(chipyard, submodule, pin)
        if sha != pin:
            problems.append(f"DORA_OUT was rendered by DORA {sha}, generators/dora is at {pin}")
        if dirty is not False:
            problems.append(f"DORA_OUT was rendered from a DORA tree with dirty={dirty!r}")
        _refuse_or_warn(problems, allow_dev, "DORA_OUT producer", PIN_REMEDY)

    def get(self, key: str) -> str:
        if key == "module_prefix":
            return self.module_prefix
        if key == "top":
            return str(self.top)
        if key == "interchange":
            return str(self.interchange)
        if key == "header":
            return str(self.header)
        if key == "cells":
            return " ".join(str(path) for path in self.cells)
        _fail(f"unknown key {key!r}")

    def stamp_content(self) -> str:
        """The interchange's absolute path, then the SHA-256 of it and each cell."""
        base = self.interchange.parent
        lines = [str(self.interchange.resolve())]
        for path in [self.interchange, *self.cells]:
            lines.append(f"{_sha256(path)}  {path.relative_to(base).as_posix()}")
        return "\n".join(lines) + "\n"


def verify(
    out: Path,
    top: Optional[str],
    submodule: Optional[Path],
    chipyard: Optional[Path],
    allow_dev: bool,
) -> Manifest:
    manifest = Manifest(out, top)
    if submodule is not None:
        if chipyard is None:
            _fail("verify --submodule needs --chipyard-root (the pin is Chipyard's gitlink)")
        manifest.check_producer(submodule, chipyard, allow_dev)
    print(
        f"dora_soc: {manifest.out}: fabric {manifest.top}, hardware "
        f"{manifest.doc.get('hardware_digest')}, prefix {manifest.module_prefix}, "
        f"{len(manifest.cells)} cut cells, K3 {manifest.k3.get('run_cycles')} cycles; "
        f"producer DORA {manifest.producer.get('dora_git_sha')} "
        f"(dirty={manifest.producer.get('dirty')}); every file matches soc.json"
    )
    return manifest


def stamp(out: Path, stamp_file: Path, generated: Optional[Path]) -> None:
    manifest = Manifest(out)
    content = manifest.stamp_content()
    if generated is not None:
        if not stamp_file.is_file() or stamp_file.read_text(encoding="utf-8") != content:
            _fail(
                f"the SoC was not generated from {manifest.interchange} (the stamp "
                f"{stamp_file} names another fabric or is missing); run soc-smoke first"
            )
        if not generated.is_file() or generated.stat().st_mtime < stamp_file.stat().st_mtime:
            _fail(f"{generated} is missing or older than the fabric stamp; run soc-smoke first")
        print(f"dora_soc: {generated.name} was generated from {manifest.interchange}")
        return
    stamp_file.parent.mkdir(parents=True, exist_ok=True)
    if stamp_file.is_file() and stamp_file.read_text(encoding="utf-8") == content:
        print(f"dora_soc: fabric stamp {stamp_file} unchanged")
        return
    fd, tmp = tempfile.mkstemp(dir=stamp_file.parent, prefix=".stamp-")
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(content)
    os.replace(tmp, stamp_file)
    print(f"dora_soc: fabric stamp {stamp_file} rewritten (the fabric changed)")


def _mock_faults(mock: Path) -> list[str]:
    text = mock.read_text(encoding="utf-8")
    block = re.search(r"faults\[\]\s*=\s*\{(.*?)\};", text, re.S)
    if not block:
        _fail(f"{mock} has no faults[] table")
    faults = re.findall(r'"([a-z0-9-]+)"', block.group(1))
    if not faults:
        _fail(f"{mock}'s faults[] table is empty")
    return faults


_PROBLEM = re.compile(r"expected|[1-9][0-9]* of [0-9]+ .*differ|ERROR = |timed out|not the fabric|cannot")


def mock_test(out: Path, tests: Path, mock: Path, build: Path, cc: str) -> None:
    manifest = Manifest(out)
    build.mkdir(parents=True, exist_ok=True)
    binary = build / "dora-static-hycube-mock"
    env = dict(os.environ, CCACHE_DISABLE="1")
    base = [
        *cc.split(),
        "-std=gnu99",
        "-O2",
        "-g",
        "-Wall",
        "-Wextra",
        "-Werror",
        "-DDORA_RUNTIME_MMIO_HOOKS",
        "-DDORA_POLL_LIMIT=20000",
        f'-DDORA_FABRIC_HEADER="{manifest.header.name}"',
        f"-I{manifest.header.parent}",
        f"-I{tests}",
        str(tests / "dora-static-hycube.c"),
        str(tests / "dora-runtime.c"),
        str(mock),
        "-o",
        str(binary),
    ]
    sanitized = base[:3] + ["-fsanitize=address,undefined", "-fno-sanitize-recover=all"] + base[3:]
    compiled = subprocess.run(sanitized, capture_output=True, text=True, env=env)
    note = "with ASan and UBSan"
    if compiled.returncode != 0:
        compiled = subprocess.run(base, capture_output=True, text=True, env=env)
        note = "without sanitizers (the compiler rejected them)"
    if compiled.returncode != 0:
        _fail(f"compiling the mock test failed:\n{compiled.stderr}")
    print(f"dora_soc: built {binary} {note}")

    def run(fault: str) -> subprocess.CompletedProcess[str]:
        run_env = dict(env, DORA_MOCK_FAULT=fault)
        return subprocess.run([str(binary)], capture_output=True, text=True, env=run_env, timeout=600)

    faithful = run("")
    log = build / "faithful.log"
    log.write_text(faithful.stdout + faithful.stderr, encoding="utf-8")
    if faithful.returncode != 0 or PASS_LINE not in faithful.stdout:
        _fail(f"the faithful mock run did not PASS (exit {faithful.returncode}); see {log}:\n{faithful.stdout}{faithful.stderr}")
    print(faithful.stdout.rstrip())
    print(faithful.stderr.rstrip())
    problems = []
    for fault in _mock_faults(mock):
        result = run(fault)
        (build / f"fault-{fault}.log").write_text(result.stdout + result.stderr, encoding="utf-8")
        verdict = [line for line in result.stdout.splitlines() if line.startswith(FAIL_LINE)]
        if result.returncode != 1 or not verdict or PASS_LINE in result.stdout:
            problems.append(f"fault {fault}: exit {result.returncode}, not a FAIL verdict (see fault-{fault}.log)")
            continue
        detail = [
            line
            for line in result.stdout.splitlines()
            if line.startswith("dora: ") and _PROBLEM.search(line)
        ]
        print(f"dora_soc: fault {fault:<14} -> {verdict[-1]}  [{detail[0] if detail else ''}]")
    if problems:
        _fail("the mock test missed faults:\n  " + "\n  ".join(problems))
    print(f"dora_soc: mock test passed: PASS when faithful, FAIL under all {len(_mock_faults(mock))} faults")


# -- wiring -----------------------------------------------------------------------------------

#: What drives a fabric input of each role (``integration.roles``), in the
#: CHIRRTL of the module that instantiates the fabric; ``io.in`` and
#: ``mem.rdata`` are handled apart.
ROLE_SOURCES = {
    "clock": "clock",
    "prog.clock": "clock",
    "reset": "shell.io.fabric.reset",
    "prog.reset": "shell.io.fabric.progRst",
    "enable": "shell.io.fabric.en",
    "prog.done": "shell.io.fabric.progDone",
    "scan.we_in": "shell.io.fabric.progWe",
    "scan.din": "shell.io.fabric.progDin",
}
#: The fabric outputs the shell reads, by role, and the shell input each feeds.
MEMORY_SINKS = {"mem.addr": "addr", "mem.wdata": "wdata", "mem.we": "we"}

_MODULE = re.compile(r"^\s*(?:public\s+)?(?:ext)?module\s+(\S+)\s*:", re.M)
_LOCATOR = re.compile(r"\s*@\[.*\]\s*$")
_ZERO = re.compile(r"UInt(?:<\d+>)?\((?:0h0+|0)\)")


def _module_bodies(text: str) -> dict[str, list[str]]:
    """Every module of a CHIRRTL circuit: its statements, locators stripped."""
    bodies: dict[str, list[str]] = {}
    starts = list(_MODULE.finditer(text))
    for index, match in enumerate(starts):
        end = starts[index + 1].start() if index + 1 < len(starts) else len(text)
        lines = text[match.end() : end].splitlines()
        bodies[match.group(1)] = [
            _LOCATOR.sub("", line).strip() for line in lines if line.strip()
        ]
    return bodies


def wiring_problems(interchange: Any, prefix: str, text: str) -> tuple[list[str], int]:
    """Differences between the CHIRRTL ``text`` and the interchange's roles
    (see ``wiring`` in the module docstring), and the connections compared."""
    top = interchange["top"]
    roles = interchange["integration"]["roles"]
    module = next((m for m in interchange["modules"] if m["name"] == top), None)
    if module is None:
        return [f"the interchange has no top module {top}"], 0
    inputs = [port["n"] for port in module["ports"] if port["d"] == "in"]
    outputs = [port["n"] for port in module["ports"] if port["d"] == "out"]
    fabric_module = f"{prefix}{top}"
    owners = [
        name
        for name, body in _module_bodies(text).items()
        if f"inst fabric of {fabric_module}" in body
    ]
    if len(owners) != 1:
        return [
            f"{len(owners)} modules instantiate `fabric` of {fabric_module} "
            f"({', '.join(owners) or 'none'}); expected exactly one"
        ], 0
    body = _module_bodies(text)[owners[0]]
    nodes: dict[str, str] = {}
    connects: dict[str, list[str]] = {}
    for line in body:
        if line.startswith("node "):
            name, _, expression = line[len("node ") :].partition(" = ")
            bits = re.fullmatch(r"bits\((\S+), 0, 0\)", expression)
            nodes[name.strip()] = bits.group(1) if bits else expression
        elif line.startswith("connect "):
            sink, _, source = line[len("connect ") :].partition(", ")
            connects.setdefault(sink.strip(), []).append(source.strip())

    def source_of(sink: str) -> Optional[str]:
        sources = connects.get(sink, [])
        if len(sources) != 1:
            problems.append(f"{sink} is connected {len(sources)} times, not once")
            return None
        source = sources[0]
        return nodes.get(source, source)

    problems: list[str] = []
    compared = 0
    memory: dict[int, dict[str, str]] = {}
    for name, role in roles.items():
        if role.get("role") in MEMORY_SINKS or role.get("role") == "mem.rdata":
            memory.setdefault(int(role["port"]), {})[role["role"]] = name
    for name in inputs:
        role = roles.get(name, {}).get("role")
        source = source_of(f"fabric.{name}")
        compared += 1
        if source is None:
            continue
        if role == "io.in":
            ok = _ZERO.fullmatch(source) is not None
            want = "0"
        elif role == "mem.rdata":
            want = f"shell.io.fabric.mem[{int(roles[name]['port'])}].rdata"
            ok = source == want
        elif role in ROLE_SOURCES:
            want = ROLE_SOURCES[role]
            ok = source == want
        else:
            problems.append(f"fabric input {name} has role {role!r}, which the shell does not drive")
            continue
        if not ok:
            problems.append(f"fabric.{name} (role {role}) is driven by {source}, expected {want}")
    for port, names in sorted(memory.items()):
        for role, field in MEMORY_SINKS.items():
            if role not in names:
                problems.append(f"memory port {port} has no {role} port")
                continue
            sink = f"shell.io.fabric.mem[{port}].{field}"
            source = source_of(sink)
            compared += 1
            if source is not None and source != f"fabric.{names[role]}":
                problems.append(f"{sink} is driven by {source}, expected fabric.{names[role]}")
    read = {
        name
        for sources in connects.values()
        for source in sources
        for name in re.findall(r"\bfabric\.(\w+)", nodes.get(source, source))
    }
    read |= {
        name
        for expression in nodes.values()
        for name in re.findall(r"\bfabric\.(\w+)", expression)
    }
    allowed = {names[role] for names in memory.values() for role in MEMORY_SINKS if role in names}
    for name in sorted(read - allowed):
        if name in outputs:
            problems.append(f"fabric output {name} (role {roles.get(name, {}).get('role')}) is read; "
                            "the shell reads only the memory ports")
    extra = sorted(
        sink[len("fabric.") :]
        for sink in connects
        if sink.startswith("fabric.") and sink[len("fabric.") :] not in inputs
    )
    for name in extra:
        problems.append(f"fabric.{name} is connected but is not a fabric input")
    return problems, compared


def check_wiring(out: Path, firrtl: Path) -> None:
    manifest = Manifest(out)
    interchange = _load_json(manifest.interchange, "the interchange")
    try:
        text = firrtl.read_text(encoding="utf-8")
    except OSError as exc:
        _fail(f"cannot read the SoC's CHIRRTL {firrtl}: {exc}; run soc-smoke first")
    problems, compared = wiring_problems(interchange, manifest.module_prefix, text)
    if problems:
        _fail(
            f"the shell-to-fabric wiring in {firrtl.name} differs from the interchange's roles:\n  - "
            + "\n  - ".join(problems)
        )
    print(
        f"dora_soc: {firrtl.name}: the shell drives every fabric input and reads the memory "
        f"ports as integration.roles says ({compared} connections compared; no other "
        "fabric output read)"
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="dora_soc.py", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("check-root", help="gen's DORA_ROOT precondition")
    p.add_argument("--dora-root", type=Path, required=True)
    p.add_argument("--submodule", type=Path, required=True)
    p.add_argument("--chipyard-root", type=Path, required=True)
    p.add_argument("--allow-dev", action="store_true")

    p = sub.add_parser("verify", help="check DORA_OUT/soc.json and its files")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--top")
    p.add_argument("--submodule", type=Path)
    p.add_argument("--chipyard-root", type=Path)
    p.add_argument("--allow-dev", action="store_true")

    p = sub.add_parser("stamp", help="write (or --check) the fabric's content stamp")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--stamp", type=Path, required=True)
    p.add_argument("--check", type=Path, metavar="GENERATED")

    p = sub.add_parser("get", help="print one manifest value")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("key", choices=("module_prefix", "top", "interchange", "header", "cells"))

    p = sub.add_parser("mock-test", help="run the software against the mock shell")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--tests", type=Path, required=True)
    p.add_argument("--mock", type=Path, required=True)
    p.add_argument("--build", type=Path, required=True)
    p.add_argument("--cc", default="cc")

    p = sub.add_parser("wiring", help="check the shell-to-fabric wiring in the SoC's CHIRRTL")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--firrtl", type=Path, required=True)

    args = parser.parse_args(argv)
    try:
        if args.command == "check-root":
            check_root(args.dora_root, args.submodule, args.chipyard_root, args.allow_dev)
        elif args.command == "verify":
            verify(args.out, args.top, args.submodule, args.chipyard_root, args.allow_dev)
        elif args.command == "stamp":
            stamp(args.out, args.stamp, args.check)
        elif args.command == "get":
            print(Manifest(args.out).get(args.key))
        elif args.command == "mock-test":
            mock_test(args.out, args.tests, args.mock, args.build, args.cc)
        elif args.command == "wiring":
            check_wiring(args.out, args.firrtl)
    except DriverError as exc:
        print(f"dora_soc: error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
