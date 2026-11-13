"""ngen integration (``-m ngen``): model_params vs config edits, and wrapper vs ngen parity.

Needs ``cmake_build/ngen`` (or ``$NGEN_BIN``) built with BMI C and Fortran, the
CFE, Noah, PET, SLoTH and TOPMODEL libraries ngen's examples point at, and the
pymt_* wrappers. Runs the 5-catchment gauge_01073000 example for 720 hours.

"Identical" means every output column of every catchment is equal, with
outputs written at 25 significant digits.
"""

import re
import shutil
from pathlib import Path

import numpy as np
import pytest

from ngen_bmi import INIT_CONFIG, MODEL_PARAMS, NgenRunError, Project, find_ngen
from ngen_bmi.registry import REPO_ROOT

pytestmark = pytest.mark.ngen

GAUGE = REPO_ROOT / "data/gauge_01073000"
REALIZATION = GAUGE / "example_bmi_multi_realization_config_w_routing.json"
GPKG = GAUGE / "gauge_01073000.gpkg"
CAT = "cat-11223"
OUTPUTS = ["Q_OUT", "RAIN_RATE", "QINSUR", "SNEQV", "ETRAN", "SOIL_STORAGE", "GW_STORAGE", "ACTUAL_ET",
           "POTENTIAL_ET", "DEEP_GW_TO_CHANNEL_FLUX", "water_potential_evaporation_flux"]


def _prerequisites():
    try:
        find_ngen()
    except FileNotFoundError as err:
        return str(err)
    for mod in ("pymt_cfe", "pymt_noah_owp", "pymt_pet"):
        try:
            __import__(mod)
        except ImportError:
            return f"{mod} is not installed"
    if not GPKG.is_file():
        return f"{GPKG} is missing"
    return None


_missing = _prerequisites()
if _missing:
    pytest.skip(f"ngen integration prerequisites: {_missing}", allow_module_level=True)


@pytest.fixture(scope="module")
def runs(tmp_path_factory):
    return tmp_path_factory.mktemp("runs")


def load(outputs=OUTPUTS) -> Project:
    p = Project.load(REALIZATION, hydrofabric=GPKG, root=REPO_ROOT)
    multi = p.realization["global"]["formulations"][0]["params"]
    multi["output_variables"] = list(outputs)
    multi["output_precision"] = 25
    return p


def results(project: Project, run_dir: Path):
    run = project.run(run_dir, drop_routing=True, overwrite=True)
    return {cat: run.catchment(cat).drop(columns=["Time"]) for cat in run.catchment_ids()}


def identical(a, b) -> bool:
    return a.keys() == b.keys() and all(a[c].equals(b[c]) for c in a)


def worst_rel(a, b) -> float:
    worst = 0.0
    for c in a:
        x, y = a[c].to_numpy(float), b[c].to_numpy(float)
        scale = np.maximum(np.abs(x).max(axis=0), 1e-300)
        worst = max(worst, float((np.abs(x - y).max(axis=0) / scale).max()))
    return worst


@pytest.fixture(scope="module")
def base(runs):
    return results(load(), runs / "base")


# ------------------------------------------------ CFE: model_params equal a config edit
@pytest.mark.parametrize("name,value", [("satdk", 2.0e-05), ("refkdt", 3.0), ("b", 8.0),
                                        ("maxsmc", 0.40)])
def test_cfe_model_params_equal_config_edit(runs, base, name, value):
    a = load()
    a.module("cfe").set(**{name: value})
    assert a.changes[0].route == MODEL_PARAMS
    b = load()
    b.module("cfe").set(route=INIT_CONFIG, **{name: value})
    ra, rb = results(a, runs / f"{name}_mp"), results(b, runs / f"{name}_cfg")
    assert identical(ra, rb), f"model_params vs config edit: worst rel {worst_rel(ra, rb):.3g}"
    assert not identical(ra, base), f"{name}={value} had no effect"


def test_cfe_max_gw_storage_goes_through_the_config(runs, base):
    """Catalog says `differs` (CFE's Set_value bug): the default route edits the config."""
    p = load()
    p.module("cfe").set(max_gw_storage=0.02)
    assert p.changes[0].route == INIT_CONFIG
    ra = results(p, runs / "gwmax_route")
    # The same edit made by hand, outside ngen_bmi.
    hand = runs / "gwmax_hand_configs"
    hand.mkdir(exist_ok=True)
    for f in (GAUGE / "CFE").glob("*_bmi_config_cfe_pass.txt"):
        text, n = re.subn(r"^max_gw_storage=[^\[\n]*", "max_gw_storage=0.02", f.read_text(),
                          flags=re.M)
        assert n == 1
        (hand / f.name).write_text(text)
    b = load()
    b.module("cfe").params["init_config"] = str(hand / "{{id}}_bmi_config_cfe_pass.txt")
    rb = results(b, runs / "gwmax_hand")
    assert identical(ra, rb)
    assert not identical(ra, base)


