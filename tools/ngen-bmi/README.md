# ngen_bmi

Set up, parameterize and run an ngen realization from Python. The `pymt_*` BMI wrappers, through
`bmi_setup` (pkdash/BMI), decide what a parameter is called, its type and its length. ngen runs
the simulation.

```python
from ngen_bmi import Project

p = Project.load("data/gauge_01073000/example_bmi_multi_realization_config_w_routing.json",
                 hydrofabric="data/gauge_01073000/gauge_01073000.gpkg")

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

Use the Make targets. Each one installs into, or runs from, the workspace venv (`.venv-linux`):

```sh
make -C commands install-bmi-wrappers BMI_REF=add-bmi-setup FORCE=1   # wrappers with the get/set_value fixes
make -C commands install-ngen-bmi                 # bmi_setup (pkdash/BMI) and this package, editable
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

Without Make:

```sh
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
