#!/usr/bin/env python3
"""Stage the Chipyard RTA V4 reference from a verified DORA package.

The DORA design package is the sole RTL input.  This script verifies its
complete manifest -> SHA256SUMS -> payload chain, appends the Chipyard-owned
adapter, stages package licenses verbatim, and keeps compiler metadata and
known-good workload images on the Chipyard side of the ownership boundary.
It never imports DORA Python code and never loads a workspace pickle.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Iterable

from dora_package_import import assemble_chipyard_bundle, verify_dora_package


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
SYSTOLIC_PHASES = (
    "clear",
    "compute",
    "drain_col0",
    "drain_col1",
    "drain_col2",
    "drain_col3",
)
DORA_LICENSE_FILENAME = "LICENSE.dora"
BASEJUMP_LICENSE_FILENAME = "LICENSE.basejump_stl"
PACKAGE_LICENSES = (
    ("licenses/basejump_stl-LICENSE", BASEJUMP_LICENSE_FILENAME),
    ("licenses/dora-LICENSE", DORA_LICENSE_FILENAME),
)
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
    | {
        f"systolic_{phase}{suffix}"
        for phase in SYSTOLIC_PHASES
        for suffix in (".bin", ".fasm")
    }
)

EXPECTED_PACKAGE_NAME = "rta-v4-array"
EXPECTED_PACKAGE_TOP = "rta_v4_array"
EXPECTED_PACKAGE_BUNDLE = "rtl/bundle.sv"
EXPECTED_PACKAGE_FILELIST = "rtl/files.f"
EXPECTED_DORA_PACKAGE_MANIFEST_SHA256 = (
    "ac462b1165bc68445abda143582c1d6e5c6bc8b215a08b31d31e3e546a5a5ea1"
)
EXPECTED_COMPILER_ARCH_SCHEMA_VERSION = 6
EXPECTED_BITSTREAM_BITS = 3140
EXPECTED_FABRIC_CONTEXTS = 1
EXPECTED_LAYOUT_HASH = (
    "36c02b053e3686484ccd7b8433bd5facfc295734667b01ac7a4ba9268a0b9e7a"
)
EXPECTED_COMPILER_ARCH_SHA256 = (
    "b324d16f32987cee5bf25995059391147e823bcb9800d78dbf0679dab8d4b1ae"
)
EXPECTED_ADD_CHAIN_SHA256 = (
    "567763f047f3b75e5190dc2baf09fdec1fae0dd91df55a67fca3dbeb2937ceab"
)
EXPECTED_ADD_CHAIN_FASM_SHA256 = (
    "d0355eb0d564f3a266ed262b873f4ba5a1762b4cb8d932d29bcd309557d0b1d0"
)
EXPECTED_SYSTOLIC_SHA256 = {
    "clear": {
        "bin": "b1bf5027957a95a3cf225ccb3214fbe2acc45dbb7d074d454f735f871ba81084",
        "fasm": "df671716683aeaab6a3078c4d8d9666a9802813767be9d719ff25fae01918a09",
    },
    "compute": {
        "bin": "58e2d7f526a6a6c67185880a220c539726f14d80e5d79c3eb8721ad894af571d",
        "fasm": "a292b81673e9bb31fbff446f33f64af1d15afc9296d2c424767f792d6ad5d84a",
    },
    "drain_col0": {
        "bin": "d2cb47bb1670fed8253a70dda94ac99c778f7a3e0c760980ae59eaaa285c5e05",
        "fasm": "c838ad21bb274f0fb589e8f0593bf43e2fc28d17fdcb6485a9c88b94a130df39",
    },
    "drain_col1": {
        "bin": "fe341d9cfd5c99fd026b1b98ca3a8fe69d107f2c4c25d18024446b069e07578e",
        "fasm": "f0fdf21209b9b30bd5024a6d52e3b970deaa39d7d30a48913acb256a672a8e2a",
    },
    "drain_col2": {
        "bin": "1362fb728db0330a423b0dbd6db7c1930fc1778098afc7918e710d82e63ce26a",
        "fasm": "98b1252f4395794920f76e9f491e52b8d992ff1950c4f5fe6727b9f7a885b4c1",
    },
    "drain_col3": {
        "bin": "cf2cb5a1b74648122b648a30fea1eaac18a026cf716248fb2e34c395a1c75d3a",
        "fasm": "23107c21a5b6790b4ee399f5cc658906dbb6f2ddee4fe352aea41371e13f1105",
    },
}
SYSTOLIC_WORKLOAD_PROTOCOL = {
    "oracle": "tests/array_systolic",
    "rows": 4,
    "columns": 4,
    "lanes_per_packet": 4,
    "operand_format": "signed_int4",
    "accumulator_bits": 16,
    "accumulator_signed": True,
    "k_min": 1,
    "k_max": 8,
    "configuration_modes": {
        "cold": {
            "reset_compute_state": True,
            "compute_enabled_during_scan": False,
        },
        "preserve_compute_state": {
            "reset_compute_state": False,
            "compute_enabled_during_scan": False,
        },
    },
    "phase_order": [
        "clear",
        "compute",
        "drain_col3",
        "drain_col2",
        "drain_col1",
        "drain_col0",
    ],
    "phases": [
        {
            "phase": "clear",
            "bitstream": "systolic_clear.bin",
            "fasm": "systolic_clear.fasm",
            "configuration": "cold",
            "release_compute_reset": True,
            "input": "zero",
            "enabled_cycles": 3,
        },
        {
            "phase": "compute",
            "bitstream": "systolic_compute.bin",
            "fasm": "systolic_compute.fasm",
            "configuration": "preserve_compute_state",
            "input": "west_A_rows_north_B_columns",
            "input_cycles": "K",
            "flush_input": "zero",
            "flush_cycles": 16,
        },
        {
            "phase": "drain_col3",
            "bitstream": "systolic_drain_col3.bin",
            "fasm": "systolic_drain_col3.fasm",
            "configuration": "preserve_compute_state",
            "input": "zero",
            "enabled_cycles": 2,
            "output_column": 3,
            "output": "east_data1:east_data0_per_row",
        },
        {
            "phase": "drain_col2",
            "bitstream": "systolic_drain_col2.bin",
            "fasm": "systolic_drain_col2.fasm",
            "configuration": "preserve_compute_state",
            "input": "zero",
            "enabled_cycles": 3,
            "output_column": 2,
            "output": "east_data1:east_data0_per_row",
        },
        {
            "phase": "drain_col1",
            "bitstream": "systolic_drain_col1.bin",
            "fasm": "systolic_drain_col1.fasm",
            "configuration": "preserve_compute_state",
            "input": "zero",
            "enabled_cycles": 4,
            "output_column": 1,
            "output": "east_data1:east_data0_per_row",
        },
        {
            "phase": "drain_col0",
            "bitstream": "systolic_drain_col0.bin",
            "fasm": "systolic_drain_col0.fasm",
            "configuration": "preserve_compute_state",
            "input": "zero",
            "enabled_cycles": 5,
            "output_column": 0,
            "output": "east_data1:east_data0_per_row",
        },
    ],
}
BUNDLE_HEADER = (
    "// Generated by scripts/prepare-rta-v4-bundle.py. DO NOT EDIT.\n"
    "// This is a deterministic reference snapshot, not a stable DORA ABI.\n"
    "// Source hashes and provenance are recorded in "
    "rta_v4_artifact_lock.json.\n\n"
    "`timescale 1ns/1ps\n\n"
).encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def require_regular_file(path: Path, description: str) -> None:
    if path.is_symlink() or not path.is_file():
        raise ValueError(
            f"{description} is missing or not a regular non-symlink file: {path}"
        )


def validate_output_closure(output_dir: Path) -> None:
    if not output_dir.exists():
        return
    if output_dir.is_symlink() or not output_dir.is_dir():
        raise ValueError(f"artifact output is not a regular directory: {output_dir}")
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


def parse_args(argv: Iterable[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    package_default = os.environ.get("DORA_PACKAGE")
    parser.add_argument(
        "--dora-package",
        type=Path,
        default=Path(package_default) if package_default else None,
        required=package_default is None,
        help="DORA design-package root (or set DORA_PACKAGE)",
    )
    parser.add_argument(
        "--compiler-arch",
        type=Path,
        help=(
            "RTA compiler_arch.json; defaults to the build directory that "
            "contains the package/ directory"
        ),
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
        "--systolic-dir",
        type=Path,
        required=True,
        help=(
            "directory generated by array_systolic/gen_systolic_bitstreams.py; "
            "must contain clear, compute, and drain_col0..3 .bin/.fasm pairs"
        ),
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
        if path.read_bytes() != data:
            raise ValueError(f"checked-in artifact is stale: {path}")
        print(f"verified {path}")
        return
    if path.is_file() and not path.is_symlink() and path.read_bytes() == data:
        print(f"unchanged {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    print(f"wrote {path}")


def validate_compiler_arch(path: Path) -> tuple[dict[str, Any], str]:
    require_regular_file(path, "compiler metadata")
    digest = sha256_file(path)
    if digest != EXPECTED_COMPILER_ARCH_SHA256:
        raise ValueError(
            "compiler metadata digest differs from the supplied reference: "
            f"{digest}"
        )
    metadata = json.loads(path.read_text(encoding="utf-8"))
    expected = {
        "schema_version": EXPECTED_COMPILER_ARCH_SCHEMA_VERSION,
        "design": EXPECTED_PACKAGE_TOP,
        "bitstream_size": EXPECTED_BITSTREAM_BITS,
        "fabric_contexts": EXPECTED_FABRIC_CONTEXTS,
        "layout_hash": EXPECTED_LAYOUT_HASH,
    }
    for key, value in expected.items():
        if metadata.get(key) != value:
            raise ValueError(
                f"compiler metadata {key} mismatch: expected {value!r}, "
                f"got {metadata.get(key)!r}"
            )
    return metadata, digest


def validate_bitstream(data: bytes, description: str) -> None:
    expected_bytes = (EXPECTED_BITSTREAM_BITS + 7) // 8
    valid_bits_last_byte = EXPECTED_BITSTREAM_BITS % 8 or 8
    if len(data) != expected_bytes:
        raise ValueError(
            f"expected {expected_bytes} bytes in {description}, got {len(data)}"
        )
    unused_mask = 0xFF & ~((1 << valid_bits_last_byte) - 1)
    if data[-1] & unused_mask:
        raise ValueError(
            f"unused high bits of {description} must be zero: 0x{data[-1]:02x}"
        )


def validate_fasm(data: bytes, description: str) -> None:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError(f"{description} is not UTF-8") from error
    match = re.search(
        r"^# dora_layout_hash: ([0-9a-f]{64})$", text, re.MULTILINE
    )
    if match is None or match.group(1) != EXPECTED_LAYOUT_HASH:
        raise ValueError(f"{description} layout hash does not match compiler metadata")


def artifact_record(data: bytes, **metadata: object) -> dict[str, object]:
    return {"bytes": len(data), "sha256": sha256_bytes(data), **metadata}


def main(argv: Iterable[str] = sys.argv[1:]) -> int:
    args = parse_args(argv)
    package_path = args.dora_package.absolute()
    output_dir = args.output_dir.absolute()
    validate_output_closure(output_dir)

    package = verify_dora_package(
        package_path,
        expected_manifest_sha256=EXPECTED_DORA_PACKAGE_MANIFEST_SHA256,
        expected_name=EXPECTED_PACKAGE_NAME,
        expected_top=EXPECTED_PACKAGE_TOP,
        allow_workspace=False,
    )
    if package.manifest.get("bundle") != EXPECTED_PACKAGE_BUNDLE:
        raise ValueError(
            f"expected package bundle {EXPECTED_PACKAGE_BUNDLE!r}, got "
            f"{package.manifest.get('bundle')!r}"
        )
    if package.manifest.get("filelist") != EXPECTED_PACKAGE_FILELIST:
        raise ValueError(
            f"expected package filelist {EXPECTED_PACKAGE_FILELIST!r}, got "
            f"{package.manifest.get('filelist')!r}"
        )
    if not package.source_paths:
        raise ValueError(
            "the DORA package filelist and bundle contain no compile sources"
        )

    compiler_arch_path = (
        args.compiler_arch.absolute()
        if args.compiler_arch is not None
        else (package_path.parent.parent / "compiler_arch.json").absolute()
    )
    _, compiler_arch_sha256 = validate_compiler_arch(compiler_arch_path)

    adapter_path = args.adapter.absolute()
    bitstream_path = args.add_chain_bitstream.absolute()
    fasm_path = args.add_chain_fasm.absolute()
    systolic_dir = args.systolic_dir.absolute()
    require_regular_file(adapter_path, "packed SystemVerilog adapter")
    require_regular_file(bitstream_path, "add-chain bitstream")
    require_regular_file(fasm_path, "add-chain FASM")
    if systolic_dir.is_symlink() or not systolic_dir.is_dir():
        raise ValueError(
            "systolic artifact directory is missing or not a regular directory: "
            f"{systolic_dir}"
        )

    bitstream = bitstream_path.read_bytes()
    validate_bitstream(bitstream, "add-chain bitstream")
    bitstream_sha256 = sha256_bytes(bitstream)
    if bitstream_sha256 != EXPECTED_ADD_CHAIN_SHA256:
        raise ValueError(
            "add-chain bitstream digest does not match the known-good reference: "
            f"{bitstream_sha256}"
        )
    fasm = fasm_path.read_bytes()
    validate_fasm(fasm, "add-chain FASM")
    fasm_sha256 = sha256_bytes(fasm)
    if fasm_sha256 != EXPECTED_ADD_CHAIN_FASM_SHA256:
        raise ValueError(
            "add-chain FASM digest does not match the known-good reference: "
            f"{fasm_sha256}"
        )

    systolic_artifacts: dict[str, tuple[bytes, bytes]] = {}
    for phase in SYSTOLIC_PHASES:
        phase_bitstream_path = systolic_dir / f"{phase}.bin"
        phase_fasm_path = systolic_dir / f"{phase}.fasm"
        require_regular_file(phase_bitstream_path, f"systolic {phase} bitstream")
        require_regular_file(phase_fasm_path, f"systolic {phase} FASM")
        phase_bitstream = phase_bitstream_path.read_bytes()
        phase_fasm = phase_fasm_path.read_bytes()
        validate_bitstream(phase_bitstream, f"systolic {phase} bitstream")
        validate_fasm(phase_fasm, f"systolic {phase} FASM")
        if sha256_bytes(phase_bitstream) != EXPECTED_SYSTOLIC_SHA256[phase]["bin"]:
            raise ValueError(
                f"systolic {phase} bitstream digest does not match the "
                "known-good DORA oracle"
            )
        if sha256_bytes(phase_fasm) != EXPECTED_SYSTOLIC_SHA256[phase]["fasm"]:
            raise ValueError(
                f"systolic {phase} FASM digest does not match the known-good "
                "DORA oracle"
            )
        systolic_artifacts[phase] = (phase_bitstream, phase_fasm)

    bundle, adapter = assemble_chipyard_bundle(
        package,
        adapter_path.read_bytes(),
        header_bytes=BUNDLE_HEADER,
        adapter_display_path=f"chipyard/{ADAPTER_FILENAME}",
    )
    if re.search(rb"^\s*`include\b", bundle, re.MULTILINE):
        raise ValueError("assembled bundle contains an external include directive")

    payload_by_path = {entry.path: entry for entry in package.payload_entries}
    license_data: dict[str, bytes] = {}
    license_mappings: list[dict[str, str]] = []
    for package_rel, staged_name in PACKAGE_LICENSES:
        entry = payload_by_path.get(package_rel)
        if entry is None:
            raise ValueError(f"package license is missing from payload: {package_rel}")
        data = package.read_payload(package_rel)
        license_data[staged_name] = data
        license_mappings.append(
            {"package_path": package_rel, "staged_path": staged_name}
        )

    package_bundle_entry = payload_by_path[EXPECTED_PACKAGE_BUNDLE]
    package_filelist_entry = payload_by_path[EXPECTED_PACKAGE_FILELIST]
    package_payload = [
        {"bytes": entry.size, "path": entry.path, "sha256": entry.sha256}
        for entry in package.payload_entries
    ]
    expected_bitstream_bytes = (EXPECTED_BITSTREAM_BITS + 7) // 8
    valid_bits_last_byte = EXPECTED_BITSTREAM_BITS % 8 or 8

    artifacts: dict[str, dict[str, object]] = {
        BUNDLE_FILENAME: artifact_record(
            bundle,
            role="DORA package bundle followed by the Chipyard adapter",
        ),
        STAGED_ADAPTER_FILENAME: artifact_record(
            adapter,
            role="auditable Chipyard source copy; appended to RtaV4Bundle.sv",
        ),
        BITSTREAM_FILENAME: artifact_record(
            bitstream,
            kernel="cgra_add_chain",
            expected_behavior=(
                "west lane 0 data0 -> east lane 0 data0; y = x + 10"
            ),
            enabled_cycle_latency=13,
            manual_steps_from_reset=14,
        ),
        FASM_FILENAME: artifact_record(
            fasm,
            layout_hash=EXPECTED_LAYOUT_HASH,
            kernel="cgra_add_chain",
        ),
        "compiler_arch.json": {
            "bytes": compiler_arch_path.stat().st_size,
            "sha256": compiler_arch_sha256,
            "bundled": False,
            "role": "Chipyard-side compiler and configuration metadata",
        },
    }
    for phase, (phase_bitstream, phase_fasm) in systolic_artifacts.items():
        artifacts[f"systolic_{phase}.bin"] = artifact_record(
            phase_bitstream,
            kernel="systolic_dot4_gemm",
            phase=phase,
            oracle="tests/array_systolic",
        )
        artifacts[f"systolic_{phase}.fasm"] = artifact_record(
            phase_fasm,
            layout_hash=EXPECTED_LAYOUT_HASH,
            kernel="systolic_dot4_gemm",
            phase=phase,
            oracle="tests/array_systolic",
        )
    for package_rel, staged_name in PACKAGE_LICENSES:
        scope = (
            "BaseJump sections embedded in the composite DORA bundle"
            if staged_name == BASEJUMP_LICENSE_FILENAME
            else "DORA-generated sections embedded in the composite DORA bundle"
        )
        artifacts[staged_name] = artifact_record(
            license_data[staged_name],
            package_path=package_rel,
            license_scope=scope,
        )

    lock = {
        "schema": "chipyard.rta_v4.reference_artifact_lock",
        "schema_version": 2,
        "stability": "experimental_reference_snapshot",
        "design": {
            "generated_top_module": EXPECTED_PACKAGE_TOP,
            "adapter_top_module": "rta_v4_chipyard_adapter",
            "compiler_arch_schema_version": EXPECTED_COMPILER_ARCH_SCHEMA_VERSION,
            "fabric_contexts": EXPECTED_FABRIC_CONTEXTS,
            "layout_hash": EXPECTED_LAYOUT_HASH,
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
            "scan_tail_completion": (
                "deassert prog_we_i, then wait for prog_we_o == 0"
            ),
            "scan_write_enable_first_high_bit": 66,
            "scan_tail_cycles": 65,
        },
        "workloads": {"systolic_dot4_gemm": SYSTOLIC_WORKLOAD_PROTOCOL},
        "artifacts": artifacts,
        "dora_package": {
            "manifest": package.manifest,
            "manifest_bytes": len(package.manifest_bytes),
            "manifest_sha256": package.manifest_sha256,
            "checksums_bytes": len(package.checksums_bytes),
            "checksums_sha256": package.checksums_sha256,
            "payload_file_count": len(package.payload_entries),
            "payload": package_payload,
            "filelist": {
                "path": package_filelist_entry.path,
                "bytes": package_filelist_entry.size,
                "sha256": package_filelist_entry.sha256,
                "source_count": len(package.source_paths),
                "include_dirs": list(package.include_dirs),
                "compile_working_directory": "rtl",
                "supported_invocation": "<tool> -f files.f",
                "vcs_capital_f_rebases_incdirs": False,
            },
            "bundle": {
                "path": package_bundle_entry.path,
                "bytes": package_bundle_entry.size,
                "sha256": package_bundle_entry.sha256,
                "source_count": len(package.source_paths),
                "composite_license": True,
                "licenses": license_mappings,
                "source_marker_traceability": (
                    "BEGIN SOURCE paths identify each embedded source's package "
                    "path and license ownership."
                ),
            },
        },
        "provenance": {
            "package_manifest_sha256": package.manifest_sha256,
            "package_payload_digest": package.manifest["payload_digest"],
            "package_provenance": package.manifest["provenance"],
            "identity_semantics": (
                "The canonical DORA manifest hash transitively pins exact "
                "SHA256SUMS bytes and every package payload byte."
            ),
            "rtl_revalidation_semantics": (
                "Compare the package bundle/source digests when provenance-only "
                "DORA commits change the manifest identity."
            ),
            "consumer_boundary": (
                "The package owns RTL and its licenses; Chipyard owns the "
                "adapter, compiler metadata, ABI, and workload images."
            ),
        },
    }
    lock_data = (json.dumps(lock, indent=2, sort_keys=True) + "\n").encode("utf-8")

    if not args.check:
        output_dir.mkdir(parents=True, exist_ok=True)
    outputs = {
        BUNDLE_FILENAME: bundle,
        STAGED_ADAPTER_FILENAME: adapter,
        BITSTREAM_FILENAME: bitstream,
        FASM_FILENAME: fasm,
        LOCK_FILENAME: lock_data,
        **license_data,
    }
    for phase, (phase_bitstream, phase_fasm) in systolic_artifacts.items():
        outputs[f"systolic_{phase}.bin"] = phase_bitstream
        outputs[f"systolic_{phase}.fasm"] = phase_fasm
    for filename, data in outputs.items():
        check_or_write(output_dir / filename, data, check=args.check)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(2) from error
