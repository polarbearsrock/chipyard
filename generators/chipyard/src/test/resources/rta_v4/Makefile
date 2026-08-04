MAKEFILE_DIR := $(patsubst %/,%,$(dir $(abspath $(lastword $(MAKEFILE_LIST)))))
CHIPYARD_ROOT := $(abspath $(MAKEFILE_DIR)/../../../../../..)
RESOURCE_DIR := $(CHIPYARD_ROOT)/generators/chipyard/src/main/resources/vsrc/rta_v4

ifndef TMPDIR
$(error TMPDIR must be set)
endif

PYTHON ?= python3
VERILATOR ?= verilator
FLOCK ?= flock
CMAKE ?= cmake
VERILATOR_REALPATH := $(realpath $(shell command -v $(VERILATOR)))
VERILATOR_TOOL_DIR := $(dir $(VERILATOR_REALPATH))
export PATH := $(VERILATOR_TOOL_DIR):$(PATH)
BUNDLE := $(RESOURCE_DIR)/RtaV4Bundle.sv
ADAPTER_DIR := $(CHIPYARD_ROOT)/generators/chipyard/src/main/resources/rta_v4
ADAPTER := $(ADAPTER_DIR)/rta_v4_chipyard_adapter.sv
BITSTREAM := $(RESOURCE_DIR)/add_chain_compute.bin
TESTBENCH := $(MAKEFILE_DIR)/tb_rta_v4_chipyard_adapter.sv
MAPPING_TESTBENCH := $(MAKEFILE_DIR)/tb_rta_v4_adapter_mapping.sv
VERIFY := $(MAKEFILE_DIR)/verify_artifact.py
VERIFY_TEST := $(MAKEFILE_DIR)/test_verify_artifact.py
ARTIFACT_TAG := $(shell sha256sum $(BUNDLE) $(ADAPTER) $(BITSTREAM) \
  $(TESTBENCH) $(MAPPING_TESTBENCH) $(VERIFY) $(VERIFY_TEST) $(MAKEFILE_DIR)/Makefile \
  | sha256sum | cut -c1-16)
VERILATOR_TAG := $(shell $(VERILATOR) --version | sha256sum | cut -c1-8)
BUILD_DIR ?= $(TMPDIR)/chipyard_rta_v4_bundle_verilator/$(ARTIFACT_TAG)-$(VERILATOR_TAG)
FUNCTIONAL_OBJ_DIR := $(BUILD_DIR)/functional
MAPPING_OBJ_DIR := $(BUILD_DIR)/mapping
FUNCTIONAL_SIMV := $(FUNCTIONAL_OBJ_DIR)/simv
MAPPING_SIMV := $(MAPPING_OBJ_DIR)/simv
SOC_TEST_SOURCE_DIR := $(CHIPYARD_ROOT)/tests
SOC_TEST_BUILD_DIR ?= $(TMPDIR)/chipyard_rta_v4_soc_test
SOC_TEST_BINARY := $(SOC_TEST_BUILD_DIR)/rta-v4.riscv
SOC_SYSTOLIC_TEST_BINARY := $(SOC_TEST_BUILD_DIR)/rta-v4-systolic.riscv
SOC_CONFIG ?= RtaV4RocketConfig
SOC_TIMEOUT_CYCLES ?= 50000000
SOC_BUILD_JOBS ?= 4

VERILATOR_FLAGS := --timing --assert --timescale 1ns/1ps -o simv -Wno-fatal

.PHONY: all verify verify-negative lint compile run soc-smoke \
	soc-systolic-smoke soc-smoke-all

all: run

verify:
	$(PYTHON) $(VERIFY) $(RESOURCE_DIR) --adapter-source $(ADAPTER)

verify-negative: verify
	$(PYTHON) $(VERIFY_TEST) $(RESOURCE_DIR) $(ADAPTER)

lint: verify
	$(VERILATOR) --lint-only --top-module rta_v4_chipyard_adapter $(BUNDLE)

$(FUNCTIONAL_SIMV): $(BUNDLE) $(ADAPTER) $(BITSTREAM) $(TESTBENCH) \
  $(MAKEFILE_DIR)/Makefile | verify
	mkdir -p $(BUILD_DIR)
	$(FLOCK) $(BUILD_DIR)/functional.lock $(VERILATOR) --binary $(VERILATOR_FLAGS) \
	  --top-module tb_rta_v4_chipyard_adapter --Mdir $(FUNCTIONAL_OBJ_DIR) \
	  $(BUNDLE) $(TESTBENCH)

$(MAPPING_SIMV): $(ADAPTER) $(MAPPING_TESTBENCH) $(MAKEFILE_DIR)/Makefile | verify
	mkdir -p $(BUILD_DIR)
	$(FLOCK) $(BUILD_DIR)/mapping.lock $(VERILATOR) --binary $(VERILATOR_FLAGS) \
	  --top-module tb_rta_v4_adapter_mapping --Mdir $(MAPPING_OBJ_DIR) \
	  $(ADAPTER) $(MAPPING_TESTBENCH)

compile: $(MAPPING_SIMV) $(FUNCTIONAL_SIMV)

run: lint verify-negative compile
	$(MAPPING_SIMV)
	$(FUNCTIONAL_SIMV) +BITSTREAM=$(BITSTREAM)

# Opt-in full-SoC proof. LOADMEM preloads DRAM for speed; the Rocket core still
# boots the ELF and every RTA access traverses the generated TileLink/MMIO path.
soc-smoke:
	$(CMAKE) -S $(SOC_TEST_SOURCE_DIR) -B $(SOC_TEST_BUILD_DIR) \
	  -D CMAKE_BUILD_TYPE=Release
	$(CMAKE) --build $(SOC_TEST_BUILD_DIR) --target rta-v4 \
	  --parallel $(SOC_BUILD_JOBS)
	$(MAKE) -C $(CHIPYARD_ROOT)/sims/verilator \
	  CONFIG=$(SOC_CONFIG) \
	  BINARY=$(SOC_TEST_BINARY) \
	  LOADMEM=1 \
	  TIMEOUT_CYCLES=$(SOC_TIMEOUT_CYCLES) \
	  run-binary-fast

# This is the architectural systolic proof: the Rocket core programs six
# frozen DORA images and warm-reloads between phases without resetting the RMU
# accumulators, then checks the complete 4x4 signed-INT4 GEMM result matrix.
soc-systolic-smoke:
	$(CMAKE) -S $(SOC_TEST_SOURCE_DIR) -B $(SOC_TEST_BUILD_DIR) \
	  -D CMAKE_BUILD_TYPE=Release
	$(CMAKE) --build $(SOC_TEST_BUILD_DIR) --target rta-v4-systolic \
	  --parallel $(SOC_BUILD_JOBS)
	$(MAKE) -C $(CHIPYARD_ROOT)/sims/verilator \
	  CONFIG=$(SOC_CONFIG) \
	  BINARY=$(SOC_SYSTOLIC_TEST_BINARY) \
	  LOADMEM=1 \
	  TIMEOUT_CYCLES=$(SOC_TIMEOUT_CYCLES) \
	  run-binary-fast

soc-smoke-all: soc-smoke soc-systolic-smoke
