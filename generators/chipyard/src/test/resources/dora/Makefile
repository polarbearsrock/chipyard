# s2chitni & Claude (AI-generated)
#
# DORA's Chipyard driver (DORA Chisel pilot step 5, plan item 8): render a
# static HyCUBE fabric with a DORA checkout, run the bare-metal K3 kernel
# (tests/dora-static-hycube.c) on it in DoraStaticHyCubeRocketConfig under
# Verilator, and check the SoC's fabric RTL against DORA's interchange.
#
#   make -C generators/chipyard/src/test/resources/dora soc-smoke-all
#
# Targets:
#   gen            render the fabric, its C header and K3 with DORA_ROOT into
#                  DORA_OUT (static_hycube build --soc). Refuses unless DORA_ROOT
#                  is at the pinned commit with a clean tree (gen-check): the
#                  commit Chipyard's HEAD records for generators/dora (the
#                  gitlink), which generators/dora must have checked out
#   gen-check      only gen's DORA_ROOT check
#   verify         check DORA_OUT/soc.json against its files and the pin
#   test-software  run the K3 program on the host against mock-shell.c, a model
#                  of the shell ABI: PASS when faithful, FAIL under every fault
#   shell-unit-test  the shell's chiseltest unit tests (DoraShellSpec, in
#                  generators/dora/dora.chisel/chipyard/src/test/scala) on the
#                  synthetic fixture and on DORA_OUT's fabric, through Chipyard's
#                  sbt (sims/verilator launch-sbt); every case must pass, none
#                  may be canceled
#   soc-sw         build tests/dora-static-hycube.c against DORA_OUT's header
#   soc-smoke      soc-sw, then run it in the SoC (Verilator, LOADMEM=1); the
#                  program must print "DORA K3 mem_axpy: PASS"
#   check          after soc-smoke: DORA's checker on the SoC's gen-collateral
#                  (--prefix from soc.json, the Verilator file list) and on the
#                  shell's generated register map (regmap.json against the
#                  interchange's shell_abi), and the shell-to-fabric wiring in
#                  the SoC's CHIRRTL against the interchange's roles
#   soc-smoke-all  gen, test-software, shell-unit-test, soc-smoke, check
#   test           this driver's own tests (refusal paths, manifest, stamp,
#                  wiring)
#
# Variables (defaults in brackets):
#   DORA_ROOT            a full DORA checkout outside Chipyard, with recursive
#                        submodules and scripts/install -d [$(CHIPYARD_ROOT)/../dora]
#   DORA_OUT             the render, absolute and below $TMPDIR, outside
#                        generators/ [$(TMPDIR)/dora-soc/hycube_array-4x4-c4]
#   DORA_ROWS, DORA_COLUMNS, DORA_CONTEXTS  the fabric [4, 4, 4]; K3 needs at
#                        least 4x3 PEs
#   DORA_GEN_ALLOW_DEV=1 DEVELOPMENT ONLY: gen and verify warn loudly instead of
#                        refusing a DORA_ROOT (or a DORA_OUT producer) that is not
#                        the pinned commit or has uncommitted changes, or a
#                        generators/dora whose checkout is not Chipyard's pin
#   SOC_CONFIG           [DoraStaticHyCubeRocketConfig]
#   SOC_TIMEOUT_CYCLES   [20000000]
#   SOC_TEST_BUILD_DIR   the CMake build of tests/
#                        [$(TMPDIR)/dora-soc-build/<checkout key>]
#   DORA_STAMP           the fabric's content stamp
#                        [$(TMPDIR)/dora-soc-stamps/<checkout key>/$(SOC_CONFIG).stamp]
#   SHELL_TEST_DIR       chiseltest's output and the unit test's log
#                        [$(TMPDIR)/dora-shell-test/<checkout key>]
#   SHELL_TESTS          [dora.chisel.soc.DoraShellSpec]
#   JAVA_TOOL_OPTIONS    sbt's JVM options: the environment's, else Chipyard's
#                        default (variables.mk; shell-unit-test runs Chipyard's
#                        launch-sbt)
#   and those of ../offline-sbt.mk (DORA_COURSIER_CACHE, CHIPYARD_SBT_HOME,
#   DORA_SBT_ONLINE): soc-smoke and shell-unit-test may re-assemble or
#   recompile chipyard.
#   <checkout key> is the first 12 hex digits of sha256(CHIPYARD_ROOT), so two
#   Chipyard checkouts under one TMPDIR never share a build directory.
#
# Chipyard elaborates the fabric from DORA_FABRIC = DORA_OUT/hdl/<top>.dnl.json
# (exported, absolute) with the dora.chisel classes built from generators/dora;
# DoraFabric refuses an interchange whose producer source digest is not the
# jar's. make compares times only, and the SoC's build directory depends only on
# CONFIG, so EXTRA_GENERATOR_REQS lists the interchange, its cut cells and a
# stamp that is rewritten only when the fabric's path or content changes.

