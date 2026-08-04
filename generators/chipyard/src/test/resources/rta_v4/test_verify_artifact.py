#!/usr/bin/env python3
"""Adversarial checks for the offline RTA V4 artifact verifier."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


VERIFIER = Path(__file__).resolve().with_name("verify_artifact.py")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("resource_dir", type=Path)
    parser.add_argument("adapter_source", type=Path)
    return parser.parse_args()


def replace_once(path: Path, old: bytes, new: bytes) -> None:
    data = path.read_bytes()
    if data.count(old) != 1:
        raise RuntimeError(f"expected one mutation target in {path}: {old!r}")
    path.write_bytes(data.replace(old, new, 1))


def load_lock(resource_dir: Path) -> dict[str, object]:
    return json.loads(
        (resource_dir / "rta_v4_artifact_lock.json").read_text(encoding="utf-8")
    )


def write_lock(resource_dir: Path, lock: dict[str, object]) -> None:
    data = (json.dumps(lock, indent=2, sort_keys=True) + "\n").encode("utf-8")
    (resource_dir / "rta_v4_artifact_lock.json").write_bytes(data)


def refresh_artifact_record(resource_dir: Path, filename: str) -> None:
    lock = load_lock(resource_dir)
    artifacts = lock["artifacts"]
    if not isinstance(artifacts, dict) or filename not in artifacts:
        raise RuntimeError(f"missing artifact record: {filename}")
    record = artifacts[filename]
    if not isinstance(record, dict):
        raise RuntimeError(f"invalid artifact record: {filename}")
    data = (resource_dir / filename).read_bytes()
    record["bytes"] = len(data)
    record["sha256"] = hashlib.sha256(data).hexdigest()
    write_lock(resource_dir, lock)


def run_verifier(resource_dir: Path, adapter_source: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(VERIFIER),
            str(resource_dir),
            "--adapter-source",
            str(adapter_source),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )


def require_pass(resource_dir: Path, adapter_source: Path, name: str) -> None:
    result = run_verifier(resource_dir, adapter_source)
    if result.returncode != 0:
        raise RuntimeError(
            f"{name}: verifier unexpectedly failed\n{result.stdout}{result.stderr}"
        )


def require_fail(
    resource_dir: Path, adapter_source: Path, name: str, expected: str
) -> None:
    result = run_verifier(resource_dir, adapter_source)
    output = result.stdout + result.stderr
    if result.returncode == 0:
        raise RuntimeError(f"{name}: verifier unexpectedly accepted corruption")
    if expected not in output:
        raise RuntimeError(
            f"{name}: verifier failed for the wrong reason; expected {expected!r}\n"
            f"{output}"
        )


def copy_case(root: Path, name: str, resource_dir: Path, adapter: Path) -> tuple[Path, Path]:
    case_dir = root / name
    case_resource = case_dir / "resources"
    case_adapter = case_dir / "adapter.sv"
    shutil.copytree(resource_dir, case_resource)
    case_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(adapter, case_adapter)
    return case_resource, case_adapter


def main() -> int:
    args = parse_args()
    resource_dir = args.resource_dir.resolve()
    adapter = args.adapter_source.resolve()
    tmpdir = os.environ.get("TMPDIR")
    if not tmpdir:
        raise RuntimeError("TMPDIR must be set")

    require_pass(resource_dir, adapter, "baseline")

    with tempfile.TemporaryDirectory(prefix="rta-v4-verifier-", dir=tmpdir) as temp:
        root = Path(temp)

        case_resource, case_adapter = copy_case(
            root, "normalized-adapter", resource_dir, adapter
        )
        text = case_adapter.read_text(encoding="utf-8")
        case_adapter.write_bytes(text.replace("\n", "\r\n").encode("utf-8"))
        require_pass(case_resource, case_adapter, "CRLF adapter normalization")

        case_resource, case_adapter = copy_case(
            root, "authored-drift", resource_dir, adapter
        )
        replace_once(case_adapter, b"west_data0_i[7:0]", b"west_data0_i[8:1]")
        require_fail(
            case_resource,
            case_adapter,
            "authored adapter drift",
            "SHA-256 mismatch after source normalization",
        )

        case_resource, case_adapter = copy_case(
            root, "embedded-drift", resource_dir, adapter
        )
        bundle = case_resource / "RtaV4Bundle.sv"
        replace_once(bundle, b"west_data0_i[7:0]", b"west_data0_i[8:1]")
        refresh_artifact_record(case_resource, "RtaV4Bundle.sv")
        require_fail(
            case_resource,
            case_adapter,
            "embedded adapter drift",
            "bundled source SHA-256 mismatch: chipyard/rta_v4_chipyard_adapter.sv",
        )

        case_resource, case_adapter = copy_case(
            root, "unrecorded-content", resource_dir, adapter
        )
        bundle = case_resource / "RtaV4Bundle.sv"
        replace_once(
            bundle,
            b"// Source hashes and provenance are recorded in "
            b"rta_v4_artifact_lock.json.\n\n`timescale 1ns/1ps\n\n",
            b"// Source hashes and provenance are recorded in "
            b"rta_v4_artifact_lock.json.\n\n`timescale 1ns/1ps\n\n"
            b"module unrecorded; endmodule\n\n",
        )
        refresh_artifact_record(case_resource, "RtaV4Bundle.sv")
        require_fail(
            case_resource,
            case_adapter,
            "unrecorded bundle content",
            "unexpected content before bundled source section",
        )

        case_resource, case_adapter = copy_case(
            root, "bitstream-corruption", resource_dir, adapter
        )
        bitstream = case_resource / "add_chain_compute.bin"
        data = bytearray(bitstream.read_bytes())
        data[0] ^= 1
        bitstream.write_bytes(data)
        refresh_artifact_record(case_resource, "add_chain_compute.bin")
        require_fail(
            case_resource,
            case_adapter,
            "bitstream corruption",
            "golden bitstream mismatch",
        )

        case_resource, case_adapter = copy_case(
            root, "fasm-corruption", resource_dir, adapter
        )
        fasm = case_resource / "add_chain_compute.fasm"
        replace_once(
            fasm,
            b"pe_0_0.const_inst[7:0] = 8'b00000001",
            b"pe_0_0.const_inst[7:0] = 8'b00000000",
        )
        refresh_artifact_record(case_resource, "add_chain_compute.fasm")
        require_fail(
            case_resource,
            case_adapter,
            "FASM corruption",
            "golden FASM mismatch",
        )

        case_resource, case_adapter = copy_case(
            root, "systolic-bitstream-corruption", resource_dir, adapter
        )
        bitstream = case_resource / "systolic_compute.bin"
        data = bytearray(bitstream.read_bytes())
        data[0] ^= 1
        bitstream.write_bytes(data)
        refresh_artifact_record(case_resource, "systolic_compute.bin")
        require_fail(
            case_resource,
            case_adapter,
            "systolic bitstream corruption",
            "golden systolic compute bitstream mismatch",
        )

        case_resource, case_adapter = copy_case(
            root, "systolic-fasm-corruption", resource_dir, adapter
        )
        fasm = case_resource / "systolic_compute.fasm"
        replace_once(
            fasm,
            b"pe_0_0.rmu_inst[4:0] = 5'b00011",
            b"pe_0_0.rmu_inst[4:0] = 5'b00010",
        )
        refresh_artifact_record(case_resource, "systolic_compute.fasm")
        require_fail(
            case_resource,
            case_adapter,
            "systolic FASM corruption",
            "golden systolic compute FASM mismatch",
        )

        case_resource, case_adapter = copy_case(
            root, "systolic-protocol-corruption", resource_dir, adapter
        )
        lock = load_lock(case_resource)
        workloads = lock.get("workloads")
        if not isinstance(workloads, dict):
            raise RuntimeError("invalid workload records")
        workload = workloads.get("systolic_dot4_gemm")
        if not isinstance(workload, dict):
            raise RuntimeError("missing systolic workload record")
        phases = workload.get("phases")
        if not isinstance(phases, list) or not isinstance(phases[1], dict):
            raise RuntimeError("invalid systolic phase records")
        phases[1]["configuration"] = "cold"
        write_lock(case_resource, lock)
        require_fail(
            case_resource,
            case_adapter,
            "systolic protocol corruption",
            "systolic workload protocol mismatch",
        )

        case_resource, case_adapter = copy_case(
            root, "systolic-provenance-corruption", resource_dir, adapter
        )
        lock = load_lock(case_resource)
        artifacts = lock.get("artifacts")
        if not isinstance(artifacts, dict):
            raise RuntimeError("invalid artifact records")
        record = artifacts.get("systolic_compute.bin")
        if not isinstance(record, dict):
            raise RuntimeError("missing systolic compute record")
        record["oracle"] = "tests/not_the_array_systolic_oracle"
        write_lock(case_resource, lock)
        require_fail(
            case_resource,
            case_adapter,
            "systolic provenance corruption",
            "systolic compute bitstream provenance mismatch",
        )

        case_resource, case_adapter = copy_case(
            root, "unexpected-artifact", resource_dir, adapter
        )
        (case_resource / "unexpected.txt").write_text(
            "not part of the locked artifact\n", encoding="utf-8"
        )
        require_fail(
            case_resource,
            case_adapter,
            "unexpected artifact entry",
            "artifact directory closure mismatch (unexpected: unexpected.txt)",
        )

        case_resource, case_adapter = copy_case(
            root, "missing-artifact", resource_dir, adapter
        )
        (case_resource / "systolic_drain_col0.fasm").unlink()
        require_fail(
            case_resource,
            case_adapter,
            "missing artifact entry",
            "artifact directory closure mismatch (missing: systolic_drain_col0.fasm)",
        )

        case_resource, case_adapter = copy_case(
            root, "symlink-artifact", resource_dir, adapter
        )
        symlink = case_resource / "LICENSE.dora"
        symlink.unlink()
        symlink.symlink_to("LICENSE.basejump_stl")
        require_fail(
            case_resource,
            case_adapter,
            "symlink artifact entry",
            "artifact entry is not a regular non-symlink file: LICENSE.dora",
        )

        case_resource, case_adapter = copy_case(
            root, "metadata-corruption", resource_dir, adapter
        )
        lock = load_lock(case_resource)
        design = lock["design"]
        if not isinstance(design, dict):
            raise RuntimeError("invalid design record")
        design["fabric_contexts"] = 2
        write_lock(case_resource, lock)
        require_fail(
            case_resource,
            case_adapter,
            "lock metadata corruption",
            "fabric context count mismatch",
        )

    print("PASS: RTA V4 artifact verifier adversarial regression")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, json.JSONDecodeError) as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(2) from error
