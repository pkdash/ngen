#
# Terminal-friendly equivalents of the VS Code tasks in .vscode/tasks.json.
#
# Run from anywhere in the repo:
#
#     make -C commands <target>            # or: make -f commands/Makefile <target>
#
# Every recipe cd's to the repo root itself, so the directory you invoke make
# from does not matter. `make -C commands` with no target prints the help.
#
# This file is the single source of truth for the CMake flag sets; the tasks in
# .vscode/tasks.json are thin wrappers that call these targets, so the two can
# no longer drift. See setup-commands.md for the ordered walkthrough of each
# configuration and ngen-vscode-dev-setup.md for the reasoning behind the flags.
#

# Recipes source .venv-linux/bin/activate, which is a bashism — /bin/sh is dash
# on the Ubuntu image.
SHELL := /bin/bash

# Absolute path to the repo root, derived from this makefile's own location.
MAKEFILE_PATH := $(abspath $(lastword $(MAKEFILE_LIST)))
ROOT          := $(abspath $(dir $(MAKEFILE_PATH))..)

BUILD_DIR    := cmake_build
CACHE        := $(ROOT)/$(BUILD_DIR)/CMakeCache.txt
JOBS         ?= $(shell nproc 2>/dev/null || echo 4)

# Overridable from the environment, exactly as the tasks do.
BOOST_ROOT   ?= /opt/boost_1_79_0
BOOST_BUILT  := /opt/boost-built
EWTS_PREFIX  := /opt/ewts
VENV         := .venv-linux

# CFE, built standalone so the Python BMI wrapper can link it. Separate from
# $(BUILD_DIR): extern/cfe is its own CMake project, not part of the ngen build.
CFE_BUILD_DIR := extern/cfe/cmake_build
CFE_LIB       := $(ROOT)/$(CFE_BUILD_DIR)/libcfebmi.so
LASAM_LIB     := $(ROOT)/extern/lgar-c/cmake_build/liblasambmi.so
PET_LIB       := $(ROOT)/extern/evapotranspiration/evapotranspiration/cmake_build/libpetbmi.so
SAC_SMA_LIB   := $(ROOT)/extern/sac-sma/cmake_build/libsacbmi.so
# SFT/SMP build to the OUTPUT dir ngen's own CMakeLists.txt uses for them
# (one level above the nested source dir), so a library built by ngen's
# configure and one built by build-sft-lib/build-smp-lib land in the same place.
SFT_BUILD_DIR := extern/SoilFreezeThaw/cmake_build
SMP_BUILD_DIR := extern/SoilMoistureProfiles/cmake_build
SFT_LIB       := $(ROOT)/$(SFT_BUILD_DIR)/libsftbmi.so
SMP_LIB       := $(ROOT)/$(SMP_BUILD_DIR)/libsmpbmi.so
SNOW17_LIB    := $(ROOT)/extern/snow17/cmake_build/libsnow17bmi.so
TOPMODEL_LIB  := $(ROOT)/extern/topmodel/cmake_build/libtopmodelbmi.so
UEB_LIB       := $(ROOT)/extern/ueb-bmi/cmake_build/src/libbmiuebcxx.so
BMI_WRAPPER_LIB_DIRS := $(ROOT)/extern/cfe/cmake_build:$(ROOT)/extern/noah-owp-modular/cmake_build:$(ROOT)/extern/lgar-c/cmake_build:$(ROOT)/extern/evapotranspiration/evapotranspiration/cmake_build:$(ROOT)/extern/sac-sma/cmake_build:$(ROOT)/$(SFT_BUILD_DIR):$(ROOT)/$(SMP_BUILD_DIR):$(ROOT)/extern/snow17/cmake_build:$(ROOT)/extern/topmodel/cmake_build:$(ROOT)/extern/ueb-bmi/cmake_build/src:$(BOOST_BUILT)/lib:$(EWTS_PREFIX)/lib

# Noah-OWP-Modular. Unlike CFE, extern/noah-owp-modular is not a standalone
# CMake project: its CMakeLists only links iso_c_bmi and skips NetCDF
# discovery inside the NGEN_IS_MAIN_PROJECT branch, so `cmake -S
# extern/noah-owp-modular` alone hits its broken else-branch instead (needs
# NetCDF). So build-noah-lib reconfigures the SAME $(BUILD_DIR) as every other
# configure target, with configure-fortran's flags, rather than a separate
# build dir: add_external_subdirectory always passes
# extern/noah-owp-modular/cmake_build (and extern/iso_c_fortran_bmi/cmake_build
# for iso_c_bmi) as those targets' own binary dirs, as a FIXED path outside of
# whichever top build dir triggered the configure — so a separate build dir
# would not actually be isolated from $(BUILD_DIR) at all, just an illusion of
# one. This means build-noah-lib can revert $(BUILD_DIR)'s active flags the
# same way switching between configure-python/configure-fortran/etc. already
# does; `make -C commands clean` is the fix if that surprises you.
NOAH_LIB := $(ROOT)/extern/noah-owp-modular/cmake_build/libsurfacebmi.so

# Overridable like TARGETS, for the bmi-io target.
MODEL        ?= cfe
WORKDIR      ?=

