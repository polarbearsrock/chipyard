#!/usr/bin/env python3
"""Dependency-free verifier and importer helpers for DORA design packages.

This module intentionally uses only the Python standard library.  A package
consumer must not need a DORA checkout (or deserialize DORA's workspace) in
order to trust and compile a published design package.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


_MANIFEST = "dora-package.json"
_CHECKSUMS = "SHA256SUMS"
_REQUIRED_MANIFEST_KEYS = frozenset(
    {
        "dora_package_format",
        "name",
        "top",
        "filelist",
        "bundle",
        "checksums",
        "payload_digest",
        "provenance",
    }
)
_OPTIONAL_MANIFEST_KEYS = frozenset({"workspace"})
_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
_SUM_LINE_RE = re.compile(r"^([0-9a-f]{64})  ([^\s].*)$")
_PACKAGE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_PATH_COMPONENT_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9._+-]*$")
_INCLUDE_TOKEN_RE = re.compile(r"`include(?![A-Za-z0-9_$])")
_BEGIN_PREFIX = "// BEGIN SOURCE: "
_END_PREFIX = "// END SOURCE: "
_INCDIR_PREFIX = "+incdir+"
_DIVIDER = "// " + "=" * 76


class DoraPackageError(ValueError):
    """A DORA package or requested import operation is invalid."""


@dataclass(frozen=True)
class PackageFile:
    """One checksummed payload file, in ``SHA256SUMS`` order."""

    path: str
    sha256: str
    size: int


@dataclass(frozen=True)
class VerifiedDoraPackage:
    """All trusted data needed by a consumer after package verification."""

    root: Path
    manifest: dict[str, Any]
    manifest_bytes: bytes
    manifest_sha256: str
    checksums_bytes: bytes
    checksums_sha256: str
    payload_entries: tuple[PackageFile, ...]
    bundle_bytes: bytes
    filelist_bytes: bytes
    source_paths: tuple[str, ...]
    include_dirs: tuple[str, ...]

    @property
    def payload_by_path(self) -> dict[str, PackageFile]:
        return {entry.path: entry for entry in self.payload_entries}

    @property
    def license_paths(self) -> tuple[str, ...]:
        return tuple(
            entry.path
            for entry in self.payload_entries
            if entry.path.startswith("licenses/")
        )

    def read_payload(self, package_rel_path: str) -> bytes:
        """Read a payload and verify the exact bytes before returning them."""

        entry = self.payload_by_path.get(package_rel_path)
        if entry is None:
            raise DoraPackageError(
                f"not a verified package payload: {package_rel_path!r}"
            )
        return _read_payload_matching(self.root, entry)


def _error(message: str) -> DoraPackageError:
    return DoraPackageError(message)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while True:
            block = stream.read(1 << 20)
            if not block:
                break
            digest.update(block)
            size += len(block)
    return digest.hexdigest(), size


def _validate_package_name(value: str, *, label: str) -> None:
    if value in (".", "..") or _PACKAGE_NAME_RE.fullmatch(value) is None:
        raise _error(f"{label} is not a valid package name: {value!r}")


def _validate_rel_path(value: str, *, label: str = "path") -> str:
    if not isinstance(value, str):
        raise _error(f"{label} must be a string")
    violations: list[str] = []
    if value.startswith("/"):
        violations.append("absolute")
    if "\\" in value:
        violations.append("contains a backslash")
    if any(ch.isspace() or ord(ch) < 32 or ord(ch) == 127 for ch in value):
        violations.append("contains whitespace or a control character")
    if violations:
        raise _error(f"{label} {value!r} is invalid: {', '.join(violations)}")
    for component in value.split("/"):
        if component == "":
            raise _error(f"{label} {value!r} has an empty component")
        if component in (".", ".."):
            raise _error(f"{label} {value!r} has a dot component")
        if _PATH_COMPONENT_RE.fullmatch(component) is None:
            raise _error(
                f"{label} {value!r} has invalid component {component!r}"
            )
    return value


def _absolute_without_resolving(path: os.PathLike[str] | str) -> Path:
    # Path.resolve() would silently dereference the package-root symlink that
    # the format requires us to reject before reading a byte through it.
    return Path(os.path.abspath(os.fspath(path)))


def _scan_tree(root: Path) -> tuple[set[str], set[str]]:
    files: set[str] = set()
    directories: set[str] = set()

    def visit(directory: Path, prefix: str) -> None:
        try:
            entries = sorted(os.scandir(directory), key=lambda entry: entry.name)
        except OSError as exc:
            raise _error(f"cannot scan package directory {directory}: {exc}") from exc
        for entry in entries:
            rel_path = f"{prefix}/{entry.name}" if prefix else entry.name
            try:
                mode = entry.stat(follow_symlinks=False).st_mode
            except OSError as exc:
                raise _error(
                    f"cannot inspect package entry {rel_path!r}: {exc}"
                ) from exc
            if stat.S_ISLNK(mode):
                raise _error(f"package entry is a symlink: {rel_path!r}")
            if stat.S_ISDIR(mode):
                directories.add(rel_path)
                visit(Path(entry.path), rel_path)
            elif stat.S_ISREG(mode):
                files.add(rel_path)
            else:
                raise _error(f"package entry is a special file: {rel_path!r}")

    visit(root, "")
    return files, directories


def _read_regular(root: Path, rel_path: str) -> bytes:
    _validate_rel_path(rel_path)
    path = root.joinpath(*rel_path.split("/"))
    try:
        mode = os.lstat(path).st_mode
    except OSError as exc:
        raise _error(f"cannot inspect required file {rel_path!r}: {exc}") from exc
    if stat.S_ISLNK(mode):
        raise _error(f"required file is a symlink: {rel_path!r}")
    if not stat.S_ISREG(mode):
        raise _error(f"required file is not regular: {rel_path!r}")
    try:
        return path.read_bytes()
    except OSError as exc:
        raise _error(f"cannot read required file {rel_path!r}: {exc}") from exc


def _read_payload_matching(root: Path, entry: PackageFile) -> bytes:
    """Read and authenticate the same immutable bytes returned to the caller."""

    data = _read_regular(root, entry.path)
    actual_digest = _sha256_bytes(data)
    if len(data) != entry.size or actual_digest != entry.sha256:
        raise _error(
            f"payload changed after verification for {entry.path!r}: expected "
            f"{entry.sha256} ({entry.size} bytes), got {actual_digest} "
            f"({len(data)} bytes)"
        )
    return data


def _decode_utf8(data: bytes, *, label: str) -> str:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise _error(f"{label} is not UTF-8: {exc}") from exc


def _parse_sha256sums(data: bytes) -> tuple[tuple[str, str], ...]:
    text = _decode_utf8(data, label=_CHECKSUMS)
    if "\r" in text:
        raise _error("SHA256SUMS must use LF-only line endings")
    if text and not text.endswith("\n"):
        raise _error("SHA256SUMS must end with a trailing LF")
    lines = text[:-1].split("\n") if text else []
    entries: list[tuple[str, str]] = []
    seen: set[str] = set()
    for number, line in enumerate(lines, 1):
        match = _SUM_LINE_RE.fullmatch(line)
        if match is None:
            raise _error(
                f"malformed SHA256SUMS line {number}; expected "
                "'<64 lowercase hex>  <relative path>'"
            )
        digest, rel_path = match.groups()
        _validate_rel_path(rel_path, label=f"SHA256SUMS line {number} path")
        if rel_path in seen:
            raise _error(f"duplicate SHA256SUMS path: {rel_path!r}")
        if rel_path in (_CHECKSUMS, _MANIFEST):
            raise _error(f"reserved file must not appear in SHA256SUMS: {rel_path!r}")
        seen.add(rel_path)
        entries.append((digest, rel_path))
    paths = [path for _, path in entries]
    if paths != sorted(paths):
        raise _error("SHA256SUMS entries are not sorted canonically by path")
    canonical = "".join(f"{digest}  {path}\n" for digest, path in entries).encode(
        "utf-8"
    )
    if data != canonical:
        raise _error("SHA256SUMS bytes are not in canonical format")
    return tuple(entries)


def _json_object(pairs: Iterable[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _error(f"duplicate JSON key in dora-package.json: {key!r}")
        result[key] = value
    return result


def _parse_manifest(data: bytes) -> dict[str, Any]:
    text = _decode_utf8(data, label=_MANIFEST)

    def reject_constant(value: str) -> None:
        raise _error(f"non-finite JSON value in dora-package.json: {value}")

    try:
        parsed = json.loads(
            text,
            object_pairs_hook=_json_object,
            parse_constant=reject_constant,
        )
    except DoraPackageError:
        raise
    except json.JSONDecodeError as exc:
        raise _error(f"invalid dora-package.json: {exc}") from exc
    if not isinstance(parsed, dict):
        raise _error("dora-package.json must contain a JSON object")
    try:
        canonical = (
            json.dumps(
                parsed,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            ).encode("utf-8")
            + b"\n"
        )
    except (TypeError, ValueError) as exc:
        raise _error(
            f"dora-package.json cannot be represented canonically: {exc}"
        ) from exc
    if data != canonical:
        raise _error("dora-package.json bytes are not canonical JSON")
    return parsed


def _validate_manifest_schema(
    manifest: dict[str, Any],
    payload_paths: frozenset[str],
    *,
    allow_workspace: bool,
) -> None:
    keys = frozenset(manifest)
    missing = sorted(_REQUIRED_MANIFEST_KEYS - keys)
    unknown = sorted(keys - _REQUIRED_MANIFEST_KEYS - _OPTIONAL_MANIFEST_KEYS)
    if missing or unknown:
        parts: list[str] = []
        if missing:
            parts.append("missing keys: " + ", ".join(missing))
        if unknown:
            parts.append("unknown keys: " + ", ".join(unknown))
        raise _error("invalid format-1 manifest schema (" + "; ".join(parts) + ")")
    if type(manifest["dora_package_format"]) is not int or manifest[
        "dora_package_format"
    ] != 1:
        raise _error("dora_package_format must be integer 1")
    name = manifest["name"]
    if not isinstance(name, str):
        raise _error("manifest name must be a string")
    _validate_package_name(name, label="manifest name")
    top = manifest["top"]
    if not isinstance(top, str) or not top:
        raise _error("manifest top must be a non-empty string")

    fixed_paths = {
        "filelist": "rtl/files.f",
        "bundle": "rtl/bundle.sv",
        "checksums": _CHECKSUMS,
    }
    for key, required in fixed_paths.items():
        value = manifest[key]
        if not isinstance(value, str):
            raise _error(f"manifest {key} must be a string")
        _validate_rel_path(value, label=f"manifest {key}")
        if value != required:
            raise _error(
                f"format-1 manifest {key} must be {required!r}, got {value!r}"
            )
    for key in ("filelist", "bundle"):
        if manifest[key] not in payload_paths:
            raise _error(f"manifest {key} is not a checksummed payload")

    payload_digest = manifest["payload_digest"]
    if not isinstance(payload_digest, str) or re.fullmatch(
        r"sha256:[0-9a-f]{64}", payload_digest
    ) is None:
        raise _error("manifest payload_digest must be 'sha256:<64 lowercase hex>'")

    provenance = manifest["provenance"]
    if not isinstance(provenance, dict) or not provenance:
        raise _error("manifest provenance must be a non-empty object")
    if "dora" not in provenance:
        raise _error("manifest provenance must contain the dora component")
    expected_license_paths: set[str] = set()
    for component, record in provenance.items():
        _validate_package_name(component, label="provenance component")
        if not isinstance(record, dict) or set(record) != {"revision", "dirty"}:
            raise _error(
                f"provenance entry {component!r} must contain revision and dirty"
            )
        if not isinstance(record["revision"], str) or not record["revision"]:
            raise _error(f"provenance revision for {component!r} must be a string")
        if type(record["dirty"]) is not bool:
            raise _error(f"provenance dirty for {component!r} must be Boolean")
        license_path = f"licenses/{component}-LICENSE"
        expected_license_paths.add(license_path)
        if license_path not in payload_paths:
            raise _error(
                f"manifest component {component!r} has no {license_path!r} payload"
            )
    actual_license_paths = {
        path for path in payload_paths if path.startswith("licenses/")
    }
    if actual_license_paths != expected_license_paths:
        unexpected = sorted(actual_license_paths - expected_license_paths)
        raise _error(
            "package license closure contains paths without provenance: "
            + ", ".join(unexpected)
        )

    workspace_in_manifest = "workspace" in manifest
    workspace_in_payload = "workspace.pkl" in payload_paths
    if workspace_in_manifest:
        value = manifest["workspace"]
        if not isinstance(value, str):
            raise _error("manifest workspace must be a string")
        _validate_rel_path(value, label="manifest workspace")
        if value != "workspace.pkl":
            raise _error("format-1 manifest workspace must be 'workspace.pkl'")
        if not allow_workspace:
            raise _error("workspace.pkl is forbidden by this importer invocation")
    if workspace_in_manifest != workspace_in_payload:
        raise _error("workspace.pkl payload and manifest workspace key disagree")


def _parse_filelist(
    data: bytes,
    *,
    payload_paths: frozenset[str],
    directories: frozenset[str],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    text = _decode_utf8(data, label="rtl/files.f")
    if "\r" in text:
        raise _error("rtl/files.f must use LF-only line endings")
    if text and not text.endswith("\n"):
        raise _error("rtl/files.f must end with a trailing LF")
    lines = text[:-1].split("\n") if text else []
    include_dirs: list[str] = []
    sources: list[str] = []
    seen_dirs: set[str] = set()
    seen_sources: set[str] = set()
    reached_sources = False
    for number, line in enumerate(lines, 1):
        if not line:
            raise _error(f"rtl/files.f line {number} is blank")
        if line.startswith(_INCDIR_PREFIX):
            if reached_sources:
                raise _error("rtl/files.f +incdir+ entries must precede sources")
            relative = line[len(_INCDIR_PREFIX) :]
            if not relative:
                raise _error(f"rtl/files.f line {number} has an empty +incdir+")
            package_path = "rtl/" + relative
            _validate_rel_path(package_path, label=f"rtl/files.f line {number}")
            if package_path in seen_dirs:
                raise _error(
                    "duplicate rtl/files.f include directory: "
                    f"{package_path!r}"
                )
            if package_path not in directories:
                raise _error(
                    f"rtl/files.f include directory is missing: {package_path!r}"
                )
            seen_dirs.add(package_path)
            include_dirs.append(relative)
            continue
        reached_sources = True
        package_path = "rtl/" + line
        _validate_rel_path(package_path, label=f"rtl/files.f line {number}")
        if package_path in seen_sources:
            raise _error(f"duplicate rtl/files.f source: {package_path!r}")
        if package_path not in payload_paths:
            raise _error(f"rtl/files.f source is not a payload: {package_path!r}")
        seen_sources.add(package_path)
        sources.append(package_path)
    if not sources:
        raise _error("rtl/files.f contains no compile sources")
    canonical_lines = [
        *(_INCDIR_PREFIX + path for path in include_dirs),
        *(path[len("rtl/") :] for path in sources),
    ]
    canonical = ("\n".join(canonical_lines) + "\n").encode("utf-8")
    if data != canonical:
        raise _error("rtl/files.f bytes are not canonical")
    return tuple(include_dirs), tuple(sources)


def _mask_comments_and_strings(text: str) -> str:
    """Mask SystemVerilog comments and strings while preserving positions."""

    chars = list(text)
    index = 0
    state = "code"
    while index < len(text):
        pair = text[index : index + 2]
        character = text[index]

        if state == "code":
            if pair == "//":
                chars[index : index + 2] = "  "
                index += 2
                state = "line-comment"
            elif pair == "/*":
                chars[index : index + 2] = "  "
                index += 2
                state = "block-comment"
            elif character == '"':
                chars[index] = " "
                index += 1
                state = "string"
            elif character == "\\":
                chars[index] = " "
                index += 1
                state = "escaped-identifier"
            else:
                index += 1
            continue

        if state == "escaped-identifier":
            if character.isspace():
                state = "code"
            else:
                chars[index] = " "
            index += 1
            continue

        if state == "line-comment":
            if character in "\r\n":
                state = "code"
            else:
                chars[index] = " "
            index += 1
            continue

        if state == "block-comment":
            if pair == "*/":
                chars[index : index + 2] = "  "
                index += 2
                state = "code"
            else:
                if character not in "\r\n":
                    chars[index] = " "
                index += 1
            continue

        if character == "\\":
            chars[index] = " "
            index += 1
            if index < len(text):
                if text[index] not in "\r\n":
                    chars[index] = " "
                index += 1
        elif character == '"':
            chars[index] = " "
            index += 1
            state = "code"
        elif character in "\r\n":
            # An unescaped newline terminates an invalid string. Resetting here
            # keeps later real directives visible to this conservative scan.
            index += 1
            state = "code"
        else:
            chars[index] = " "
            index += 1

    return "".join(chars)


def _verify_bundle(
    data: bytes, source_paths: tuple[str, ...], top_module: str
) -> None:
    text = _decode_utf8(data, label="rtl/bundle.sv")
    if "\r" in text:
        raise _error("rtl/bundle.sv must use LF-only line endings")
    if text and not text.endswith("\n"):
        raise _error("rtl/bundle.sv must end with a trailing LF")
    cursor = 0
    for source_path in source_paths:
        begin = (
            f"{_DIVIDER}\n"
            f"{_BEGIN_PREFIX}{source_path}\n"
            f"{_DIVIDER}\n"
        )
        if not text.startswith(begin, cursor):
            raise _error(
                "rtl/bundle.sv source framing/order differs from rtl/files.f "
                f"at {source_path!r}"
            )
        body_start = cursor + len(begin)
        end = f"{_END_PREFIX}{source_path}\n"
        body_end = text.find(end, body_start)
        if body_end < body_start:
            raise _error(f"bundle source section is not closed: {source_path!r}")
        if body_end > body_start and text[body_end - 1] != "\n":
            raise _error(
                f"bundle source body is not LF-terminated: {source_path!r}"
            )
        cursor = body_end + len(end)
    if cursor != len(text):
        raise _error("rtl/bundle.sv contains unrecorded or trailing content")

    masked_text = _mask_comments_and_strings(text)
    for number, masked in enumerate(masked_text.splitlines(), 1):
        if _INCLUDE_TOKEN_RE.search(masked) is not None:
            raise _error(
                f"rtl/bundle.sv contains an unresolved `include on line {number}"
            )
    top_pattern = re.compile(
        rf"^\s*module\s+{re.escape(top_module)}(?![A-Za-z0-9_$])",
        re.MULTILINE,
    )
    if len(top_pattern.findall(masked_text)) != 1:
        raise _error(
            f"rtl/bundle.sv must define top module {top_module!r} exactly once"
        )


def _normalize_pin(value: str | None, *, label: str) -> str | None:
    if value is None:
        return None
    if _HEX64_RE.fullmatch(value) is None:
        raise _error(f"{label} must be 64 lowercase hexadecimal characters")
    return value


def verify_dora_package(
    path: os.PathLike[str] | str,
    expected_manifest_sha256: str | None = None,
    expected_name: str | None = None,
    expected_top: str | None = None,
    allow_workspace: bool = True,
) -> VerifiedDoraPackage:
    """Verify a complete format-1 package and return its trusted contents."""

    root = _absolute_without_resolving(path)
    try:
        root_mode = os.lstat(root).st_mode
    except OSError as exc:
        raise _error(f"cannot inspect package root {root}: {exc}") from exc
    if stat.S_ISLNK(root_mode):
        raise _error(
            f"package root is a symlink: {root}; pass the real directory explicitly"
        )
    if not stat.S_ISDIR(root_mode):
        raise _error(f"package root is not a directory: {root}")

    actual_files, directories = _scan_tree(root)
    for required in (_CHECKSUMS, _MANIFEST):
        if required not in actual_files:
            raise _error(f"package is missing required regular file {required!r}")

    checksums_bytes = _read_regular(root, _CHECKSUMS)
    checksum_pairs = _parse_sha256sums(checksums_bytes)
    expected_files = {path for _, path in checksum_pairs} | {_CHECKSUMS, _MANIFEST}
    missing = sorted(expected_files - actual_files)
    stray = sorted(actual_files - expected_files)
    if missing or stray:
        details: list[str] = []
        if missing:
            details.append("missing: " + ", ".join(missing))
        if stray:
            details.append("stray: " + ", ".join(stray))
        raise _error("package file closure mismatch (" + "; ".join(details) + ")")

    payload_entries: list[PackageFile] = []
    for expected_digest, rel_path in checksum_pairs:
        absolute = root.joinpath(*rel_path.split("/"))
        try:
            mode = os.lstat(absolute).st_mode
        except OSError as exc:
            raise _error(f"cannot inspect payload {rel_path!r}: {exc}") from exc
        if not stat.S_ISREG(mode) or stat.S_ISLNK(mode):
            raise _error(f"payload is not a regular file: {rel_path!r}")
        actual_digest, size = _sha256_file(absolute)
        if actual_digest != expected_digest:
            raise _error(
                f"payload SHA-256 mismatch for {rel_path!r}: expected "
                f"{expected_digest}, got {actual_digest}"
            )
        payload_entries.append(PackageFile(rel_path, actual_digest, size))

    manifest_bytes = _read_regular(root, _MANIFEST)
    manifest = _parse_manifest(manifest_bytes)
    manifest_sha256 = _sha256_bytes(manifest_bytes)
    pin = _normalize_pin(expected_manifest_sha256, label="manifest SHA-256 pin")
    if pin is not None and manifest_sha256 != pin:
        raise _error(
            f"manifest SHA-256 pin mismatch: expected {pin}, got {manifest_sha256}"
        )
    payload_paths = frozenset(entry.path for entry in payload_entries)
    _validate_manifest_schema(
        manifest, payload_paths, allow_workspace=allow_workspace
    )
    checksums_sha256 = _sha256_bytes(checksums_bytes)
    linked_digest = "sha256:" + checksums_sha256
    if manifest["payload_digest"] != linked_digest:
        raise _error(
            "manifest payload_digest does not match the exact SHA256SUMS bytes: "
            f"expected {linked_digest}, got {manifest['payload_digest']}"
        )
    if expected_name is not None and manifest["name"] != expected_name:
        raise _error(
            f"package name mismatch: expected {expected_name!r}, "
            f"got {manifest['name']!r}"
        )
    if expected_top is not None and manifest["top"] != expected_top:
        raise _error(
            f"package top mismatch: expected {expected_top!r}, "
            f"got {manifest['top']!r}"
        )

    payload_by_path = {entry.path: entry for entry in payload_entries}
    filelist_bytes = _read_payload_matching(
        root, payload_by_path[manifest["filelist"]]
    )
    include_dirs, source_paths = _parse_filelist(
        filelist_bytes,
        payload_paths=payload_paths,
        directories=frozenset(directories),
    )
    bundle_bytes = _read_payload_matching(
        root, payload_by_path[manifest["bundle"]]
    )
    _verify_bundle(bundle_bytes, source_paths, manifest["top"])
    return VerifiedDoraPackage(
        root=root,
        manifest=manifest,
        manifest_bytes=manifest_bytes,
        manifest_sha256=manifest_sha256,
        checksums_bytes=checksums_bytes,
        checksums_sha256=checksums_sha256,
        payload_entries=tuple(payload_entries),
        bundle_bytes=bundle_bytes,
        filelist_bytes=filelist_bytes,
        source_paths=source_paths,
        include_dirs=include_dirs,
    )


def load_dora_package(
    path: os.PathLike[str] | str,
    **kwargs: Any,
) -> VerifiedDoraPackage:
    """Compatibility spelling for consumers that describe verification as load."""

    return verify_dora_package(path, **kwargs)


def normalize_source_bytes(data: bytes) -> bytes:
    """Return deterministic LF text suitable for a generated source section."""

    text = _decode_utf8(data, label="source")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = "\n".join(line.rstrip(" \t") for line in text.split("\n"))
    text = text.rstrip()
    return (text + "\n").encode("utf-8") if text else b""


def source_section_text(display_path: str, text: str) -> str:
    """Wrap normalized source text in auditable BEGIN/END markers."""

    _validate_rel_path(display_path, label="source display path")
    normalized = normalize_source_bytes(text.encode("utf-8")).decode("utf-8")
    return (
        f"{_DIVIDER}\n"
        f"{_BEGIN_PREFIX}{display_path}\n"
        f"{_DIVIDER}\n"
        f"{normalized}"
        f"{_END_PREFIX}{display_path}\n"
    )


def source_section_bytes(display_path: str, data: bytes) -> bytes:
    """Byte-oriented variant of :func:`source_section_text`."""

    normalized = normalize_source_bytes(data)
    return source_section_text(display_path, normalized.decode("utf-8")).encode(
        "utf-8"
    )


def _reject_unresolved_includes(data: bytes, *, label: str) -> None:
    text = _decode_utf8(data, label=label)
    for number, masked in enumerate(
        _mask_comments_and_strings(text).splitlines(), 1
    ):
        if _INCLUDE_TOKEN_RE.search(masked) is not None:
            raise _error(f"{label} contains an unresolved `include on line {number}")


def validate_header_bytes(data: bytes) -> bytes:
    """Validate bytes that will be prepended to a self-contained bundle."""

    if not isinstance(data, bytes):
        raise TypeError("header bytes must be bytes")
    if data:
        _reject_unresolved_includes(data, label="bundle header")
    return data


def assemble_chipyard_bundle(
    package: VerifiedDoraPackage,
    adapter_bytes: bytes,
    header_bytes: bytes = b"",
    adapter_display_path: str = "chipyard/adapter.sv",
) -> tuple[bytes, bytes]:
    """Prepend a Chipyard header and append its adapter to a verified bundle.

    The package's own bundle bytes are never normalized or rewritten.  The
    returned second value is the normalized adapter used in the first value.
    """

    normalized_adapter = normalize_source_bytes(adapter_bytes)
    if not normalized_adapter:
        raise _error("adapter source is empty")
    _reject_unresolved_includes(normalized_adapter, label="adapter source")
    adapter_section = source_section_bytes(
        adapter_display_path, normalized_adapter
    )
    validate_header_bytes(header_bytes)
    if package.bundle_bytes and not package.bundle_bytes.endswith(b"\n"):
        raise _error("verified package bundle unexpectedly lacks a trailing LF")
    return (
        header_bytes + package.bundle_bytes + adapter_section,
        normalized_adapter,
    )


def package_metadata(package: VerifiedDoraPackage) -> dict[str, Any]:
    """Stable, host-path-independent metadata for locks and CLI output."""

    return {
        "schema": "chipyard.dora_package_import",
        "schema_version": 1,
        "manifest": package.manifest,
        "manifest_bytes": len(package.manifest_bytes),
        "manifest_sha256": package.manifest_sha256,
        "checksums_bytes": len(package.checksums_bytes),
        "checksums_sha256": package.checksums_sha256,
        "payload_file_count": len(package.payload_entries),
        "payload": [
            {"bytes": item.size, "path": item.path, "sha256": item.sha256}
            for item in package.payload_entries
        ],
        "compile_set": {
            "bundle": package.manifest["bundle"],
            "filelist": package.manifest["filelist"],
            "source_count": len(package.source_paths),
            "include_dirs": list(package.include_dirs),
        },
    }


def sha256_bytes(data: bytes) -> str:
    """Public spelling used by importer clients when recording outputs."""

    return _sha256_bytes(data)


def check_or_write(path: Path, data: bytes, *, check: bool) -> None:
    """Write one imported output, or compare it without mutation."""

    output = _absolute_without_resolving(path)
    if check:
        try:
            mode = os.lstat(output).st_mode
        except OSError as exc:
            raise _error(
                f"cannot inspect checked import output {output}: {exc}"
            ) from exc
        if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
            raise _error(f"checked import output is not a regular file: {output}")
        if output.read_bytes() != data:
            raise _error(f"checked import output is stale: {output}")
        return
    if output.is_symlink():
        raise _error(f"refusing to replace symlinked import output: {output}")
    if output.is_file() and output.read_bytes() == data:
        return
    if output.exists() and not output.is_file():
        raise _error(f"import output is not a regular file: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(data)


def parse_license_outputs(values: Iterable[str]) -> tuple[tuple[str, Path], ...]:
    """Parse repeatable ``PACKAGE_REL=OUTPUT`` license mappings."""

    mappings: list[tuple[str, Path]] = []
    package_paths: set[str] = set()
    output_paths: set[Path] = set()
    for value in values:
        if "=" not in value:
            raise _error(
                "--license-output must be PACKAGE_RELATIVE_PATH=OUTPUT_PATH"
            )
        package_path, output_text = value.split("=", 1)
        _validate_rel_path(package_path, label="license path")
        if not package_path.startswith("licenses/"):
            raise _error(
                f"--license-output source is not under licenses/: {package_path}"
            )
        if not output_text:
            raise _error("--license-output destination must not be empty")
        output_path = _absolute_without_resolving(output_text)
        if package_path in package_paths:
            raise _error(f"duplicate package license mapping: {package_path}")
        if output_path in output_paths:
            raise _error(f"duplicate license output path: {output_path}")
        package_paths.add(package_path)
        output_paths.add(output_path)
        mappings.append((package_path, output_path))
    return tuple(mappings)


__all__ = [
    "DoraPackageError",
    "PackageFile",
    "VerifiedDoraPackage",
    "assemble_chipyard_bundle",
    "load_dora_package",
    "normalize_source_bytes",
    "package_metadata",
    "check_or_write",
    "parse_license_outputs",
    "sha256_bytes",
    "source_section_bytes",
    "source_section_text",
    "validate_header_bytes",
    "verify_dora_package",
]
