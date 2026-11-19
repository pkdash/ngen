# Setting `max_gw_storage` through BMI does not rescale the initial groundwater storage

## Summary

At initialization, CFE sets the groundwater reservoir's storage as a fraction of its capacity: `storage_m = gw_storage * storage_max_m`. When the capacity is changed afterwards through BMI (`set_value("max_gw_storage", ...)`), `Set_value` is meant to recompute that storage, but the recomputation never runs. It checks for the name `"storage_max_m"`, while the parameter's BMI name is `"max_gw_storage"`.

As a result, setting `max_gw_storage` after `initialize` leaves the groundwater storage computed from the old capacity. Results then differ from putting the same value in the config file. This affects any framework that sets calibration parameters after `initialize`, including ngen's `model_params` and calibration tools built on it.

Observed on `master` at `f9182df` (2026-04-06), and on `a349a95`, the commit ngen currently pins.

## Where

`src/bmi_cfe.c`, `Set_value` (line 2243 on `master`):

```c
    memcpy (dest, src, nbytes);
    ...
    if (strcmp (name, "storage_max_m") == 0) {                       // line 2268
         cfe_state_struct* cfe_ptr = (cfe_state_struct *) self->data;
         cfe_ptr->gw_reservoir.storage_m = cfe_ptr->gw_reservoir.gw_storage * cfe_ptr->gw_reservoir.storage_max_m;
     }
```

- The calibratable parameter is published as `"max_gw_storage"` (`param_var_names`, line 31). `Get_value_ptr` maps that name to `gw_reservoir.storage_max_m` (line 1948), so `set_value("max_gw_storage", ...)` does update the capacity.
- `"storage_max_m"` appears only in the internal state-variable table used for serialization (`var_info`, entries 6 and 17). It is not a BMI variable. `get_var_type`, `get_var_nbytes` and `get_value_ptr` reject it, so `Set_value` can never be called with that name. The recomputation is unreachable.
- At config time the storage is derived the same way (line 685):
  ```c
  model->gw_reservoir.storage_m = model->gw_reservoir.gw_storage * model->gw_reservoir.storage_max_m;
  ```
  So a config edit of `max_gw_storage` changes both capacity and initial storage. A BMI set changes only the capacity.

The soil-reservoir parameters in the same function (`maxsmc`, `b`, `satdk`, ...) do recompute their derived state, through `init_soil_reservoir()`. Only the groundwater capacity is missed. The check was added in #64 ("Fix bug with calibratable parameters and add new parameters").

## Steps to reproduce

**Direct check.** With `configs/cfe_config_cat_87_pass.txt` (`max_gw_storage=0.25`, `gw_storage=0.125`):

```c
Bmi *m = malloc(sizeof(Bmi));
register_bmi_cfe(m);
m->initialize(m, "configs/cfe_config_cat_87_pass.txt");
cfe_state_struct *s = (cfe_state_struct *) m->data;
printf("%f\n", s->gw_reservoir.storage_m);     /* 0.031250 = 0.125 * 0.25 */

double new_max = 0.5;
m->set_value(m, "max_gw_storage", &new_max);
printf("%f\n", s->gw_reservoir.storage_m);     /* still 0.031250; a config with max_gw_storage=0.5 gives 0.062500 */
```

**Effect on results.** Compare two runs with identical forcing:
- **A:** `max_gw_storage=X` in the config file.
- **B:** the original config, then `set_value("max_gw_storage", &X)` right after `initialize`.

**Expected:** A and B are identical. Setting a parameter right after `initialize` should be equivalent to setting it in the config.

**Actual:** they differ. We used config `cat-11223` from ngen's `data/gauge_01073000`, changed `max_gw_storage` from 0.01286 to 0.01929 m, and ran 720 hourly steps of AORC forcing. A and B differed by up to 61% of the peak `DEEP_GW_TO_CHANNEL_FLUX`.

For comparison, the same test on the other calibratable parameters gave output bit-identical to the config edit, for each of `b`, `satdk`, `satpsi`, `maxsmc`, `wltsmc`, `alpha_fc`, `Cgw`, `expon` and `refkdt`.

## Proposed fix

Check the parameter's BMI name in `Set_value`:

```c
    if (strcmp (name, "max_gw_storage") == 0) {
         cfe_state_struct* cfe_ptr = (cfe_state_struct *) self->data;
         cfe_ptr->gw_reservoir.storage_m = cfe_ptr->gw_reservoir.gw_storage * cfe_ptr->gw_reservoir.storage_max_m;
     }
```

Keeping `"storage_max_m"` as an alternative would do no harm, but nothing can reach it.

**Test addition** in `test/test_bmi_model.c`, registered in `CMakeLists.txt` as `test_set_value_max_gw_storage_1`. The test (`test_set_value_max_gw_storage`):
1. initializes from the existing example config;
2. checks the precondition `storage_m == gw_storage * storage_max_m`;
3. sets `max_gw_storage` to twice its value;
4. asserts that the capacity was set and that `storage_m` was rescaled to `gw_storage * new_max`.

**Note on mass balance:**
- `initialize_volume_trackers()` records the starting groundwater volume (`volstart`, `vol_in_gw_start`) during `initialize`, before any `set_value`. With the fix, the storage changes after that point, so the mass-balance start volume reflects the config value.
- The soil-reservoir parameters already behave this way: `init_soil_reservoir()` in `Set_value` resets `soil_reservoir.storage_m` without touching the trackers.
- If the mass-balance report should be exact after a parameter change, both cases need the trackers refreshed. That can be a separate change.

## Verification of the proposed fix

Built from `master` (`f9182df`) with `-DNGEN=ON`, with and without the change:

- **New test:**
  - **fails on unpatched `master`:** `Expected: 0.062500 | Value: 0.031250`, "Groundwater storage was not rescaled after setting 'max_gw_storage'";
  - **passes with the fix.**
- **Existing CTest suite:** all 43 existing tests pass with and without the fix (44 with the new one).
- **End to end through a BMI host** (the A/B comparison above, 720 steps, every output compared bit-for-bit):
  - `max_gw_storage` goes from differing (up to 61% of peak `DEEP_GW_TO_CHANNEL_FLUX`) to **bit-identical**;
  - the results for all other 17 calibratable parameters are unchanged.

## Local fix in this ngen checkout

_For ngen-bmi work. Remove this section before filing the ticket upstream._

- **Branch:** `fix-max-gw-storage-set-value` in `extern/cfe/cfe`, commit `3ec291a`, based on upstream `master` (`f9182df`). It changes `src/bmi_cfe.c`, `test/test_bmi_model.c` and `CMakeLists.txt`.
- **The branch exists only in this machine's submodule clone.** It has not been pushed. A copy is saved as [`patches/cfe/0001-WIP-max_gw_storage-set_value-fix.patch`](patches/cfe/0001-WIP-max_gw_storage-set_value-fix.patch).
- **ngen's pin is `a349a95`, not `master`.** The full patch does not apply there: `test/test_bmi_model.c` does not exist at the pin and the `CMakeLists.txt` hunk conflicts. The `src/bmi_cfe.c` hunk, which is the fix itself, applies cleanly.

**Get the fix back:**

```sh
# Branch still in the submodule clone
git -C extern/cfe/cfe switch fix-max-gw-storage-set-value

# Branch lost (fresh clone or re-cloned submodule): recreate it from the patch
git -C extern/cfe/cfe switch -c fix-max-gw-storage-set-value f9182df
git -C extern/cfe/cfe am "$PWD/patches/cfe/0001-WIP-max_gw_storage-set_value-fix.patch"

# Fix only, on ngen's pin, without a branch
git -C extern/cfe/cfe apply --include=src/bmi_cfe.c "$PWD/patches/cfe/0001-WIP-max_gw_storage-set_value-fix.patch"
```

Then rebuild the library and reinstall the wrapper: `make -C commands build-cfe-lib` and `make -C commands install-bmi-wrappers BMI_REF=add-bmi-setup FORCE=1`.

**Go back to ngen's pin** before `configure-*` or any `build-*-lib`, which run `git submodule update` and refuse to while the submodule has local changes:

```sh
git submodule update -- extern/cfe/cfe
```

**Drop this section, the branch and the patch** once the fix is merged upstream and ngen's `extern/cfe/cfe` pin includes it. Then mark `max_gw_storage` `equivalent` in the `bmi_setup` CFE catalog, as described in `tools/ngen-bmi/README.md`.
