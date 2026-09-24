########################################################################################################################
# file:  CMakeLists.txt
#
# usage: 
#   Edit "VARIABLES"-section to suit project requirements.
#   Build instructions:
#     cmake -S ./ -B ./build/ -D CMAKE_BUILD_TYPE=Debug
#     cmake --build ./build/ --target all
#   Cleaning:
#     cmake --build ./build/ --target clean
########################################################################################################################
cmake_minimum_required(VERSION 3.10)

project(chipyard-tests LANGUAGES C CXX)


#################################
# RISCV Toolchain
#################################

set(CMAKE_SYSTEM_NAME         "Generic" CACHE STRING "")
set(CMAKE_SYSTEM_PROCESSOR    "riscv"   CACHE STRING "")

set(TOOLCHAIN_PREFIX    "riscv64-unknown-elf-")

set(CMAKE_AR            "${TOOLCHAIN_PREFIX}ar")
set(CMAKE_ASM_COMPILER  "${TOOLCHAIN_PREFIX}gcc")
set(CMAKE_C_COMPILER    "${TOOLCHAIN_PREFIX}gcc")
set(CMAKE_CXX_COMPILER  "${TOOLCHAIN_PREFIX}g++")
set(CMAKE_LINKER        "${TOOLCHAIN_PREFIX}ld")
set(CMAKE_OBJCOPY       "${TOOLCHAIN_PREFIX}objcopy")
set(CMAKE_OBJDUMP       "${TOOLCHAIN_PREFIX}objdump")
set(CMAKE_SIZE          "${TOOLCHAIN_PREFIX}size")

set(CMAKE_EXECUTABLE_SUFFIX            ".riscv")


#################################
# Flags
#################################

# CPU architecture
set(ARCH                "rv64imafd")
set(ABI                 "lp64d")
set(CMODEL              "medany")
set(ARCH_FLAGS          -march=${ARCH} -mabi=${ABI} -mcmodel=${CMODEL})

# spec
set(SPECS               "htif_nano.specs")
set(SPEC_FLAGS          -specs=${SPECS})

# linker script
set(LINKER_SCRIPT       "htif.ld")

add_compile_options(-std=gnu99)
add_compile_options(-O2 -Wall -Wextra)
add_compile_options(-fno-common -fno-builtin-printf)
add_compile_options(${ARCH_FLAGS})
add_compile_options(${SPEC_FLAGS})

add_link_options(-static)
add_link_options(${SPEC_FLAGS})
add_link_options(-T ${LINKER_SCRIPT})


#################################
# Build
#################################

add_executable(pwm pwm.c)
add_executable(blkdev blkdev.c)
add_executable(accum accum.c)
add_executable(charcount charcount.c)
add_executable(cpp-hello cpp-hello.cpp)
add_executable(nic-loopback nic-loopback.c)
add_executable(big-blkdev big-blkdev.c)
add_executable(pingd pingd.c)
add_executable(streaming-passthrough streaming-passthrough.c)
add_executable(streaming-fir streaming-fir.c)
add_executable(nvdla nvdla.c)
add_executable(spiflashread spiflashread.c)
add_executable(spiflashwrite spiflashwrite.c)
add_executable(fft fft.c)
add_executable(gcd gcd.c)
add_executable(rta-v4 rta-v4.c rta-v4-test-runtime.c)

set(RTA_V4_RESOURCE_DIR
    "${CMAKE_CURRENT_SOURCE_DIR}/../generators/chipyard/src/main/resources/vsrc/rta_v4")
set(RTA_V4_SYSTOLIC_OBJECTS)
foreach(phase clear compute drain_col0 drain_col1 drain_col2 drain_col3)
    set(bitstream "${RTA_V4_RESOURCE_DIR}/systolic_${phase}.bin")
    set(object "${CMAKE_CURRENT_BINARY_DIR}/rta-v4-systolic-${phase}.o")
    add_custom_command(
        OUTPUT "${object}"
        COMMAND ${CMAKE_OBJCOPY}
            --input-target=binary
            --output-target=elf64-littleriscv
            --binary-architecture=riscv
            --rename-section .data=.rodata,alloc,load,readonly,data,contents
            "systolic_${phase}.bin" "${object}"
        DEPENDS "${bitstream}"
        WORKING_DIRECTORY "${RTA_V4_RESOURCE_DIR}"
        COMMENT "Embedding RTA V4 systolic ${phase} bitstream"
        VERBATIM
    )
    set_source_files_properties("${object}" PROPERTIES
        EXTERNAL_OBJECT TRUE
        GENERATED TRUE
    )
    list(APPEND RTA_V4_SYSTOLIC_OBJECTS "${object}")