MAKEFILE_PATH := $(abspath $(lastword $(MAKEFILE_LIST)))
MAKEFILE_DIR := $(patsubst %/,%,$(dir $(MAKEFILE_PATH)))
CHIPYARD_ROOT := $(abspath $(MAKEFILE_DIR)/../../../../../..)

ifndef TMPDIR
$(error TMPDIR must be set)
endif

SHELL := /bin/bash

# One set of build directories per Chipyard checkout.
CHIPYARD_KEY := $(shell printf '%s' '$(CHIPYARD_ROOT)' | sha256sum | cut -c1-12)

# sbt offline, from DORA_COURSIER_CACHE, with nothing under $HOME: soc-smoke
# re-assembles chipyard.jar whenever its sources changed.
include $(MAKEFILE_DIR)/../offline-sbt.mk

PYTHON ?= python3
CMAKE ?= cmake
HOST_CC ?= cc

DORA_ROOT ?= $(abspath $(CHIPYARD_ROOT)/../dora)
override DORA_SUBMODULE := $(CHIPYARD_ROOT)/generators/dora
DORA_ROWS ?= 4
DORA_COLUMNS ?= 4
DORA_CONTEXTS ?= 4
# static HyCUBE's top module, and the header tests/dora-static-hycube.c includes
DORA_TOP := hycube_array
DORA_OUT ?= $(TMPDIR)/dora-soc/$(DORA_TOP)-$(DORA_ROWS)x$(DORA_COLUMNS)-c$(DORA_CONTEXTS)
DORA_GEN_ALLOW_DEV ?=

ifeq ($(filter /%,$(DORA_OUT)),)
$(error DORA_OUT=$(DORA_OUT) must be an absolute path (below $$TMPDIR, outside generators/))
endif
ifeq ($(filter /%,$(DORA_ROOT)),)
$(error DORA_ROOT=$(DORA_ROOT) must be an absolute path)
endif
override DORA_OUT := $(abspath $(DORA_OUT))
override DORA_ROOT := $(abspath $(DORA_ROOT))

