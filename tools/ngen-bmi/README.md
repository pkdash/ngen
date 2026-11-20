# ngen_bmi

Set up, parameterize and run an ngen realization from Python. The `pymt_*` BMI wrappers, through
`bmi_setup` (pkdash/BMI), decide what a parameter is called, its type and its length. ngen runs
the simulation.

## Before you start (devcontainer)

Run these once, from the repo root inside the devcontainer, in this order. The Python code below
needs all of them.

```sh
make -C commands setup-venv          # creates the workspace venv .venv-linux (numpy<2)
make -C commands configure-fortran   # ngen with BMI C + Fortran (CFE, PET, SLoTH, Noah-OWP)
make -C commands build               # builds ngen and the model libraries the realization loads
make -C commands install-bmi-wrappers BMI_REF=add-bmi-setup FORCE=1   # pymt_* wrappers
make -C commands install-ngen-bmi    # bmi_setup (pkdash/BMI) and ngen_bmi, editable
```

- **Build configuration.** The default `make -C commands configure` turns off BMI C and Fortran.
  A binary built that way cannot run CFE, PET or Noah, so `run()` raises `NgenRunError`. Check
  the active configuration with `make -C commands show-config`.
- **Missing wrappers.** `install-bmi-wrappers` skips any wrapper whose native library is missing
  and tells you which `build-*-lib` target to run. With `build` done first, CFE, Noah-OWP and
  PET install. Ignore the skips for models you don't use.
- **Activate the venv.** Every package above goes into `.venv-linux`, and the Make targets call
  its interpreter directly. To run your own Python (a script, `python -m pytest`, a REPL),
  activate it first, from the repo root:

  ```sh
  source .venv-linux/bin/activate
  ```

  Or call `.venv-linux/bin/python` directly. The venv is a Linux build, so use it only inside
  the container.
- **Working directory.** Start Python from the repo root, or pass `root=` to `Project.load`.
  Relative paths such as `data/...` are resolved from there.

### Next sessions

The setup does not need repeating. The repo folder is bind-mounted from the host, so
`cmake_build/ngen`, the model libraries in `extern/*/cmake_build/` and `.venv-linux` are kept
when the container is reopened, restarted or rebuilt. A new session only needs
`source .venv-linux/bin/activate`.

Rebuild only in these cases:

- **Code changed.** After a `git pull`, a submodule update or your own edits to model or ngen
  code, run `make -C commands build`. If a library that a wrapper links changed, also run
  `install-bmi-wrappers ... FORCE=1`.
- **Configuration changed.** Every `configure-*` target writes to the same `cmake_build`. After
  `configure` or `configure-python` and a `build`, ngen no longer runs CFE or Noah. Check with
  `make -C commands show-config`. To restore it, run `configure-fortran` and then `build`.
- **Container image changed.** After the Dockerfile changes and the container is rebuilt, the
  system libraries (NetCDF, gfortran, ...) may differ from the ones the binaries were linked
  against. If ngen or a wrapper then fails to load a `.so`, run `make -C commands rebuild` and
  reinstall the wrappers with `FORCE=1`.
- **`/opt` was wiped.** The compiled Boost (`/opt/boost-built`) and EWTS (`/opt/ewts`) live in
  the container, not the repo, so a container rebuild removes them. Only UEB and
  `configure-all` need them; restore them with `setup-boost` and `setup-ewts`. CFE, Noah-OWP and
  PET do not use them.

## Preparing input data

