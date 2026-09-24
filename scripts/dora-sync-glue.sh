#!/usr/bin/env bash
# s2chitni & Claude (AI-generated)
#
# Development helper for DORA's Chipyard glue (Chisel pilot step 5); normal
# builds do not need it.
#
# The glue lives in DORA (dora.chisel/chipyard/, its source of truth) and is
# compiled only here, from generators/dora. While it is being developed, this
# script copies DORA_ROOT's dora.chisel/chipyard/ into the generators/dora
# working tree (leaving the submodule dirty), so it can be built before it is
# committed in DORA and the submodule pin is bumped. With --all it copies every
# source of dora.chisel/ (*.scala and the build files) instead.
#
# It then compares dora_chisel_source_digest of both trees. The jar compiles
# that digest in, and DoraFabric refuses an interchange whose producer digest
# differs, so renders from DORA_ROOT elaborate here only when the two agree.
#
# Usage: scripts/dora-sync-glue.sh [--all] [--check]
#   --all    copy all of dora.chisel/'s sources, not only chipyard/
#   --check  copy nothing; only compare the digests (exit 1 when they differ)
# Environment: DORA_ROOT, a DORA checkout [<chipyard>/../dora]

set -euo pipefail

RDIR="$(git -C "$(dirname "${BASH_SOURCE[0]}")" rev-parse --show-toplevel)"
DORA_ROOT="${DORA_ROOT:-$(cd "${RDIR}/.." && pwd)/dora}"
SUBMODULE="${RDIR}/generators/dora"

ALL=0
CHECK=0
while [[ $# -gt 0 ]]; do
    case "$1" in
        --all) ALL=1 ;;
        --check) CHECK=1 ;;
        -h|--help) sed -n '2,24p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "dora-sync-glue: unknown option $1 (see --help)" >&2; exit 2 ;;
    esac
    shift
done

[[ -d "${DORA_ROOT}/dora.chisel" ]] || { echo "dora-sync-glue: ${DORA_ROOT} has no dora.chisel/ (set DORA_ROOT)" >&2; exit 1; }
[[ -e "${SUBMODULE}/.git" ]] || { echo "dora-sync-glue: generators/dora is not initialized" >&2; exit 1; }

if (( ! CHECK )); then
    if (( ALL )); then
        # Every digest input: *.scala (outside target/ and dot directories) and the build files.
        rsync -a --delete --prune-empty-dirs \
            --exclude 'target/' --exclude '.*' \
            --include '*/' --include '*.scala' --include '/build.sbt' \
            --include '/project/build.properties' --include '/chipyard/README.md' \
            --exclude '*' \
            "${DORA_ROOT}/dora.chisel/" "${SUBMODULE}/dora.chisel/"
    else
        rsync -a --delete --exclude 'target/' --exclude '.*' \
            "${DORA_ROOT}/dora.chisel/chipyard/" "${SUBMODULE}/dora.chisel/chipyard/"
    fi
    echo "dora-sync-glue: copied ${DORA_ROOT}/dora.chisel/$( (( ALL )) || echo chipyard/) into generators/dora"
fi

# dora_chisel_source_digest (the rule in dora.chisel/build.sbt and Chipyard's build.sbt).
digest() {
    python3 - "$1" <<'EOF'
import hashlib, os, sys
root = sys.argv[1]
files = []
for dirpath, dirnames, filenames in os.walk(root):
    for name in filenames:
        rel = os.path.relpath(os.path.join(dirpath, name), root).replace(os.sep, "/")
        parts = rel.split("/")
        if rel in ("build.sbt", "project/build.properties") or (
            rel.endswith(".scala") and not any(p == "target" or p.startswith(".") for p in parts)
        ):
            files.append(rel)
total = hashlib.sha256()
for rel in sorted(files):
    with open(os.path.join(root, rel), "rb") as handle:
        total.update(f"{rel}\0{hashlib.sha256(handle.read()).hexdigest()}\n".encode())
print("sha256:" + total.hexdigest())
EOF
}

dora_digest="$(digest "${DORA_ROOT}/dora.chisel")"
submodule_digest="$(digest "${SUBMODULE}/dora.chisel")"
echo "dora-sync-glue: DORA_ROOT       ${dora_digest}"
echo "dora-sync-glue: generators/dora ${submodule_digest}"
if [[ "${dora_digest}" != "${submodule_digest}" ]]; then
    echo "dora-sync-glue: the dora.chisel sources differ; DoraFabric will refuse DORA_ROOT's renders." >&2
    diff -rq -x target -x '.*' "${DORA_ROOT}/dora.chisel" "${SUBMODULE}/dora.chisel" >&2 || true
    exit 1
fi
echo "dora-sync-glue: equal source digests"
