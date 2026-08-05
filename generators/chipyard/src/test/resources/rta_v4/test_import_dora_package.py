#!/usr/bin/env python3
"""Adversarial regression for the checkout-independent DORA package importer.

The fixtures in this test are deliberately synthetic.  They exercise the
format-1 consumer contract without depending on a DORA checkout or on the
large checked-in RTA V4 artifact.  Every temporary package and output is kept
under ``TMPDIR``.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Iterable


TEST_PATH = Path(__file__).resolve()
CHIPYARD_ROOT = TEST_PATH.parents[6]
IMPORTER = CHIPYARD_ROOT / "scripts" / "import-dora-package.py"
SCRIPTS_DIR = CHIPYARD_ROOT / "scripts"
sys.dont_write_bytecode = True
sys.path.insert(0, str(SCRIPTS_DIR))

import dora_package_import  # noqa: E402  (path setup is intentional)

PACKAGE_NAME = "fixture-design"
PACKAGE_TOP = "fixture_top"
ADAPTER_DISPLAY_PATH = "chipyard/fixture_adapter.sv"
REVISION = "a" * 40
SOURCE_PATH = "rtl/src/generated/top.sv"
DEPENDENCY_SOURCE_PATH = "rtl/src/dependencies/basejump_stl/bsg_stub.sv"
DIVIDER = "// " + "=" * 76


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_json(value: object) -> bytes:
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


def _source_section(path: str, source: str) -> str:
    return (
        f"{DIVIDER}\n"
        f"// BEGIN SOURCE: {path}\n"
        f"{DIVIDER}\n"
        f"{source.rstrip()}\n"
        f"// END SOURCE: {path}\n"
    )


class SyntheticPackage:
    """Small valid format-1 package plus mutation helpers."""

    payload_paths = (
        "README.md",
        "licenses/basejump_stl-LICENSE",
        "licenses/dora-LICENSE",
        "rtl/bundle.sv",
        "rtl/files.f",
        DEPENDENCY_SOURCE_PATH,
        SOURCE_PATH,
    )

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True)

        source = (
            "module fixture_top(\n"
            "    input  logic a_i,\n"
            "    output logic y_o\n"
            ");\n"
            "  assign y_o = a_i;\n"
            "endmodule\n"
        )
        dependency_source = "module bsg_stub; endmodule\n"
        readme = (
            "# fixture-design\n\n"
            "A self-contained DORA design package.\n\n"
            "## Licenses\n\n"
            "Generated sources use `licenses/dora-LICENSE`.\n"
            "Dependency sources under `rtl/src/dependencies/basejump_stl/` use "
            "`licenses/basejump_stl-LICENSE`.\n"
            "`rtl/bundle.sv` is a composite compile unit; every shipped "
            "license applies to its corresponding source section.\n"
        )
        payloads = {
            "README.md": readme.encode("utf-8"),
            "licenses/basejump_stl-LICENSE": b"Synthetic BaseJump license.\n",
            "licenses/dora-LICENSE": b"Synthetic DORA license fixture.\n",
            "rtl/bundle.sv": (
                _source_section(DEPENDENCY_SOURCE_PATH, dependency_source)
                + _source_section(SOURCE_PATH, source)
            ).encode("utf-8"),
            "rtl/files.f": (
                b"src/dependencies/basejump_stl/bsg_stub.sv\n"
                b"src/generated/top.sv\n"
            ),
            DEPENDENCY_SOURCE_PATH: dependency_source.encode("utf-8"),
            SOURCE_PATH: source.encode("utf-8"),
        }
        for rel_path, data in payloads.items():
            path = self.root / rel_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)

        self.manifest: dict[str, object] = {
            "bundle": "rtl/bundle.sv",
            "checksums": "SHA256SUMS",
            "dora_package_format": 1,
            "filelist": "rtl/files.f",
            "name": PACKAGE_NAME,
            "payload_digest": "",
            "provenance": {
                "basejump_stl": {"dirty": False, "revision": "b" * 40},
                "dora": {"dirty": False, "revision": REVISION},
            },
            "top": PACKAGE_TOP,
        }
        self.rewrite_checksums()
        self.refresh_manifest_link()

    @property
    def checksums_path(self) -> Path:
        return self.root / "SHA256SUMS"

    @property
    def manifest_path(self) -> Path:
        return self.root / "dora-package.json"

    @property
    def manifest_sha256(self) -> str:
        return _sha256(self.manifest_path.read_bytes())

    def rewrite_checksums(self, paths: Iterable[str] | None = None) -> None:
        entries = []
        for rel_path in paths if paths is not None else self.payload_paths:
            entries.append((_sha256((self.root / rel_path).read_bytes()), rel_path))
        entries.sort(key=lambda entry: entry[1])
        self.checksums_path.write_bytes(
            "".join(
                f"{digest}  {rel_path}\n" for digest, rel_path in entries
            ).encode("utf-8")
        )

    def write_manifest(self, *, canonical: bool = True) -> None:
        if canonical:
            data = _canonical_json(self.manifest)
        else:
            data = (json.dumps(self.manifest, indent=2, sort_keys=True) + "\n").encode(
                "utf-8"
            )
        self.manifest_path.write_bytes(data)

    def refresh_manifest_link(self, *, canonical: bool = True) -> None:
        self.manifest["payload_digest"] = (
            "sha256:" + _sha256(self.checksums_path.read_bytes())
        )
        self.write_manifest(canonical=canonical)

    def repair_integrity(self) -> str:
        self.rewrite_checksums()
        self.refresh_manifest_link()
        return self.manifest_sha256


class ImportDoraPackageTest(unittest.TestCase):
    maxDiff = None

    def setUp(self) -> None:
        tmpdir = os.environ.get("TMPDIR")
        if not tmpdir:
            self.fail("TMPDIR must be set")
        self._temporary = tempfile.TemporaryDirectory(
            prefix="chipyard-dora-import-test-", dir=tmpdir
        )
        self.work = Path(self._temporary.name)
        self.package = SyntheticPackage(self.work / "fixture.dora")
        self.adapter = self.work / "fixture_adapter.sv"
        self.adapter.write_text(
            "module fixture_adapter(\n"
            "    input logic a_i,\n"
            "    output logic y_o\n"
            ");\n"
            "  fixture_top dut (.a_i(a_i), .y_o(y_o));\n"
            "endmodule\n",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self._temporary.cleanup()

    def _run_import(
        self,
        *,
        package: Path | None = None,
        output: Path | None = None,
        manifest_sha256: str | None = None,
        expected_name: str = PACKAGE_NAME,
        expected_top: str = PACKAGE_TOP,
        bundle_output: Path | None = None,
        adapter_output: Path | None = None,
        metadata_output: Path | None = None,
        header: Path | None = None,
        include_adapter: bool = True,
        check: bool = False,
        timeout: int = 15,
    ) -> subprocess.CompletedProcess[str]:
        package = package if package is not None else self.package.root
        output = output if output is not None else self.work / "output"
        bundle_output = (
            bundle_output
            if bundle_output is not None
            else output / "DoraBundle.sv"
        )
        adapter_output = (
            adapter_output
            if adapter_output is not None
            else output / "adapter.sv.source"
        )
        metadata_output = (
            metadata_output
            if metadata_output is not None
            else output / "dora_package_import.json"
        )
        manifest_sha256 = (
            manifest_sha256
            if manifest_sha256 is not None
            else self.package.manifest_sha256
        )
        command = [
            sys.executable,
            str(IMPORTER),
            str(package),
            "--manifest-sha256",
            manifest_sha256,
            "--name",
            expected_name,
            "--top",
            expected_top,
            "--bundle-output",
            str(bundle_output),
            "--license-output",
            (
                "licenses/basejump_stl-LICENSE="
                + str(output / "licenses" / "basejump_stl-LICENSE")
            ),
            "--license-output",
            (
                "licenses/dora-LICENSE="
                + str(output / "licenses" / "dora-LICENSE")
            ),
            "--metadata-output",
            str(metadata_output),
        ]
        if include_adapter:
            command.extend(
                (
                    "--adapter",
                    str(self.adapter),
                    "--adapter-display-path",
                    ADAPTER_DISPLAY_PATH,
                    "--adapter-output",
                    str(adapter_output),
                )
            )
        if header is not None:
            command.extend(("--header", str(header)))
        if check:
            command.append("--check")
        environment = os.environ.copy()
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        return subprocess.run(
            command,
            cwd=CHIPYARD_ROOT,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
            timeout=timeout,
        )

    def _verify(
        self,
        *,
        package: Path | None = None,
        manifest_sha256: str | None = None,
        expected_name: str = PACKAGE_NAME,
        expected_top: str = PACKAGE_TOP,
    ) -> object:
        package = package if package is not None else self.package.root
        manifest_sha256 = (
            manifest_sha256
            if manifest_sha256 is not None
            else self.package.manifest_sha256
        )
        return dora_package_import.verify_dora_package(
            package,
            expected_manifest_sha256=manifest_sha256,
            expected_name=expected_name,
            expected_top=expected_top,
        )

    def _assert_pass(self, result: subprocess.CompletedProcess[str]) -> None:
        self.assertEqual(
            result.returncode,
            0,
            msg=f"import unexpectedly failed:\n{result.stdout}{result.stderr}",
        )

    def _assert_rejected(self, result: subprocess.CompletedProcess[str]) -> None:
        self.assertNotEqual(
            result.returncode,
            0,
            msg=f"import unexpectedly accepted malformed package:\n{result.stdout}",
        )

    def _assert_verify_rejected(self, **kwargs: object) -> None:
        with self.assertRaises((ValueError, OSError)):
            self._verify(**kwargs)

    @staticmethod
    def _production_bundle(output: Path) -> Path:
        matches = []
        for candidate in output.rglob("*.sv"):
            data = candidate.read_bytes()
            if b"module fixture_top" in data and b"module fixture_adapter" in data:
                matches.append(candidate)
        if len(matches) != 1:
            raise AssertionError(
                f"expected one imported production bundle, got {matches}"
            )
        return matches[0]

    def test_baseline_import_preserves_bundle_and_appends_adapter_last(self) -> None:
        package = self._verify()
        assembled, normalized_adapter = dora_package_import.assemble_chipyard_bundle(
            package,
            self.adapter.read_bytes(),
            adapter_display_path=ADAPTER_DISPLAY_PATH,
        )
        self.assertIn((self.package.root / "rtl/bundle.sv").read_bytes(), assembled)
        self.assertIn(normalized_adapter, assembled)

        output = self.work / "baseline-output"
        result = self._run_import(output=output)
        self._assert_pass(result)
        metadata = json.loads(
            (output / "dora_package_import.json").read_text(encoding="utf-8")
        )
        self.assertEqual(json.loads(result.stdout), metadata)

        bundle = self._production_bundle(output).read_bytes()
        package_bundle = (self.package.root / "rtl/bundle.sv").read_bytes()
        self.assertIn(package_bundle, bundle)
        package_offset = bundle.index(package_bundle)
        adapter_marker = f"// BEGIN SOURCE: {ADAPTER_DISPLAY_PATH}\n".encode()
        self.assertEqual(bundle.count(adapter_marker), 1)
        adapter_offset = bundle.index(adapter_marker)
        self.assertGreater(adapter_offset, package_offset + len(package_bundle) - 1)
        self.assertEqual(bundle.rfind(b"// BEGIN SOURCE: "), adapter_offset)
        self.assertIn(
            f"// END SOURCE: {ADAPTER_DISPLAY_PATH}\n".encode("utf-8"),
            bundle[adapter_offset:],
        )
        self.assertEqual(
            (output / "adapter.sv.source").read_bytes(), normalized_adapter
        )

        for license_name in ("basejump_stl-LICENSE", "dora-LICENSE"):
            staged_licenses = list(output.rglob(license_name))
            self.assertEqual(len(staged_licenses), 1)
            self.assertEqual(
                staged_licenses[0].read_bytes(),
                (self.package.root / "licenses" / license_name).read_bytes(),
            )

    def test_payload_bytes_are_checked_against_sha256sums(self) -> None:
        (self.package.root / "README.md").write_bytes(b"corrupt payload\n")
        self._assert_verify_rejected()

    def test_verified_payload_reads_use_the_bytes_that_were_hashed(self) -> None:
        verified = self._verify()
        package_path = "licenses/dora-LICENSE"
        self.assertEqual(
            _sha256(verified.read_payload(package_path)),
            verified.payload_by_path[package_path].sha256,
        )
        (self.package.root / package_path).write_bytes(b"post-verification change\n")

        with self.assertRaises(dora_package_import.DoraPackageError):
            verified.read_payload(package_path)

    def test_manifest_payload_digest_is_linked_to_exact_sha256sums_bytes(self) -> None:
        (self.package.root / "README.md").write_bytes(b"changed payload\n")
        self.package.rewrite_checksums()
        # The manifest and its expected identity remain the original bytes.
        self._assert_verify_rejected()

    def test_manifest_identity_pin_closes_the_integrity_chain(self) -> None:
        original_identity = self.package.manifest_sha256
        (self.package.root / "README.md").write_bytes(b"changed payload\n")
        self.package.rewrite_checksums()
        self.package.refresh_manifest_link()
        self.assertNotEqual(self.package.manifest_sha256, original_identity)
        self._assert_verify_rejected(manifest_sha256=original_identity)

    def test_stray_and_missing_payloads_are_rejected(self) -> None:
        with self.subTest("stray"):
            (self.package.root / "unlisted.sv").write_text(
                "module unlisted; endmodule\n", encoding="utf-8"
            )
            self._assert_verify_rejected()
            (self.package.root / "unlisted.sv").unlink()

        with self.subTest("missing"):
            readme = self.package.root / "README.md"
            original = readme.read_bytes()
            readme.unlink()
            self._assert_verify_rejected()
            readme.write_bytes(original)

    def test_every_provenance_component_has_a_checksums_pinned_license(self) -> None:
        missing_license = "licenses/basejump_stl-LICENSE"
        (self.package.root / missing_license).unlink()
        self.package.rewrite_checksums(
            path for path in self.package.payload_paths if path != missing_license
        )
        self.package.refresh_manifest_link()
        self._assert_verify_rejected()

    def test_root_and_nested_symlinks_are_rejected_even_when_bytes_match(self) -> None:
        with self.subTest("root"):
            root_link = self.work / "package-link.dora"
            root_link.symlink_to(self.package.root, target_is_directory=True)
            self._assert_verify_rejected(package=root_link)

        with self.subTest("nested-file"):
            source = self.package.root / SOURCE_PATH
            identical = self.work / "identical-top.sv"
            identical.write_bytes(source.read_bytes())
            source.unlink()
            source.symlink_to(identical)
            self._assert_verify_rejected()

    @unittest.skipUnless(hasattr(os, "mkfifo"), "requires POSIX mkfifo")
    def test_special_file_is_rejected_without_being_opened(self) -> None:
        source = self.package.root / SOURCE_PATH
        source.unlink()
        os.mkfifo(source)
        try:
            result = self._run_import(timeout=5)
        except subprocess.TimeoutExpired as error:
            self.fail(f"importer tried to open a FIFO and hung: {error}")
        self._assert_rejected(result)

    def test_malformed_and_noncanonical_sha256sums_are_rejected(self) -> None:
        original = self.package.checksums_path.read_bytes()
        mutations = {
            "one-space-separator": original.replace(b"  ", b" ", 1),
            "uppercase-digest": original[:64].upper() + original[64:],
            "missing-final-lf": original.rstrip(b"\n"),
            "crlf": original.replace(b"\n", b"\r\n"),
            "blank-line": original.replace(b"\n", b"\n\n", 1),
            "duplicate-path": original.splitlines(keepends=True)[0] + original,
            "unsorted": b"".join(reversed(original.splitlines(keepends=True))),
        }
        for name, mutated in mutations.items():
            with self.subTest(name):
                self.package.checksums_path.write_bytes(mutated)
                self.package.refresh_manifest_link()
                self._assert_verify_rejected()
                self.package.checksums_path.write_bytes(original)
                self.package.refresh_manifest_link()

    def test_reserved_and_traversing_checksum_paths_are_rejected(self) -> None:
        original = self.package.checksums_path.read_bytes()
        first_line = original.splitlines(keepends=True)[0]
        digest = first_line[:64]
        mutations = {
            "reserved-manifest": original + digest + b"  dora-package.json\n",
            "reserved-checksums": original + digest + b"  SHA256SUMS\n",
            "parent-traversal": original.replace(b"  README.md\n", b"  ../escape\n"),
            "absolute": original.replace(b"  README.md\n", b"  /escape\n"),
            "backslash": original.replace(b"  README.md\n", b"  rtl\\escape.sv\n"),
            "dot-segment": original.replace(b"  README.md\n", b"  rtl/../escape.sv\n"),
        }
        for name, mutated in mutations.items():
            with self.subTest(name):
                self.package.checksums_path.write_bytes(mutated)
                self.package.refresh_manifest_link()
                self._assert_verify_rejected()
                self.package.checksums_path.write_bytes(original)
                self.package.refresh_manifest_link()

    def test_malformed_noncanonical_and_duplicate_key_manifest_is_rejected(
        self,
    ) -> None:
        canonical = self.package.manifest_path.read_bytes()
        duplicate_top = canonical.replace(
            b'"top":"fixture_top"',
            b'"top":"fixture_top","top":"shadow_top"',
            1,
        )
        pretty = (
            json.dumps(self.package.manifest, indent=2, sort_keys=True) + "\n"
        ).encode("utf-8")
        mutations = {
            "malformed-json": b"{not json}\n",
            "noncanonical-json": pretty,
            "duplicate-key": duplicate_top,
        }
        for name, mutated in mutations.items():
            with self.subTest(name):
                self.package.manifest_path.write_bytes(mutated)
                self._assert_verify_rejected(manifest_sha256=_sha256(mutated))
                self.package.manifest_path.write_bytes(canonical)

    def test_manifest_paths_cannot_escape_the_package(self) -> None:
        for field in ("bundle", "filelist", "checksums"):
            with self.subTest(field):
                original = self.package.manifest[field]
                self.package.manifest[field] = "../outside"
                self.package.write_manifest()
                self._assert_verify_rejected()
                self.package.manifest[field] = original
                self.package.write_manifest()

    def test_filelist_sources_and_include_directories_cannot_escape(self) -> None:
        files_f = self.package.root / "rtl/files.f"
        original = files_f.read_bytes()
        mutations = {
            "source-parent": b"../outside.sv\n",
            "source-absolute": b"/outside.sv\n",
            "incdir-parent": b"+incdir+../outside\n" + original,
            "incdir-absolute": b"+incdir+/outside\n" + original,
        }
        for name, mutated in mutations.items():
            with self.subTest(name):
                files_f.write_bytes(mutated)
                current_identity = self.package.repair_integrity()
                self._assert_verify_rejected(
                    manifest_sha256=current_identity
                )
                files_f.write_bytes(original)
                self.package.repair_integrity()

    def test_format_name_top_and_manifest_identity_are_pinned(self) -> None:
        cases = (
            ("identity", {"manifest_sha256": "0" * 64}),
            ("name", {"expected_name": "different-name"}),
            ("top", {"expected_top": "different_top"}),
        )
        for name, arguments in cases:
            with self.subTest(name):
                self._assert_verify_rejected(**arguments)

        for bad_format in (2, "1", True):
            with self.subTest(format=bad_format):
                self.package.manifest["dora_package_format"] = bad_format
                self.package.write_manifest()
                self._assert_verify_rejected()
        self.package.manifest["dora_package_format"] = 1
        self.package.write_manifest()

    def test_files_f_and_bundle_source_markers_must_describe_same_compile_set(
        self,
    ) -> None:
        files_f = self.package.root / "rtl/files.f"
        files_f.write_bytes(b"")
        current_identity = self.package.repair_integrity()
        self._assert_verify_rejected(manifest_sha256=current_identity)

    def test_bundle_marker_mismatch_is_rejected(self) -> None:
        bundle = self.package.root / "rtl/bundle.sv"
        bundle.write_bytes(
            bundle.read_bytes().replace(
                SOURCE_PATH.encode("utf-8"), b"rtl/src/generated/shadow.sv"
            )
        )
        current_identity = self.package.repair_integrity()
        self._assert_verify_rejected(manifest_sha256=current_identity)

    def test_bundle_with_unresolved_include_is_rejected(self) -> None:
        bundle = self.package.root / "rtl/bundle.sv"
        bundle.write_bytes(
            bundle.read_bytes().replace(
                b"module fixture_top(", b'`include "outside.sv"\nmodule fixture_top('
            )
        )
        current_identity = self.package.repair_integrity()
        self._assert_verify_rejected(manifest_sha256=current_identity)

    def test_string_comment_delimiter_cannot_hide_an_include(self) -> None:
        bundle = self.package.root / "rtl/bundle.sv"
        bundle.write_bytes(
            bundle.read_bytes().replace(
                b"  assign y_o = a_i;",
                b'  string marker = "/*";\n'
                b'  `include "outside.sv"\n'
                b"  assign y_o = a_i;",
                1,
            )
        )
        current_identity = self.package.repair_integrity()
        self._assert_verify_rejected(manifest_sha256=current_identity)

    def test_escaped_identifier_cannot_hide_an_include(self) -> None:
        bundle = self.package.root / "rtl/bundle.sv"
        bundle.write_bytes(
            bundle.read_bytes().replace(
                b"  assign y_o = a_i;",
                b"  wire \\marker/* ;\n"
                b'  `include "outside.sv"\n'
                b"  assign y_o = a_i;",
                1,
            )
        )
        current_identity = self.package.repair_integrity()
        self._assert_verify_rejected(manifest_sha256=current_identity)

    def test_commented_out_top_module_does_not_satisfy_top_check(self) -> None:
        bundle = self.package.root / "rtl/bundle.sv"
        data = bundle.read_bytes().replace(
            b"module fixture_top(", b"/*\nmodule fixture_top(", 1
        )
        end_marker = f"// END SOURCE: {SOURCE_PATH}\n".encode("utf-8")
        data = data.replace(
            b"endmodule\n" + end_marker,
            b"endmodule\n*/\nmodule shadow_top; endmodule\n" + end_marker,
            1,
        )
        bundle.write_bytes(data)
        current_identity = self.package.repair_integrity()
        self._assert_verify_rejected(manifest_sha256=current_identity)

    def test_longer_dollar_identifier_does_not_satisfy_top_check(self) -> None:
        bundle = self.package.root / "rtl/bundle.sv"
        bundle.write_bytes(
            bundle.read_bytes().replace(
                b"module fixture_top(", b"module fixture_top$shadow(", 1
            )
        )
        current_identity = self.package.repair_integrity()
        self._assert_verify_rejected(manifest_sha256=current_identity)

    def test_macro_with_include_prefix_is_not_an_include_directive(self) -> None:
        bundle = self.package.root / "rtl/bundle.sv"
        bundle.write_bytes(
            bundle.read_bytes().replace(
                b"module fixture_top(",
                b"`define included_value 1\nmodule fixture_top(",
                1,
            )
        )
        current_identity = self.package.repair_integrity()
        self._verify(manifest_sha256=current_identity)

    def test_header_only_import_rejects_an_unresolved_include(self) -> None:
        header = self.work / "header.sv"
        header.write_text('`include "outside.sv"\n', encoding="utf-8")
        output = self.work / "header-only-output"

        result = self._run_import(
            output=output,
            header=header,
            include_adapter=False,
        )

        self._assert_rejected(result)
        self.assertFalse((output / "DoraBundle.sv").exists())

    def test_check_mode_detects_drift_without_repairing_it(self) -> None:
        output = self.work / "check-output"
        self._assert_pass(self._run_import(output=output))
        self._assert_pass(self._run_import(output=output, check=True))

        bundle = self._production_bundle(output)
        drifted = bundle.read_bytes() + b"// local drift\n"
        bundle.write_bytes(drifted)
        self._assert_rejected(self._run_import(output=output, check=True))
        self.assertEqual(bundle.read_bytes(), drifted, "--check repaired a stale file")

    def test_cli_rejects_colliding_output_paths_before_writing(self) -> None:
        output = self.work / "colliding-output"
        result = self._run_import(
            output=output,
            metadata_output=output / "DoraBundle.sv",
        )
        self._assert_rejected(result)
        self.assertFalse(
            (output / "DoraBundle.sv").exists(),
            "CLI discovered an output collision only after writing",
        )

    def test_cli_outputs_cannot_alias_inputs_or_the_verified_package(self) -> None:
        adapter_before = self.adapter.read_bytes()
        input_collision_output = self.work / "input-collision-output"
        result = self._run_import(
            output=input_collision_output,
            bundle_output=self.adapter,
        )
        self._assert_rejected(result)
        self.assertEqual(self.adapter.read_bytes(), adapter_before)
        self.assertFalse(
            input_collision_output.exists(),
            "CLI wrote partial outputs before rejecting an input collision",
        )

        readme = self.package.root / "README.md"
        readme_before = readme.read_bytes()
        package_collision_output = self.work / "package-collision-output"
        result = self._run_import(
            output=package_collision_output,
            bundle_output=readme,
        )
        self._assert_rejected(result)
        self.assertEqual(readme.read_bytes(), readme_before)
        self.assertFalse(
            package_collision_output.exists(),
            "CLI wrote partial outputs before rejecting a package-tree collision",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
