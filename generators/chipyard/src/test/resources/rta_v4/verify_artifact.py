#!/usr/bin/env python3
"""Verify the frozen RTA V4 bundle and golden workloads without DORA."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path


EXPECTED_SCHEMA = "chipyard.rta_v4.reference_artifact_lock"
EXPECTED_SCHEMA_VERSION = 2
EXPECTED_DESIGN = "rta_v4_array"
EXPECTED_ADAPTER = "rta_v4_chipyard_adapter"
EXPECTED_PACKAGE_NAME = "rta-v4-array"
EXPECTED_PACKAGE_FORMAT = 1
EXPECTED_PACKAGE_MANIFEST_SHA256 = (
    "ac462b1165bc68445abda143582c1d6e5c6bc8b215a08b31d31e3e546a5a5ea1"
)
EXPECTED_PACKAGE_BUNDLE_PATH = "rtl/bundle.sv"
EXPECTED_PACKAGE_FILELIST_PATH = "rtl/files.f"
EXPECTED_PACKAGE_CHECKSUMS_PATH = "SHA256SUMS"
EXPECTED_PACKAGE_INCLUDE_DIRS = ["src/dependencies/basejump_stl/bsg_misc"]
EXPECTED_PACKAGE_LICENSES = [
    {
        "package_path": "licenses/basejump_stl-LICENSE",
        "staged_path": "LICENSE.basejump_stl",
    },
    {
        "package_path": "licenses/dora-LICENSE",
        "staged_path": "LICENSE.dora",
    },
]
EXPECTED_SOURCE_MARKER_TRACEABILITY = (
    "BEGIN SOURCE paths identify each embedded source's package path and "
    "license ownership."
)
EXPECTED_LICENSE_SCOPES = {
    "LICENSE.basejump_stl": (
        "BaseJump sections embedded in the composite DORA bundle"
    ),
    "LICENSE.dora": "DORA-generated sections embedded in the composite DORA bundle",
}
EXPECTED_COMPILER_ARCH_SCHEMA_VERSION = 6
EXPECTED_FABRIC_CONTEXTS = 1
EXPECTED_LAYOUT_HASH = (
    "36c02b053e3686484ccd7b8433bd5facfc295734667b01ac7a4ba9268a0b9e7a"
)
EXPECTED_BITSTREAM_BITS = 3140
EXPECTED_BITSTREAM_BYTES = 393
EXPECTED_BITSTREAM_SHA256 = (
    "567763f047f3b75e5190dc2baf09fdec1fae0dd91df55a67fca3dbeb2937ceab"
)
EXPECTED_FASM_SHA256 = (
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
EXPECTED_SYSTOLIC_WORKLOAD_PROTOCOL = {
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
EXPECTED_UNBUNDLED_INPUTS = {
    "compiler_arch.json": (
        2_805_559,
        "b324d16f32987cee5bf25995059391147e823bcb9800d78dbf0679dab8d4b1ae",
    ),
}
EXPECTED_BUNDLED_ARTIFACT_FILENAMES = frozenset(
    {
        "LICENSE.basejump_stl",
        "LICENSE.dora",
        "RtaV4Bundle.sv",
        "add_chain_compute.bin",
        "add_chain_compute.fasm",
        "rta_v4_chipyard_adapter.sv.source",
    }
    | {
        f"systolic_{phase}{suffix}"
        for phase in EXPECTED_SYSTOLIC_SHA256
        for suffix in (".bin", ".fasm")
    }
)
EXPECTED_RESOURCE_FILENAMES = EXPECTED_BUNDLED_ARTIFACT_FILENAMES | {
    "README.md",
    "rta_v4_artifact_lock.json",
}
EXPECTED_ARTIFACT_RECORD_NAMES = EXPECTED_BUNDLED_ARTIFACT_FILENAMES | frozenset(
    EXPECTED_UNBUNDLED_INPUTS
)
SOURCE_DIVIDER = "// " + "=" * 76
BUNDLE_PREFIX = (
    "// Generated by scripts/prepare-rta-v4-bundle.py. DO NOT EDIT.\n"
    "// This is a deterministic reference snapshot, not a stable DORA ABI.\n"
    "// Source hashes and provenance are recorded in "
    "rta_v4_artifact_lock.json.\n\n"
    "`timescale 1ns/1ps\n\n"
)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def require_record(
    records: object, name: str, *, collection: str = "artifact"
) -> dict[str, object]:
    require(isinstance(records, dict), f"invalid {collection} record collection")
    record = records.get(name)
    require(isinstance(record, dict), f"missing {collection} record: {name}")
    return record


def require_regular_file(path: Path, description: str) -> None:
    require(
        not path.is_symlink() and path.is_file(),
        f"{description} is not a regular non-symlink file: {path.name}",
    )


def verify_resource_closure(resource_dir: Path) -> None:
    require(
        not resource_dir.is_symlink() and resource_dir.is_dir(),
        f"artifact resource path is not a regular directory: {resource_dir}",
    )
    entries = {path.name: path for path in resource_dir.iterdir()}
    missing = sorted(EXPECTED_RESOURCE_FILENAMES - entries.keys())
    unexpected = sorted(entries.keys() - EXPECTED_RESOURCE_FILENAMES)
    if missing or unexpected:
        details = []
        if missing:
            details.append("missing: " + ", ".join(missing))
        if unexpected:
            details.append("unexpected: " + ", ".join(unexpected))
        raise ValueError(
            "artifact directory closure mismatch (" + "; ".join(details) + ")"
        )
    for name, path in sorted(entries.items()):
        require_regular_file(path, "artifact entry")


def verify_file(path: Path, record: dict[str, object]) -> bytes:
    require_regular_file(path, "artifact")
    data = path.read_bytes()
    require(len(data) == record.get("bytes"), f"size mismatch: {path}")
    require(sha256(data) == record.get("sha256"), f"SHA-256 mismatch: {path}")
    return data


def normalized_source_bytes(data: bytes, path: Path) -> bytes:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError(f"source is not UTF-8: {path}") from error
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = "\n".join(line.rstrip(" \t") for line in text.split("\n"))
    return (text.rstrip() + "\n").encode("utf-8")


def canonical_json_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
        + b"\n"
    )


def require_package_path(path: object, description: str) -> str:
    require(isinstance(path, str) and path != "", f"invalid {description} path")
    require(
        not path.startswith("/")
        and "\\" not in path
        and not any(character.isspace() for character in path),
        f"unsafe {description} path: {path}",
    )
    components = path.split("/")
    require(
        all(component not in ("", ".", "..") for component in components),
        f"unsafe {description} path: {path}",
    )
    return path


def verify_dora_package(
    lock: dict[str, object],
) -> tuple[dict[str, object], dict[str, dict[str, object]]]:
    package = lock.get("dora_package")
    require(isinstance(package, dict), "missing DORA package record")
    require(
        set(package)
        == {
            "manifest",
            "manifest_bytes",
            "manifest_sha256",
            "checksums_bytes",
            "checksums_sha256",
            "payload_file_count",
            "payload",
            "filelist",
            "bundle",
        },
        "DORA package record closure mismatch",
    )

    manifest = package.get("manifest")
    require(isinstance(manifest, dict), "invalid DORA package manifest")
    require(
        set(manifest)
        == {
            "bundle",
            "checksums",
            "dora_package_format",
            "filelist",
            "name",
            "payload_digest",
            "provenance",
            "top",
        },
        "DORA package manifest field closure mismatch",
    )
    manifest_data = canonical_json_bytes(manifest)
    manifest_sha256 = sha256(manifest_data)
    require(
        package.get("manifest_bytes") == len(manifest_data),
        "DORA package manifest byte count mismatch",
    )
    require(
        package.get("manifest_sha256") == manifest_sha256,
        "DORA package manifest record hash mismatch",
    )
    require(
        manifest_sha256 == EXPECTED_PACKAGE_MANIFEST_SHA256,
        "DORA package manifest pin mismatch",
    )
    require(
        manifest.get("dora_package_format") == EXPECTED_PACKAGE_FORMAT,
        "unsupported DORA package format",
    )
    require(
        manifest.get("name") == EXPECTED_PACKAGE_NAME,
        "unexpected DORA package name",
    )
    require(
        manifest.get("top") == EXPECTED_DESIGN,
        "DORA package top mismatch",
    )
    require(
        manifest.get("bundle") == EXPECTED_PACKAGE_BUNDLE_PATH,
        "DORA package bundle path mismatch",
    )
    require(
        manifest.get("filelist") == EXPECTED_PACKAGE_FILELIST_PATH,
        "DORA package filelist path mismatch",
    )
    require(
        manifest.get("checksums") == EXPECTED_PACKAGE_CHECKSUMS_PATH,
        "DORA package checksums path mismatch",
    )
    package_provenance = manifest.get("provenance")
    require(
        isinstance(package_provenance, dict) and package_provenance,
        "invalid DORA package provenance",
    )
    for component, record in package_provenance.items():
        require(
            isinstance(component, str) and component != "" and isinstance(record, dict),
            "invalid DORA package provenance component",
        )
        require(
            set(record) == {"revision", "dirty"}
            and isinstance(record.get("revision"), str)
            and record.get("revision") != ""
            and isinstance(record.get("dirty"), bool),
            f"invalid DORA package provenance record: {component}",
        )

    payload = package.get("payload")
    require(isinstance(payload, list), "invalid DORA package payload inventory")
    require(
        package.get("payload_file_count") == len(payload),
        "DORA package payload file count mismatch",
    )
    payload_by_path: dict[str, dict[str, object]] = {}
    checksum_lines: list[str] = []
    for entry in payload:
        require(
            isinstance(entry, dict) and set(entry) == {"path", "bytes", "sha256"},
            "invalid DORA package payload record",
        )
        path = require_package_path(entry.get("path"), "payload")
        digest = entry.get("sha256")
        byte_count = entry.get("bytes")
        require(
            isinstance(digest, str)
            and re.fullmatch(r"[0-9a-f]{64}", digest) is not None,
            f"invalid DORA package payload digest: {path}",
        )
        require(
            isinstance(byte_count, int)
            and not isinstance(byte_count, bool)
            and byte_count >= 0,
            f"invalid DORA package payload byte count: {path}",
        )
        require(path not in payload_by_path, f"duplicate DORA package payload: {path}")
        payload_by_path[path] = entry
        checksum_lines.append(f"{digest}  {path}\n")
    require(
        list(payload_by_path) == sorted(payload_by_path),
        "DORA package payload inventory is not in SHA256SUMS path order",
    )
    require(
        "dora-package.json" not in payload_by_path
        and EXPECTED_PACKAGE_CHECKSUMS_PATH not in payload_by_path,
        "DORA package payload inventory contains a reserved file",
    )

    checksums_data = "".join(checksum_lines).encode("utf-8")
    checksums_sha256 = sha256(checksums_data)
    require(
        package.get("checksums_bytes") == len(checksums_data),
        "DORA package SHA256SUMS byte count mismatch",
    )
    require(
        package.get("checksums_sha256") == checksums_sha256,
        "DORA package SHA256SUMS record hash mismatch",
    )
    payload_digest = f"sha256:{checksums_sha256}"
    require(
        manifest.get("payload_digest") == payload_digest,
        "DORA package manifest payload linkage mismatch",
    )

    for required_path in (
        EXPECTED_PACKAGE_BUNDLE_PATH,
        EXPECTED_PACKAGE_FILELIST_PATH,
        "README.md",
    ):
        require(
            required_path in payload_by_path,
            f"missing DORA package payload record: {required_path}",
        )

    filelist_record = package.get("filelist")
    require(isinstance(filelist_record, dict), "invalid DORA package filelist record")
    require(
        set(filelist_record)
        == {
            "path",
            "bytes",
            "sha256",
            "source_count",
            "include_dirs",
            "compile_working_directory",
            "supported_invocation",
            "vcs_capital_f_rebases_incdirs",
        },
        "DORA package filelist record closure mismatch",
    )
    package_filelist_payload = payload_by_path[EXPECTED_PACKAGE_FILELIST_PATH]
    require(
        filelist_record.get("path") == EXPECTED_PACKAGE_FILELIST_PATH
        and filelist_record.get("bytes") == package_filelist_payload.get("bytes")
        and filelist_record.get("sha256") == package_filelist_payload.get("sha256"),
        "DORA package filelist and payload inventory disagree",
    )
    source_count = filelist_record.get("source_count")
    require(
        isinstance(source_count, int)
        and not isinstance(source_count, bool)
        and source_count > 0,
        "invalid DORA package filelist source count",
    )
    require(
        filelist_record.get("include_dirs") == EXPECTED_PACKAGE_INCLUDE_DIRS,
        "DORA package filelist include directories mismatch",
    )
    require(
        filelist_record.get("compile_working_directory") == "rtl"
        and filelist_record.get("supported_invocation") == "<tool> -f files.f"
        and filelist_record.get("vcs_capital_f_rebases_incdirs") is False,
        "DORA package filelist invocation contract mismatch",
    )

    bundle_record = package.get("bundle")
    require(isinstance(bundle_record, dict), "invalid DORA package bundle record")
    require(
        set(bundle_record)
        == {
            "path",
            "bytes",
            "sha256",
            "source_count",
            "composite_license",
            "licenses",
            "source_marker_traceability",
        },
        "DORA package bundle record closure mismatch",
    )
    package_bundle_payload = payload_by_path[EXPECTED_PACKAGE_BUNDLE_PATH]
    require(
        bundle_record.get("path") == EXPECTED_PACKAGE_BUNDLE_PATH
        and bundle_record.get("bytes") == package_bundle_payload.get("bytes")
        and bundle_record.get("sha256") == package_bundle_payload.get("sha256"),
        "DORA package bundle and payload inventory disagree",
    )
    require(
        bundle_record.get("source_count") == source_count,
        "DORA package compile sets disagree on source count",
    )
    require(
        bundle_record.get("composite_license") is True,
        "DORA package bundle must be marked composite-licensed",
    )
    require(
        bundle_record.get("licenses") == EXPECTED_PACKAGE_LICENSES,
        "DORA package bundle license attribution mismatch",
    )
    require(
        bundle_record.get("source_marker_traceability")
        == EXPECTED_SOURCE_MARKER_TRACEABILITY,
        "DORA package source-marker attribution mismatch",
    )
    for license_mapping in EXPECTED_PACKAGE_LICENSES:
        package_path = license_mapping["package_path"]
        require(
            package_path in payload_by_path,
            f"missing DORA package license payload: {package_path}",
        )

    provenance = lock.get("provenance")
    require(isinstance(provenance, dict), "invalid package provenance record")
    require(
        set(provenance)
        == {
            "package_manifest_sha256",
            "package_payload_digest",
            "package_provenance",
            "identity_semantics",
            "rtl_revalidation_semantics",
            "consumer_boundary",
        },
        "package provenance record closure mismatch",
    )
    require(
        provenance.get("package_manifest_sha256") == manifest_sha256,
        "package provenance manifest hash mismatch",
    )
    require(
        provenance.get("package_payload_digest") == payload_digest,
        "package provenance payload digest mismatch",
    )
    require(
        provenance.get("package_provenance") == package_provenance,
        "package provenance differs from the manifest",
    )
    require(
        isinstance(provenance.get("identity_semantics"), str)
        and provenance.get("identity_semantics") != "",
        "missing package identity semantics",
    )
    require(
        isinstance(provenance.get("rtl_revalidation_semantics"), str)
        and provenance.get("rtl_revalidation_semantics") != "",
        "missing RTL revalidation semantics",
    )
    require(
        isinstance(provenance.get("consumer_boundary"), str)
        and provenance.get("consumer_boundary") != "",
        "missing package consumer-boundary semantics",
    )
    return bundle_record, payload_by_path


def adapter_source_section(adapter: bytes) -> bytes:
    path = "chipyard/rta_v4_chipyard_adapter.sv"
    return (
        f"{SOURCE_DIVIDER}\n"
        f"// BEGIN SOURCE: {path}\n"
        f"{SOURCE_DIVIDER}\n"
    ).encode("utf-8") + adapter + f"// END SOURCE: {path}\n".encode("utf-8")


def verify_combined_bundle(
    bundle: bytes,
    adapter: bytes,
    package_bundle_record: dict[str, object],
    package_payload_paths: set[str],
) -> None:
    prefix = BUNDLE_PREFIX.encode("utf-8")
    require(bundle.startswith(prefix), "bundle prefix mismatch")
    package_bytes = package_bundle_record.get("bytes")
    require(isinstance(package_bytes, int), "invalid package bundle byte count")
    package_start = len(prefix)
    package_end = package_start + package_bytes
    require(package_end <= len(bundle), "truncated package bundle")
    package_bundle = bundle[package_start:package_end]
    require(
        sha256(package_bundle) == package_bundle_record.get("sha256"),
        "DORA package bundle SHA-256 mismatch",
    )
    require(
        bundle == prefix + package_bundle + adapter_source_section(adapter),
        "combined bundle is not package bundle followed by the adapter section",
    )

    package_text = package_bundle.decode("utf-8")
    begin_paths = re.findall(r"^// BEGIN SOURCE: (.+)$", package_text, re.MULTILINE)
    end_paths = re.findall(r"^// END SOURCE: (.+)$", package_text, re.MULTILINE)
    require(
        begin_paths == end_paths
        and len(begin_paths) == package_bundle_record.get("source_count"),
        "DORA package source-marker sequence mismatch",
    )
    require(
        len(set(begin_paths)) == len(begin_paths),
        "DORA package source-marker paths are not unique",
    )
    require(
        all(path in package_payload_paths for path in begin_paths),
        "DORA package source marker lacks a payload record",
    )
    require(
        re.search(r"^\s*`include\b", package_text, re.MULTILINE) is None,
        "DORA package bundle still contains an external include directive",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("resource_dir", type=Path)
    parser.add_argument(
        "--adapter-source",
        type=Path,
        help="optional authored adapter to compare with the bundled snapshot",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    resource_dir = args.resource_dir.absolute()
    verify_resource_closure(resource_dir)
    lock_path = resource_dir / "rta_v4_artifact_lock.json"
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    require(isinstance(lock, dict), "artifact lock must be a JSON object")

    require(lock.get("schema") == EXPECTED_SCHEMA, "unexpected lock schema")
    require(
        lock.get("schema_version") == EXPECTED_SCHEMA_VERSION,
        "unexpected lock schema version",
    )
    package_bundle_record, package_payload = verify_dora_package(lock)

    design = lock.get("design", {})
    require(
        design.get("generated_top_module") == EXPECTED_DESIGN,
        "unexpected generated top module",
    )
    require(
        design.get("adapter_top_module") == EXPECTED_ADAPTER,
        "unexpected adapter top module",
    )
    require(design.get("layout_hash") == EXPECTED_LAYOUT_HASH, "layout hash mismatch")
    require(
        design.get("compiler_arch_schema_version")
        == EXPECTED_COMPILER_ARCH_SCHEMA_VERSION,
        "compiler architecture schema mismatch",
    )
    require(
        design.get("fabric_contexts") == EXPECTED_FABRIC_CONTEXTS,
        "fabric context count mismatch",
    )

    interface = lock.get("interface", {})
    require(interface.get("data_width") == 8, "unexpected data width")
    require(interface.get("data_planes") == 2, "unexpected data-plane count")
    require(interface.get("predicate_width") == 1, "unexpected predicate width")
    require(interface.get("rows") == 4, "unexpected row count")
    require(interface.get("columns") == 4, "unexpected column count")
    require(
        interface.get("packed_lane_slice") == "data[8*lane +: 8]",
        "packed-lane convention mismatch",
    )
    require(
        interface.get("west_input") == "lane r -> ipin_x(r+1)y0_*"
        and interface.get("north_input") == "lane c -> ipin_x0y(c+1)_*"
        and interface.get("east_output") == "lane r -> opin_x(r+1)y5_*"
        and interface.get("south_output") == "lane c -> opin_x5y(c+1)_*",
        "logical-to-raw lane mapping mismatch",
    )
    require(
        interface.get("activity_masks_are_runtime_valid") is False,
        "activity masks must not be described as ready/valid",
    )

    execution = lock.get("execution", {})
    require(execution.get("clock_enable") == "en_i", "clock-enable mismatch")
    require(
        execution.get("runtime_ready_valid") is False,
        "reference adapter must not claim a ready/valid protocol",
    )

    configuration = lock.get("configuration", {})
    require(
        configuration.get("protocol") == "serial_scan",
        "configuration protocol mismatch",
    )
    require(
        configuration.get("bitstream_bits") == EXPECTED_BITSTREAM_BITS,
        "bitstream length mismatch",
    )
    require(
        configuration.get("bitstream_bytes") == EXPECTED_BITSTREAM_BYTES,
        "bitstream byte count mismatch",
    )
    require(
        configuration.get("byte_order") == "ascending",
        "bitstream byte order mismatch",
    )
    require(
        configuration.get("bit_order_within_byte")
        == "least_significant_bit_first",
        "bitstream packing mismatch",
    )
    require(
        configuration.get("valid_bits_in_last_byte") == 4,
        "final bitstream byte width mismatch",
    )
    require(
        configuration.get("scan_tail_completion")
        == "deassert prog_we_i, then wait for prog_we_o == 0",
        "scan-tail completion rule mismatch",
    )
    require(
        configuration.get("scan_write_enable_first_high_bit") == 66,
        "scan write-enable assertion timing mismatch",
    )
    require(
        configuration.get("scan_tail_cycles") == 65,
        "scan-tail drain timing mismatch",
    )

    require(
        lock.get("workloads")
        == {"systolic_dot4_gemm": EXPECTED_SYSTOLIC_WORKLOAD_PROTOCOL},
        "systolic workload protocol mismatch",
    )

    artifacts = lock.get("artifacts", {})
    require(isinstance(artifacts, dict), "invalid artifact record collection")
    require(
        set(artifacts) == EXPECTED_ARTIFACT_RECORD_NAMES,
        "artifact record closure mismatch",
    )
    staged_adapter_record = require_record(
        artifacts, "rta_v4_chipyard_adapter.sv.source"
    )
    staged_adapter = verify_file(
        resource_dir / "rta_v4_chipyard_adapter.sv.source",
        staged_adapter_record,
    )
    if args.adapter_source is not None:
        adapter_source = args.adapter_source.resolve()
        require_regular_file(adapter_source, "authored adapter")
        adapter_source_data = normalized_source_bytes(
            adapter_source.read_bytes(), adapter_source
        )
        require(
            len(adapter_source_data) == staged_adapter_record.get("bytes"),
            f"size mismatch after source normalization: {adapter_source}",
        )
        require(
            sha256(adapter_source_data) == staged_adapter_record.get("sha256"),
            f"SHA-256 mismatch after source normalization: {adapter_source}",
        )

    bundle_path = resource_dir / "RtaV4Bundle.sv"
    bundle = verify_file(
        bundle_path, require_record(artifacts, "RtaV4Bundle.sv")
    )
    verify_combined_bundle(
        bundle,
        staged_adapter,
        package_bundle_record,
        set(package_payload),
    )
    bitstream_path = resource_dir / "add_chain_compute.bin"
    bitstream = verify_file(
        bitstream_path, require_record(artifacts, "add_chain_compute.bin")
    )
    require(sha256(bitstream) == EXPECTED_BITSTREAM_SHA256, "golden bitstream mismatch")
    fasm = verify_file(
        resource_dir / "add_chain_compute.fasm",
        require_record(artifacts, "add_chain_compute.fasm"),
    )
    require(sha256(fasm) == EXPECTED_FASM_SHA256, "golden FASM mismatch")
    require(
        f"# dora_layout_hash: {EXPECTED_LAYOUT_HASH}" in fasm.decode("utf-8"),
        "golden FASM layout hash mismatch",
    )
    fasm_record = require_record(artifacts, "add_chain_compute.fasm")
    require(
        fasm_record.get("layout_hash") == EXPECTED_LAYOUT_HASH
        and fasm_record.get("kernel") == "cgra_add_chain",
        "golden FASM provenance mismatch",
    )

    for phase, expected_digests in EXPECTED_SYSTOLIC_SHA256.items():
        bitstream_name = f"systolic_{phase}.bin"
        phase_bitstream = verify_file(
            resource_dir / bitstream_name,
            require_record(artifacts, bitstream_name),
        )
        require(
            sha256(phase_bitstream) == expected_digests["bin"],
            f"golden systolic {phase} bitstream mismatch",
        )
        require(
            len(phase_bitstream) == EXPECTED_BITSTREAM_BYTES,
            f"systolic {phase} bitstream byte count mismatch",
        )
        require(
            phase_bitstream[-1] & 0xF0 == 0,
            f"unused high bits in systolic {phase} bitstream are nonzero",
        )
        bitstream_record = require_record(artifacts, bitstream_name)
        require(
            bitstream_record.get("kernel") == "systolic_dot4_gemm"
            and bitstream_record.get("phase") == phase
            and bitstream_record.get("oracle") == "tests/array_systolic",
            f"systolic {phase} bitstream provenance mismatch",
        )

        fasm_name = f"systolic_{phase}.fasm"
        phase_fasm = verify_file(
            resource_dir / fasm_name,
            require_record(artifacts, fasm_name),
        )
        require(
            sha256(phase_fasm) == expected_digests["fasm"],
            f"golden systolic {phase} FASM mismatch",
        )
        require(
            f"# dora_layout_hash: {EXPECTED_LAYOUT_HASH}"
            in phase_fasm.decode("utf-8"),
            f"systolic {phase} FASM layout hash mismatch",
        )
        phase_fasm_record = require_record(artifacts, fasm_name)
        require(
            phase_fasm_record.get("layout_hash") == EXPECTED_LAYOUT_HASH
            and phase_fasm_record.get("kernel") == "systolic_dot4_gemm"
            and phase_fasm_record.get("phase") == phase
            and phase_fasm_record.get("oracle") == "tests/array_systolic",
            f"systolic {phase} FASM provenance mismatch",
        )
    for license_mapping in EXPECTED_PACKAGE_LICENSES:
        package_path = license_mapping["package_path"]
        staged_path = license_mapping["staged_path"]
        staged_license_record = require_record(artifacts, staged_path)
        require(
            staged_license_record.get("package_path") == package_path
            and staged_license_record.get("license_scope")
            == EXPECTED_LICENSE_SCOPES[staged_path],
            f"staged license attribution mismatch: {staged_path}",
        )
        staged_license = verify_file(
            resource_dir / staged_path, staged_license_record
        )
        package_license_record = package_payload[package_path]
        require(
            len(staged_license) == package_license_record.get("bytes")
            and sha256(staged_license) == package_license_record.get("sha256"),
            f"staged license differs from DORA package payload: {package_path}",
        )

    bitstream_record = require_record(artifacts, "add_chain_compute.bin")
    require(bitstream_record.get("kernel") == "cgra_add_chain", "kernel mismatch")
    require(
        bitstream_record.get("expected_behavior")
        == "west lane 0 data0 -> east lane 0 data0; y = x + 10",
        "golden behavior mismatch",
    )
    require(
        bitstream_record.get("enabled_cycle_latency") == 13,
        "golden latency mismatch",
    )
    require(
        bitstream_record.get("manual_steps_from_reset") == 14,
        "golden manual-step count mismatch",
    )

    for name, (expected_size, expected_digest) in EXPECTED_UNBUNDLED_INPUTS.items():
        record = require_record(artifacts, name)
        require(record.get("bundled") is False, f"{name} must remain unbundled")
        require(record.get("bytes") == expected_size, f"{name} size mismatch")
        require(record.get("sha256") == expected_digest, f"{name} digest mismatch")
    require(
        len(bitstream) == EXPECTED_BITSTREAM_BYTES,
        "incorrect bitstream byte count",
    )
    valid_bits = EXPECTED_BITSTREAM_BITS % 8 or 8
    unused_mask = 0xFF & ~((1 << valid_bits) - 1)
    require(
        bitstream[-1] & unused_mask == 0,
        "unused high bits in final bitstream byte are nonzero",
    )

    bundle_text = bundle.decode("utf-8")
    require(
        re.search(r"^\s*`include", bundle_text, re.MULTILINE) is None,
        "bundle still contains an external include directive",
    )
    require(
        len(re.findall(r"\bmodule\s+rta_v4_array\b", bundle_text)) == 1,
        "bundle must define rta_v4_array exactly once",
    )
    require(
        len(
            re.findall(
                r"\bmodule\s+rta_v4_chipyard_adapter\b", bundle_text
            )
        )
        == 1,
        "bundle must define rta_v4_chipyard_adapter exactly once",
    )
    print(
        "verified package-backed RTA V4 reference artifact: "
        f"{len(bundle)} bundle bytes, {len(bitstream)} bitstream bytes"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, json.JSONDecodeError) as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(2) from error
