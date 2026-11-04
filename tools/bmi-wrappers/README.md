# Python BMI wrappers (introspection tooling)

Answers "what does this model actually need, and what does it produce?" by asking
the compiled model itself.

ngen keeps running these models through its own C/Fortran BMI adapters. Nothing
here is imported by the `ngen` binary, and installing these packages does not
change how ngen behaves — `.venv-linux` simply gains some extra modules.

## Why there is no lookup table

These wrapper packages ship no static metadata: no variable list, no units table.
That is deliberate. The authoritative source for a model's I/O contract is its
compiled BMI implementation, so every fact here is queried live. For example,
the source for CFE's contract is
`extern/cfe/cfe/src/bmi_cfe.c` (Noah-OWP-Modular's is
`extern/noah-owp-modular/noah-owp-modular/bmi/bmi_noahowp.f90`); a checked-in
copy would drift silently. A model must be **initialized with a real config**
before it can be asked anything.

## Prerequisites, in order

Each wrapper is a Cython extension that links the model's BMI shared library at
build time and loads it at import time. Build the matching native library before
installing that wrapper. All ten distributions are pinned in
`requirements.txt`; the Makefile installs each one independently, skipping
wrappers whose native library has not been built and returning an error if a
package installation itself fails.

```sh
make -C commands setup-venv            # once: .venv-linux with numpy<2
make -C commands build-cfe-lib         # or choose one build-*-lib target below
make -C commands install-bmi-wrappers  # pip install into .venv-linux
```

Available native-library targets (the VS Code task picker offers the same
choices):

| Model | Make target | Native BMI library |
| --- | --- | --- |
| CFE | `build-cfe-lib` | `extern/cfe/cmake_build/libcfebmi.so` |
| Noah-OWP-Modular | `build-noah-lib` | `extern/noah-owp-modular/cmake_build/libsurfacebmi.so` |
| LASAM | `build-lasam-lib` | `extern/lgar-c/cmake_build/liblasambmi.so` |
| PET | `build-pet-lib` | `extern/evapotranspiration/evapotranspiration/cmake_build/libpetbmi.so` |
| SAC-SMA | `build-sac-sma-lib` | `extern/sac-sma/cmake_build/libsacbmi.so` |
| Soil Freeze Thaw | `build-sft-lib` | `extern/SoilFreezeThaw/cmake_build/libsftbmi.so` |
| Soil Moisture Profiles | `build-smp-lib` | `extern/SoilMoistureProfiles/cmake_build/libsmpbmi.so` |
| SNOW-17 | `build-snow17-lib` | `extern/snow17/cmake_build/libsnow17bmi.so` |
| TOPMODEL | `build-topmodel-lib` | `extern/topmodel/cmake_build/libtopmodelbmi.so` |
| UEB | `build-ueb-lib` | `extern/ueb-bmi/cmake_build/src/libbmiuebcxx.so` |

The targets initialize their own model submodules and build only the needed
library. Noah's target reconfigures the shared ngen `cmake_build` using the
Fortran flags. SAC-SMA and SNOW-17 need a Fortran compiler and the
`extern/iso_c_fortran_bmi` source tree. UEB needs the one-time setup targets
`setup-boost` and `setup-ewts` first. The `build-bmi-wrapper-libs` convenience
target builds all ten libraries and therefore has all of those prerequisites;
normally, build only the library for the wrapper you need.

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

`install-bmi-wrappers` installs wrappers individually, gated on their
corresponding libraries. It exports the model-specific build variables each
package's setup script needs, including `CFE_ROOT`/`CFE_LIB_DIR` and
`NOAH_ROOT`/`NOAH_LIB_DIR`/`NOAH_MOD_DIR`. Each installed wrapper embeds an RPATH to its native library's build
directory, so it imports without `LD_LIBRARY_PATH`. The Makefile still sets the
loader path while installing and when `bmi-io` runs, as a fallback.

