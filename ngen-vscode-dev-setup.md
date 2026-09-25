# ngen VSCode Development Environment Setup Guide

## Project Overview

**ngen** is the NOAA-OWP/CIROH "Next Gen Water Modeling Framework" — a C++14 CMake project that
drives hydrologic model formulations (native C++ or external models wired in via
[BMI](https://bmi.readthedocs.io/)) over a catchment/nexus hydrofabric. This guide only covers getting a working build/debug environment set up
in VS Code.

The project has a large dependency surface (Boost ≥1.79, NetCDF, UDUNITS2, SQLite3, optionally
MPI/Python/Fortran, plus a dozen `extern/` git submodules for individual hydrologic models), so
the **Dev Container is the supported way to build and debug it** in this setup — it gives you a
known-good, pinned Ubuntu 22.04 toolchain instead of fighting host-OS package versions, and it
works identically whether your host is macOS, Linux, or **Windows** (Docker Desktop always runs
the container as Linux, regardless of host OS).

This guide was validated against `CIROH-UA/ngen` at commit
`ad1c083a1db21c04eb13dabd9a78432b619ae0e0` on the `ngiab` branch.

## Table of Contents
1. [Dev Container Setup (Docker)](#dev-container-setup-docker)
2. [VSCode Setup](#vscode-setup)
3. [Building the Project](#building-the-project)
4. [Debugging](#debugging)
5. [Running with Example Data](#running-with-example-data)
6. [Enabling Optional Components](#enabling-optional-components)
7. [Troubleshooting](#troubleshooting)
8. [Project Structure (VS Code-relevant files)](#project-structure-vs-code-relevant-files)
9. [Quick Start Checklist](#quick-start-checklist)

---

## Dev Container Setup (Docker)

### Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) installed and running
  (Windows users: use the WSL2 backend, which is the default in current Docker Desktop versions)
- VS Code extension: **Dev Containers** (`ms-vscode-remote.remote-containers`)

### Steps

1. Open this project folder in VS Code
2. Command Palette (`Cmd/Ctrl+Shift+P`) → **"Dev Containers: Reopen in Container"** (or click the
   notification VS Code shows automatically when it detects `.devcontainer/`)
3. First time only: VS Code builds the image (installs the toolchain and downloads Boost 1.79.0) —
   this takes a few minutes; subsequent reopens reuse the cached image and are near-instant
4. On first creation, `postCreateCommand` automatically runs
   `git submodule update --init --recursive -- test/googletest` — this is the one submodule that
   must exist before CMake can configure at all (see [Troubleshooting](#troubleshooting) #1)
5. Once the container is up, build and debug as described below

### What the image gives you

- **Ubuntu 22.04** — matches the OS ngen's own CI (`.github/workflows/test_and_validate.yml`) uses,
  so the same package versions are known to build cleanly.
- **Boost 1.79.0**, vendored under `/opt/boost_1_79_0` (`$BOOST_ROOT`) — Ubuntu 22.04's own
  `libboost-dev` apt package is only 1.74, older than ngen's `find_package(Boost 1.79.0 REQUIRED)`
  floor, so the exact tarball ngen's CI and `docker/CENTOS_TEST.dockerfile` use is downloaded
  instead. Only headers are needed (no bootstrap/b2 build step) since ngen's top-level CMake target
  doesn't link a compiled Boost component.
- **NetCDF, UDUNITS2, SQLite3 dev packages** (`libnetcdf-dev`, `libnetcdf-c++4-dev`,
  `libudunits2-dev`, `libsqlite3-dev`) — matches the default flags
  `.github/actions/ngen-build/action.yaml` uses when no extra `bmi_c`/`use_python`/`use_mpi` inputs
  are passed (i.e. exactly what the `test_unit` CI job builds with).
- **gfortran** (plus `libnetcdff-dev`, which CI installs alongside it on Linux) — so BMI-Fortran and
  Noah-OWP-Modular are a CMake flag flip rather than an image rebuild. See
  [BMI-Fortran / Noah-OWP-Modular](#bmi-fortran--noah-owp-modular).
- `gdb`, with `--cap-add=SYS_PTRACE` / `seccomp=unconfined` set in `.devcontainer/devcontainer.json`
  so breakpoints and stepping work (Docker's default seccomp profile blocks the ptrace syscalls gdb
  needs).
- Python 3 + venv/dev headers, pre-installed but **unused by the default build** — they're there so
  you can flip on `NGEN_WITH_PYTHON`/BMI-Python/t-route support later without rebuilding the image.
- The C/C++ and CMake Tools VS Code extensions, pre-configured via `.devcontainer/devcontainer.json`.

### What it doesn't cover

The default configuration mirrors ngen CI's leanest job (`test_unit`) on purpose, so a first build
is fast and reliable. It does **not** by default enable:

- **BMI-C models** (CFE, TOPMODEL, PET, LGAR) — `NGEN_WITH_BMI_C=OFF`. These are the biggest lever;
  enabling them auto-fetches and builds several more `extern/` submodules. See
  [Enabling Optional Components](#enabling-optional-components).
- **Embedded Python / BMI-Python / t-route routing** — `NGEN_WITH_PYTHON=OFF` (and routing follows,
  since it depends on Python). t-route in particular is a heavy, separately-maintained Python
  package with its own build step; it's out of scope for this guide.
- **BMI-Fortran / Noah-OWP-Modular** — `NGEN_WITH_BMI_FORTRAN=OFF` by default, though `gfortran` *is*
  installed, so this one needs no image changes to enable — see
  [BMI-Fortran / Noah-OWP-Modular](#bmi-fortran--noah-owp-modular).
- **MPI / distributed processing** — `NGEN_WITH_MPI=OFF`. No MPI runtime is installed in the image.
- **macOS-native (non-Docker) debugging** — this guide is Docker/gdb-only. If you'd rather build
  directly on macOS with lldb, see `INSTALL.md` instead; nothing here prevents that, it's just not
  what `.vscode/launch.json` is wired up for.

---

## VSCode Setup

Nothing to install by hand — `.devcontainer/devcontainer.json` already declares the VS Code
extensions and settings for this workspace, applied automatically the first time you reopen the
folder in the container:

- **C/C++** (`ms-vscode.cpptools`) and **C/C++ Extension Pack** (`ms-vscode.cpptools-extension-pack`)
- **CMake Tools** (`ms-vscode.cmake-tools`)
- **CMake language support** (`twxs.cmake`, syntax highlighting for `CMakeLists.txt`)

IntelliSense is driven by `compile_commands.json` (`C_Cpp.default.compileCommands` points at
`cmake_build/compile_commands.json`, generated automatically once you configure) rather than a
hand-maintained include path list — this project has too many include directories
(`include/`, `include/core`, `include/bmi`, `include/realizations`, `include/geojson`, per-`extern/`
model headers, ...) to track by hand, and compile_commands.json always reflects whatever CMake
options are currently active.

`cmake.configureOnOpen` is set to `false` so CMake Tools doesn't race the checked-in tasks below by
auto-configuring its own separate build directory — configure/build here is driven by
`.vscode/tasks.json`, both of which are already checked into the repo.

`.vscode/tasks.json` and `.vscode/launch.json` are also already checked into the repo — no manual
creation step needed.

---

## Building the Project

### Method 1: Using VSCode Tasks (Recommended)

Press `Cmd+Shift+B` (Mac) or `Ctrl+Shift+B` (Linux/Windows) to run the default build task
(**Build ngen (CMake)**), or open the Command Palette → **Tasks: Run Task** to pick a specific one:

- **CMake: Configure** — the default configure, matching ngen CI's `test_unit` job flags:
  `cmake -S . -B cmake_build -DCMAKE_BUILD_TYPE=Debug -DCMAKE_EXPORT_COMPILE_COMMANDS=ON -DBOOST_ROOT=$BOOST_ROOT -DNGEN_WITH_TESTS=ON -DNGEN_WITH_NETCDF=ON -DNGEN_WITH_SQLITE=ON -DNGEN_WITH_UDUNITS=ON -DNGEN_WITH_BMI_C=OFF -DNGEN_WITH_BMI_FORTRAN=OFF -DNGEN_WITH_PYTHON=OFF -DNGEN_WITH_MPI=OFF`
- **Setup: Python venv (numpy<2)** — one-time; creates the container-side `.venv-linux` and
  initializes `extern/pybind11`. Only needed for the Python configure task below
- **CMake: Configure (Full: BMI-C + Python)** — same as the default, but with `NGEN_WITH_BMI_C=ON`
  and `NGEN_WITH_PYTHON=ON` (routing follows). Activates `.venv-linux` itself, so run the setup
  task above once first; see [Enabling Optional Components](#enabling-optional-components)
- **CMake: Configure (BMI-C + Fortran/Noah)** — `NGEN_WITH_BMI_C=ON` plus
  `NGEN_WITH_BMI_FORTRAN=ON`, which brings in Noah-OWP-Modular (Python stays OFF, so no venv
  needed); see [BMI-Fortran / Noah-OWP-Modular](#bmi-fortran--noah-owp-modular)
- **CMake: Configure (BMI-C + UEB)** — BMI-C plus the UEB snow model; needs the two UEB setup tasks
  run once first, see [UEB](#ueb-snow-model-bmi-c)
- **CMake: Configure (Everything)** — all of the above in one build; needs all three setup tasks
  first, see [Everything at once](#everything-at-once)
- **Build ngen (CMake)** — the default build task; builds the `ngen` target
- **Build test_unit (CMake)** — builds the `test_unit` and `test_geopackage` targets
- **Clean ngen** — `rm -rf cmake_build`
- **Rebuild ngen** — Clean, then Build, in one step

The Build tasks depend on **CMake: Configure (if needed)**, an internal helper that runs the
*default* configure only when `cmake_build` has no `CMakeCache.txt` yet. If you already configured
with one of the opt-in tasks, it prints which optional components are on and leaves your
configuration untouched — so `Cmd+Shift+B` after an Everything/Fortran/Python/UEB configure builds
what you configured, rather than reverting to the default flags. To switch configurations, run
**Clean ngen** and then the Configure task you want.

### Method 2: Using the Terminal

```bash
cmake -S . -B cmake_build \
    -DCMAKE_BUILD_TYPE=Debug \
    -DCMAKE_EXPORT_COMPILE_COMMANDS=ON \
    -DBOOST_ROOT=$BOOST_ROOT \
    -DNGEN_WITH_TESTS:BOOL=ON \
    -DNGEN_WITH_NETCDF:BOOL=ON \
    -DNGEN_WITH_SQLITE:BOOL=ON \
    -DNGEN_WITH_UDUNITS:BOOL=ON \
    -DNGEN_WITH_BMI_C:BOOL=OFF \
    -DNGEN_WITH_BMI_FORTRAN:BOOL=OFF \
    -DNGEN_WITH_PYTHON:BOOL=OFF \
    -DNGEN_WITH_MPI:BOOL=OFF

cmake --build cmake_build --target ngen testbmicppmodel -- -j $(nproc)
```

### Build Outputs

- `cmake_build/ngen` — the main driver executable
- `extern/test_bmi_cpp/cmake_build/libtestbmicppmodel.so` — the test BMI-C++ model
  `data/example_realization_config.json` loads by relative path (note: this lands next to the
  source tree under `extern/`, not inside `cmake_build/`); only built if you build the
  `testbmicppmodel` target (the checked-in "Build ngen (CMake)" task already does this)
- `cmake_build/test/test_unit`, `cmake_build/test/test_geopackage`, `cmake_build/test/test_all`,
  etc. — the Google Test suites (only built if you run the corresponding target)
- `cmake_build/partitionGenerator` — the MPI partition-config generator tool

---

## Debugging

Six configurations are defined in `.vscode/launch.json`:

### "Debug ngen (example config)"

The main config. Press `F5`, select it from the Run and Debug panel dropdown if it isn't already
selected. It:
1. Runs the **Build ngen (CMake)** task first (configures + builds if needed)
2. Launches `cmake_build/ngen` under gdb with `cwd` set to the repo root and the same example
   arguments from `README.md`'s [Usage](README.md#usage) section (a subset of the sample
   hydrofabric in `data/`)

### "Debug test_unit"

Builds and debugs the `test_unit` Google Test binary directly (all tests in the suite).

### "Debug test_unit (filtered)"

Same as above, but prompts for a `--gtest_filter` value (e.g.
`HymodKernelTest.TestCalcET0:HymodKernelTest.TestRun0`) so you can target a single test/fixture —
much faster than stepping through the whole suite.

### "Debug test_geopackage"

Builds and debugs the `test_geopackage` Google Test binary (WKB/SQLite/GeoPackage parsing tests).
Its preLaunchTask is the same **Build test_unit (CMake)** task used above, since that task already
builds both `test_unit` and `test_geopackage` together.

### "Debug a test binary"

`test/CMakeLists.txt` defines around twenty separate test executables beyond `test_unit` and
`test_geopackage` (`test_partition`, `test_nexus`, `test_geojson`, `test_mdarray`, `test_logging`,
`test_realization_config`, `test_multilayer`, ...; grep `test/CMakeLists.txt` for `ngen_add_test(`
to see the full, current list, since which ones exist depends on which `NGEN_WITH_*` options are
configured). Rather than hand-writing a launch entry for each one, this single config is
parameterized: it prompts for a **binary/target name** (default `test_unit`) and an optional
**gtest filter** (default `*`, meaning run everything), then builds and debugs whichever one you
typed.

Concretely, to debug `test_partition`:
1. Press `F5`, choose **"Debug a test binary"**
2. VS Code runs its preLaunchTask, **"Build test binary (CMake)"**, which prompts:
   *"CMake target name to build..."* → type `test_partition`, press Enter. This runs
   `cmake --build cmake_build --target test_partition`.
3. VS Code then evaluates the launch config's own `program` path, which prompts a **second time**
   for essentially the same thing: *"Test binary to launch, under cmake_build/test/..."* → type
   `test_partition` again, press Enter.
4. Third prompt, the gtest filter → press Enter to accept the default `*` (run all tests in that
   binary), or type something like `PartitionsParserTest.empty_remote_test` to target one test.
5. gdb launches `cmake_build/test/test_partition --gtest_filter=*` with `cwd` set to the repo root.

The double-prompt in steps 2–3 is a real quirk, not a bug to fix: VS Code resolves
`${input:...}` variables separately per JSON file, so a task-side input (declared in
`.vscode/tasks.json`) and a launch-side input with the same id (declared in `.vscode/launch.json`)
are two independent prompts even though they share a name — just type the same binary name both
times. This trades one extra keystroke for not having to hand-maintain a launch entry per test
target as the suite grows.

### "Attach to running ngen process"

Attaches gdb to an already-running `ngen` process (Command Palette → pick the PID). Useful if you
started the executable manually from a terminal first.

### Setting Breakpoints

- Click in the left margin next to a line number in the gutter, or press `F9` on a line
- A good first breakpoint to try: `src/realizations/catchment/Formulation_Constructors.cpp`, on the
  `return std::make_shared<T>(id, forcing_provider, output_stream);` line inside the
  `create_formulation_constructor` lambda — the example config's catchments all use the `bmi_c++`
  formulation, so this line fires once per catchment as `ngen` constructs its formulations, with
  `id` showing the catchment being built (e.g. `cat-27`)

### Debug Console Commands

```
p myVariable          # print a variable
p myArray[0]@10       # print array elements
p myStruct.member      # print struct members
```

---

## Running with Example Data

The repo ships a small example hydrofabric usable without any extra setup:

```bash
./cmake_build/ngen \
    ./data/catchment_data.geojson "cat-27,cat-52" \
    ./data/nexus_data.geojson "nex-26,nex-34" \
    ./data/example_realization_config.json
```

Run from the repo root (relative paths in both the CLI args and inside `example_realization_config.json`
resolve against the current working directory). This is exactly what the "Debug ngen (example
config)" launch configuration runs under gdb.

`data/README.md` documents the other example configs in that directory (multi-layer, BMI-multi
chains, NetCDF forcing, etc.) — most of the more exotic ones require `NGEN_WITH_BMI_C`/`_PYTHON` to
be on (see below) since they reference CFE/PET/Noah-OWP-Modular formulations.

---

## Enabling Optional Components

### BMI-C models (CFE, TOPMODEL, PET, LGAR) + Python

Run the **Setup: Python venv (numpy<2)** task once, then **CMake: Configure (Full: BMI-C + Python)**
instead of the default one, and build as usual. The setup task does both prerequisites:

```bash
python3 -m venv .venv-linux
.venv-linux/bin/pip install 'numpy<2.0'
git submodule update --init --recursive -- extern/pybind11
```

- **NumPy `<2.0`** must be visible to the interpreter CMake finds — `numpy>=2.0.0` is explicitly
  rejected by `CMakeLists.txt`.
- **`extern/pybind11`** must exist before configure. BMI-C's own submodules (SLoTH, TOPMODEL, CFE,
  PET, LGAR) auto-initialize via `cmake/GitUpdateSubmodules.cmake`, but pybind11 does not.

The venv is named `.venv-linux`, not `.venv`, on purpose: a `.venv` created on a macOS host is
bind-mounted into the container but its binaries can't run there. The configure task activates
`.venv-linux` itself — a Command Palette task doesn't inherit whatever you activated in a
terminal — and refuses to run with a pointer to the setup task if it's missing. CMake binds to the
interpreter present at configure time, so activate the same venv yourself
(`source .venv-linux/bin/activate`) when you later *run* that `ngen` binary.

### MPI / distributed processing

Not installed in the default image. Add to `.devcontainer/Dockerfile`'s apt-get list:

```
libopenmpi-dev openmpi-bin openmpi-common
```

Rebuild the container (Command Palette → **"Dev Containers: Rebuild Container"**), then configure
with `-DNGEN_WITH_MPI:BOOL=ON` and an explicit partition config
(see `doc/DISTRIBUTED_PROCESSING.md`).

### BMI-Fortran / Noah-OWP-Modular

`gfortran` is in the image, so there is nothing to install and no setup task to run — unlike UEB
below, Noah-OWP-Modular has no `find_package` dependency and needs no compiled Boost. Run the
**CMake: Configure (BMI-C + Fortran/Noah)** task, or equivalently:

```bash
cmake -S . -B cmake_build -DCMAKE_BUILD_TYPE=Debug -DCMAKE_EXPORT_COMPILE_COMMANDS=ON \
    -DBOOST_ROOT=$BOOST_ROOT -DNGEN_WITH_TESTS:BOOL=ON -DNGEN_WITH_NETCDF:BOOL=ON \
    -DNGEN_WITH_SQLITE:BOOL=ON -DNGEN_WITH_UDUNITS:BOOL=ON -DNGEN_WITH_BMI_C:BOOL=ON \
    -DNGEN_WITH_BMI_FORTRAN:BOOL=ON -DNGEN_WITH_PYTHON:BOOL=OFF -DNGEN_WITH_MPI:BOOL=OFF

cmake --build cmake_build --target ngen -- -j $(nproc)
```

`NGEN_WITH_PYTHON` is deliberately OFF here: Noah needs nothing from it, and turning it on makes
configure fail with `Could NOT find Python (missing: Python_NumPy_INCLUDE_DIRS NumPy)` unless a
`numpy<2.0` virtualenv is active *in the shell the task runs in* — which a Command Palette task
does not inherit. Combine Python with Fortran only from a terminal where you've activated the venv
yourself.

What happens under the hood, all driven by `NGEN_WITH_BMI_FORTRAN=ON`:

- `extern/iso_c_fortran_bmi` is added as a subdirectory (`libiso_c_bmi.so`) — the `iso_c_binding`
  middleware `Bmi_Fortran_Adapter` calls through. Note the `BMI_FORTRAN_ISO_C_LIB_DIR`/`_NAME`
  entries in the configure summary print as `OFF`; that's cosmetic (they're declared with
  `option()`, which coerces a string default to a bool) and doesn't affect linkage, which goes
  through the `iso_c_bmi` CMake target.
- `NGEN_WITH_EXTERN_NOAH_OWP_MODULAR` defaults ON whenever `NGEN_WITH_BMI_FORTRAN` is ON
  (`cmake_dependent_option` in the top-level `CMakeLists.txt`), so Noah builds as `libsurfacebmi.so`
  at `extern/noah-owp-modular/cmake_build/` — exactly the path the shipped realization configs
  expect. Pass `-DNGEN_WITH_EXTERN_NOAH_OWP_MODULAR:BOOL=OFF` for Fortran BMI without Noah.
- The nested `extern/noah-owp-modular/noah-owp-modular` submodule is cloned during configure by
  `add_external_subdirectory(... GIT_UPDATE ...)`, so no manual `git submodule update` is needed
  (network access at configure time is, though).

BMI-C is kept ON in the task because the ready-made Noah realization configs are `bmi_multi`
formulations that also use SLoTH, PET and CFE. To verify the whole stack the way ngen's own
`.github/workflows/module_integration.yml` job does:

```bash
./cmake_build/ngen data/catchment_data.geojson "cat-27" data/nexus_data.geojson "nex-26" \
    data/example_bmi_multi_realization_config_w_noah_pet_cfe.json
```

That should end with `Finished 720 timesteps.` and write `output_dir/cat-27.csv` (Noah's `QINSUR`
feeding CFE's runoff columns) plus `output_dir/nex-26_output.csv`. A pile of
`WARN: Unit conversion unsuccessful ... out_units value none` lines and one
`surface_partitioning_scheme` deprecation warning are expected and harmless.

> **Caveat:** build the `ngen` target, not the test suites, with this configure. `test_bmi_fortran`
> does not compile — `test/realizations/catchments/Bmi_Fortran_Formulation_Test.cpp` constructs
> `forcing_params` with four arguments while the constructor in `include/forcing/AorcForcing.hpp`
> requires five (`bool enable_cache`, no default). This is pre-existing and not Fortran-specific:
> `Bmi_C_Formulation_Test.cpp` has the identical stale call. The adapter and formulation code
> themselves are fine, as the simulation run above demonstrates.

### UEB (snow model, BMI-C++)

UEB (`extern/ueb-bmi`, a pinned submodule — currently pinned at commit
`5574a89ef2392dcd5d1301b8073d4dc446b934d3`) is loaded through the `bmi_c++` formulation —
`Bmi_Cpp_Adapter`/`bmi_c++` support is compiled into ngen unconditionally, so there's no
`NGEN_WITH_BMI_CXX` flag to flip; enabling it is just `-DNGEN_WITH_EXTERN_UEB:BOOL=ON`. It pulls in
two dependencies the default image doesn't have, neither baked into the Dockerfile since UEB is
the first component in this repo to need them:

1. **A real Boost build with the `serialization` component.** The default image only unpacks
   Boost headers to `$BOOST_ROOT` — no other extern model here links a compiled Boost library.
   Inside the container:

   ```bash
   cd $BOOST_ROOT
   ./bootstrap.sh --with-libraries=serialization
   ./b2 install --prefix=/opt/boost-built
   ```

   Configure with `-DBOOST_ROOT=/opt/boost-built` (or add it to `-DCMAKE_PREFIX_PATH` alongside
   `$BOOST_ROOT`) so both the headers and the compiled library resolve.

2. **EWTS** (`extern/ewts`, a pinned submodule of NGWPC's "Error and Warning Trapping System") — a
   hard, non-optional dependency of UEB's `src/CMakeLists.txt` (`find_package(ewts CONFIG
   REQUIRED)`; there's no flag to disable it at the pinned UEB commit). EWTS itself needs
   `gfortran` (already in the image) and MPI dev libraries (its ngen bridge does
   `find_package(MPI REQUIRED COMPONENTS CXX)`):

   ```bash
   apt-get update && apt-get install -y --no-install-recommends libopenmpi-dev openmpi-bin
   ```

   Build and install it with the ngen bridge enabled. `extern/ewts/INSTALL.md` (upstream) says to
   configure from `-S runtime`, but at this repo's pinned commit that fails: `runtime/CMakeLists.txt`
   has no `project()` call of its own, so `CMAKE_PROJECT_VERSION` is unset and
   `write_basic_package_version_file` errors out. The real `project(ewts VERSION ...)` lives one
   level up, in `extern/ewts/CMakeLists.txt`, which `add_subdirectory(runtime)`s — configure from
   there instead. Separately, the ngen bridge (`extern/ewts/integrations/ngen`) `#include`s
   `boost/property_tree/...` but never calls `find_package(Boost)`, so its headers need to be added
   explicitly via `CMAKE_CXX_FLAGS`:

   ```bash
   cmake -B /tmp/ewts-build -S extern/ewts -DCMAKE_BUILD_TYPE=Release -DEWTS_WITH_NGEN=ON \
         -DCMAKE_CXX_FLAGS="-I${BOOST_ROOT}"
   cmake --build /tmp/ewts-build -j
   cmake --install /tmp/ewts-build --prefix /opt/ewts
   ```

   EWTS also packages a Python wheel as part of this build; upstream docs say it expects Python
   >= 3.11, though in practice it has built fine against the default image's Ubuntu 22.04 `python3`
   (3.10) — if it does fail for you, that's the first thing to suspect, and you'd need a venv with
   a newer interpreter active before configuring.

With both built, configure ngen itself with `-DNGEN_WITH_EXTERN_UEB:BOOL=ON` plus
`-Dewts_DIR=/opt/ewts/lib/cmake/ewts` (or add `/opt/ewts` to `-DCMAKE_PREFIX_PATH`). Omitting
`ewts_DIR`/`CMAKE_PREFIX_PATH` fails the configure fast with a clear "the 'ewts' package was not
found" error rather than a confusing `find_package` failure deep in `extern/ueb-bmi`.

With `NGEN_WITH_NETCDF:BOOL=ON` (the default configure's setting), two more flags are needed:

```bash
cmake -DCMAKE_BUILD_TYPE=Debug \
      -DCMAKE_EXPORT_COMPILE_COMMANDS=ON \
      -DBOOST_ROOT=/opt/boost-built \
      -DNGEN_WITH_TESTS:BOOL=ON \
      -DNGEN_WITH_NETCDF:BOOL=ON \
      -DNGEN_WITH_SQLITE:BOOL=ON \
      -DNGEN_WITH_UDUNITS:BOOL=ON \
      -DNGEN_WITH_BMI_C:BOOL=ON \
      -DNGEN_WITH_PYTHON:BOOL=OFF \
      -DNGEN_WITH_EXTERN_UEB:BOOL=ON \
      -Dewts_DIR=/opt/ewts/lib/cmake/ewts \
      -DCMAKE_POLICY_DEFAULT_CMP0057=NEW \
      -DNETCDF_C_LIB_DIR=/usr/lib/$(gcc -dumpmachine) \
      -DNETCDF_C_INCLUDE_DIR=/usr/include \
      -B cmake_build -S .
```

`NGEN_WITH_PYTHON` is OFF here for the same reason as in the Noah section above: UEB is a `bmi_c++`
model that needs nothing from Python, and `ON` would fail configure with
`Could NOT find Python (missing: Python_NumPy_INCLUDE_DIRS NumPy)` unless a `numpy<2.0` venv is
active in the shell the task runs in. Note that a venv created on a macOS host (e.g. a `.venv/` in
the repo, which is bind-mounted into the container) is *not* usable inside the Linux container —
it would have to be created in the container.

The above cmake configuration command for ngen is also wired up as the **CMake: Configure (BMI-C +
UEB)** VS Code task (with matching **Setup: Build Boost with serialization (UEB)** /
**Setup: Build and install EWTS (UEB)** tasks for steps 1–2 above) — run those two setup tasks
(BOOST and EWTS) once, then this configure task (ngen), then the usual **Build ngen (CMake)** task.

### Everything at once

For a runtime with every model component this image supports, run the three setup tasks once, in
this order, then the **CMake: Configure (Everything)** task:

1. **Setup: Python venv (numpy<2)** — `.venv-linux` + `extern/pybind11`
2. **Setup: Build Boost with serialization (UEB)** — `/opt/boost-built`
3. **Setup: Build and install EWTS (UEB)** — `/opt/ewts`

The configure task checks all three up front and names the missing one rather than failing inside
CMake. It uses `/opt/boost-built` as `BOOST_ROOT` throughout: UEB needs that compiled Boost, and it
serves the rest of the build too. Then build — **Build ngen (CMake)** keeps this configuration, or
from a terminal, to get the two extra model libraries in one go:

```bash
cmake --build cmake_build --target ngen bmiuebcxx surfacebmi -j $(nproc)
```

`./cmake_build/ngen --info` should then report `BMI_FORTRAN: ON`, `BMI_C: ON`, `PYTHON: ON`,
`ROUTING: ON` and extern models `SLOTH`, `TOPMODEL`, `CFE`, `PET`, `NOAH_OWP_MODULAR`, `UEB` all ON.

Two things this does **not** include:

- **MPI** — no runtime in the image; see [MPI / distributed processing](#mpi--distributed-processing).
- **SMP / SoilFreezeThaw** — `NGEN_WITH_EXTERN_SMP` / `NGEN_WITH_EXTERN_SFT` are independent options
  that default OFF and aren't covered by any task here. Add `-DNGEN_WITH_EXTERN_SMP:BOOL=ON
  -DNGEN_WITH_EXTERN_SFT:BOOL=ON` to the configure command if you need them (untested in this
  setup).

### BMI wrapper tooling (model I/O introspection)

A way to ask a model what it actually consumes and produces, rather than reading
`extern/cfe/cfe/src/bmi_cfe.c` (or Noah-OWP-Modular's
`extern/noah-owp-modular/noah-owp-modular/bmi/bmi_noahowp.f90`) to find out. It works by importing a
Python BMI wrapper for the model and querying it live. CFE's half is fully orthogonal to every
configure above (`extern/cfe` is its own standalone CMake project); Noah's half is not — see step 3
below.

This is a developer aid. ngen still runs these models through its own C/Fortran BMI adapters;
nothing installed here is imported by the `ngen` binary, and it does not require
`NGEN_WITH_PYTHON=ON`.

Each wrapper is an extension that links its model's shared library, so the order is fixed:

1. **Setup: Python venv (numpy<2)** — `.venv-linux` (skip if you already have it)
2. **Setup: Build CFE shared library** — `extern/cfe/cmake_build/libcfebmi.so`
3. **Setup: Build Noah-OWP-Modular shared library** — `extern/noah-owp-modular/cmake_build/libsurfacebmi.so`
   (reconfigures the same `cmake_build` every configure task uses, with the Fortran configure's
   flags, then builds only `surfacebmi` — Noah's own `CMakeLists.txt` only builds correctly as part
   of the main project, unlike CFE, and its build output always lands at a fixed path under
   `extern/` regardless of which build dir triggered the configure, so there is no isolated build
   dir to use instead. Reverts `cmake_build`'s active configuration to the Fortran flags if it was
   something else; **Clean ngen** first for a from-scratch reconfigure.)
4. **Setup: Install BMI Python wrappers** — pip installs into `.venv-linux`, one wrapper at a time,
   gated on each wrapper's own shared library already existing (a missing Noah lib only skips
   Noah's wrapper, not CFE's)

Then **BMI: Show model input/output requirements**, or from a terminal:

```bash
make -C commands bmi-io
make -C commands bmi-io MODEL=noah CONFIG=data/gauge_01073000/NOAH/cat-11223.input
make -C commands bmi-io REALIZATION=data/example_bmi_multi_realization_config_w_noah_pet_cfe.json
```

The `REALIZATION=` form cross-checks a realization config's `variables_names_map` against the
model's real variables, flags typos with a "did you mean", and exits non-zero on a genuine error.
Full details, and how to add wrappers for other models, in
[tools/bmi-wrappers/README.md](tools/bmi-wrappers/README.md).

---

## Troubleshooting

#### 1. CMake configure fails: `add_subdirectory` / `googletest` errors, or "the source directory ... does not contain a CMakeLists.txt"

**Cause**: `test/googletest` isn't initialized. Unlike most other `extern/` submodules, this one
has no automatic `git submodule update` call in `test/CMakeLists.txt` — it must already exist
before CMake configures at all.

**Solution**: This is already handled by `postCreateCommand` in `.devcontainer/devcontainer.json`
the first time the container is created. If you hit this anyway (e.g. after a manual
`git submodule deinit`), run:
```bash
git submodule update --init --recursive -- test/googletest
```

#### 2. CMake configure fails: git "detected dubious ownership in repository"

**Cause**: The bind-mounted repo is owned by your host user, but the container runs as root; recent
git versions refuse to operate on a directory it doesn't own — which breaks the `git submodule
update` / `git rev-parse HEAD` calls ngen's own `CMakeLists.txt` makes during configure
(`cmake/GitUpdateSubmodules.cmake`).

**Solution**: Already handled by `postCreateCommand`'s
`git config --global --add safe.directory ${containerWorkspaceFolder}`. If you hit this outside
that flow (e.g. a manually-created container), run the same command yourself inside the container.

#### 3. CMake configure fails: `Could NOT find Boost` or version too old

**Cause**: You're not inside the devcontainer (e.g. running `cmake` on the host Mac). Boost 1.79.0
is only guaranteed at `$BOOST_ROOT` inside this project's devcontainer image.

**Solution**: Make sure the VS Code status bar shows you're connected to the Dev Container before
building.

#### 3b. CMake configure fails: `Found unsuitable version "0.0.0"` with `version.hpp cannot be read`

```text
file STRINGS file "/opt/boost-built/include/boost/version.hpp" cannot be read.
Could NOT find Boost: Found unsuitable version "0.0.0", but required is at least "1.79.0"
  (found /opt/boost-built/include, )
```

**Cause**: A *partial* Boost installation. `b2 install` copies headers roughly alphabetically, so
an interrupted or failed **Setup: Build Boost with serialization (UEB)** task leaves early-alphabet
headers (`config.hpp`) in place but never writes `version.hpp`. FindBoost locates the include
directory, then can't determine a version from it. Two ways it reaches a configure that isn't even
UEB-related: the UEB configure task points `BOOST_ROOT` there by design, and all configure tasks
share one `cmake_build`, so a cached `Boost_INCLUDE_DIR` from a previous UEB configure can be
picked up by a later one.

**Solution**: Run **Clean ngen** to drop the stale cache, then re-run your configure task. If you
do want UEB, re-run the Boost setup task and let it finish — it now verifies `version.hpp` landed
and fails loudly if it didn't. The configure tasks also check this up front, so you get a message
naming the task to run instead of the CMake error above.

#### 4. CMake configure fails: `Could NOT find Python (missing: Python_NumPy_INCLUDE_DIRS NumPy)`

**Cause**: An `NGEN_WITH_PYTHON=ON` configure ran without a `numpy<2.0` virtualenv active in *the
shell the task ran in*. A task launched from the Command Palette does **not** inherit a venv you
activated in an integrated terminal. Note also that a `.venv/` created on a macOS host is
bind-mounted into the container but its binaries can't execute there.

**Solution**: Run the **Setup: Python venv (numpy<2)** task once — it creates a container-side
`.venv-linux` and initializes `extern/pybind11`. The **CMake: Configure (Full: BMI-C + Python)**
task activates that venv itself, and refuses to run with a message pointing at the setup task if
it's missing. Activate it yourself (`source .venv-linux/bin/activate`) before *running* an ngen
built with embedded Python, since CMake binds to the interpreter present at configure time.

Only the Python task needs this. The **BMI-C + Fortran/Noah** and **BMI-C + UEB** tasks have
`NGEN_WITH_PYTHON=OFF` — neither model needs Python — so they run with no venv at all.

#### 5. Breakpoints aren't hit / gdb can't attach

**Cause**: Docker's default seccomp profile blocks the `ptrace` syscall gdb needs.

**Solution**: Already handled by `--cap-add=SYS_PTRACE` / `--security-opt seccomp=unconfined` in
`.devcontainer/devcontainer.json`'s `runArgs` — if you hit this, check you're running the container
VS Code built from this repo's `.devcontainer/`, not some other image.

#### 6. IntelliSense not working / red squiggles everywhere

**Solution**:
1. Make sure `cmake_build/compile_commands.json` exists — run the **CMake: Configure** task at
   least once
2. Command Palette → **"C/C++: Reset IntelliSense Database"**
3. Command Palette → **"Developer: Reload Window"**

#### 7. `ngen` exits immediately with a usage message

**Cause**: The driver takes 5 positional args minimum (catchment data, catchment subset, nexus
data, nexus subset, realization config), plus optional partition config /
`--subdivided-hydrofabric`. If you're using the debug launch config, this shouldn't happen — `args`
is already set correctly. If running manually, see [Running with Example Data](#running-with-example-data)
or `README.md`'s [Usage](README.md#usage) section.

---

#### 8. `ImportError: libcfebmi.so: cannot open shared object file`

**Cause**: The Python CFE wrapper resolves `libcfebmi.so` through an RPATH baked in when it was
installed, pointing at `extern/cfe/cmake_build`. Deleting or moving that directory — a
`make -C commands clean` does not touch it, but removing `extern/cfe/cmake_build` by hand does —
breaks the installed module.

**Solution**: Rebuild the library and reinstall the wrapper, so the RPATH is re-baked:
```bash
make -C commands build-cfe-lib
make -C commands install-bmi-wrappers
```
Setting `LD_LIBRARY_PATH` also works, but reinstalling is preferred — it keeps the module
self-contained for every future shell.

---

#### 9. Installing `pymt_noah_owp` fails while compiling `bmi_interoperability.f90`, or it imports but every call segfaults

**Cause**: `pymt_noah_owp`'s Cython wrapper compiles its own `bmi_interoperability.f90` shim against
the `.mod` files under `extern/noah-owp-modular/cmake_build/mod/` (`bmif_2_0.mod`, `bminoahowp.mod`).
Fortran module files are compiler- and version-specific — if the gfortran used to build the wrapper
differs from the one that built `libsurfacebmi.so`, the mismatch either fails at compile time with an
unreadable/incompatible `.mod` error, or — worse — compiles but produces a binary whose ABI
assumptions don't match the library, which can crash or silently misread data at runtime instead of
failing cleanly.

**Solution**: Rebuild both with the same toolchain — inside the devcontainer, `build-noah-lib` and
`install-bmi-wrappers` both use whatever `gfortran`/`FC` is on `PATH`, so as long as you haven't
mixed a host-built library with a container-built wrapper (or vice versa), this shouldn't happen. If
it does, `make -C commands build-noah-lib` again before reinstalling the wrapper.

---

## Project Structure (VS Code-relevant files)

```
ngen/
├── .devcontainer/
│   ├── Dockerfile              # Ubuntu 22.04 image: build tools, NetCDF/UDUNITS2/SQLite3, Boost 1.79.0, gdb
│   └── devcontainer.json       # VS Code extensions/settings, ptrace/seccomp runArgs, submodule init
├── .vscode/
│   ├── settings.json           # IntelliSense via compile_commands.json, disables CMake Tools auto-configure
│   ├── tasks.json              # Configure (default + full) / Build / Clean / Rebuild tasks
│   ├── launch.json             # gdb debug configs for ngen and test_unit
│   └── extensions.json         # Recommended extensions
├── CMakeLists.txt              # Top-level build: options table, finds Boost/NetCDF/UDUNITS/SQLite/Python
├── test/CMakeLists.txt         # test_unit / test_integration / test_all / test_geopackage / ... targets
├── data/                       # Example hydrofabric + realization configs used for the debug launch config
└── ngen-vscode-dev-setup.md    # This file
```

---

## Quick Start Checklist

- [ ] Install Docker Desktop and the VS Code Dev Containers extension
- [ ] Open this folder in VS Code → **"Dev Containers: Reopen in Container"**
- [ ] Build: `Cmd/Ctrl+Shift+B`, or Command Palette → Tasks: Run Task → **Build ngen (CMake)**
- [ ] Smoke test: `./cmake_build/ngen ./data/catchment_data.geojson "cat-27,cat-52" ./data/nexus_data.geojson "nex-26,nex-34" ./data/example_realization_config.json`
- [ ] Set a breakpoint and press `F5`, selecting **"Debug ngen (example config)"**
- [ ] Run the unit tests: Tasks: Run Task → **Build test_unit (CMake)**, then
      `./cmake_build/test/test_unit`