endforeach()
add_executable(rta-v4-systolic
    rta-v4-systolic.c
    rta-v4-test-runtime.c
    ${RTA_V4_SYSTOLIC_OBJECTS}
)
add_executable(hello hello.c)
add_executable(mt-hello mt-hello.c)
add_executable(symmetric symmetric.c)
add_executable(ctc-test ctc-test.c)
add_executable(multi-ctc-test multi-ctc-test.c)
add_executable(triple-chiplet triple-chiplet.c)

#################################
# Disassembly
#################################

# Add a target to generate all disassemblies
add_custom_target(dump ALL)

# Function to add disassembly target for an executable
function(add_dump_target target_name)
    add_custom_target(${target_name}-dump
        BYPRODUCTS ${CMAKE_BINARY_DIR}/${target_name}.dump
        COMMAND ${CMAKE_OBJDUMP} -D $<TARGET_FILE:${target_name}> > ${CMAKE_BINARY_DIR}/${target_name}.dump
        DEPENDS ${target_name}
        COMMENT "Generating disassembly for ${target_name}"
    )
    add_dependencies(${target_name}-dump ${target_name})
    add_dependencies(dump ${target_name}-dump)
endfunction()

add_dump_target(pwm)
add_dump_target(blkdev)
add_dump_target(accum)
add_dump_target(charcount)
add_dump_target(cpp-hello)
add_dump_target(nic-loopback)
add_dump_target(big-blkdev)
add_dump_target(pingd)
add_dump_target(streaming-passthrough)
add_dump_target(streaming-fir)
add_dump_target(nvdla)
add_dump_target(spiflashread)
add_dump_target(spiflashwrite)
add_dump_target(fft)
add_dump_target(gcd)
add_dump_target(rta-v4)
add_dump_target(rta-v4-systolic)
add_dump_target(hello)
add_dump_target(mt-hello)
add_dump_target(symmetric)
add_dump_target(ctc-test)
add_dump_target(multi-ctc-test)
add_dump_target(triple-chiplet)


# Add custom command to generate spiflash.img from spiflash.py
add_custom_command(
    OUTPUT ${CMAKE_BINARY_DIR}/spiflash.img
    COMMAND python3 ${CMAKE_SOURCE_DIR}/spiflash.py --outfile ${CMAKE_SOURCE_DIR}/spiflash.img
    DEPENDS ${CMAKE_SOURCE_DIR}/spiflash.py
    COMMENT "Generating spiflash.img"
)

# Add a target for spiflash.img
add_custom_target(spiflash_img ALL
    DEPENDS ${CMAKE_BINARY_DIR}/spiflash.img
)


#################################
# DORA fabric (Chisel pilot step 5)
#################################

# Only with -D DORA_GEN_DIR=<DORA_OUT>/sw, the sw/ directory of a DORA
# `static_hycube.build --soc` render (generators/chipyard/src/test/resources/dora,
# `make gen`), which holds the DORA-generated header dora_<top>.h. Without it, or
# with it empty, no DORA target exists and nothing above changes. DORA_GEN_DIR
# is a cache variable, so a build directory keeps it: -D DORA_GEN_DIR= (or
# -U DORA_GEN_DIR) turns the target off again.
if(DORA_GEN_DIR)
    # static HyCUBE's top module is hycube_array; dora-static-hycube.c
    # includes this header and dora-runtime.c takes its generic part.
    set(DORA_HEADER "dora_hycube_array.h")
    if(NOT IS_ABSOLUTE "${DORA_GEN_DIR}")
        message(FATAL_ERROR
            "DORA_GEN_DIR='${DORA_GEN_DIR}' must be an absolute path: the sw/ "
            "directory of a DORA --soc render (or empty, with -D DORA_GEN_DIR=, "
            "to build without the DORA target)")
    endif()
    if(NOT EXISTS "${DORA_GEN_DIR}/${DORA_HEADER}")
        message(FATAL_ERROR
            "DORA_GEN_DIR=${DORA_GEN_DIR} has no ${DORA_HEADER}. Render the fabric "
            "with DORA first: make -C generators/chipyard/src/test/resources/dora "
            "gen (DORA's static_hycube build --soc writes <DORA_OUT>/sw/${DORA_HEADER}). "
            "This build directory remembers DORA_GEN_DIR; configure it with "
            "-D DORA_GEN_DIR= (or -U DORA_GEN_DIR) to build without the DORA target.")
    endif()
    message(STATUS "DORA fabric header: ${DORA_GEN_DIR}/${DORA_HEADER}")

    add_executable(dora-static-hycube dora-static-hycube.c dora-runtime.c)
    target_include_directories(dora-static-hycube PRIVATE "${DORA_GEN_DIR}")
    target_compile_definitions(dora-static-hycube PRIVATE
        "DORA_FABRIC_HEADER=\"${DORA_HEADER}\"")
    target_compile_options(dora-static-hycube PRIVATE -Werror)
    add_dump_target(dora-static-hycube)
endif()