**Rerunning the install does not rebuild installed wrappers.** pip resolves
the pinned source, sees the same name and version already installed, and keeps
the old build without saying so — the target still prints `Installed <name>`.
This holds even when `requirements.txt` now pins a different source. After
changing a pin, or after rebuilding, moving or deleting a native library's
build directory (which invalidates the baked-in RPATH), force a rebuild:

```sh
make -C commands install-bmi-wrappers FORCE=1   # pip --force-reinstall --no-deps
```

`--no-deps` leaves numpy (pinned below 2.0 by `setup-venv`) untouched. To check
which source each wrapper was actually built from (prints the pinned git
revision, or the local path for a non-VCS install):

```sh
.venv-linux/bin/pip inspect 2>/dev/null | .venv-linux/bin/python -c "
import json, sys
for p in json.load(sys.stdin)['installed']:
    if p['metadata']['name'].startswith('pymt'):
        d = p.get('direct_url', {})
        print(p['metadata']['name'], d.get('vcs_info', {}).get('requested_revision') or d.get('url'))"
```

All of this runs inside the devcontainer. `libcfebmi.so`/`libsurfacebmi.so` are
ELF objects and `.venv-linux` is not executable from a macOS host.

## Usage

```sh
make -C commands bmi-io                       # CFE, registry's sample config
make -C commands bmi-io MODEL=cfe CONFIG=path/to/cat-N_bmi_config_cfe.txt
make -C commands bmi-io MODEL=noah CONFIG=data/gauge_01073000/NOAH/cat-11223.input
make -C commands bmi-io MODEL=topmodel         # registry config and working directory
make -C commands bmi-io MODEL=sft              # registry config (Laramie) and working directory
make -C commands bmi-io MODEL=smp              # registry config (conceptual soil storage)
make -C commands bmi-io MODEL=ueb              # registry config (bmi_test, ngen-style) and working directory
make -C commands bmi-io MODEL=ueb CONFIG=path/to/control.dat WORKDIR=path/to/model/data
make -C commands bmi-io REALIZATION=data/example_bmi_multi_realization_config_w_noah_pet_cfe.json
```

Models without a registered sample config (SAC-SMA and SNOW-17) require
`CONFIG=...`. `WORKDIR` is optional and is repo-root-relative unless absolute;
it selects the directory used to resolve paths referenced inside the model
config. The registry supplies it for the LASAM, SFT, TOPMODEL, and UEB sample
configs.

SAC-SMA and SNOW-17 do ship a working example (`ex1`), but it is not
registered: initialization writes output/state files next to tracked reference
outputs (SAC-SMA), or the example only exists as a tarball (SNOW-17). The
ngen-oriented configs these submodules ship
(`extern/sac-sma/ngen_files/sac-init-HHWM8.namelist.input`,
`extern/snow17/configs/snow17-init-cat-27.namelist.input`) cannot be used
either: they reference forcing/parameter paths that do not exist in the tree.

Run `ex1` from a scratch copy, **with `n_hrus` reduced from 2 to 1**. Both
BMIs report every variable on a scalar grid (one value), so with two HRUs
`set_value` only fills the first and the second runs on uninitialized forcing:
SAC-SMA then spins forever in `update()`, and SNOW-17 returns `inf`
(`raim`, `precip_scf`). Introspection alone works either way, but stepping the
model does not. This matches how ngen drives them (one HRU per catchment).

```sh
cp -r extern/sac-sma/test_cases/ex1 /tmp/sac_ex1
sed -i 's/^n_hrus *= *2/n_hrus = 1/' /tmp/sac_ex1/run/namelist.bmi.HHWM8
make -C commands bmi-io MODEL=sac_sma CONFIG=/tmp/sac_ex1/run/namelist.bmi.HHWM8 WORKDIR=/tmp/sac_ex1/run

mkdir -p /tmp/snow17 && tar -xzf extern/snow17/test_cases/ex1.tgz -C /tmp/snow17
sed -i 's/^n_hrus *= *2/n_hrus = 1/' /tmp/snow17/ex1/run/namelist.bmi.HHWM8
make -C commands bmi-io MODEL=snow17 CONFIG=/tmp/snow17/ex1/run/namelist.bmi.HHWM8 WORKDIR=/tmp/snow17/ex1/run
```