def test_one_catchment_only(runs, base):
    """A catchment override changes that catchment and nothing else."""
    one = load()
    one.module("cfe").set(refkdt=3.0, catchments=[CAT])
    every = load()
    every.module("cfe").set(refkdt=3.0)
    r_one, r_all = results(one, runs / "refkdt_one"), results(every, runs / "refkdt_all")
    assert r_one[CAT].equals(r_all[CAT])
    assert not r_one[CAT].equals(base[CAT])
    for cat in base:
        if cat != CAT:
            assert r_one[cat].equals(base[cat]), cat


# ----------------------------------------------- Noah: model_params equal a table edit
def _noah_table_variant(root: Path, column: str, value: float) -> str:
    """Copies of the Noah inputs whose SOILPARM.TBL has ``column`` = ``value`` for every class."""
    shutil.copytree(GAUGE / "NOAH/parameters", root / "parameters", dirs_exist_ok=True)
    tbl = root / "parameters/SOILPARM.TBL"
    lines = tbl.read_text().splitlines()
    header = re.findall(r"[A-Z0-9]+", lines[2].split("'")[1])
    col = header.index(column) + 1
    for i, line in enumerate(lines):
        parts = line.split(",")
        if i >= 3 and len(parts) > col and parts[0].strip().isdigit():
            parts[col] = f"   {value!r}"
            lines[i] = ",".join(parts)
    tbl.write_text("\n".join(lines) + "\n")
    for f in (GAUGE / "NOAH").glob("cat-*.input"):
        text = re.sub(r'parameter_dir\s*=\s*"[^"]*"', f'parameter_dir = "{root}/parameters/"',
                      f.read_text())
        (root / f.name).write_text(text)
    return str(root / "{{id}}.input")


@pytest.mark.parametrize("name,column,value", [("SMCMAX", "MAXSMC", 0.40), ("BEXP", "BB", 7.0)])
def test_noah_scalar_is_written_as_layers_and_equals_table_edit(runs, base, name, column, value):
    a = load()
    a.module("noah").set(**{name: value})
    ra = results(a, runs / f"noah_{name}")
    written = (runs / f"noah_{name}/realization.json").read_text()
    assert f'"{name}": [\n' in written                    # a list, one value per layer
    b = load()
    b.module("noah").params["init_config"] = _noah_table_variant(runs / f"noah_{name}_tbl",
                                                                 column, value)
    rb = results(b, runs / f"noah_{name}_tbl_run")
    assert identical(ra, rb), f"worst rel {worst_rel(ra, rb):.3g}"
    assert not identical(ra, base)


# ------------------------------------------------------------------ PET (config only)
def test_pet_config_route(runs, base):
    # zero_plane_displacement_height_m feeds the combination method (pet_method=3 here).
    # vegetation_height_m would not do: PET reads it but no method uses it.
    p = load()
    p.module("pet").set(zero_plane_displacement_height_m=0.001)
    assert p.changes[0].route == INIT_CONFIG
    r = results(p, runs / "pet_zpd")
    assert not identical(r, base)
    assert "zero_plane_displacement_height_m=0.001\n" in \
        (runs / f"pet_zpd/configs/pet/{CAT}_pet_config.txt").read_text()


# ------------------------------------------------------------------ failures are loud
def test_parameter_ngen_skips_raises(runs):
    p = load()
    p.module("cfe").params["model_params"] = {"satdk": "not a number"}
    with pytest.raises(NgenRunError, match="skipped parameter.*satdk"):
        p.run(runs / "bad_string", validate=False, drop_routing=True, overwrite=True)


def test_unknown_parameter_raises(runs):
    p = load()
    p.module("cfe").params["model_params"] = {"no_such_parameter": 1.0}
    with pytest.raises(NgenRunError):
        p.run(runs / "bad_name", validate=False, drop_routing=True, overwrite=True)


