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
