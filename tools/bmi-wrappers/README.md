# Python BMI wrappers (introspection tooling)

Answers "what does this model actually need, and what does it produce?" by asking
the compiled model itself.

ngen keeps running these models through its own C/Fortran BMI adapters. Nothing
here is imported by the `ngen` binary, and installing these packages does not
change how ngen behaves — `.venv-linux` simply gains some extra modules.

## Why there is no lookup table

These wrapper packages ship no static metadata: no variable list, no units table.
That is deliberate. The authoritative source for CFE's I/O contract is
`extern/cfe/cfe/src/bmi_cfe.c` (Noah-OWP-Modular's is
`extern/noah-owp-modular/noah-owp-modular/bmi/bmi_noahowp.f90`), and a checked-in
copy of either would drift silently. So every fact here is queried live, which
means a model must be **initialized with a real config** before it can be asked
anything.

## Prerequisites, in order

Each wrapper is a Cython extension that links the model's BMI shared library at
build time and `dlopen`s it at import time. So the library must exist first:

```sh
make -C commands setup-venv            # once: .venv-linux with numpy<2
make -C commands build-cfe-lib         # extern/cfe -> libcfebmi.so + cfebmi.pc
make -C commands build-noah-lib        # full ngen configure -> extern/noah-owp-modular/cmake_build/libsurfacebmi.so
make -C commands install-bmi-wrappers  # pip install into .venv-linux
```

`build-noah-lib` reconfigures the same `cmake_build` every other configure
target uses, with `configure-fortran`'s flags, rather than configuring
`extern/noah-owp-modular` standalone the way `build-cfe-lib` configures
`extern/cfe`: that subdirectory's own `CMakeLists.txt` only links `iso_c_bmi`
and skips NetCDF discovery inside its `NGEN_IS_MAIN_PROJECT` branch, so a
standalone configure hits the other, broken branch instead (it requires
NetCDF and has a non-functional `surfacebmi.pc.in`). There is no isolated
build directory to use instead: `extern/noah-owp-modular` and
`extern/iso_c_fortran_bmi`'s own `CMakeLists.txt` files always place their
build output at a fixed path under `extern/` regardless of which top-level
build directory triggered the configure, so a separate directory would not
actually be isolated from `cmake_build` — just an illusion of isolation. If
`cmake_build` was configured differently before (e.g. `configure-python`),
`build-noah-lib` reverts it to the Fortran flags, the same as running any
other `configure-*` target would; run `make -C commands clean` first for a
from-scratch reconfigure.

`install-bmi-wrappers` installs each wrapper individually, gated on its own
shared library already existing — not one combined
`pip install -r requirements.txt` — so a missing Noah lib only skips Noah's
wrapper (with a note on how to build it) rather than blocking CFE's install
too, and vice versa. It exports `CFE_ROOT` and `CFE_LIB_DIR`, which is what
`pymt_cfe`'s `setup.py` looks for (it also falls back to `pkg-config cfebmi`).
Note its `$CFE_ROOT/build` fallback does not match ngen's `cmake_build`, so
`CFE_LIB_DIR` has to be passed explicitly — the Makefile target does that. It
likewise exports `NOAH_ROOT`, `NOAH_LIB_DIR`, and `NOAH_MOD_DIR` for
`pymt_noah_owp`'s `setup.py`, which (unlike CFE's) has no `pkg-config`
fallback, so these three env vars are its only discovery route.

The installed extensions carry an RPATH pointing at their respective build
dirs (`extern/cfe/cmake_build`, `extern/noah-owp-modular/cmake_build`), so
`import pymt_cfe`/`import pymt_noah_owp` work without `LD_LIBRARY_PATH` being
set — for Noah this required a small patch to `pymt_noah_owp`'s `setup.py`
upstream (`pkdash/BMI`, tag `pymt_noah_owp-v0.2.0`),
mirroring what `pymt_cfe`'s `setup.py` already did. **If you move or delete a
build directory, reinstall the wrapper** rather than patching your
environment.

All of this runs inside the devcontainer. `libcfebmi.so`/`libsurfacebmi.so` are
ELF objects and `.venv-linux` is not executable from a macOS host.

## Usage

```sh
make -C commands bmi-io                       # CFE, registry's sample config
make -C commands bmi-io MODEL=cfe CONFIG=path/to/cat-N_bmi_config_cfe.txt
make -C commands bmi-io MODEL=noah CONFIG=data/gauge_01073000/NOAH/cat-11223.input
make -C commands bmi-io REALIZATION=data/example_bmi_multi_realization_config_w_noah_pet_cfe.json
```

Or directly, which is the only way to reach `--json`, `--values` and `--verbose`:

```sh
.venv-linux/bin/python tools/bmi-wrappers/bmi_introspect.py list
.venv-linux/bin/python tools/bmi-wrappers/bmi_introspect.py cfe --json
.venv-linux/bin/python tools/bmi-wrappers/bmi_introspect.py cfe --values
.venv-linux/bin/python tools/bmi-wrappers/bmi_introspect.py noah --json
```

