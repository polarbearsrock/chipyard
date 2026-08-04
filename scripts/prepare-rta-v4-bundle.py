#!/usr/bin/env python3
"""Create the frozen RTA V4 SystemVerilog reference artifact.

This script intentionally consumes generated DORA collateral without importing
DORA Python modules or unpickling ``workspace.pkl``.  It produces one ordered,
self-contained SystemVerilog compilation unit, copies a known-good bitstream
and its FASM, and records enough provenance to audit or reproduce the snapshot.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable


SCRIPT_PATH = Path(__file__).resolve()
CHIPYARD_ROOT = SCRIPT_PATH.parents[1]
DEFAULT_OUTPUT_DIR = (
    CHIPYARD_ROOT
    / "generators"
    / "chipyard"
    / "src"
    / "main"
    / "resources"
    / "vsrc"
    / "rta_v4"
)
ADAPTER_FILENAME = "rta_v4_chipyard_adapter.sv"
STAGED_ADAPTER_FILENAME = "rta_v4_chipyard_adapter.sv.source"
DEFAULT_ADAPTER_PATH = (
    CHIPYARD_ROOT
    / "generators"
    / "chipyard"
    / "src"
    / "main"
    / "resources"
    / "rta_v4"
    / ADAPTER_FILENAME
)
BUNDLE_FILENAME = "RtaV4Bundle.sv"
LOCK_FILENAME = "rta_v4_artifact_lock.json"
BITSTREAM_FILENAME = "add_chain_compute.bin"
FASM_FILENAME = "add_chain_compute.fasm"
DORA_LICENSE_FILENAME = "LICENSE.dora"
BASEJUMP_LICENSE_FILENAME = "LICENSE.basejump_stl"
ALLOWED_OUTPUT_FILENAMES = frozenset(
    {
        STAGED_ADAPTER_FILENAME,
        BASEJUMP_LICENSE_FILENAME,
        BITSTREAM_FILENAME,
        BUNDLE_FILENAME,
        DORA_LICENSE_FILENAME,
        FASM_FILENAME,
        LOCK_FILENAME,
        "README.md",
    }
)
HDL_SUFFIXES = frozenset({".sv", ".svh", ".v", ".vh"})

EXPECTED_DESIGN = "rta_v4_array"
EXPECTED_COMPILER_ARCH_SCHEMA_VERSION = 6
EXPECTED_BITSTREAM_BITS = 3140
EXPECTED_FABRIC_CONTEXTS = 1
EXPECTED_LAYOUT_HASH = (
    "36c02b053e3686484ccd7b8433bd5facfc295734667b01ac7a4ba9268a0b9e7a"
)
EXPECTED_RTA_SOURCE_COUNT = 43
EXPECTED_BASEJUMP_SOURCE_COUNT = 7
EXPECTED_ADD_CHAIN_SHA256 = (
    "567763f047f3b75e5190dc2baf09fdec1fae0dd91df55a67fca3dbeb2937ceab"
)
EXPECTED_ADD_CHAIN_FASM_SHA256 = (
    "d0355eb0d564f3a266ed262b873f4ba5a1762b4cb8d932d29bcd309557d0b1d0"
)
EXPECTED_DORA_REVISION = "f57db1855de46f68b976db12fa9400a59d54d55a"
EXPECTED_BASEJUMP_REVISION = "b8142d3c3b0c673a1d92041b24fba5fdef4c393a"
EXPECTED_COMPILER_ARCH_SHA256 = (
    "b324d16f32987cee5bf25995059391147e823bcb9800d78dbf0679dab8d4b1ae"
)
EXPECTED_WORKSPACE_SHA256 = (
    "fa507fdefde2650049df61bbcbd3e51f4188373498b2c848a8f6baff05719a4a"
)
EXPECTED_RMU_FILELIST_SHA256 = (
    "c25d5484268a5a8b16ee8f8ab01379c065e0237709ac81e958a94638e4f12f26"
)

BASEJUMP_RELATIVE_DIR = Path("dora.py/external/basejump_stl/bsg_misc")
RTA_BUILD_RELATIVE_DIR = Path("examples/devices/ee_526/rta-v4/build")
EXPECTED_RMU_FILELIST = (
    "common/rta_v4_pkg.sv",
    "rmu/rta_v4_rmu_mul_array.sv",
    "rmu/rta_v4_rmu_cgra_mul_backend.sv",
    "rmu/rta_v4_rmu_systolic_dot4_backend.sv",
    "rmu/rta_v4_rmu.sv",
)

# Ordering is part of the reference artifact.  In particular, the package and
# BaseJump definitions must precede modules that consume them.
BASEJUMP_SOURCES = (
    "bsg_defines.sv",
    "bsg_dff.sv",
    "bsg_dff_async_reset.sv",
    "bsg_dff_reset.sv",
    "bsg_dff_reset_en.sv",
    "bsg_adder_cin.sv",
    "bsg_mul_synth.sv",
)

RTA_SOURCES = (
    "common/rta_v4_pkg.sv",
    "stdlib/simple_buf.sv",
    "stdlib/simple_bufr.sv",
    "scanchain_delim.sv",
    "scanchain_data_d1_contexts_1.sv",
    "scanchain_data_d2_contexts_1.sv",
    "scanchain_data_d4_contexts_1.sv",
    "scanchain_data_d5_contexts_1.sv",
    "scanchain_data_d8_contexts_1.sv",
    "sw_11_8b.sv",
    "sw_2_1b.sv",
    "sw_2_8b.sv",
    "sw_3_8b.sv",
    "sw_9_1b.sv",
    "reg_1b.sv",
    "reg_8b.sv",
    "rta_alu.sv",
    "rta_const_unit_8b.sv",
    "rmu/rta_v4_rmu_mul_array.sv",
    "rmu/rta_v4_rmu_cgra_mul_backend.sv",
    "rmu/rta_v4_rmu_systolic_dot4_backend.sv",
    "rmu/rta_v4_rmu.sv",
    "rta_v4_data0_crossbar_8b.sv",
    "rta_v4_data1_crossbar_8b.sv",
    "rta_v4_pred_crossbar.sv",
    "rta_v4_skew_bypass_2x8b_pred.sv",
    "rta_v4_input_pad_8b_s0.sv",
    "rta_v4_input_pad_8b_s1.sv",
    "rta_v4_input_pad_1b_s2.sv",
    "rta_v4_output_pad_8b_s0.sv",
    "rta_v4_output_pad_8b_s1.sv",
    "rta_v4_output_pad_1b_s2.sv",
    "rta_v4_input_io_tile_2x8b_pred.sv",
    "rta_v4_output_io_tile_2x8b_pred.sv",
    "rta_v4_input_boundary_cell_2x8b_pred.sv",
    "rta_v4_input_boundary_cell_2x8b_pred_skew1.sv",
    "rta_v4_input_boundary_cell_2x8b_pred_skew2.sv",
    "rta_v4_input_boundary_cell_2x8b_pred_skew3.sv",
    "rta_v4_output_boundary_cell_2x8b_pred.sv",
    "rta_v4_active_or3.sv",
    "rta_v4_active_pack4.sv",
    "rta_v4_pe.sv",
    "rta_v4_array.sv",
)

BSG_DEFINES_INCLUDE_RE = re.compile(
    r'^\s*`include\s+"bsg_defines\.sv"\s*(?://.*)?$', re.MULTILINE
)
DORA_GENERATED_ON_RE = re.compile(r"^// Generated on:.*$", re.MULTILINE)
DORA_AUTHOR_RE = re.compile(r"^// Author:.*$", re.MULTILINE)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def git_output(repo: Path, *args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), *args],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip()


def require_regular_file(path: Path, description: str) -> None:
    if not path.is_file():
        raise ValueError(f"{description} is missing or not a regular file: {path}")


def require_git_checkout(repo: Path, description: str) -> str:
    top = git_output(repo, "rev-parse", "--show-toplevel")
    revision = git_output(repo, "rev-parse", "HEAD")
    if top is None or Path(top).resolve() != repo.resolve():
        raise ValueError(f"{description} is not a Git checkout root: {repo}")
    if revision is None or re.fullmatch(r"[0-9a-f]{40}", revision) is None:
        raise ValueError(f"cannot determine full {description} revision: {repo}")
    return revision


def validate_source_closure(rtl_dir: Path) -> None:
    expected = set(RTA_SOURCES)
    actual = {
        path.relative_to(rtl_dir).as_posix()
        for path in rtl_dir.rglob("*")
        if path.is_file() and path.suffix.lower() in HDL_SUFFIXES
    }
    missing = sorted(expected - actual)
    unexpected = sorted(actual - expected)
    if missing or unexpected:
        details = []
        if missing:
            details.append("missing: " + ", ".join(missing))
        if unexpected:
            details.append("unexpected: " + ", ".join(unexpected))
        raise ValueError(
            "RTA V4 RTL closure differs from the locked reference ("
            + "; ".join(details)
            + ")"
        )


def validate_output_closure(output_dir: Path) -> None:
    if not output_dir.exists():
        return
    if not output_dir.is_dir():
        raise ValueError(f"artifact output is not a directory: {output_dir}")
    unexpected = sorted(
        path.name
        for path in output_dir.iterdir()
        if path.name not in ALLOWED_OUTPUT_FILENAMES
        or not path.is_file()
        or path.is_symlink()
    )
    if unexpected:
        raise ValueError(
            "artifact output contains unexpected entries: "
            + ", ".join(unexpected)
        )


def normalize_source(
    text: str, *, strip_bsg_include: bool, canonicalize_dora_header: bool
) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = "\n".join(line.rstrip(" \t") for line in text.split("\n"))
    if canonicalize_dora_header:
        text = DORA_GENERATED_ON_RE.sub("// Generated on: <canonicalized>", text)
        text = DORA_AUTHOR_RE.sub("// Author: <canonicalized>", text)
    if strip_bsg_include:
        text = BSG_DEFINES_INCLUDE_RE.sub(
            "// bsg_defines.sv is inlined at the start of this bundle.", text
        )
    return text.rstrip() + "\n"


def source_section(display_path: str, text: str) -> str:
    divider = "// " + "=" * 76
    return (
        f"{divider}\n"
        f"// BEGIN SOURCE: {display_path}\n"
        f"{divider}\n"
        f"{text}"
        f"{divider}\n"
        f"// END SOURCE: {display_path}\n"
        f"{divider}\n\n"
    )


def source_record(
    display_path: str, text: str, *, bundle_order: int
) -> dict[str, Any]:
    data = text.encode("utf-8")
    return {
        "bundle_order": bundle_order,
        "path": display_path,
        "bytes": len(data),
        "sha256": sha256_bytes(data),
    }


def parse_args(argv: Iterable[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    dora_default = os.environ.get("DORA_ROOT")
    parser.add_argument(
        "--dora-root",
        type=Path,
        default=Path(dora_default) if dora_default else None,
        required=dora_default is None,
        help="DORA repository/worktree root (or set DORA_ROOT)",
    )
    parser.add_argument(
        "--rta-build-dir",
        type=Path,
        help="generated RTA V4 build directory; defaults below --dora-root",
    )
    parser.add_argument(
        "--add-chain-bitstream",
        type=Path,
        required=True,
        help="known-good compute.bin generated by the RTA V4 add-chain test",
    )
    parser.add_argument(
        "--add-chain-fasm",
        type=Path,
        required=True,
        help="known-good compute.fasm used to generate the add-chain bitstream",
    )
    parser.add_argument(
        "--adapter",
        type=Path,
        default=DEFAULT_ADAPTER_PATH,
        help=f"authored packed adapter (default: {DEFAULT_ADAPTER_PATH})",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"artifact output directory (default: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify checked-in outputs match regenerated content without writing",
    )
    return parser.parse_args(list(argv))


def check_or_write(path: Path, data: bytes, *, check: bool) -> None:
    if check:
        require_regular_file(path, "checked-in generated artifact")
        existing = path.read_bytes()
        if existing != data:
            raise ValueError(f"checked-in artifact is stale: {path}")
        print(f"verified {path}")
        return
    if path.is_file() and path.read_bytes() == data:
        print(f"unchanged {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    print(f"wrote {path}")


def main(argv: Iterable[str] = sys.argv[1:]) -> int:
    args = parse_args(argv)
    dora_root = args.dora_root.resolve()
    output_dir = args.output_dir.resolve()
    validate_output_closure(output_dir)
    rta_build_dir = (
        args.rta_build_dir.resolve()
        if args.rta_build_dir
        else (dora_root / RTA_BUILD_RELATIVE_DIR).resolve()
    )
    try:
        rta_build_dir.relative_to(dora_root)
    except ValueError as error:
        raise ValueError(
            f"RTA build directory must be inside the attributed DORA checkout: "
            f"{rta_build_dir}"
        ) from error

    basejump_checkout = (
        dora_root / "dora.py" / "external" / "basejump_stl"
    ).resolve()
    dora_revision = require_git_checkout(dora_root, "DORA checkout")
    basejump_revision = require_git_checkout(
        basejump_checkout, "BaseJump checkout"
    )
    if dora_revision != EXPECTED_DORA_REVISION:
        raise ValueError(
            f"expected DORA revision {EXPECTED_DORA_REVISION}, got {dora_revision}"
        )
    if basejump_revision != EXPECTED_BASEJUMP_REVISION:
        raise ValueError(
            "expected BaseJump revision "
            f"{EXPECTED_BASEJUMP_REVISION}, got {basejump_revision}"
        )
    rtl_dir = rta_build_dir / "rtl"
    compiler_arch_path = rta_build_dir / "compiler_arch.json"
    workspace_path = rta_build_dir / "workspace.pkl"
    rmu_filelist_path = rtl_dir / "rta_v4_rmu_sources.f"
    adapter_path = args.adapter.resolve()
    bitstream_path = args.add_chain_bitstream.resolve()
    fasm_path = args.add_chain_fasm.resolve()
    dora_license_path = dora_root / "LICENSE"
    basejump_license_path = basejump_checkout / "LICENSE"

    require_regular_file(compiler_arch_path, "compiler metadata")
    require_regular_file(workspace_path, "DORA workspace snapshot")
    require_regular_file(rmu_filelist_path, "RMU source filelist")
    require_regular_file(adapter_path, "packed SystemVerilog adapter")
    require_regular_file(bitstream_path, "add-chain bitstream")
    require_regular_file(fasm_path, "add-chain FASM")
    require_regular_file(dora_license_path, "DORA license")
    require_regular_file(basejump_license_path, "BaseJump license")
    validate_source_closure(rtl_dir)

    compiler_arch_sha256 = sha256_file(compiler_arch_path)
    workspace_sha256 = sha256_file(workspace_path)
    rmu_filelist_sha256 = sha256_file(rmu_filelist_path)
    expected_input_digests = (
        ("compiler metadata", compiler_arch_sha256, EXPECTED_COMPILER_ARCH_SHA256),
        ("workspace snapshot", workspace_sha256, EXPECTED_WORKSPACE_SHA256),
        ("RMU source filelist", rmu_filelist_sha256, EXPECTED_RMU_FILELIST_SHA256),
    )
    for description, actual_digest, expected_digest in expected_input_digests:
        if actual_digest != expected_digest:
            raise ValueError(
                f"{description} digest differs from the supplied reference: "
                f"{actual_digest}"
            )

    rmu_filelist_entries = tuple(
        line.strip()
        for line in rmu_filelist_path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    )
    if rmu_filelist_entries != EXPECTED_RMU_FILELIST:
        raise ValueError(
            "RMU source filelist differs from the expected five-file subset: "
            f"{rmu_filelist_entries}"
        )

    compiler_arch = json.loads(compiler_arch_path.read_text(encoding="utf-8"))
    if (
        compiler_arch.get("schema_version")
        != EXPECTED_COMPILER_ARCH_SCHEMA_VERSION
    ):
        raise ValueError(
            "expected compiler architecture schema_version "
            f"{EXPECTED_COMPILER_ARCH_SCHEMA_VERSION}, got "
            f"{compiler_arch.get('schema_version')}"
        )
    if compiler_arch.get("design") != EXPECTED_DESIGN:
        raise ValueError(
            f"expected design {EXPECTED_DESIGN}, got {compiler_arch.get('design')}"
        )
    if compiler_arch.get("bitstream_size") != EXPECTED_BITSTREAM_BITS:
        raise ValueError(
            "expected bitstream_size "
            f"{EXPECTED_BITSTREAM_BITS}, got {compiler_arch.get('bitstream_size')}"
        )
    if compiler_arch.get("fabric_contexts") != EXPECTED_FABRIC_CONTEXTS:
        raise ValueError(
            "expected fabric_contexts "
            f"{EXPECTED_FABRIC_CONTEXTS}, got {compiler_arch.get('fabric_contexts')}"
        )
    layout_hash = compiler_arch.get("layout_hash")
    if layout_hash != EXPECTED_LAYOUT_HASH:
        raise ValueError(
            f"expected layout_hash {EXPECTED_LAYOUT_HASH}, got {layout_hash}"
        )

    expected_bitstream_bytes = (EXPECTED_BITSTREAM_BITS + 7) // 8
    valid_bits_last_byte = EXPECTED_BITSTREAM_BITS % 8 or 8
    bitstream = bitstream_path.read_bytes()
    if len(bitstream) != expected_bitstream_bytes:
        raise ValueError(
            f"expected {expected_bitstream_bytes} bitstream bytes, got {len(bitstream)}"
        )
    unused_mask = 0xFF & ~((1 << valid_bits_last_byte) - 1)
    if bitstream[-1] & unused_mask:
        raise ValueError(
            "unused high bits of the final bitstream byte must be zero: "
            f"0x{bitstream[-1]:02x}"
        )
    bitstream_sha256 = sha256_bytes(bitstream)
    if bitstream_sha256 != EXPECTED_ADD_CHAIN_SHA256:
        raise ValueError(
            "add-chain bitstream digest does not match the known-good reference: "
            f"{bitstream_sha256}"
        )

    fasm = fasm_path.read_bytes()
    try:
        fasm_text = fasm.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError(f"add-chain FASM is not UTF-8: {fasm_path}") from error
    fasm_layout_match = re.search(
        r"^# dora_layout_hash: ([0-9a-f]{64})$", fasm_text, re.MULTILINE
    )
    if fasm_layout_match is None:
        raise ValueError("add-chain FASM does not declare a DORA layout hash")
    if fasm_layout_match.group(1) != EXPECTED_LAYOUT_HASH:
        raise ValueError(
            "add-chain FASM layout hash does not match compiler metadata: "
            f"{fasm_layout_match.group(1)}"
        )
    fasm_sha256 = sha256_bytes(fasm)
    if fasm_sha256 != EXPECTED_ADD_CHAIN_FASM_SHA256:
        raise ValueError(
            "add-chain FASM digest does not match the known-good reference: "
            f"{fasm_sha256}"
        )

    if len(RTA_SOURCES) != EXPECTED_RTA_SOURCE_COUNT:
        raise AssertionError("internal RTA source-count invariant failed")
    if len(BASEJUMP_SOURCES) != EXPECTED_BASEJUMP_SOURCE_COUNT:
        raise AssertionError("internal BaseJump source-count invariant failed")

    bundle_parts = [
        "// Generated by scripts/prepare-rta-v4-bundle.py. DO NOT EDIT.\n",
        "// This is a deterministic reference snapshot, not a stable DORA ABI.\n",
        "// Source hashes and provenance are recorded in rta_v4_artifact_lock.json.\n\n",
        "`timescale 1ns/1ps\n\n",
    ]
    source_records: list[dict[str, Any]] = []
    bundle_order = 0

    basejump_dir = dora_root / BASEJUMP_RELATIVE_DIR
    for relative in BASEJUMP_SOURCES:
        path = basejump_dir / relative
        require_regular_file(path, "BaseJump source")
        display = f"basejump_stl/bsg_misc/{relative}"
        text = normalize_source(
            path.read_text(encoding="utf-8"),
            strip_bsg_include=relative != "bsg_defines.sv",
            canonicalize_dora_header=False,
        )
        source_records.append(
            source_record(display, text, bundle_order=bundle_order)
        )
        bundle_parts.append(source_section(display, text))
        bundle_order += 1

    for relative in RTA_SOURCES:
        path = rtl_dir / relative
        require_regular_file(path, "RTA V4 source")
        display = f"rta_v4/rtl/{relative}"
        text = normalize_source(
            path.read_text(encoding="utf-8"),
            strip_bsg_include=True,
            canonicalize_dora_header=True,
        )
        source_records.append(
            source_record(display, text, bundle_order=bundle_order)
        )
        bundle_parts.append(source_section(display, text))
        bundle_order += 1

    adapter_display = f"chipyard/{ADAPTER_FILENAME}"
    adapter_data = adapter_path.read_bytes()
    adapter_text = normalize_source(
        adapter_data.decode("utf-8"),
        strip_bsg_include=False,
        canonicalize_dora_header=False,
    )
    source_records.append(
        source_record(adapter_display, adapter_text, bundle_order=bundle_order)
    )
    bundle_parts.append(source_section(adapter_display, adapter_text))
    adapter = adapter_text.encode("utf-8")

    bundle_text = "".join(bundle_parts)
    if re.search(r"^\s*`include\b", bundle_text, re.MULTILINE):
        raise ValueError("assembled bundle contains an external include directive")
    bundle = bundle_text.encode("utf-8")
    bundle_path = output_dir / BUNDLE_FILENAME
    output_adapter_path = output_dir / STAGED_ADAPTER_FILENAME
    output_bitstream_path = output_dir / BITSTREAM_FILENAME
    output_fasm_path = output_dir / FASM_FILENAME
    dora_license = normalize_source(
        dora_license_path.read_text(encoding="utf-8"),
        strip_bsg_include=False,
        canonicalize_dora_header=False,
    ).encode("utf-8")
    basejump_license = normalize_source(
        basejump_license_path.read_text(encoding="utf-8"),
        strip_bsg_include=False,
        canonicalize_dora_header=False,
    ).encode("utf-8")

    lock = {
        "schema": "chipyard.rta_v4.reference_artifact_lock",
        "schema_version": 1,
        "stability": "experimental_reference_snapshot",
        "design": {
            "generated_top_module": EXPECTED_DESIGN,
            "adapter_top_module": "rta_v4_chipyard_adapter",
            "compiler_arch_schema_version": EXPECTED_COMPILER_ARCH_SCHEMA_VERSION,
            "fabric_contexts": EXPECTED_FABRIC_CONTEXTS,
            "layout_hash": layout_hash,
        },
        "interface": {
            "data_width": 8,
            "data_planes": 2,
            "predicate_width": 1,
            "rows": 4,
            "columns": 4,
            "packed_lane_slice": "data[8*lane +: 8]",
            "west_input": "lane r -> ipin_x(r+1)y0_*",
            "north_input": "lane c -> ipin_x0y(c+1)_*",
            "east_output": "lane r -> opin_x(r+1)y5_*",
            "south_output": "lane c -> opin_x5y(c+1)_*",
            "activity_masks_are_runtime_valid": False,
        },
        "execution": {
            "clock_enable": "en_i",
            "manual_step": "pulse en_i for one compute clock",
            "runtime_ready_valid": False,
        },
        "configuration": {
            "protocol": "serial_scan",
            "bitstream_bits": EXPECTED_BITSTREAM_BITS,
            "bitstream_bytes": expected_bitstream_bytes,
            "byte_order": "ascending",
            "bit_order_within_byte": "least_significant_bit_first",
            "valid_bits_in_last_byte": valid_bits_last_byte,
            "scan_tail_completion": "deassert prog_we_i, then wait for prog_we_o == 0",
            "scan_write_enable_first_high_bit": 66,
            "scan_tail_cycles": 65,
        },
        "artifacts": {
            BUNDLE_FILENAME: {
                "bytes": len(bundle),
                "sha256": sha256_bytes(bundle),
            },
            STAGED_ADAPTER_FILENAME: {
                "bytes": len(adapter),
                "sha256": sha256_bytes(adapter),
                "role": "auditable source copy; embedded in RtaV4Bundle.sv",
            },
            BITSTREAM_FILENAME: {
                "bytes": len(bitstream),
                "sha256": bitstream_sha256,
                "kernel": "cgra_add_chain",
                "expected_behavior": "west lane 0 data0 -> east lane 0 data0; y = x + 10",
                "enabled_cycle_latency": 13,
            },
            FASM_FILENAME: {
                "bytes": len(fasm),
                "sha256": fasm_sha256,
                "layout_hash": EXPECTED_LAYOUT_HASH,
                "kernel": "cgra_add_chain",
            },
            "compiler_arch.json": {
                "bytes": compiler_arch_path.stat().st_size,
                "sha256": compiler_arch_sha256,
                "bundled": False,
            },
            "workspace.pkl": {
                "bytes": workspace_path.stat().st_size,
                "sha256": workspace_sha256,
                "bundled": False,
                "trust": "trusted DORA compiler input; never load in Chipyard",
            },
            "rta_v4_rmu_sources.f": {
                "bytes": rmu_filelist_path.stat().st_size,
                "sha256": rmu_filelist_sha256,
                "bundled": False,
                "role": "five-file RMU subset; not the complete RTL closure",
                "entries": list(rmu_filelist_entries),
            },
            DORA_LICENSE_FILENAME: {
                "bytes": len(dora_license),
                "sha256": sha256_bytes(dora_license),
            },
            BASEJUMP_LICENSE_FILENAME: {
                "bytes": len(basejump_license),
                "sha256": sha256_bytes(basejump_license),
            },
        },
        "provenance": {
            "dora_revision": dora_revision,
            "basejump_revision": basejump_revision,
            "revision_semantics": (
                "Git revisions identify the source baselines; the explicit "
                "bundled source hashes are authoritative if a worktree differs."
            ),
            "source_closure_note": (
                "The explicit ordered paths and per-file hashes below are "
                "authoritative; rta_v4_rmu_sources.f is only the RMU subset."
            ),
            "source_hash_semantics": (
                "SHA-256 over bundled LF-normalized text with per-line trailing "
                "whitespace removed after include resolution; volatile DORA "
                "Generated-on and Author headers are canonicalized."
            ),
            "source_count": len(source_records),
            "sources": source_records,
        },
    }
    lock_data = (json.dumps(lock, indent=2, sort_keys=True) + "\n").encode("utf-8")

    if not args.check:
        output_dir.mkdir(parents=True, exist_ok=True)
    check_or_write(bundle_path, bundle, check=args.check)
    check_or_write(output_adapter_path, adapter, check=args.check)
    check_or_write(output_bitstream_path, bitstream, check=args.check)
    check_or_write(output_fasm_path, fasm, check=args.check)
    check_or_write(
        output_dir / DORA_LICENSE_FILENAME, dora_license, check=args.check
    )
    check_or_write(
        output_dir / BASEJUMP_LICENSE_FILENAME, basejump_license, check=args.check
    )
    check_or_write(output_dir / LOCK_FILENAME, lock_data, check=args.check)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(2) from error
