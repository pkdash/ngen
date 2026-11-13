# `get_var_nbytes` reports `nstep` items for calibration parameters, so `get_value`/`set_value` overrun them in stand-alone mode

## Summary

For the eight calibration parameters exposed through BMI (`t0, szm, td, srmax, sr0, xk0, chv, rv`), `Get_var_nbytes` reports `nstep * sizeof(double)` bytes instead of `sizeof(double)`. `Get_value` and `Set_value` copy exactly `nbytes` bytes (`memcpy`), so in stand-alone mode a parameter read over-reads, and a parameter write overwrites memory past the scalar field. This corrupts the heap or crashes the process.

Framework mode is not affected in practice, because there `nstep` is forced to 1 (see "Why this has not shown up").

Observed on `master` at `89e4dc5`, and on `a4cb3ba`, the commit pinned by ngen.

## Where

`src/bmi_topmodel.c`, `Get_var_nbytes` (line 717 on `master`):

```c
    int item_count = -1;
    for (int i = 0; i < INPUT_VAR_NAME_COUNT; i++) { ... }      // inputs
    if (item_count < 1) {
        for (int i = 0; i < OUTPUT_VAR_NAME_COUNT; i++) { ... } // outputs
    }
    if (item_count < 1)
        item_count = ((topmodel_model *) self->data)->nstep;    // line 750

    *nbytes = item_size * item_count;
```

The parameters are in neither the input nor the output table, so they always reach the `nstep` fallback. `Get_var_type` and `Get_var_itemsize` do know about them (via `param_var_names` / `param_var_types`), so `item_size` resolves and the call succeeds with the wrong size.

The consumers copy that size:
- `Get_value`: `memcpy(dest, src, nbytes);` (line 998)
- `Set_value`: `memcpy (dest, array, nbytes);` (line 1046)

`Get_value_ptr` returns `&model->szm` etc., a single `double` in `topmodel_model`, so any `nbytes > sizeof(double)` reads or writes past it.

## Why this has not shown up

`nstep` depends on the mode chosen by the first line of the `.run` file:

| Mode | `nstep` | `get_var_nbytes("szm")` |
|---|---|---|
| Framework (`0`; used by ngen and by `test/data/topmod_unit_test.run`) | forced to 1 (`bmi_topmodel.c:304`) | 8, correct by coincidence |
| Stand-alone (`1`; e.g. `data/topmod.run`) | length of `inputs.dat` (950 for the sample data) | 7600 |

The existing test in `test/main_unit_test_bmi.c` already calls `set_value` on parameters with a single `double`, under AddressSanitizer. It passes only because its config is framework mode.

## Steps to reproduce

1. Use a stand-alone config, such as `data/topmod.run` (first line `1`) or a copy of `test/data/topmod_unit_test.run` with its first line changed to `1`.
2. Run:

```c
Bmi *m = malloc(sizeof(Bmi));
register_bmi_topmodel(m);
m->initialize(m, "topmod_standalone.run");

int nbytes = 0;
m->get_var_nbytes(m, "szm", &nbytes);
printf("nbytes(szm) = %d\n", nbytes);       // prints 7600, expected 8

double v = 0.04;
m->set_value(m, "szm", &v);                 // copies 7600 bytes from &v into &model->szm
```

**Expected:** `nbytes(szm) = 8`. `set_value` writes one `double`.

**Actual:** `nbytes(szm) = 7600`. `set_value` reads 7600 bytes from the caller's single `double` and writes them over `szm` and everything after it in the model struct and on the heap. In our runs, setting a parameter in stand-alone mode led to `malloc(): mismatching next->prev_size` or a segfault on a later call.

The same happens through any BMI host that sizes buffers from `get_var_nbytes`. We hit it through the Python (Cython) BMI wrapper for TOPMODEL.

## Proposed fix

In `Get_var_nbytes`, give the parameters an item count of 1. Then replace the `nstep` fallback with a failure: once parameters are handled, every name `Get_value_ptr` serves (inputs, outputs, parameters, serialization variables) is matched earlier, so the fallback only ever turns an invalid name into a large over-read.

```c
    // Calibratable parameters are scalars. They must not fall through to a
    // per-timestep count: in stand-alone mode nstep is the length of the input
    // series, and Get_value/Set_value copy nbytes, overrunning the scalar.
    if (item_count < 1) {
        for (int i = 0; i < PARAM_VAR_NAME_COUNT; i++) {
            if (strcmp(name, param_var_names[i]) == 0) {
                item_count = 1;
                break;
            }
        }
    }
    // Every variable Get_value_ptr serves is matched above, so anything else is
    // not a variable of this model.
    if (item_count < 1)
        return BMI_FAILURE;
```

Test addition to `test/main_unit_test_bmi.c`:
- add a stand-alone copy of the unit-test config, `test/data/topmod_unit_test_standalone.run` (first line `1`);
- initialize a second model with it;
- for all 8 parameters, assert `get_var_nbytes == sizeof(double)` and a `set_value`/`get_value` round trip;
- assert `get_var_nbytes` fails for an unknown name.

## Verification of the proposed fix

Built from `master` (`89e4dc5`) with the change, with AddressSanitizer on as in the default CMake configuration:

- the new stand-alone test **fails on unpatched `master`** (`Assertion 'param_nbytes == (int) sizeof(double)' failed`) and **passes with the fix**;
- `simple_unit_tests`, `serialization_unit_tests` and `serialization_integration_tests` all pass;
- through a BMI host, setting each parameter after `initialize` gives output bit-identical to the same value set in `params.dat`, for `t0, szm, td, srmax, sr0, chv, rv`. `xk0` has no observable effect on output in these runs.