# What the generator JVM elaborates (always DORA_OUT's, always absolute).
override DORA_FABRIC := $(DORA_OUT)/hdl/$(DORA_TOP).dnl.json
export DORA_FABRIC
DORA_GEN_DIR := $(DORA_OUT)/sw
# Evaluated when used, after gen has written DORA_OUT.
DORA_CELLS = $(sort $(wildcard $(DORA_OUT)/hdl/cells/*.sv))

SOC_CONFIG ?= DoraStaticHyCubeRocketConfig
SOC_TIMEOUT_CYCLES ?= 20000000
SOC_BUILD_JOBS ?= 4
SOC_TEST_SOURCE_DIR := $(CHIPYARD_ROOT)/tests
SOC_TEST_BUILD_DIR ?= $(TMPDIR)/dora-soc-build/$(CHIPYARD_KEY)
SOC_TEST_BINARY := $(SOC_TEST_BUILD_DIR)/dora-static-hycube.riscv
SIM_DIR := $(CHIPYARD_ROOT)/sims/verilator
SOC_LONG_NAME := chipyard.harness.TestHarness.$(SOC_CONFIG)
SOC_BUILD_DIR := $(SIM_DIR)/generated-src/$(SOC_LONG_NAME)
SOC_FIRRTL := $(SOC_BUILD_DIR)/$(SOC_LONG_NAME).fir
SOC_LOG := $(SIM_DIR)/output/$(SOC_LONG_NAME)/dora-static-hycube.log

# One stamp per Chipyard checkout and config: it guards that checkout's build.
DORA_STAMP ?= $(TMPDIR)/dora-soc-stamps/$(CHIPYARD_KEY)/$(SOC_CONFIG).stamp
MOCK_BUILD_DIR ?= $(TMPDIR)/dora-soc-mock/$(CHIPYARD_KEY)

SOC_TOOL := $(PYTHON) $(MAKEFILE_DIR)/dora_soc.py
DEV_FLAG := $(if $(filter 1,$(DORA_GEN_ALLOW_DEV)),--allow-dev,)
PIN_FLAGS := --submodule $(DORA_SUBMODULE) --chipyard-root $(CHIPYARD_ROOT) $(DEV_FLAG)

.PHONY: help gen gen-check verify test-software soc-sw skew-check soc-smoke \
	check soc-smoke-all shell-unit-test test

help:
	@awk 'NR > 2 && /^#/ { sub(/^# ?/, ""); print; next } NR > 2 { exit }' $(MAKEFILE_PATH)

gen-check:
	$(SOC_TOOL) check-root --dora-root $(DORA_ROOT) $(PIN_FLAGS)

# DORA's Python runs only from DORA_ROOT (generators/dora has no nested
# submodules); build.py refuses a DORA_OUT outside $TMPDIR or in generators/.
# The old manifest goes first, so a failed render leaves no DORA_OUT that
# verify (and so soc-smoke) would accept.
gen: gen-check
	rm -f "$(DORA_OUT)/soc.json"
	cd $(DORA_ROOT) && scripts/dora-run --cwd . \
	  python -m examples.architectures.static_hycube.build \
	  --rows $(DORA_ROWS) --columns $(DORA_COLUMNS) --contexts $(DORA_CONTEXTS) \
	  --backend chisel --soc --out "$(DORA_OUT)"
	$(SOC_TOOL) verify --out $(DORA_OUT) --top $(DORA_TOP) $(PIN_FLAGS)

verify:
	$(SOC_TOOL) verify --out $(DORA_OUT) --top $(DORA_TOP) $(PIN_FLAGS)

test-software: verify
	$(SOC_TOOL) mock-test --out $(DORA_OUT) --tests $(SOC_TEST_SOURCE_DIR) \
	  --mock $(MAKEFILE_DIR)/mock-shell.c --build $(MOCK_BUILD_DIR) \
	  --cc "$(HOST_CC)"

soc-sw: verify
	$(CMAKE) -S $(SOC_TEST_SOURCE_DIR) -B $(SOC_TEST_BUILD_DIR) \
	  -D CMAKE_BUILD_TYPE=Release -D DORA_GEN_DIR=$(DORA_GEN_DIR)
	$(CMAKE) --build $(SOC_TEST_BUILD_DIR) --target dora-static-hycube \
	  --parallel $(SOC_BUILD_JOBS)

# DoraFabric's producer check is the SoC's guard against skew; only the
# development override may run with it relaxed.
skew-check:
	@if [ "$$DORA_ALLOW_SKEW" = 1 ] && [ "$(DORA_GEN_ALLOW_DEV)" != 1 ]; then \
	  echo "dora: DORA_ALLOW_SKEW=1 would let DoraFabric elaborate a skewed interchange;" \
	    "unset it (or, for development only, also set DORA_GEN_ALLOW_DEV=1)" >&2; \
	  exit 1; \
	fi

# Opt-in full-SoC proof, following the RTA V4 recipe. LOADMEM preloads DRAM;
# the Rocket core still boots the ELF and every fabric access crosses the
# generated TileLink/MMIO path.
soc-smoke: skew-check offline-sbt-check soc-sw
	$(SOC_TOOL) stamp --out $(DORA_OUT) --stamp $(DORA_STAMP)
	$(MAKE) -C $(SIM_DIR) \
	  CONFIG=$(SOC_CONFIG) \
	  EXTRA_GENERATOR_REQS="$(DORA_FABRIC) $(DORA_CELLS) $(DORA_STAMP)" \
	  BINARY=$(SOC_TEST_BINARY) \
	  LOADMEM=1 \
	  TIMEOUT_CYCLES=$(SOC_TIMEOUT_CYCLES) \
	  run-binary-fast
	@grep -q '^DORA K3 mem_axpy: PASS' $(SOC_LOG) || \
	  { echo "dora: $(SOC_LOG) has no PASS line" >&2; exit 1; }
	@echo "dora: soc-smoke passed: $$(grep '^DORA K3 mem_axpy: PASS' $(SOC_LOG))"

check: verify
	$(SOC_TOOL) stamp --out $(DORA_OUT) --stamp $(DORA_STAMP) --check $(SOC_FIRRTL)
	prefix="$$($(SOC_TOOL) get --out $(DORA_OUT) module_prefix)" && \
	cd $(DORA_ROOT) && scripts/dora-run --cwd . python -m dora.hdl.checker \
	  --interchange $(DORA_FABRIC) --prefix "$$prefix" \
	  --file-list $(SOC_BUILD_DIR)/sim_files.common.f \
	  --regmap $(SOC_BUILD_DIR) \
	  $(SOC_BUILD_DIR)/gen-collateral
	$(SOC_TOOL) wiring --out $(DORA_OUT) --firrtl $(SOC_FIRRTL)

soc-smoke-all:
	$(MAKE) -f $(MAKEFILE_PATH) gen
	$(MAKE) -f $(MAKEFILE_PATH) test-software
	$(MAKE) -f $(MAKEFILE_PATH) shell-unit-test
	$(MAKE) -f $(MAKEFILE_PATH) soc-smoke
	$(MAKE) -f $(MAKEFILE_PATH) check

# The shell's unit tests through Chipyard's sbt (offline, like the jar build),
# with Chipyard's own sbt command and JAVA_TOOL_OPTIONS (sims/verilator
# launch-sbt); chipyard's build.sbt adds dora.chisel/chipyard/src/test/scala to
# its test sources when generators/dora is wired in. DORA_FABRIC (DORA_OUT's
# interchange) adds the cases on the real fabric, which the SoC program cannot
# check (exact en_i, drain, prog_rst and settle timing, en_i-gated writes, the
# fabric's out-of-range accesses). ScalaTest cancels a case whose interchange it
# cannot find, so the log must show every case passed and none canceled.
# chiseltest writes below SHELL_TEST_DIR.
SHELL_TEST_DIR ?= $(TMPDIR)/dora-shell-test/$(CHIPYARD_KEY)
SHELL_TESTS ?= dora.chisel.soc.DoraShellSpec
SHELL_TEST_LOG = $(SHELL_TEST_DIR)/shell-unit-test.log

shell-unit-test: offline-sbt-check verify
	mkdir -p $(SHELL_TEST_DIR)
	set -o pipefail; DORA_SHELL_TEST_DIR=$(SHELL_TEST_DIR) \
	  $(MAKE) -C $(SIM_DIR) launch-sbt \
	  SBT_COMMAND="chipyard / Test / testOnly $(SHELL_TESTS)" 2>&1 | tee $(SHELL_TEST_LOG)
	@sed 's/\x1b\[[0-9;]*m//g' $(SHELL_TEST_LOG) | \
	  grep -Eq 'Tests: succeeded [1-9][0-9]*, failed 0, canceled 0,' || \
	  { echo "dora: $(SHELL_TEST_LOG) does not show every $(SHELL_TESTS) case passed with none canceled" >&2; exit 1; }
	@echo "dora: shell-unit-test passed: $$(sed 's/\x1b\[[0-9;]*m//g' $(SHELL_TEST_LOG) | grep -Eo 'Tests: succeeded [0-9]+, failed 0, canceled 0')"

test:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) $(MAKEFILE_DIR)/test_dora_soc.py
