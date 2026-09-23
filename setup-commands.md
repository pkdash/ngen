# ngen Setup Commands (Quick Reference)

The ordered VS Code tasks and terminal commands for each supported build configuration. For the
*why* behind any of it — what the image provides, why Python is OFF for Noah/UEB, troubleshooting —
see [ngen-vscode-dev-setup.md](ngen-vscode-dev-setup.md).

Everything below runs **inside the devcontainer**, from the repo root. Task names are run via
Command Palette → **Tasks: Run Task**, and match [.vscode/tasks.json](.vscode/tasks.json) exactly.

Every task has an equivalent `make` target in [commands/Makefile](commands/Makefile), which is where
the CMake flag sets actually live — the VS Code tasks are thin wrappers around it, so the two cannot
drift. If you prefer the terminal, or are not using VS Code at all, use the make target instead of
the task; the two do exactly the same thing.

```bash
make -C commands          # list every target
make -C commands <target>
```

The Makefile resolves the repo root from its own location, so `make -C commands` works no matter
which directory you are in.

## First time in the container

1. Open this folder in VS Code → Command Palette → **"Dev Containers: Reopen in Container"**.
   `postCreateCommand` initializes `test/googletest` and sets `git safe.directory` for you.
2. Pick one configuration below and run its steps in order.

> **Switching configurations:** all configure tasks share one `cmake_build` directory. Run
> **Clean ngen** before switching, or a stale `CMakeCache.txt` will be reused — see
> [Troubleshooting #3b](ngen-vscode-dev-setup.md#3b-cmake-configure-fails-found-unsuitable-version-000-with-versionhpp-cannot-be-read).

## Configuration summary

| Configuration | Setup tasks (once) | Configure task | make target | Build targets |
| --- | --- | --- | --- | --- |
| Default (CI-matched, lean) | — | **CMake: Configure** | `configure` | `ngen testbmicppmodel` |
| BMI-C + Python | **Setup: Python venv (numpy<2)** | **CMake: Configure (Full: BMI-C + Python)** | `configure-python` | `ngen` |
| BMI-C + Fortran/Noah | — | **CMake: Configure (BMI-C + Fortran/Noah)** | `configure-fortran` | `ngen` |
| BMI-C + UEB | **Setup: Build Boost with serialization (UEB)**, then **Setup: Build and install EWTS (UEB)** | **CMake: Configure (BMI-C + UEB)** | `configure-ueb` | `ngen bmiuebcxx` |
| Everything | all three: Python venv → Boost → EWTS | **CMake: Configure (Everything)** | `configure-all` | `ngen bmiuebcxx surfacebmi` |

The setup tasks map to `setup-venv`, `setup-boost` and `setup-ewts`; the build tasks to `build`,
`build-tests` and `build-test TARGET=<name>`; and Clean/Rebuild to `clean` and `rebuild`.

---

### Default (CI-matched, lean)

1. Task: **CMake: Configure**
2. Task: **Build ngen (CMake)** (or `Cmd/Ctrl+Shift+B`)

All of it from a terminal instead: `make -C commands configure && make -C commands build`

Verify:
```bash
./cmake_build/ngen \
    ./data/catchment_data.geojson "cat-27,cat-52" \
    ./data/nexus_data.geojson "nex-26,nex-34" \
    ./data/example_realization_config.json
```

### BMI-C + Python

1. Task: **Setup: Python venv (numpy<2)** — once only; creates `.venv-linux` and initializes `extern/pybind11`
2. Task: **CMake: Configure (Full: BMI-C + Python)**
3. Task: **Build ngen (CMake)**

From a terminal instead:

```bash
make -C commands setup-venv        # once only
make -C commands configure-python
make -C commands build TARGETS=ngen
```

Verify: the Default example-data run above, but `source .venv-linux/bin/activate` first.

### BMI-C + Fortran/Noah

No setup task — `gfortran` is already in the image.

1. Task: **CMake: Configure (BMI-C + Fortran/Noah)**
2. Task: **Build ngen (CMake)**

From a terminal instead:

```bash
make -C commands configure-fortran
make -C commands build TARGETS=ngen
```

Verify:
```bash
./cmake_build/ngen data/catchment_data.geojson "cat-27" data/nexus_data.geojson "nex-26" \
    data/example_bmi_multi_realization_config_w_noah_pet_cfe.json
```
Should end with `Finished 720 timesteps.` and write `output_dir/cat-27.csv` and
`output_dir/nex-26_output.csv`. Unit-conversion `WARN` lines are expected.

### BMI-C + UEB

1. Task: **Setup: Build Boost with serialization (UEB)** — once only; produces `/opt/boost-built`
2. Task: **Setup: Build and install EWTS (UEB)** — once only; produces `/opt/ewts`
3. Task: **CMake: Configure (BMI-C + UEB)**
4. Task: **Build ngen (CMake)**

From a terminal instead:

```bash
make -C commands setup-boost       # once only
make -C commands setup-ewts        # once only
make -C commands configure-ueb
make -C commands build TARGETS="ngen bmiuebcxx"
```

Verify: the Default example-data run above.

### Everything

Run the three setup tasks once, in this order:

1. Task: **Setup: Python venv (numpy<2)**
2. Task: **Setup: Build Boost with serialization (UEB)**
3. Task: **Setup: Build and install EWTS (UEB)**
4. Task: **CMake: Configure (Everything)** — checks all three up front and names any missing one
5. Task: **Build ngen (CMake)**, or from a terminal to get the extra model libraries in one go:

   ```bash
   make -C commands build TARGETS="ngen bmiuebcxx surfacebmi"
   ```

The whole sequence from a terminal:

```bash
make -C commands setup-venv setup-boost setup-ewts
make -C commands configure-all
make -C commands build TARGETS="ngen bmiuebcxx surfacebmi"
```

Verify:
```bash
./cmake_build/ngen --info
```
Should report `BMI_FORTRAN: ON`, `BMI_C: ON`, `PYTHON: ON`, `ROUTING: ON`, and extern models
`SLOTH`, `TOPMODEL`, `CFE`, `PET`, `NOAH_OWP_MODULAR`, `UEB` all ON.

---

## Notes

- `Cmd/Ctrl+Shift+B` runs **Build ngen (CMake)** → `make -C commands build`; it only auto-configures
  with the default flags when `cmake_build/CMakeCache.txt` is absent, so it preserves an opt-in
  configure. It prints the active optional components first — `make -C commands show-config` on its
  own does the same.
- Tests: task **Build test_unit (CMake)** / `make -C commands build-tests`, then
  `./cmake_build/test/test_unit`. For one suite: `make -C commands build-test TARGET=test_partition`.
- `commands/Makefile` holds the CMake flags; the VS Code tasks only call it. Change flags there.
- With the Fortran configure, build the `ngen` target only — `test_bmi_fortran` does not compile
  (pre-existing; see [the caveat](ngen-vscode-dev-setup.md#bmi-fortran--noah-owp-modular)).
- Running a Python-enabled `ngen` needs `source .venv-linux/bin/activate` first; CMake binds to the
  interpreter present at configure time.
- Other example configs are documented in [data/README.md](data/README.md); debug configurations in
  [.vscode/launch.json](.vscode/launch.json).
- Not covered here: MPI, and the `NGEN_WITH_EXTERN_SMP` / `NGEN_WITH_EXTERN_SFT` models.