The registered UEB sample is `extern/ueb-bmi/examples/bmi_test/data/ueb/control.dat`,
the config from the submodule's ngen multi-BMI example: its forcings are
declared as supplied by ngen (`inputcontrol.dat` type 3), so they are meant to
be set through `set_value`. Avoid the file-forced `examples/TWDEF_onecell`
example for anything beyond introspection: for forcing read from files, UEB's
BMI points `Prec`/`Ta` at the *previous* timestep's slot
(`src/bmi/bmi_ueb.cxx`, `GetValuePtr`), so calling `set_value` on them before
the first `update()` writes out of bounds and corrupts the heap
(`malloc(): invalid next size`), and after that the values you set are
silently ignored.

UEB writes its configured outputs even when only queried, so running the UEB
sample writes `Point00.txt`, `SWE.nc`, `SWISM.nc`, and `SWIT.nc` into
`extern/ueb-bmi/examples/bmi_test/`. They show up as untracked files in the
`extern/ueb-bmi` submodule; delete them, or point `CONFIG`/`WORKDIR` at a copy
of the example directory to keep the submodule clean:

```sh
cp -r extern/ueb-bmi/examples/bmi_test /tmp/ueb_test
make -C commands bmi-io MODEL=ueb CONFIG=/tmp/ueb_test/data/ueb/control.dat WORKDIR=/tmp/ueb_test
```

LASAM prints its mass-balance summary when it is finalized, so its `bmi-io`
output starts with that block; the introspection report follows it.

Because the installed wrappers embed an RPATH (see above), the CLI can be run
directly without setting `LD_LIBRARY_PATH`:

```sh
.venv-linux/bin/python tools/bmi-wrappers/bmi_introspect.py list
.venv-linux/bin/python tools/bmi-wrappers/bmi_introspect.py cfe --json
```

If an import fails with `cannot open shared object file`, the library has moved
since the wrapper was built: reinstall it with `FORCE=1`.

Direct invocation is the only way to reach `--json`, `--values` and `--verbose`:

```sh
.venv-linux/bin/python tools/bmi-wrappers/bmi_introspect.py cfe --values
.venv-linux/bin/python tools/bmi-wrappers/bmi_introspect.py noah --json
.venv-linux/bin/python tools/bmi-wrappers/bmi_introspect.py topmodel --workdir extern/topmodel/topmodel
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

1. Add a line to `requirements.txt` pinning the distribution to the same
   repo-wide pkdash/BMI tag as the other wrappers (currently `v0.3.0`), so all
   wrappers come from one tested commit. If the new wrapper needs a newer BMI
   commit, tag a new release and move every pin to it together.
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

3. Add a native-library build target and its package-specific build variables
   to `commands/Makefile`. The install target handles each wrapper separately,
   gated on its own library, so an unavailable model does not block other
   installs.
4. Register a verified sample config only if its relative paths resolve from
   the configured `working_directory`; the config is optional. Add
   `working_directory` where the model needs a non-repository-root working
   directory. Use `--workdir`/`WORKDIR` for user-supplied configs.
5. Add the model key to the `bmiModel` and native-build picker inputs in
   `.vscode/tasks.json`.

`realization_model_types` is how the cross-check recognizes the model inside a
realization config; it is matched against `model_type_name`.

## Registry format

`wrappers.json`, not TOML: the devcontainer runs Python 3.10, which has no stdlib
`tomllib`, and this tool deliberately depends on nothing beyond numpy.
