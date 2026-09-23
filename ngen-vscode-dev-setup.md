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
- **BMI-Fortran** — `NGEN_WITH_BMI_FORTRAN=OFF`. No Fortran compiler is installed in the image.
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
- **CMake: Configure (Full: BMI-C + Python)** — same, but with `NGEN_WITH_BMI_C=ON` and
  `NGEN_WITH_PYTHON=ON`; see [Enabling Optional Components](#enabling-optional-components) before
  using this one
- **Build ngen (CMake)** — the default build task; re-runs Configure first (cheap/idempotent), then
  builds the `ngen` target
- **Build test_unit (CMake)** — configures, then builds the `test_unit` and `test_geopackage`
  targets
- **Clean ngen** — `rm -rf cmake_build`
- **Rebuild ngen** — Clean, then Build, in one step

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

Run the **CMake: Configure (Full: BMI-C + Python)** task instead of the default one, then build as
usual. The `extern/pybind11` submodule must exist first (BMI-C's own submodules — SLoTH, TOPMODEL,
CFE, PET, LGAR — auto-initialize themselves during configure via
`cmake/GitUpdateSubmodules.cmake`, but pybind11 does not):

```bash
git submodule update --init --recursive -- extern/pybind11
```

Building `NGEN_WITH_PYTHON=ON` requires NumPy `<2.0` visible to the Python interpreter CMake finds
(`numpy>=2.0.0` is explicitly rejected by `CMakeLists.txt`). Install it in a venv and activate it
*before* configuring, since CMake binds to whichever interpreter is active at configure time and
the same venv must stay active when you later run `ngen`:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install 'numpy<2.0'
```

### MPI / distributed processing

Not installed in the default image. Add to `.devcontainer/Dockerfile`'s apt-get list:

```
libopenmpi-dev openmpi-bin openmpi-common
```

Rebuild the container (Command Palette → **"Dev Containers: Rebuild Container"**), then configure
with `-DNGEN_WITH_MPI:BOOL=ON` and an explicit partition config
(see `doc/DISTRIBUTED_PROCESSING.md`).

### BMI-Fortran

Not installed in the default image. Add `gfortran` to the Dockerfile's apt-get list, rebuild the
container, then configure with `-DNGEN_WITH_BMI_FORTRAN:BOOL=ON`.

### UEB (snow model, BMI-C++)

UEB (`extern/ueb-bmi`, a pinned submodule) is loaded through the `bmi_c++` formulation —
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
   `gfortran` and MPI dev libraries (its ngen bridge does `find_package(MPI REQUIRED COMPONENTS
   CXX)`):

   ```bash
   apt-get update && apt-get install -y --no-install-recommends gfortran libopenmpi-dev openmpi-bin
   ```

   Build and install it with the ngen bridge enabled (see `extern/ewts/INSTALL.md` for the
   upstream instructions):

   ```bash
   cmake -B /tmp/ewts-build -S extern/ewts/runtime -DCMAKE_BUILD_TYPE=Release -DEWTS_WITH_NGEN=ON
   cmake --build /tmp/ewts-build -j
   cmake --install /tmp/ewts-build --prefix /opt/ewts
   ```

   EWTS also packages a Python wheel as part of this build and expects Python >= 3.11; the
   default image's `python3` is Ubuntu 22.04's 3.10, so that step may need its own venv with a
   newer interpreter if it fails.

With both built, configure ngen itself with `-DNGEN_WITH_EXTERN_UEB:BOOL=ON` plus
`-Dewts_DIR=/opt/ewts/lib/cmake/ewts` (or add `/opt/ewts` to `-DCMAKE_PREFIX_PATH`). Omitting
`ewts_DIR`/`CMAKE_PREFIX_PATH` fails the configure fast with a clear "the 'ewts' package was not
found" error rather than a confusing `find_package` failure deep in `extern/ueb-bmi`.

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

#### 4. CMake configure fails: `Could NOT find Python` / NumPy version errors

**Cause**: You ran the "Full: BMI-C + Python" configure task without first setting up a venv with
`numpy<2.0` active (see [Enabling Optional Components](#enabling-optional-components)).

**Solution**: Activate a venv with the right NumPy version, then re-run the Configure task from an
integrated terminal that has that venv active.

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
