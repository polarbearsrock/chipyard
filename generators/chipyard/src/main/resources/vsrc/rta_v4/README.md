# RTA V4 reference artifact

This directory contains a frozen, experimental RTA V4 artifact used to bring
the generated SystemVerilog array into Chipyard. It is a reference snapshot,
not a stable DORA–Chipyard ABI.

`RtaV4Bundle.sv` is the only production HDL compilation unit. It contains the
seven pinned BaseJump sources, all 43 generated RTA V4 sources, and the packed
`rta_v4_chipyard_adapter` in dependency order. The authored adapter lives
outside the production `vsrc` tree at
`generators/chipyard/src/main/resources/rta_v4/rta_v4_chipyard_adapter.sv`;
`rta_v4_chipyard_adapter.sv.source` is a non-compilable provenance copy. Do not
add another BaseJump provider to a build that compiles the bundle.

The bundle, add-chain binary, FASM, and provenance copy are generated files.
Their source paths, hashes, configuration format, and provenance are recorded
in `rta_v4_artifact_lock.json`. `LICENSE.dora` and
`LICENSE.basejump_stl` accompany the vendored source snapshot.

## Restage the snapshot from the supplied DORA artifact

This procedure does not regenerate the DORA architecture from its Git
revision. It requires the exact external RTA V4 `build/` directory, including
`compiler_arch.json`, `workspace.pkl`, `rtl/`, and
`rtl/rta_v4_rmu_sources.f`. The lock records byte hashes for those inputs;
`workspace.pkl` is trusted, path-specific DORA compiler state and is never
loaded by the Chipyard staging or verification scripts.

Generate the known add-chain image from that trusted DORA workspace:

```sh
: "${DORA_ROOT:?set DORA_ROOT to the DORA checkout}"
: "${CHIPYARD_ROOT:?set CHIPYARD_ROOT to the Chipyard checkout}"
: "${TMPDIR:?TMPDIR must be set}"
cd "$DORA_ROOT"
PYTHONDONTWRITEBYTECODE=1 scripts/dora-run python \
  examples/devices/ee_526/rta-v4/tests/cgra_add_chain/gen_add_chain_bitstreams.py \
  --out-dir "$TMPDIR/rta_v4_chipyard_add_chain"
```

Then stage the deterministic Chipyard artifact:

```sh
cd "$CHIPYARD_ROOT"
python3 scripts/prepare-rta-v4-bundle.py \
  --dora-root "$DORA_ROOT" \
  --add-chain-bitstream "$TMPDIR/rta_v4_chipyard_add_chain/compute.bin" \
  --add-chain-fasm "$TMPDIR/rta_v4_chipyard_add_chain/compute.fasm"
```

Use `--check` with the same arguments to verify that the checked-in generated
files are current without rewriting them.

## Standalone verification

The regression has no runtime dependency on the DORA checkout:

```sh
make -C generators/chipyard/src/test/resources/rta_v4 run
```

It verifies every bundled source section and runs adversarial corruption
checks, compiles only the self-contained bundle and testbench, checks every
packed adapter connection against a synthetic raw top, programs all 3,140
bits, checks the exact scan write-enable/tail timing, and exercises the
add-chain under continuous and stalled enabled-clock execution.