# Targets `make build` passes to cmake --build. Override per configuration, e.g.
#     make -C commands build TARGETS="ngen bmiuebcxx surfacebmi"
TARGETS      ?= ngen testbmicppmodel

# ---------------------------------------------------------------------------
# Shared CMake flags
# ---------------------------------------------------------------------------

COMMON_FLAGS := -DCMAKE_BUILD_TYPE=Debug \
                -DCMAKE_EXPORT_COMPILE_COMMANDS=ON \
                -DNGEN_WITH_TESTS:BOOL=ON \
                -DNGEN_WITH_NETCDF:BOOL=ON \
                -DNGEN_WITH_SQLITE:BOOL=ON \
                -DNGEN_WITH_UDUNITS:BOOL=ON \
                -DNGEN_WITH_MPI:BOOL=OFF

# Works around two bugs in extern/ueb-bmi's own CMakeLists.txt that otherwise
# break NetCDF detection when NGEN_WITH_NETCDF is on.
UEB_FLAGS    := -DNGEN_WITH_EXTERN_UEB:BOOL=ON \
                -Dewts_DIR=$(EWTS_PREFIX)/lib/cmake/ewts \
                -DCMAKE_POLICY_DEFAULT_CMP0057=NEW \
                -DNETCDF_C_LIB_DIR=/usr/lib/$$(gcc -dumpmachine) \
                -DNETCDF_C_INCLUDE_DIR=/usr/include

# ---------------------------------------------------------------------------
# Preflight guards (shell snippets reused across recipes)
# ---------------------------------------------------------------------------

define require_boost_headers
	@[ -r "$(BOOST_ROOT)/boost/version.hpp" ] || [ -r "$(BOOST_ROOT)/include/boost/version.hpp" ] || { \
	    echo "ERROR: no readable boost/version.hpp under $(BOOST_ROOT). See Troubleshooting 3b (Found unsuitable version 0.0.0) in ngen-vscode-dev-setup.md."; \
	    exit 1; }
endef

define require_venv
	@[ -x "$(ROOT)/$(VENV)/bin/python" ] || { \
	    echo "ERROR: no $(VENV) in the workspace. Run 'make -C commands setup-venv' first — NGEN_WITH_PYTHON=ON needs a venv with numpy<2.0."; \
	    exit 1; }
endef

define require_boost_built
	@[ -r "$(BOOST_BUILT)/include/boost/version.hpp" ] || { \
	    echo "ERROR: $(BOOST_BUILT) has no readable boost/version.hpp — UEB needs the compiled Boost. Run (or re-run to completion) 'make -C commands setup-boost'."; \
	    exit 1; }
endef

define require_ewts
	@[ -d "$(EWTS_PREFIX)" ] || { \
	    echo "ERROR: $(EWTS_PREFIX) not found. Run 'make -C commands setup-ewts' first."; \
	    exit 1; }
endef

# ---------------------------------------------------------------------------
# Help (default goal — a bare `make` never starts a build)
# ---------------------------------------------------------------------------

.DEFAULT_GOAL := help

.PHONY: help
help:
	@echo "ngen dev commands — run as: make -C commands <target>"
	@echo
	@echo "Setup (once per container):"
	@echo "  setup-venv          Create $(VENV) with numpy<2.0 and init extern/pybind11"
	@echo "  setup-boost         Build+install Boost with serialization to $(BOOST_BUILT)  [UEB]"
	@echo "  setup-ewts          Build+install EWTS to $(EWTS_PREFIX)                      [UEB]"
	@echo
	@echo "Configure (all share one $(BUILD_DIR); run 'clean' before switching):"
	@echo "  configure           Default, CI-matched lean build"
	@echo "  configure-python    + BMI-C and embedded Python (turns routing on)   needs: setup-venv"
	@echo "  configure-fortran   + BMI-C and BMI-Fortran / Noah-OWP-Modular"
	@echo "  configure-ueb       + BMI-C and UEB                    needs: setup-boost, setup-ewts"
	@echo "  configure-all       Everything above at once           needs: all three setup targets"
	@echo
	@echo "Build:"
	@echo "  build               Configure if needed, then build TARGETS (default: $(TARGETS))"
	@echo "  build-tests         Build test_unit and test_geopackage"
	@echo "  build-test          Build one target: make -C commands build-test TARGET=test_partition"
	@echo "  clean               Remove $(BUILD_DIR)"
	@echo "  rebuild             clean, then build"
	@echo "  show-config         Print the optional components the current $(BUILD_DIR) was configured with"
	@echo
	@echo "BMI wrapper tooling (Python introspection; does not affect the ngen binary):"
	@echo "  build-*-lib           Build an individual wrapper's native BMI library"
	@echo "  build-bmi-wrapper-libs Build native BMI libraries for all ten wrappers"
	@echo "  install-bmi-wrappers  pip install each wrapper whose native library exists"
	@echo "                        FORCE=1 rebuilds already-installed wrappers"
	@echo "  bmi-io                Query a model: MODEL=cfe|noah|lasam|pet|sac_sma|sft|smp|snow17|topmodel|ueb"
	@echo "                        Optional: CONFIG=... WORKDIR=... REALIZATION=..."
	@echo "                        BMI_REF=<tag|branch> installs wrappers from another pkdash/BMI ref"
	@echo
	@echo "ngen_bmi (set up, parameterize and run ngen from Python; tools/ngen-bmi):"
	@echo "  install-ngen-bmi      pip install bmi_setup and ngen_bmi (editable) into the venv"
	@echo "                        BMI_SETUP=/path/to/BMI/bmi_setup installs a local checkout"
	@echo "  test-ngen-bmi         Unit, wrapper-integration and ngen-integration tests;"
	@echo "                        layers whose prerequisites are missing are skipped"
	@echo "  ngen-bmi-example      Run tools/ngen-bmi/examples/change_parameters.py (OUT=dir)"
	@echo
	@echo "Build targets per configuration:"
	@echo "  default   TARGETS=\"ngen testbmicppmodel\"       ueb   TARGETS=\"ngen bmiuebcxx\""
	@echo "  python    TARGETS=\"ngen\"                        all   TARGETS=\"ngen bmiuebcxx surfacebmi\""
	@echo "  fortran   TARGETS=\"ngen\"  (test_bmi_fortran does not compile — pre-existing)"

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

