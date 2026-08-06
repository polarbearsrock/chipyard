# RTA V4 reference artifact

This directory contains a frozen, experimental RTA V4 artifact imported from
a format-1 DORA Design Package. It is a reference snapshot, not yet a stable
DORA–Chipyard ABI.

`RtaV4Bundle.sv` is the only production HDL compilation unit. It contains the
package's exact, self-contained `rtl/bundle.sv` bytes followed by the packed
`rta_v4_chipyard_adapter`. The package bundle currently contains 50 sources
(43 generated RTA V4 sources and seven BaseJump sources). The authored adapter
lives outside the production `vsrc` tree at
`generators/chipyard/src/main/resources/rta_v4/rta_v4_chipyard_adapter.sv`;
`rta_v4_chipyard_adapter.sv.source` is a non-compilable provenance copy. Do not
add another BaseJump provider to a build that compiles the bundle.

The bundle, add-chain image, six `array_systolic` phase images, their FASMs,
and the provenance copy are generated files. The lock records the canonical
DORA manifest hash, its complete payload inventory, the package bundle digest,
configuration format, and the exact ordered state-preserving systolic workload
protocol. `LICENSE.dora` and `LICENSE.basejump_stl` are copied byte-for-byte
from the package. The package bundle is composite-licensed; its `BEGIN SOURCE`
markers map each embedded section back to its package path and license owner.

## Restage the snapshot from the supplied DORA artifact

The RTL consumer requires only the exported `.dora/` package. Before reading
payload bytes, the importer rejects symlinks and special files, checks exact
tree closure and every `SHA256SUMS` entry, links `payload_digest` back to the
exact checksum-file bytes, validates the canonical format-1 manifest, and pins
`sha256(dora-package.json)`. The current pin is
`ac462b1165bc68445abda143582c1d6e5c6bc8b215a08b31d31e3e546a5a5ea1`.
The package contains no `workspace.pkl`, and neither staging nor verification
imports DORA Python.

Package provenance follows the producer's HEAD, so a new DORA commit can
change the manifest identity even when the RTL is byte-identical. The lock
therefore records package bundle and payload digests separately: update the
manifest pin for identity, but compare RTL digests when deciding whether
hardware behavior must be revalidated.

`compiler_arch.json` and the known-good bitstream/FASM workloads remain
Chipyard-side integration inputs because the generic design package is RTL
only. The commands below regenerate those workloads in the producer checkout;
that producer workflow may use DORA compiler state, but the package importer
does not load it.

Generate the known add-chain image from that trusted DORA workspace:

```sh
: "${DORA_ROOT:?set DORA_ROOT to the DORA checkout}"
: "${DORA_PACKAGE:=$DORA_ROOT/examples/devices/ee_526/rta-v4/build/package/rta-v4-array.dora}"
: "${CHIPYARD_ROOT:?set CHIPYARD_ROOT to the Chipyard checkout}"
: "${TMPDIR:?TMPDIR must be set}"
cd "$DORA_ROOT"
PYTHONDONTWRITEBYTECODE=1 scripts/dora-run python \
  examples/devices/ee_526/rta-v4/tests/cgra_add_chain/gen_add_chain_bitstreams.py \
  --out-dir "$TMPDIR/rta_v4_chipyard_add_chain"

PYTHONDONTWRITEBYTECODE=1 scripts/dora-run python \
  examples/devices/ee_526/rta-v4/tests/array_systolic/gen_systolic_bitstreams.py \
  --out-dir "$TMPDIR/rta_v4_chipyard_systolic"
```

Then stage the deterministic Chipyard artifact:

```sh
cd "$CHIPYARD_ROOT"
python3 scripts/prepare-rta-v4-bundle.py \
  --dora-package "$DORA_PACKAGE" \
  --compiler-arch \
    "$DORA_ROOT/examples/devices/ee_526/rta-v4/build/compiler_arch.json" \
  --add-chain-bitstream "$TMPDIR/rta_v4_chipyard_add_chain/compute.bin" \
  --add-chain-fasm "$TMPDIR/rta_v4_chipyard_add_chain/compute.fasm" \
  --systolic-dir "$TMPDIR/rta_v4_chipyard_systolic"
```

Use `--check` with the same arguments to verify that the checked-in generated
files are current without rewriting them.

The reusable `scripts/import-dora-package.py` command implements the generic
package verification/import boundary. `prepare-rta-v4-bundle.py` uses that
same implementation, then adds the RTA-specific compiler, ABI, and workload
checks. Package roots that are symlinks are intentionally rejected; explicitly
pass the real directory when consuming a deliberately symlinked location.

The package also contains two mutually exclusive producer compile sets. The
Chipyard resource path consumes `rtl/bundle.sv`. For split compilation, first
`cd` to the package's `rtl/` directory and invoke `<tool> -f files.f`; VCS
`-F rtl/files.f` does not rebase its `+incdir+` entries.

## Standalone verification

The regression has no runtime dependency on the DORA checkout:

```sh
make -C generators/chipyard/src/test/resources/rta_v4 run
```

It verifies every bundled source section and runs adversarial corruption
checks, compiles only the self-contained bundle and testbench, checks every
packed adapter connection against a synthetic raw top, programs all 3,140
bits, checks the exact scan write-enable/tail timing, and exercises the
add-chain under continuous and stalled enabled-clock execution. It also locks
and verifies every systolic phase image, then adversarially corrupts
representative systolic bitstream and FASM images and the multi-image protocol
metadata. The full state-retention and systolic datapath proof runs through the
Chipyard controller and TileLink shell. It checks DORA's fixed oracle and eight
deterministic pseudo-random `K=1..8` matrices against a reference model running
on the simulated Rocket core:

```sh
make -C generators/chipyard/src/test/resources/rta_v4 soc-systolic-smoke
```

The add-chain's enabled-cycle latency is 13 when expressed as the difference
between launch and observation cycle indices. Manual bring-up from reset must
issue 14 enabled edges because the launch edge itself is included and the
east output pad is registered.
