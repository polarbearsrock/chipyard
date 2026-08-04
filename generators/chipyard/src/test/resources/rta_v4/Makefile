MAKEFILE_DIR := $(patsubst %/,%,$(dir $(abspath $(lastword $(MAKEFILE_LIST)))))
CHIPYARD_ROOT := $(abspath $(MAKEFILE_DIR)/../../../../../..)
RESOURCE_DIR := $(CHIPYARD_ROOT)/generators/chipyard/src/main/resources/vsrc/rta_v4

ifndef TMPDIR
$(error TMPDIR must be set)
endif

PYTHON ?= python3
VERILATOR ?= verilator
FLOCK ?= flock
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

VERILATOR_FLAGS := --timing --assert --timescale 1ns/1ps -o simv -Wno-fatal

.PHONY: all verify verify-negative lint compile run

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