# Deliberately NOT named .venv: a .venv created on a macOS host is bind-mounted
# into the container but its binaries cannot run there.
.PHONY: setup-venv
setup-venv:
	cd $(ROOT) && \
	python3 -m venv $(VENV) && \
	$(VENV)/bin/pip install --quiet --upgrade pip && \
	$(VENV)/bin/pip install --quiet "numpy<2.0" && \
	git submodule update --init --recursive -- extern/pybind11 && \
	echo -n "venv ready: numpy " && \
	$(VENV)/bin/python -c "import numpy; print(numpy.__version__)"

# The default image only ships Boost headers. Slow — let it finish; an
# interrupted b2 install leaves early-alphabet headers behind and every later
# configure then fails with "Found unsuitable version 0.0.0".
.PHONY: setup-boost
setup-boost:
	cd $(BOOST_ROOT) && \
	./bootstrap.sh --with-libraries=serialization && \
	./b2 install --prefix=$(BOOST_BUILT)
	@[ -r "$(BOOST_BUILT)/include/boost/version.hpp" ] && echo "Boost install complete." || { \
	    echo "ERROR: b2 install did not complete — $(BOOST_BUILT)/include/boost/version.hpp is missing. Re-run this target; a partial install makes every configure fail with Boost version 0.0.0."; \
	    exit 1; }

# Configures from extern/ewts (the root CMakeLists.txt with the real
# project()/VERSION), not extern/ewts/runtime as upstream's INSTALL.md says —
# the runtime-only configure has no project() and fails at
# write_basic_package_version_file. Boost headers go in via CMAKE_CXX_FLAGS
# because EWTS's ngen bridge includes boost/property_tree but never calls
# find_package(Boost) itself.
.PHONY: setup-ewts
setup-ewts:
	cd $(ROOT) && \
	apt-get update && \
	apt-get install -y --no-install-recommends libopenmpi-dev openmpi-bin && \
	cmake -B /tmp/ewts-build -S extern/ewts \
	    -DCMAKE_BUILD_TYPE=Release \
	    -DEWTS_WITH_NGEN=ON \
	    -DCMAKE_CXX_FLAGS="-I$(BOOST_ROOT)" && \
	cmake --build /tmp/ewts-build -j $(JOBS) && \
	cmake --install /tmp/ewts-build --prefix $(EWTS_PREFIX)

# ---------------------------------------------------------------------------
# Configure
# ---------------------------------------------------------------------------

# Matches ngen CI's test_unit job: NetCDF/UDUNITS/SQLite on, BMI-C/Python/MPI off.
.PHONY: configure
configure:
	$(require_boost_headers)
	cd $(ROOT) && cmake -S . -B $(BUILD_DIR) $(COMMON_FLAGS) \
	    -DBOOST_ROOT="$(BOOST_ROOT)" \
	    -DNGEN_WITH_BMI_C:BOOL=OFF \
	    -DNGEN_WITH_BMI_FORTRAN:BOOL=OFF \
	    -DNGEN_WITH_PYTHON:BOOL=OFF

# BMI-C pulls in TOPMODEL/CFE/PET/LGAR; NGEN_WITH_PYTHON=ON turns routing on too.
.PHONY: configure-python
configure-python:
	$(require_venv)
	$(require_boost_headers)
	cd $(ROOT) && source $(VENV)/bin/activate && \
	cmake -S . -B $(BUILD_DIR) $(COMMON_FLAGS) \
	    -DBOOST_ROOT="$(BOOST_ROOT)" \
	    -DNGEN_WITH_BMI_C:BOOL=ON \
	    -DNGEN_WITH_BMI_FORTRAN:BOOL=OFF \
	    -DNGEN_WITH_PYTHON:BOOL=ON