**Piping `BMI_IO_FLAGS=--json` through the Makefile target:** `make -C commands` prints
`make: Entering directory '...'` on stdout ahead of anything the recipe does — this comes
from the `-C` flag itself, before the Makefile is even read, so nothing inside the Makefile
can suppress it. That line breaks any consumer expecting stdout to be pure JSON. Add
`--no-print-directory` before `-C`:

```sh
make --no-print-directory -C commands bmi-io MODEL=cfe BMI_IO_FLAGS=--json | python3 -m json.tool
```

Calling the script directly (as above) doesn't have this problem, since there's no `make -C`
in the way.

## Direct access

The wrapper packages are ordinary Python objects — the CLI is a convenience layer
over them, not the only way in. For a one-off getter, or a method the CLI doesn't
expose (`update()`, stepping through time, etc.), drive the model directly:

```python
.venv-linux/bin/python
>>> from pymt_cfe import CFE
>>> model = CFE()
>>> model.initialize("path/to/cat-N_bmi_config_cfe.txt")   # required before most getters work
>>> dir(model)
>>> model.get_component_name()
>>> model.get_input_var_names()
>>> model.get_output_var_names()
>>> model.get_var_units("some_var")
```

Same rule as everywhere else in this README: there's no static metadata, so most
getters raise or return meaningless data until `initialize()` has run against a real
config.

### Cross-checking a realization config

With `--realization`, the tool compares what the model really needs against how a
realization config wires it up, and exits non-zero on a real error:

| Level | Meaning |
| --- | --- |
| `ERROR` | An input nothing can satisfy, a `main_output_variable` that is not an output, or a name close enough to a real one to be a typo (reported with "did you mean"). |
| `WARN` | A `variables_names_map` key naming no variable of this model — dead config, harmless at runtime. Also an input that cannot be *proved* missing (see below). |

An input's identifier is its `variables_names_map` alias, or its own name. That
identifier must match either a framework forcing name or an output of another
module in the same `bmi_multi` formulation.

**One honest limitation.** Only the target model is introspectable, so a sibling
module's real output list is unknown. The tool approximates it from what the
config declares: `main_output_variable`, any `variables_names_map` alias, and any
variable synthesised through `model_params` (how SLoTH publishes, e.g.
`"sloth_smp(1,double,1,node)"`). When an input cannot be resolved and opaque
siblings exist, it is reported as `WARN` rather than `ERROR` — unless the
identifier is a near-miss for a known one, which is treated as a confident typo.

Forcing identifiers are parsed out of `include/forcing/AorcForcing.hpp` at runtime
rather than copied here, so this tool cannot drift from the C++ source.

Running it against the shipped multi-BMI example reports 5 resolved inputs and 7
warnings — those warnings are real: that config carries seven `variables_names_map`
entries for variables CFE does not have.

## Adding another wrapper

No Python changes are needed. The Noah-OWP-Modular entry below is a real,
working example of this recipe, not a sketch.

1. Add a line to `requirements.txt` pinning the distribution to a tag or commit.
2. Add a block to `wrappers.json`:

```json
"noah": {
  "description": "Noah-OWP-Modular (NOAA-OWP/noah-owp-modular), via pymt_noah_owp",
  "distribution": "pymt_noah_owp",
  "import_path": "pymt_noah_owp",
  "class_name": "NOAH_OWP",
  "lib_file": "extern/noah-owp-modular/cmake_build/libsurfacebmi.so",
  "build_env": {
    "NOAH_ROOT": "extern/noah-owp-modular/noah-owp-modular",
    "NOAH_LIB_DIR": "extern/noah-owp-modular/cmake_build",
    "NOAH_MOD_DIR": "extern/noah-owp-modular/cmake_build/mod"
  },
  "sample_config": "data/gauge_01073000/NOAH/cat-11223.input",
  "realization_model_types": ["bmi_fortran_noahowp"]
}
```

3. If the new model needs different env vars at pip-install time, extend the
   `install-bmi-wrappers` recipe in `commands/Makefile` (as done for Noah's
   `NOAH_ROOT`/`NOAH_LIB_DIR`/`NOAH_MOD_DIR`) — install it individually, gated
   on its own lib being present, rather than folding it into one
   `pip install -r requirements.txt`; otherwise a missing lib for the new
   model blocks installing every other wrapper too.
4. If the model's own `setup.py` has no RPATH-embedding (Noah's didn't — see
   the "Prerequisites" section above), patch it upstream rather than shipping
   an `LD_LIBRARY_PATH` workaround here.
5. Add the model's key to the `bmiModel` input's `options` in
   `.vscode/tasks.json` — it is a separate, hardcoded list (VS Code tasks
   can't read `wrappers.json` at picker-render time), so a model added only
   here and in `wrappers.json` works from a terminal but won't show up in the
   "BMI: Show model input/output requirements" task's picker.

`realization_model_types` is how the cross-check recognizes the model inside a
realization config; it is matched against `model_type_name`.

## Registry format

`wrappers.json`, not TOML: the devcontainer runs Python 3.10, which has no stdlib
`tomllib`, and this tool deliberately depends on nothing beyond numpy.