`ngen_bmi` starts from files that already exist: a hydrofabric subset (`.gpkg`), forcings, the
per-catchment model configs and a realization. [NGIAB_data_preprocess](https://github.com/CIROH-UA/NGIAB_data_preprocess)
(`ngiab-data-preprocess` on PyPI) makes all four for a gage or catchment. Run it once per domain
and simulation period, before `Project.load`.

**Don't install it into `.venv-linux`.** It pins exact versions of dask, xarray, zarr, s3fs,
requests and Flask, and limits Python to 3.12 or older. In the wrapper venv those pins would
conflict with `bmi_setup` and the `pymt_*` wrappers. Nothing in `ngen_bmi` imports it, because
the two hand over files only. The make target therefore runs it in its own environment:

```sh
make -C commands prepare-data GAGE=10109001 START=2010-10-01 END=2011-09-30
```

- **What it does:** subsets, makes forcings and writes the realization (`-sfr`) into
  `data/gage-10109001/`.
- **Environment:** the target uses `uvx` if it is on `PATH`. Otherwise run
  `make -C commands setup-prep-venv` once; it creates `.venv-prep`, which is gitignored.
- **Apple silicon: run it on the macOS host, not in the devcontainer.** The container is Linux
  arm64, and the tool's dependency `exactextract==0.2.0` has no Linux arm64 wheel; its source
  build fails. Both targets stop with this message there. Run the same command in a host
  terminal from the repo root, with [uv](https://docs.astral.sh/uv/) installed. The output goes
  to the bind-mounted `data/`, so the container sees it, and the hydrofabric download in the
  host's `~/.ngiab/` survives container rebuilds. On x86_64, the container works.
- **Windows.** On a usual x86_64 PC, run the make target in the devcontainer, which is Linux
  x86_64 there. The Windows host has no `make`, and the target needs bash. To run the prep on
  the host anyway, for example on Windows on ARM, where the container is Linux arm64, call the
  tool directly with `uv`, from the repo root in PowerShell:

  ```powershell
  uvx --from ngiab-data-preprocess==4.9.4 cli -i gage-10109001 -sfr --start 2010-10-01 --end 2011-09-30 -o "$PWD\data\gage-10109001"
  ```

  The output goes to the same `data\gage-<id>\` layout. This has not been tested on Windows. On
  Windows on ARM, some dependencies may have no wheels.
- **Version:** `ngiab-data-preprocess` is pinned with `NGIAB_PREP_VERSION`, 4.9.4 by default.
- **Other options:** pass the CLI arguments yourself, as in
  `PREP_ARGS="-i cat-5173 -sfr --start ... --end ... -o $PWD/data/cat-5173"`. See the tool's
  README for the options, such as `--source aorc` and `--lstm`.
- **First run:** it asks two questions:
  - whether to use the default output directory; answer `y`, because `-o` overrides it anyway;
  - whether to download the CONUS hydrofabric, several GB, into `~/.ngiab/`.

  On x86_64, if you run it in the devcontainer, `~` is not bind-mounted there, so the
  hydrofabric download is lost when the container is rebuilt.
- **No `--run`:** that flag starts the NGIAB Docker image. Use `Project.run` instead.

The output layout is `data/gage-<id>/config/` (the `gage-<id>_subset.gpkg`, `realization.json`
and `cat_config/<model>/`) and `data/gage-<id>/forcings/`. Point `Project.load` at it:

```python
p = Project.load("data/gage-10109001/config/realization.json",
                 hydrofabric="data/gage-10109001/config/gage-10109001_subset.gpkg",
                 root="data/gage-10109001")
```

`root=` is required. The realization's paths, such as `./config/cat_config/CFE/{{id}}.ini`
and `./forcings/forcings.nc`, are relative to the output folder, because NGIAB starts ngen
there. Without `root=`, they are resolved from the current directory.

**Paths into the NGIAB image are remapped.** The generated files point at the NGIAB Docker
image: `library_file` is `/dmod/shared_libs/<lib>`, and Noah's `parameter_dir` is
`/dmod/datasets/static/`. When such a path does not exist, `ngen_bmi` replaces it with the local
build and issues a `LocalizationWarning`:
- **Libraries:** the library of the same name in `extern/*/cmake_build/`.
- **Data directories:** the directory given by the registry's `local_config_dirs`; for Noah,
  `extern/noah-owp-modular/noah-owp-modular/parameters/`. The edit is made in the config copies
  written to `<run_dir>/configs/<model>/`.

The prepared folder itself is never edited, so it still runs in NGIAB.

**Noah version.** NGIAB's Noah configs set `stomatal_resistance_option = 4` and
`evap_srfc_resistance_option = 5`. Noah reads these options in `initialize`, before any `set()`,
and the older pin (0abb891, 2024-09) aborts on them. The `noah-owp-modular` submodule is now
pinned at f80bd28, the commit CIROH-UA/ngen `ngiab` uses, which accepts both. After pulling
this change:

```sh
git submodule update -- extern/noah-owp-modular/noah-owp-modular
make -C commands build TARGETS="ngen surfacebmi"
make -C commands install-bmi-wrappers BMI_REF=add-bmi-setup FORCE=1   # rebuilds pymt_noah_owp
```

## Usage

```python
from ngen_bmi import Project

p = Project.load("data/gauge_01073000/example_bmi_multi_realization_config_w_routing.json",
                 hydrofabric="data/gauge_01073000/gauge_01073000.gpkg")

p.modules()                                    # {registry key: model_type_name}; keys for p.module()
cfe = p.module("cfe")                          # found through wrappers.json realization_model_types
cfe.parameters()                               # DataFrame: catalog plus live values, route per parameter
cfe.set(satdk=2.0e-5, b=8.0)                   # every catchment, via model_params
cfe.set(refkdt=3.0, catchments=["cat-11223"])  # one catchment (a catchments.<id> override)
cfe.set(max_gw_storage=0.02)                   # catalog says "differs": edits the config files
p.module("noah").set(SMCMAX=0.40)              # written as one value per soil layer (nsoil)
p.module("pet").set(zero_plane_displacement_height_m=0.001)   # PET is config-only

run = p.run("runs/exp1", drop_routing=True)    # validate, write, run ngen
run.catchment("cat-11223")                     # DataFrame of cat-11223.csv
run.nexus("nex-11224")                         # DataFrame of nex-11224_output.csv
```

## How a change reaches ngen

| Catalog status | Route | Notes |
|---|---|---|
| `equivalent` | `model_params` | proven bit-identical to a config edit |
| `unexercised`, `untested` | `model_params` | `validate()` warns: no effect shown or not compared |
| `differs`, `none` (config-only) | `init_config` | the config files are copied into `<run_dir>/configs/<model>/` and edited |

`set(..., route="init_config")` or `route="model_params"` forces a route when the catalog allows
it. When a parameter is changed for some catchments and also for all of them, the
catchment-specific value wins.

## What `run()` does

- **Paths.** The working directory for ngen is `root` (default: the current directory at
  `Project.load`). Relative paths in the realization and inside model configs are resolved from
  there, the same way as when ngen runs by hand. The written `realization.json` uses absolute
  paths.
- **Output.** Output goes to `run_dir` (`output_root`), along with `ngen.log`, `changes.json` and
  the edited configs.
- **Validation.** `validate()` runs first. It opens each changed module's wrapper once per
  distinct config, applies every change and checks that each value reads back exactly.
- **Errors.** `NgenRunError` is raised for any of these:
  - ngen exits non-zero (the message has the end of the log);
  - ngen logs that it skipped a parameter;
  - the binary was built without a feature the realization needs (from `ngen --info`).
- **Binary.** The `ngen` binary is the `ngen=` argument, then `$NGEN_BIN`, then
  `cmake_build/ngen`, then `PATH`.

**Not supported yet:**
- input realizations that already have a `catchments` block;
- changing the simulation period;
- routing (use `drop_routing=True` with a binary built without it).

## Known upstream issues

Two model bugs shape what `ngen_bmi` does and what `make -C commands test-ngen-bmi` expects. Each
has a ticket draft in the repo root, ready to file upstream. When either fix lands, update the
catalog or the library as described below.

| Model | Issue | Ticket | Effect here | When the fix lands |
|---|---|---|---|---|
| TOPMODEL | `get_var_nbytes` reports `nstep` items for the 8 calibration parameters, so the wrapper's `get_value`/`set_value` overrun them in stand-alone mode. ngen's framework mode is not affected. | [`topmodel-issue-ticket.md`](../../topmodel-issue-ticket.md) | The wrapper needs a fixed `libtopmodelbmi.so`. With an unfixed one, the wrapper test fails `CatalogMismatch` (950 elements per parameter). Until then, put a fixed library first with `LD_LIBRARY_PATH=<dir> make -C commands test-ngen-bmi`. | Move the `extern/topmodel/topmodel` pointer to the fix, or backport it to ngen's pin `a4cb3ba` (upstream `master` needs Boost ≥ 1.86), then `build-topmodel-lib` and reinstall `pymt_topmodel`. |
| CFE | `Set_value` checks for the name `storage_max_m` instead of `max_gw_storage`, so changing `max_gw_storage` after `initialize` does not rescale the initial groundwater storage. | [`cfe-issue-ticket.md`](../../cfe-issue-ticket.md) | The `bmi_setup` catalog marks `max_gw_storage` `differs`, so `set(max_gw_storage=...)` edits the config instead of using `model_params`. | Rebuild `libcfebmi.so`. The wrapper test then fails with "catalog says differs, measured equivalent" (checked against the local fix). Mark the entry `equivalent` in `bmi_setup/catalogs/cfe.json` (pkdash/BMI) and drop its note. `max_gw_storage` then goes through `model_params`. |

`build-cfe-lib` and `build-topmodel-lib` start with `git submodule update`. While either submodule
is checked out on a fix branch with local changes, that step refuses to run, and git keeps the
changes. TOPMODEL also has an infiltration-excess bug (`xk0` has no effect, because `expinf()`
truncates its rate to `int`). It is outside BMI and has no ticket; the catalog keeps `xk0`
`unexercised`.

## Install, test and the worked example (devcontainer)

Use the Make targets. Each one installs into, or runs from, the workspace venv (`.venv-linux`), so
none of them needs the venv to be active. The setup steps are in
[Before you start](#before-you-start-devcontainer).

```sh
make -C commands test-ngen-bmi                    # all three test layers; missing prerequisites skip a layer
make -C commands ngen-bmi-example OUT=/tmp/ex     # examples/change_parameters.py
```

- **Local `bmi_setup`.** `install-ngen-bmi BMI_SETUP=/path/to/BMI/bmi_setup` installs a local
  checkout in editable mode.
- **Default source.** Without `BMI_SETUP`, `bmi_setup` comes from pkdash/BMI at `BMI_SETUP_REF`
  (default `add-bmi-setup`, until `bmi_setup` is tagged).
- **`test-ngen-bmi`** runs three layers:
  1. the unit tests of both packages; the `bmi_setup` ones run only when it is installed from a
     checkout;
  2. `bmi_setup`'s wrapper integration (`-m wrappers`), for each wrapper that imports;
  3. this package's ngen integration (`-m ngen`).
- **Loader path.** `LD_LIBRARY_PATH` from the caller comes first. That lets a fixed library
  (TOPMODEL's `get_var_nbytes`) built outside `extern/` stand in for the one the wrapper links.

Without Make, activate the venv first:

```sh
source .venv-linux/bin/activate
python -m pip install -e tools/ngen-bmi            # needs bmi-setup, numpy<2, pandas
python -m pytest tools/ngen-bmi -m "not ngen"     # unit tests, no native code
python -m pytest tools/ngen-bmi -m ngen           # needs cmake_build/ngen (BMI C + Fortran) and the wrappers
python tools/ngen-bmi/examples/change_parameters.py
```

## The worked example

`examples/change_parameters.py` uses the gauge_01073000 example. It:
1. prints CFE's parameters, read live from the library, with the route each one would take;
2. runs a baseline;
3. changes parameters in five ways: CFE `satdk` everywhere, CFE `b` for one catchment, CFE
   `max_gw_storage` (config edit), Noah `SMCMAX` (per soil layer) and a PET config key;
4. runs again and compares total nexus flow and `cat-11223` `Q_OUT`.

The runs, logs, edited configs and `changes.json` stay in `--out`.

## Registry

`ngen_bmi.registry` loads `tools/bmi-wrappers/wrappers.json`. It needs only the standard
library, and `bmi_introspect.py` imports it too, so the registry is read in one place.
`realization_model_types` is compared exactly with a realization's `model_type_name`, ignoring
case.