# NGEN_WITH_BMI_FORTRAN=ON also turns on Noah-OWP-Modular. BMI-C is ON because
# Noah's shipped realization configs are bmi_multi with SLoTH/PET/CFE; Python is
# OFF because Noah needs nothing from it.
.PHONY: configure-fortran
configure-fortran:
	$(require_boost_headers)
	cd $(ROOT) && cmake -S . -B $(BUILD_DIR) $(COMMON_FLAGS) \
	    -DBOOST_ROOT="$(BOOST_ROOT)" \
	    -DNGEN_WITH_BMI_C:BOOL=ON \
	    -DNGEN_WITH_BMI_FORTRAN:BOOL=ON \
	    -DNGEN_WITH_PYTHON:BOOL=OFF

# UEB (bmi_c++ snow model). Python is OFF because UEB needs nothing from it.
.PHONY: configure-ueb
configure-ueb:
	$(require_boost_built)
	$(require_ewts)
	cd $(ROOT) && cmake -S . -B $(BUILD_DIR) $(COMMON_FLAGS) \
	    -DBOOST_ROOT=$(BOOST_BUILT) \
	    -DNGEN_WITH_BMI_C:BOOL=ON \
	    -DNGEN_WITH_BMI_FORTRAN:BOOL=OFF \
	    -DNGEN_WITH_PYTHON:BOOL=OFF \
	    $(UEB_FLAGS)

# Every model component this image supports at once. Uses the compiled Boost
# since UEB needs it, and that install serves the rest too. Not included: MPI
# (no runtime in the image) and SMP/SoilFreezeThaw (untested here).
.PHONY: configure-all
configure-all:
	$(require_venv)
	$(require_boost_built)
	$(require_ewts)
	cd $(ROOT) && source $(VENV)/bin/activate && \
	cmake -S . -B $(BUILD_DIR) $(COMMON_FLAGS) \
	    -DBOOST_ROOT=$(BOOST_BUILT) \
	    -DNGEN_WITH_BMI_C:BOOL=ON \
	    -DNGEN_WITH_BMI_FORTRAN:BOOL=ON \
	    -DNGEN_WITH_PYTHON:BOOL=ON \
	    $(UEB_FLAGS)

# The "configure if needed" behaviour: because this is a real file target used
# as an order-only prerequisite below, the default configure runs only when
# CMakeCache.txt is absent. An opt-in configure is never silently reverted.
$(CACHE):
	@echo "No $(BUILD_DIR)/CMakeCache.txt — running the default configure."
	@$(MAKE) -f $(MAKEFILE_PATH) configure

# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------

.PHONY: show-config
show-config:
	@[ -f $(CACHE) ] || { echo "$(BUILD_DIR) is not configured yet."; exit 1; }
	@echo "Active $(BUILD_DIR) configuration:"
	@grep -E "^NGEN_WITH_(BMI_C|BMI_FORTRAN|PYTHON|MPI|EXTERN_UEB):" $(CACHE) | sed "s/^/  /"

.PHONY: build
build: | $(CACHE)
	@$(MAKE) -s -f $(MAKEFILE_PATH) show-config
	cd $(ROOT) && cmake --build $(BUILD_DIR) --target $(TARGETS) -- -j $(JOBS)

.PHONY: build-tests
build-tests: | $(CACHE)
	cd $(ROOT) && cmake --build $(BUILD_DIR) --target test_unit test_geopackage -- -j $(JOBS)

# Replaces the tasks.json promptString input; pass the target explicitly.
.PHONY: build-test
build-test: | $(CACHE)
	@[ -n "$(TARGET)" ] || { \
	    echo "ERROR: set TARGET, e.g. make -C commands build-test TARGET=test_partition"; \
	    echo "       (see test/CMakeLists.txt for the full list: test_unit, test_nexus, test_geojson, test_mdarray, test_logging, ...)"; \
	    exit 1; }
	cd $(ROOT) && cmake --build $(BUILD_DIR) --target $(TARGET) -- -j $(JOBS)

# Also the fix when a configure picks up stale cached paths from a different
# configure — they all share one cmake_build.
.PHONY: clean
clean:
	rm -rf $(ROOT)/$(BUILD_DIR)

.PHONY: rebuild
rebuild:
	@$(MAKE) -f $(MAKEFILE_PATH) clean
	@$(MAKE) -f $(MAKEFILE_PATH) build

# ---------------------------------------------------------------------------
# BMI wrapper tooling
#
# The Python BMI wrappers are introspection helpers only: they let you ask a
# model what it actually consumes and produces. ngen keeps running these models
# through its own C/Fortran adapters, and nothing here is imported by the ngen
# binary. See tools/bmi-wrappers/README.md.
# ---------------------------------------------------------------------------

# extern/cfe is a standalone CMake project (not part of the ngen build), and
# builds libcfebmi as SHARED on every non-Windows platform with no options.
.PHONY: build-cfe-lib
build-cfe-lib:
	cd $(ROOT) && git submodule update --init --recursive -- extern/cfe && \
	cmake -S extern/cfe -B $(CFE_BUILD_DIR) && \
	cmake --build $(CFE_BUILD_DIR) -- -j $(JOBS)

