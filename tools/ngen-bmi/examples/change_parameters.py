"""Worked example: change CFE, Noah-OWP and PET parameters and compare with a baseline.

Uses the 5-catchment gauge_01073000 example that ships with ngen (720 hours,
CFE + Noah-OWP + PET + SLoTH in a bmi_multi formulation). Run it from anywhere:

    python tools/ngen-bmi/examples/change_parameters.py [--out DIR]
    make -C commands ngen-bmi-example

Needs ``cmake_build/ngen`` built with BMI C and Fortran (``$NGEN_BIN`` also
works), the model libraries the realization points at, and pymt_cfe,
pymt_noah_owp and pymt_pet installed with ``bmi_setup`` and ``ngen_bmi``.
"""

import argparse
import tempfile
from pathlib import Path

import pandas as pd

from ngen_bmi import Project
from ngen_bmi.registry import REPO_ROOT

GAUGE = REPO_ROOT / "data" / "gauge_01073000"
REALIZATION = GAUGE / "example_bmi_multi_realization_config_w_routing.json"
HYDROFABRIC = GAUGE / "gauge_01073000.gpkg"
CATCHMENT = "cat-11223"


def load() -> Project:
    # root is where ngen runs and what the realization's relative paths mean.
    return Project.load(REALIZATION, hydrofabric=HYDROFABRIC, root=REPO_ROOT)


def summarize(run, label: str) -> pd.Series:
    """Total flow over the run at every nexus (m3/s summed over hourly steps)."""
    return pd.Series({nex: run.nexus(nex)["flow"].sum() for nex in run.nexus_ids()}, name=label)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path,
                        help="directory for the two runs (default: a new temporary directory)")
    args = parser.parse_args(argv)
    out = (args.out or Path(tempfile.mkdtemp(prefix="ngen_bmi_example_"))).resolve()

    project = load()
    print(project)
    print("Modules found through wrappers.json:", project.modules())

    # 1. What CFE accepts, read live from the compiled library through pymt_cfe.
    cfe = project.module("cfe")
    params = cfe.parameters(CATCHMENT)
    cols = [c for c in ("value", "units", "set_value", "route") if c in params.columns]
    print(f"\nCFE parameters for {CATCHMENT} (catalog plus live values):")
    print(params[cols].to_string())

    # 2. Baseline: the realization unchanged.
    baseline = project.run(out / "baseline", drop_routing=True, overwrite=True)

    # 3. The same realization with changes. Each takes the route the catalog
    #    allows: model_params where post-initialize set_value was shown to equal
    #    a config edit, a copied and edited init config otherwise.
    cfe.set(satdk=cfe_value(params, "satdk") * 2)          # every catchment
    cfe.set(b=8.0, catchments=[CATCHMENT])                   # one catchment
    cfe.set(max_gw_storage=0.02)                             # "differs": config edit
    project.module("noah").set(SMCMAX=0.40)                  # one value per soil layer
    project.module("pet").set(zero_plane_displacement_height_m=0.001)   # PET is config-only

    print("\nChanges and how each reaches ngen:")
    print(pd.DataFrame([c.as_dict() for c in project.changes]).to_string(index=False))

    print("\nWarnings from validate() (parameters whose effect is unproven):")
    for note in project.validate() or ["none"]:
        print("  ", note)

    changed = project.run(out / "changed", drop_routing=True, overwrite=True)

    # 4. Compare.
    table = pd.concat([summarize(baseline, "baseline"), summarize(changed, "changed")], axis=1)
    table["change %"] = 100 * (table["changed"] / table["baseline"] - 1)
    print("\nTotal nexus flow over the run:")
    print(table.round(3).to_string())

    q0 = baseline.catchment(CATCHMENT)["Q_OUT"]
    q1 = changed.catchment(CATCHMENT)["Q_OUT"]
    print(f"\n{CATCHMENT} Q_OUT: peak {q0.max():.4g} -> {q1.max():.4g}, "
          f"mean {q0.mean():.4g} -> {q1.mean():.4g}")
    print(f"\nRuns, logs, edited configs and changes.json are in {out}")
    return 0


def cfe_value(params: pd.DataFrame, name: str) -> float:
    return float(params.loc[name, "value"])


if __name__ == "__main__":
    raise SystemExit(main())