# ------------------------------------------------- the wrapper reproduces ngen (CFE)
def test_cfe_wrapper_matches_ngen(base):
    """CFE in the wrapper, fed what ngen fed it, reproduces ngen's CFE outputs."""
    from bmi_setup import open_model
    ng = base[CAT]
    cols = ["RAIN_RATE", "Q_OUT", "SOIL_STORAGE", "GW_STORAGE", "DEEP_GW_TO_CHANNEL_FLUX", "ACTUAL_ET"]
    rec = {c: [] for c in cols}
    with open_model("cfe", GAUGE / f"CFE/{CAT}_bmi_config_cfe_pass.txt", workdir=REPO_ROOT) as m:
        for t in range(len(ng)):
            # CFE's own record of its inputs (per hour step), not Noah's QINSUR and PET's
            # flux: ngen prints those with only ~9 significant digits.
            m.set("atmosphere_water__liquid_equivalent_precipitation_rate",
                  ng["RAIN_RATE"].iloc[t] * 1000.0)                   # m h-1 -> mm h-1
            m.set("water_potential_evaporation_flux", ng["POTENTIAL_ET"].iloc[t] / 3600.0)  # m s-1
            for v in ("ice_fraction_schaake", "ice_fraction_xinanjiang", "soil_moisture_profile"):
                m.set(v, 0.0)
            m.update()
            for c in cols:
                rec[c].append(float(m.get(c)[0]))
    for c in cols:
        a, b = ng[c].to_numpy(float), np.array(rec[c])
        rel = np.abs(a - b).max() / max(np.abs(a).max(), 1e-300)
        # Feeding the inputs back costs a rounding (x1000, /3600); measured worst 5e-13.
        assert rel < 1e-11, f"{c}: worst rel {rel:.3g}"


# ------------------------------------------------------------------ TOPMODEL
TOPMODEL_DATA = REPO_ROOT / "extern/topmodel/topmodel/data"


@pytest.fixture(scope="module")
def topmodel_run_file(runs):
    """A framework-mode .run file (forcing through BMI, as under ngen)."""
    if not (TOPMODEL_DATA / "params.dat").is_file():
        pytest.skip("TOPMODEL sources are not checked out")
    pytest.importorskip("pymt_topmodel")
    d = runs / "topmodel_cfg"
    d.mkdir(exist_ok=True)
    shutil.copy(TOPMODEL_DATA / "params.dat", d / "params.dat")
    (d / "topmod.run").write_text(
        f"0\nngen_bmi integration test\n{TOPMODEL_DATA}/inputs.dat\n{TOPMODEL_DATA}/subcat.dat\n"
        f"{d}/params.dat\n{d}/topmod.out\n{d}/hyd.out\n")
    return d / "topmod.run"


def load_topmodel(run_file: Path) -> Project:
    p = load(["Qout", "QINSUR", "water_potential_evaporation_flux"])
    mods = p.realization["global"]["formulations"][0]["params"]["modules"]
    cfe = next(m for m in mods if m["params"]["model_type_name"] == "bmi_c_cfe")
    cfe["params"] = {
        "model_type_name": "bmi_c_topmodel",
        "library_file": str(REPO_ROOT / "extern/topmodel/cmake_build/libtopmodelbmi.so"),
        "registration_function": "register_bmi_topmodel",
        "init_config": str(run_file),
        "allow_exceed_end_time": True,
        "main_output_variable": "Qout",
        "uses_forcing_file": False,
        "variables_names_map": {
            "water_potential_evaporation_flux": "water_potential_evaporation_flux",
            "atmosphere_water__liquid_equivalent_precipitation_rate": "QINSUR"},
    }
    p.realization["global"]["formulations"][0]["params"]["main_output_variable"] = "Qout"
    return p


@pytest.mark.parametrize("name,value", [("t0", 3.0), ("szm", 0.05)])
def test_topmodel_model_params_equal_config_edit(runs, topmodel_run_file, name, value):
    base_tm = results(load_topmodel(topmodel_run_file), runs / "tm_base")
    a = load_topmodel(topmodel_run_file)
    a.module("topmodel").set(**{name: value})
    b = load_topmodel(topmodel_run_file)
    b.module("topmodel").set(route=INIT_CONFIG, **{name: value})
    ra, rb = results(a, runs / f"tm_{name}_mp"), results(b, runs / f"tm_{name}_cfg")
    assert identical(ra, rb), f"worst rel {worst_rel(ra, rb):.3g}"
    assert not identical(ra, base_tm), f"{name}={value} had no effect"