# Full ngen configure (not standalone, unlike CFE) with NGEN_WITH_BMI_FORTRAN
# so NGEN_IS_MAIN_PROJECT's branch links iso_c_bmi; only the surfacebmi target
# (and its dependency iso_c_bmi) is actually built. Reconfigures the SHARED
# $(BUILD_DIR) with configure-fortran's flags -- there is no isolated build dir
# to use instead, since extern/noah-owp-modular's and extern/iso_c_fortran_bmi's
# own CMakeLists always place their build output at a fixed path under extern/,
# regardless of which top build dir triggered the configure. If $(BUILD_DIR)
# was configured differently (e.g. configure-python), this reverts it to the
# Fortran flags, same as running any other configure-* target would; run
# 'make -C commands clean' first if you want a from-scratch reconfigure.
.PHONY: build-noah-lib
build-noah-lib:
	$(require_boost_headers)
	cd $(ROOT) && git submodule update --init --recursive -- extern/noah-owp-modular extern/iso_c_fortran_bmi && \
	cmake -S . -B $(BUILD_DIR) $(COMMON_FLAGS) \
	    -DBOOST_ROOT="$(BOOST_ROOT)" \
	    -DNGEN_WITH_BMI_C:BOOL=ON \
	    -DNGEN_WITH_BMI_FORTRAN:BOOL=ON \
	    -DNGEN_WITH_PYTHON:BOOL=OFF && \
	cmake --build $(BUILD_DIR) --target surfacebmi -- -j $(JOBS)

# These wrapper-specific builds use the model submodules directly. They are
# kept separate from ngen's default configure so introspection does not silently
# enable optional native components in the main build.
.PHONY: build-lasam-lib
build-lasam-lib:
	cd $(ROOT) && git submodule update --init --recursive -- extern/lgar-c/LGAR-C && \
	cmake -S extern/lgar-c -B extern/lgar-c/cmake_build && \
	cmake --build extern/lgar-c/cmake_build --target lasambmi -- -j $(JOBS)

.PHONY: build-pet-lib
build-pet-lib:
	cd $(ROOT) && git submodule update --init --recursive -- extern/evapotranspiration/evapotranspiration && \
	cmake -S extern/evapotranspiration/evapotranspiration \
	    -B extern/evapotranspiration/evapotranspiration/cmake_build && \
	cmake --build extern/evapotranspiration/evapotranspiration/cmake_build --target petbmi -- -j $(JOBS)

.PHONY: build-sac-sma-lib
build-sac-sma-lib:
	cd $(ROOT) && git submodule update --init --recursive -- extern/sac-sma && \
	cmake -S extern/sac-sma -B extern/sac-sma/cmake_build \
	    -DISO_C_FORTRAN_BMI_PATH=$(ROOT)/extern/iso_c_fortran_bmi && \
	cmake --build extern/sac-sma/cmake_build --target sacbmi -- -j $(JOBS)

.PHONY: build-sft-lib
build-sft-lib:
	cd $(ROOT) && git submodule update --init --recursive -- extern/SoilFreezeThaw/SoilFreezeThaw && \
	cmake -S extern/SoilFreezeThaw/SoilFreezeThaw \
	    -B $(SFT_BUILD_DIR) -DNGEN=1 && \
	cmake --build $(SFT_BUILD_DIR) --target sftbmi -- -j $(JOBS)

.PHONY: build-smp-lib
build-smp-lib:
	cd $(ROOT) && git submodule update --init --recursive -- extern/SoilMoistureProfiles/SoilMoistureProfiles && \
	cmake -S extern/SoilMoistureProfiles/SoilMoistureProfiles \
	    -B $(SMP_BUILD_DIR) -DNGEN=1 && \
	cmake --build $(SMP_BUILD_DIR) --target smpbmi -- -j $(JOBS)

.PHONY: build-snow17-lib
build-snow17-lib:
	cd $(ROOT) && git submodule update --init --recursive -- extern/snow17 && \
	cmake -S extern/snow17 -B extern/snow17/cmake_build \
	    -DISO_C_FORTRAN_BMI_PATH=$(ROOT)/extern/iso_c_fortran_bmi && \
	cmake --build extern/snow17/cmake_build --target snow17bmi -- -j $(JOBS)

.PHONY: build-topmodel-lib
build-topmodel-lib:
	cd $(ROOT) && git submodule update --init --recursive -- extern/topmodel/topmodel && \
	cmake -S extern/topmodel -B extern/topmodel/cmake_build && \
	cmake --build extern/topmodel/cmake_build --target topmodelbmi -- -j $(JOBS)

.PHONY: build-ueb-lib
build-ueb-lib:
	$(require_boost_built)
	$(require_ewts)
	cd $(ROOT) && git submodule update --init --recursive -- extern/ueb-bmi extern/bmi-cxx && \
	cmake -S extern/ueb-bmi -B extern/ueb-bmi/cmake_build \
	    -DBOOST_ROOT=$(BOOST_BUILT) \
	    -Dewts_DIR=$(EWTS_PREFIX)/lib/cmake/ewts \
	    -DCMAKE_POLICY_DEFAULT_CMP0057=NEW \
	    -DNETCDF_C_LIB_DIR=/usr/lib/$$(gcc -dumpmachine) \
	    -DNETCDF_C_INCLUDE_DIR=/usr/include && \
	cmake --build extern/ueb-bmi/cmake_build --target bmiuebcxx -- -j $(JOBS)

