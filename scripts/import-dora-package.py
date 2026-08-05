#!/usr/bin/env python3
"""Verify and import a generic format-1 DORA Design Package."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Iterable

from dora_package_import import (
    assemble_chipyard_bundle,
    check_or_write,
    normalize_source_bytes,
    package_metadata,
    parse_license_outputs,
    sha256_bytes,
    validate_header_bytes,
    verify_dora_package,
)


def parse_args(argv: Iterable[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", type=Path, help="DORA package root")
    parser.add_argument("--manifest-sha256", help="expected canonical manifest hash")
    parser.add_argument("--name", help="expected package name")
    parser.add_argument("--top", help="expected generated top-module name")
    parser.add_argument(
        "--disallow-workspace",
        action="store_true",
        help="reject a package whose manifest contains workspace",
    )
    parser.add_argument("--adapter", type=Path, help="consumer-owned adapter source")
    parser.add_argument(
        "--adapter-display-path",
        default="chipyard/adapter.sv",
        help="BEGIN SOURCE path recorded for the adapter",
    )
    parser.add_argument("--header", type=Path, help="bytes prepended to bundle")
    parser.add_argument("--bundle-output", type=Path, help="combined bundle output")
    parser.add_argument(
        "--adapter-output", type=Path, help="normalized adapter provenance output"
    )
    parser.add_argument(
        "--license-output",
        action="append",
        default=[],
        metavar="PACKAGE_REL=OUTPUT",
        help="copy one checksummed package license (repeatable)",
    )
    parser.add_argument(
        "--metadata-output", type=Path, help="deterministic JSON import metadata"
    )
    parser.add_argument(
        "--check", action="store_true", help="compare outputs without writing"
    )
    return parser.parse_args(list(argv))


def _regular_file(path: Path, description: str) -> bytes:
    path = path.absolute()
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{description} is not a regular non-symlink file: {path}")
    return path.read_bytes()


def _validate_output_paths(
    package_root: Path,
    outputs: list[Path],
    inputs: list[Path],
) -> None:
    resolved_outputs = [path.absolute().resolve(strict=False) for path in outputs]
    if len(set(resolved_outputs)) != len(resolved_outputs):
        raise ValueError("import output paths must be distinct")
    resolved_package = package_root.resolve()
    for output in resolved_outputs:
        try:
            output.relative_to(resolved_package)
        except ValueError:
            pass
        else:
            raise ValueError(f"refusing to write inside the verified package: {output}")
    resolved_inputs = {path.absolute().resolve(strict=False) for path in inputs}
    collisions = sorted(
        str(path) for path in resolved_outputs if path in resolved_inputs
    )
    if collisions:
        raise ValueError(
            "import output aliases an input file: " + ", ".join(collisions)
        )


def main(argv: Iterable[str] = sys.argv[1:]) -> int:
    args = parse_args(argv)
    package = verify_dora_package(
        args.package,
        expected_manifest_sha256=args.manifest_sha256,
        expected_name=args.name,
        expected_top=args.top,
        allow_workspace=not args.disallow_workspace,
    )
    license_outputs = parse_license_outputs(args.license_output)
    payload_paths = {entry.path for entry in package.payload_entries}

    output_paths = [
        path
        for path in (
            args.bundle_output,
            args.adapter_output,
            args.metadata_output,
        )
        if path is not None
    ] + [output_path for _, output_path in license_outputs]
    input_paths = [
        path for path in (args.adapter, args.header) if path is not None
    ]
    _validate_output_paths(package.root, output_paths, input_paths)

    adapter = None
    combined_bundle = package.bundle_bytes
    header = b""
    if args.header is not None:
        header = validate_header_bytes(
            _regular_file(args.header, "bundle header")
        )
    if args.adapter is not None:
        adapter_input = _regular_file(args.adapter, "adapter")
        combined_bundle, adapter = assemble_chipyard_bundle(
            package,
            adapter_input,
            header_bytes=header,
            adapter_display_path=args.adapter_display_path,
        )
    else:
        combined_bundle = header + package.bundle_bytes
        if args.adapter_output is not None:
            raise ValueError("--adapter-output requires --adapter")
    if args.bundle_output is None and (
        args.adapter is not None or args.header is not None
    ):
        raise ValueError("--adapter or --header requires --bundle-output")

    metadata = package_metadata(package)
    imported: dict[str, object] = {
        "bundle": {
            "bytes": len(combined_bundle),
            "sha256": sha256_bytes(combined_bundle),
        },
        "adapter": None,
        "licenses": [],
    }
    if adapter is not None:
        imported["adapter"] = {
            "bytes": len(adapter),
            "sha256": sha256_bytes(adapter),
            "display_path": args.adapter_display_path,
        }
    license_records: list[dict[str, object]] = []
    license_data: list[tuple[Path, bytes]] = []
    for package_path, output_path in license_outputs:
        if package_path not in payload_paths:
            raise ValueError(
                f"requested license is not a checksummed payload: {package_path}"
            )
        data = package.read_payload(package_path)
        license_data.append((output_path, data))
        license_records.append(
            {
                "package_path": package_path,
                "bytes": len(data),
                "sha256": sha256_bytes(data),
            }
        )
    imported["licenses"] = license_records
    metadata["imported"] = imported
    metadata_bytes = (json.dumps(metadata, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )

    if args.bundle_output is not None:
        check_or_write(args.bundle_output, combined_bundle, check=args.check)
    if args.adapter_output is not None and adapter is not None:
        check_or_write(args.adapter_output, adapter, check=args.check)
    for output_path, data in license_data:
        check_or_write(output_path, data, check=args.check)
    if args.metadata_output is not None:
        check_or_write(args.metadata_output, metadata_bytes, check=args.check)

    print(json.dumps(metadata, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(2) from error