.PHONY: build-bmi-wrapper-libs
build-bmi-wrapper-libs:
	@$(MAKE) -f $(MAKEFILE_PATH) build-cfe-lib
	@$(MAKE) -f $(MAKEFILE_PATH) build-noah-lib
	@$(MAKE) -f $(MAKEFILE_PATH) build-lasam-lib
	@$(MAKE) -f $(MAKEFILE_PATH) build-pet-lib
	@$(MAKE) -f $(MAKEFILE_PATH) build-sac-sma-lib
	@$(MAKE) -f $(MAKEFILE_PATH) build-sft-lib
	@$(MAKE) -f $(MAKEFILE_PATH) build-smp-lib
	@$(MAKE) -f $(MAKEFILE_PATH) build-snow17-lib
	@$(MAKE) -f $(MAKEFILE_PATH) build-topmodel-lib
	@$(MAKE) -f $(MAKEFILE_PATH) build-ueb-lib

# FORCE=1 rebuilds wrappers that are already installed. Without it, pip sees
# the same name and version installed and silently keeps the old build (the
# recipe still prints "Installed"), even when requirements.txt now pins a
# different source or the native library moved. --no-deps keeps the reinstall
# from touching numpy (<2 pin).
PIP_FORCE := $(if $(filter 1 yes true,$(FORCE)),--force-reinstall --no-deps)

# BMI_REF installs the wrappers from another pkdash/BMI tag, branch or commit
# than the one pinned in requirements.txt, e.g. to try a fix before it is
# tagged. bmi_setup needs the get/set_value fixes that came after v0.3.0:
#     make -C commands install-bmi-wrappers BMI_REF=add-bmi-setup FORCE=1
BMI_REF ?=

# Install independently: a missing library or a pip failure for one wrapper
# must not mask successful installs or prevent attempts for the others.
.PHONY: install-bmi-wrappers
install-bmi-wrappers:
	$(require_venv)
	@cd $(ROOT) && failed=0; \
	install_wrapper() { \
	    distribution="$$1"; lib_file="$$2"; target="$$3"; shift 3; \
	    requirement="$$(grep -m1 "^$${distribution} " tools/bmi-wrappers/requirements.txt)" || { \
	        echo "ERROR: no pin for $$distribution in tools/bmi-wrappers/requirements.txt"; failed=1; return; }; \
	    $(if $(BMI_REF),requirement="$$(echo "$$requirement" | sed -E 's|(BMI\.git)@[^#]+#|\1@$(BMI_REF)#|')";) \
	    if [ ! -r "$$lib_file" ]; then \
	        echo "SKIP $$distribution: native library not found -- run 'make -C commands $$target' first"; return; \
	    fi; \
	    echo "Installing $$distribution"; \
	    if env "$$@" LD_LIBRARY_PATH="$(BMI_WRAPPER_LIB_DIRS):$$LD_LIBRARY_PATH" \
	        LIBRARY_PATH="$(BOOST_BUILT)/lib:$(EWTS_PREFIX)/lib:$$LIBRARY_PATH" \
	        $(VENV)/bin/pip install $(PIP_FORCE) "$$requirement"; then \
	        echo "Installed $$distribution"; \
	    else \
	        echo "ERROR: pip install failed for $$distribution"; failed=1; \
	    fi; \
	}; \
	install_wrapper pymt_cfe "$(CFE_LIB)" build-cfe-lib \
	    CFE_ROOT="$(ROOT)/extern/cfe/cfe" \
	    CFE_LIB_DIR="$(ROOT)/$(CFE_BUILD_DIR)" \
	    PKG_CONFIG_PATH="$(ROOT)/$(CFE_BUILD_DIR):$$PKG_CONFIG_PATH"; \
	install_wrapper pymt_noah_owp "$(NOAH_LIB)" build-noah-lib \
	    NOAH_ROOT="$(ROOT)/extern/noah-owp-modular/noah-owp-modular" \
	    NOAH_LIB_DIR="$(ROOT)/extern/noah-owp-modular/cmake_build" \
	    NOAH_MOD_DIR="$(ROOT)/extern/noah-owp-modular/cmake_build/mod"; \
	install_wrapper pymt_lasam "$(LASAM_LIB)" build-lasam-lib \
	    LASAM_ROOT="$(ROOT)/extern/lgar-c/LGAR-C" LASAM_LIB_DIR="$(ROOT)/extern/lgar-c/cmake_build" \
	    LASAM_BMI_DIR="$(ROOT)/extern/lgar-c/LGAR-C/bmi" LASAM_RPATH="$(ROOT)/extern/lgar-c/cmake_build"; \
	install_wrapper pymt_pet "$(PET_LIB)" build-pet-lib \
	    PET_ROOT="$(ROOT)/extern/evapotranspiration/evapotranspiration" \
	    PET_LIB_DIR="$(ROOT)/extern/evapotranspiration/evapotranspiration/cmake_build" \
	    PKG_CONFIG_PATH="$(ROOT)/extern/evapotranspiration/evapotranspiration/cmake_build:$$PKG_CONFIG_PATH"; \
	install_wrapper pymt_sac_sma "$(SAC_SMA_LIB)" build-sac-sma-lib \
	    SAC_SMA_ROOT="$(ROOT)/extern/sac-sma" SAC_SMA_LIB_DIR="$(ROOT)/extern/sac-sma/cmake_build" \
	    SAC_SMA_BMI_DIR="$(ROOT)/extern/sac-sma/src/bmi" \
	    ISO_C_FORTRAN_BMI_PATH="$(ROOT)/extern/iso_c_fortran_bmi"; \
	install_wrapper pymt_sft "$(SFT_LIB)" build-sft-lib \
	    SFT_ROOT="$(ROOT)/extern/SoilFreezeThaw/SoilFreezeThaw" \
	    SFT_LIB_DIR="$(ROOT)/$(SFT_BUILD_DIR)" \
	    SFT_BMI_DIR="$(ROOT)/extern/SoilFreezeThaw/SoilFreezeThaw/bmi"; \
	install_wrapper pymt_smp "$(SMP_LIB)" build-smp-lib \
	    SMP_ROOT="$(ROOT)/extern/SoilMoistureProfiles/SoilMoistureProfiles" \
	    SMP_LIB_DIR="$(ROOT)/$(SMP_BUILD_DIR)" \
	    SMP_BMI_DIR="$(ROOT)/extern/SoilMoistureProfiles/SoilMoistureProfiles/bmi" \
	    SMP_RPATH="$(ROOT)/$(SMP_BUILD_DIR)"; \
	install_wrapper pymt_snow17 "$(SNOW17_LIB)" build-snow17-lib \
	    SNOW17_ROOT="$(ROOT)/extern/snow17" SNOW17_LIB_DIR="$(ROOT)/extern/snow17/cmake_build" \
	    SNOW17_BMI_DIR="$(ROOT)/extern/snow17/src/bmi" \
	    SNOW17_MOD_DIR="$(ROOT)/extern/snow17/cmake_build/iso_c_bmi" \
	    ISO_C_FORTRAN_BMI_PATH="$(ROOT)/extern/iso_c_fortran_bmi"; \
	install_wrapper pymt_topmodel "$(TOPMODEL_LIB)" build-topmodel-lib \
	    TOPMODEL_ROOT="$(ROOT)/extern/topmodel/topmodel" \
	    TOPMODEL_LIB_DIR="$(ROOT)/extern/topmodel/cmake_build"; \
	install_wrapper pymt_ueb "$(UEB_LIB)" build-ueb-lib \
	    UEB_ROOT="$(ROOT)/extern/ueb-bmi" UEB_LIB_DIR="$(ROOT)/extern/ueb-bmi/cmake_build/src" \
	    UEB_RPATH="$(ROOT)/extern/ueb-bmi/cmake_build/src" \
	    CPLUS_INCLUDE_PATH="$(EWTS_PREFIX)/include:$(BOOST_BUILT)/include:$$CPLUS_INCLUDE_PATH"; \
	echo "wrappers ready:"; \
	if ! LD_LIBRARY_PATH="$(BMI_WRAPPER_LIB_DIRS):$$LD_LIBRARY_PATH" \
	    $(VENV)/bin/python tools/bmi-wrappers/bmi_introspect.py list; then failed=1; fi; \
	exit $$failed

# CONFIG, WORKDIR, and REALIZATION are optional; without CONFIG the registry's
# sample is used when available. Exits non-zero when a cross-check finds an error.
.PHONY: bmi-io
bmi-io:
	$(require_venv)
	@cd $(ROOT) && LD_LIBRARY_PATH="$(BMI_WRAPPER_LIB_DIRS):$$LD_LIBRARY_PATH" \
	    $(VENV)/bin/python tools/bmi-wrappers/bmi_introspect.py $(MODEL) \
	    $(if $(CONFIG),--config $(CONFIG)) \
	    $(if $(WORKDIR),--workdir $(WORKDIR)) \
	    $(if $(REALIZATION),--realization $(REALIZATION)) \
	    $(if $(CATCHMENT),--catchment $(CATCHMENT)) \
	    $(BMI_IO_FLAGS)

# ---------------------------------------------------------------------------
# ngen_bmi: set up, parameterize and run ngen from Python (tools/ngen-bmi)
# ---------------------------------------------------------------------------

# Where bmi_setup comes from. Default: pkdash/BMI at BMI_SETUP_REF. A directory
# (a local pkdash/BMI checkout's bmi_setup/) is installed editable, and its own
# tests then join test-ngen-bmi.
# TODO: point BMI_SETUP_REF at the release tag once pkdash/BMI tags bmi_setup.
BMI_SETUP_REF ?= add-bmi-setup
BMI_SETUP     ?= git+https://github.com/pkdash/BMI.git@$(BMI_SETUP_REF)\#subdirectory=bmi_setup

.PHONY: install-ngen-bmi
install-ngen-bmi:
	$(require_venv)
	@cd $(ROOT) && \
	if [ -d "$(BMI_SETUP)" ]; then src=(-e "$(BMI_SETUP)"); else src=("bmi-setup @ $(BMI_SETUP)"); fi && \
	$(VENV)/bin/pip install "numpy<2.0" "$${src[@]}" && \
	$(VENV)/bin/pip install "numpy<2.0" -e "tools/ngen-bmi[test]" && \
	$(VENV)/bin/python -c "import bmi_setup, ngen_bmi; print('bmi_setup and ngen_bmi', ngen_bmi.__version__, 'installed')"

# Three layers:
#   1. unit tests of ngen_bmi, and of bmi_setup when installed from a checkout;
#   2. bmi_setup's wrapper integration (-m wrappers), for each model whose
#      pymt_* wrapper imports; the PYMT_<KEY>_CONFIG defaults below are the
#      configs that layer was verified with, and can be overridden;
#   3. ngen integration (-m ngen), which skips itself without cmake_build/ngen
#      (or $$NGEN_BIN) built with BMI C and Fortran.
# TOPMODEL's wrapper test needs a libtopmodelbmi.so with the get_var_nbytes
# fix (see topmodel-issue-ticket.md); an unfixed library fails the catalog check. Here,
# unlike bmi-io, the caller's LD_LIBRARY_PATH comes first, so a fixed library
# built elsewhere can stand in (the wrappers link with RUNPATH, which
# LD_LIBRARY_PATH overrides):
#     LD_LIBRARY_PATH=/path/to/topmodel/cmake_build make -C commands test-ngen-bmi
# CFE works the other way round (see cfe-issue-ticket.md). The catalog marks
# max_gw_storage "differs", because CFE's Set_value does not rescale the
# groundwater storage, so ngen_bmi edits the config for it. Layer 2 re-checks
# that status. Against a libcfebmi.so built with the upstream fix, it fails
# for max_gw_storage until the bmi_setup catalog says "equivalent". Layer 3 is
# unaffected either way.
# build-cfe-lib and build-topmodel-lib run `git submodule update`, which refuses
# while the submodule is checked out on a fix branch with local changes.
NGEN_BMI_FORCING := $(ROOT)/data/forcing/cat-27_2015-12-01 00_00_00_2015-12-30 23_00_00.csv

.PHONY: test-ngen-bmi
test-ngen-bmi:
	$(require_venv)
	@cd $(ROOT) && py="$(ROOT)/$(VENV)/bin/python" && failed=0 && \
	export LD_LIBRARY_PATH="$${LD_LIBRARY_PATH:+$$LD_LIBRARY_PATH:}$(BMI_WRAPPER_LIB_DIRS)" && \
	{ $$py -c "import bmi_setup, ngen_bmi" 2>/dev/null || { \
	    echo "ERROR: bmi_setup or ngen_bmi is not installed in $(VENV). Run 'make -C commands install-ngen-bmi' first."; exit 1; }; } && \
	default_config() { \
	    var="PYMT_$$1_CONFIG"; \
	    if [ -n "$${!var}" ]; then return; fi; \
	    if $$py -c "import $$2" >/dev/null 2>&1; then \
	        export "$$var=$(ROOT)/$$3"; \
	        if [ -n "$$4" ]; then export "PYMT_$$1_WORKDIR=$(ROOT)/$$4"; fi; \
	    else echo "SKIP $$2 wrapper tests: not installed"; fi; \
	}; \
	default_config CFE pymt_cfe data/gauge_01073000/CFE/cat-11223_bmi_config_cfe_pass.txt; \
	default_config NOAH_OWP pymt_noah_owp data/gauge_01073000/NOAH/cat-11223.input .; \
	default_config PET pymt_pet data/gauge_01073000/PET/cat-11223_pet_config.txt; \
	default_config TOPMODEL pymt_topmodel extern/topmodel/topmodel/data/topmod.run extern/topmodel/topmodel; \
	export BMI_SETUP_FORCING_CSV="$${BMI_SETUP_FORCING_CSV:-$(NGEN_BMI_FORCING)}"; \
	echo "== 1. ngen_bmi unit tests"; \
	$$py -m pytest -q tools/ngen-bmi -m "not ngen" || failed=1; \
	bmi_src="$$($$py -c 'import bmi_setup, pathlib; print(pathlib.Path(bmi_setup.__file__).resolve().parents[1])')"; \
	if [ -r "$$bmi_src/tests/test_catalog.py" ]; then \
	    echo "== 1. bmi_setup unit tests ($$bmi_src)"; \
	    (cd "$$bmi_src" && $$py -m pytest -q -m "not wrappers") || failed=1; \
	    echo "== 2. bmi_setup wrapper integration"; \
	    (cd "$$bmi_src" && $$py -m pytest -q -rs -m wrappers) || failed=1; \
	else \
	    echo "SKIP bmi_setup unit and wrapper tests: installed without its source; use install-ngen-bmi BMI_SETUP=/path/to/BMI/bmi_setup"; \
	fi; \
	echo "== 3. ngen integration"; \
	$$py -m pytest -q -rs tools/ngen-bmi -m ngen || failed=1; \
	exit $$failed

.PHONY: ngen-bmi-example
ngen-bmi-example:
	$(require_venv)
	@cd $(ROOT) && LD_LIBRARY_PATH="$${LD_LIBRARY_PATH:+$$LD_LIBRARY_PATH:}$(BMI_WRAPPER_LIB_DIRS)" \
	    $(VENV)/bin/python tools/ngen-bmi/examples/change_parameters.py $(if $(OUT),--out $(OUT))
