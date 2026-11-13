"""Project: module lookup, routes, and what write() puts on disk (no native code)."""

import json

import numpy as np
import pytest
from bmi_setup import Parameter, load_catalog

from conftest import CATS, CFE_CONFIG, NOAH_CONFIG, module_params, read_json, single_realization
from ngen_bmi import (INIT_CONFIG, MODEL_PARAMS, NotSettable, ValidationError,
                      ValidationWarning, choose_route)
from ngen_bmi.project import _normalize
from ngen_bmi.registry import keys_for_model_type, load_registry


# ------------------------------------------------------------------ registry and lookup
def test_registry_links_the_four_models_to_bmi_setup():
    reg = load_registry()
    assert {k: reg[k].get("bmi_setup_key") for k in ("cfe", "noah", "pet", "topmodel")} == \
        {"cfe": "cfe", "noah": "noah", "pet": "pet", "topmodel": "topmodel"}
    assert keys_for_model_type("PET", reg) == ["pet"]          # case-insensitive
    assert keys_for_model_type("bmi_c++_sloth", reg) == []


def test_module_lookup(load):
    p = load()
    assert p.modules() == {"pet": "PET", "noah": "bmi_fortran_noahowp", "cfe": "bmi_c_cfe"}
    cfe = p.module("cfe")
    assert cfe.ref.location == ("formulations", 0, "params", "modules", 2, "params")
    with pytest.raises(KeyError, match="no module for 'topmodel'"):
        p.module("topmodel")


def test_duplicate_module_is_an_error(load, project_dir):
    real = json.loads((project_dir / "realization.json").read_text())
    mods = real["global"]["formulations"][0]["params"]["modules"]
    mods.append(json.loads(json.dumps(mods[2])))
    with pytest.raises(KeyError, match="matches 2 modules"):
        load(real).module("cfe")


def test_registry_entry_without_bmi_setup_key(load):
    reg = load_registry()
    del reg["cfe"]["bmi_setup_key"]
    with pytest.raises(KeyError, match="no bmi_setup_key"):
        load(registry=reg).module("cfe")


def test_existing_catchment_overrides_are_refused(load, project_dir):
    real = json.loads((project_dir / "realization.json").read_text())
    real["catchments"] = {"cat-1": real["global"]}
    with pytest.raises(NotImplementedError):
        load(real)


def test_paths_are_made_absolute(load, project_dir):
    p = load()
    g = p.realization["global"]
    assert module_params(g, "bmi_c_cfe")["init_config"] == str(project_dir / "cfe/{{id}}_cfe.txt")
    assert module_params(g, "PET")["library_file"] == str(project_dir / "lib/libPET.so")
    assert g["formulations"][0]["params"]["init_config"] == ""
    assert g["forcing"]["path"] == str(project_dir / "forcing")
    assert p.realization["routing"]["t_route_config_file_with_path"] == str(project_dir / "routing.yaml")


def test_catchment_ids_from_geojson_and_gpkg(load):
    from ngen_bmi import Hydrofabric
    from ngen_bmi.registry import REPO_ROOT
    assert load().catchment_ids() == CATS
    gpkg = REPO_ROOT / "data/gauge_01073000/gauge_01073000.gpkg"
    if gpkg.is_file():
        assert sorted(Hydrofabric.from_args(gpkg).catchment_ids()) == \
            ["cat-11223", "cat-11224", "cat-11371", "cat-11410", "cat-11509"]
    with pytest.raises(ValueError):
        Hydrofabric.from_args(gpkg, catchments=gpkg)


# ------------------------------------------------------------------ routes and values
@pytest.mark.parametrize("model,name,route", [
    ("cfe", "satdk", MODEL_PARAMS),            # equivalent
    ("cfe", "Klf", MODEL_PARAMS),              # unexercised
    ("cfe", "max_gw_storage", INIT_CONFIG),    # differs, has a config key
    ("cfe", "giuh_ordinates", INIT_CONFIG),    # config only
    ("noah", "AXAJ", MODEL_PARAMS),            # untested
    ("pet", "vegetation_height_m", INIT_CONFIG),
])
def test_default_route_from_catalog(model, name, route):
    assert choose_route(load_catalog(model)[name]) == route


def test_forced_routes():
    cfe, pet, noah = load_catalog("cfe"), load_catalog("pet"), load_catalog("noah")
    assert choose_route(cfe["satdk"], INIT_CONFIG) == INIT_CONFIG
    assert choose_route(cfe["max_gw_storage"], MODEL_PARAMS) == MODEL_PARAMS
    with pytest.raises(NotSettable, match="not a BMI variable"):
        choose_route(pet["vegetation_height_m"], MODEL_PARAMS)
    with pytest.raises(NotSettable, match="no config key"):
        choose_route(noah["SMCMAX"], INIT_CONFIG)
    with pytest.raises(NotSettable, match="differ"):
        choose_route(Parameter("x", "differs", "float64"))
    with pytest.raises(ValueError):
        choose_route(cfe["satdk"], "somewhere")


def test_normalize_values():
    f = Parameter("f", "equivalent", "float64")
    i = Parameter("i", "equivalent", "int32")
    v3 = Parameter("v", "equivalent", "float32", length=3)
    assert _normalize(f, np.float32(0.5)) == 0.5 and type(_normalize(f, 2)) is float
    assert _normalize(i, 3.0) == 3 and type(_normalize(i, 3.0)) is int
    assert _normalize(v3, (1, 2, 3)) == [1.0, 2.0, 3.0]
    with pytest.raises(TypeError, match="integer"):
        _normalize(i, 1.5)
    with pytest.raises(ValueError, match="3 element"):
        _normalize(v3, [1, 2])
    with pytest.raises(ValueError, match="finite"):
        _normalize(f, float("nan"))
    for bad in ("1.0", True, [[1.0]]):
        with pytest.raises(TypeError):
            _normalize(f, bad)


def test_set_checks_names_and_catchments(load):
    cfe = load().module("cfe")
    with pytest.raises(KeyError, match="no parameter 'nope'"):
        cfe.set(nope=1.0)
    with pytest.raises(KeyError, match="cat-9"):
        cfe.set(satdk=1e-5, catchments=["cat-9"])
    with pytest.raises(NotSettable):
        load().module("pet").set(vegetation_height_m=3.0, route=MODEL_PARAMS)
    assert [c.route for c in cfe.set(satdk=1e-5, max_gw_storage=0.02).changes] == \
        [MODEL_PARAMS, INIT_CONFIG]


# ------------------------------------------------------------------ write()
def test_global_model_params(load, tmp_path, project_dir):
    p = load()
    p.module("cfe").set(satdk=2e-5, b=8)
    p.module("noah").set(SMCMAX=0.4, BEXP=[7.0, 7.0, 6.0, 6.0])
    real = read_json(p.write(tmp_path / "run"))
    g = real["global"]
    assert module_params(g, "bmi_c_cfe")["model_params"] == \
        {"refkdt": {"source": "hydrofabric"}, "satdk": 2e-5, "b": 8.0}     # hydrofabric kept
    assert module_params(g, "bmi_fortran_noahowp")["model_params"] == \
        {"SMCMAX": [0.4] * 4, "BEXP": [7.0, 7.0, 6.0, 6.0]}                # nsoil from the config
    assert module_params(g, "bmi_c_cfe")["init_config"] == str(project_dir / "cfe/{{id}}_cfe.txt")
    assert "catchments" not in real
    assert real["output_root"] == str(tmp_path / "run") + "/"
    assert "routing" in real
    assert "routing" not in read_json(p.write(tmp_path / "run2", drop_routing=True))
    assert json.loads((tmp_path / "run/changes.json").read_text())[0]["name"] == "satdk"


def test_layer_count_must_agree_across_catchments(load, project_dir, tmp_path):
    (project_dir / "noah/cat-2.input").write_text(NOAH_CONFIG.format(nsoil=3))
    p = load()
    p.module("noah").set(SMCMAX=0.4)
    with pytest.raises(ValueError, match="differs between catchments"):
        p.write(tmp_path / "run")
    p.clear_changes()
    p.module("noah").set(SMCMAX=0.4, catchments=["cat-2"])
    real = read_json(p.write(tmp_path / "run"))
    assert module_params(real["catchments"]["cat-2"], "bmi_fortran_noahowp")["model_params"] == \
        {"SMCMAX": [0.4] * 3}


def test_config_route_with_id_template(load, tmp_path, project_dir):
    p = load()
    p.module("cfe").set(max_gw_storage=0.02)
    p.module("cfe").set(max_gw_storage=0.03, gw_storage=0.5, catchments=["cat-2"])
    p.module("pet").set(vegetation_height_m=12.0)
    run = tmp_path / "run"
    real = read_json(p.write(run))
    assert "catchments" not in real          # per-catchment config edits need no override
    assert module_params(real["global"], "bmi_c_cfe")["init_config"] == \
        str(run / "configs/cfe/{{id}}_cfe.txt")
    for cat, gw_max, gw in (("cat-1", "0.02", "0.35"), ("cat-2", "0.03", "0.5"),
                            ("cat-3", "0.02", "0.35")):
        text = (run / f"configs/cfe/{cat}_cfe.txt").read_text()
        assert f"max_gw_storage={gw_max}[m]\n" in text and f"gw_storage={gw}[m/m]\n" in text
    assert (run / "configs/pet/cat-3_pet.txt").read_text() == \
        "verbose=0\nvegetation_height_m=12.0\nsite_elevation_m=100.0\n"
    assert (project_dir / "cfe/cat-1_cfe.txt").read_text() == CFE_CONFIG   # inputs untouched


def test_unchanged_catchments_are_copied_byte_for_byte(load, tmp_path, project_dir):
    p = load()
    p.module("cfe").set(max_gw_storage=0.03, catchments=["cat-1"])
    run = tmp_path / "run"
    p.write(run)
    assert (run / "configs/cfe/cat-3_cfe.txt").read_bytes() == \
        (project_dir / "cfe/cat-3_cfe.txt").read_bytes()


def test_id_in_directory_part_of_template(load, project_dir, tmp_path):
    for c in CATS:
        (project_dir / "cfe" / c).mkdir()
        (project_dir / "cfe" / c / "cfe.txt").write_text(CFE_CONFIG)
    real = json.loads((project_dir / "realization.json").read_text())
    real["global"]["formulations"][0]["params"]["modules"][2]["params"]["init_config"] = \
        "./cfe/{{id}}/cfe.txt"
    p = load(real)
    p.module("cfe").set(max_gw_storage=0.02)
    run = tmp_path / "run"
    out = read_json(p.write(run))
    assert module_params(out["global"], "bmi_c_cfe")["init_config"] == \
        str(run / "configs/cfe/{{id}}/cfe.txt")
    assert "max_gw_storage=0.02[m]" in (run / "configs/cfe/cat-2/cfe.txt").read_text()


def test_catchment_model_params_become_an_override(load, tmp_path):
    p = load()
    p.module("cfe").set(satdk=2e-5)
    p.module("cfe").set(refkdt=4.0, catchments=["cat-3"])
    p.module("pet").set(vegetation_height_m=12.0)
    real = read_json(p.write(tmp_path / "run"))
    assert list(real["catchments"]) == ["cat-3"]
    ovr = real["catchments"]["cat-3"]
    assert ovr["forcing"] == real["global"]["forcing"]               # ngen needs its own forcing
    assert module_params(ovr, "bmi_c_cfe")["model_params"] == \
        {"refkdt": 4.0, "satdk": 2e-5}                               # global change included
    # bmi_multi modules keep {{id}}: ngen substitutes it there itself.
    assert module_params(ovr, "PET")["init_config"].endswith("configs/pet/{{id}}_pet.txt")
    assert "refkdt" not in module_params(real["global"], "bmi_c_cfe")["model_params"] or \
        module_params(real["global"], "bmi_c_cfe")["model_params"]["refkdt"] == \
        {"source": "hydrofabric"}


def test_catchment_change_wins_over_a_later_global_one(load, tmp_path):
    p = load()
    p.module("cfe").set(satdk=1e-5, catchments=["cat-1"])
    p.module("cfe").set(satdk=2e-5)
    real = read_json(p.write(tmp_path / "run"))
    assert module_params(real["catchments"]["cat-1"], "bmi_c_cfe")["model_params"]["satdk"] == 1e-5
    assert module_params(real["global"], "bmi_c_cfe")["model_params"]["satdk"] == 2e-5


def test_catchment_config_edit_is_not_undone_by_global_model_params(load, tmp_path):
    p = load()
    p.module("cfe").set(satdk=2e-5)
    p.module("cfe").set(satdk=3e-5, catchments=["cat-2"], route=INIT_CONFIG)
    run = tmp_path / "run"
    real = read_json(p.write(run))
    assert "satdk" not in module_params(real["catchments"]["cat-2"], "bmi_c_cfe")["model_params"]
    assert "soil_params.satdk=3e-05[m s-1]" in (run / "configs/cfe/cat-2_cfe.txt").read_text()


def test_single_module_shared_config(load, tmp_path, project_dir):
    p = load(single_realization("./cfe/shared.txt"))
    p.module("cfe").set(max_gw_storage=0.02)
    p.module("cfe").set(max_gw_storage=0.05, catchments=["cat-3"])
    run = tmp_path / "run"
    real = read_json(p.write(run))
    assert real["global"]["formulations"][0]["params"]["init_config"] == \
        str(run / "configs/cfe/shared.txt")
    ovr = real["catchments"]["cat-3"]["formulations"][0]["params"]
    assert ovr["init_config"] == str(run / "configs/cfe/cat-3/shared.txt")
    assert "max_gw_storage=0.05[m]" in (run / "configs/cfe/cat-3/shared.txt").read_text()
    assert "max_gw_storage=0.02[m]" in (run / "configs/cfe/shared.txt").read_text()


def test_single_module_override_resolves_id(load, tmp_path, project_dir):
    p = load(single_realization("./cfe/{{id}}_cfe.txt"))
    p.module("cfe").set(satdk=2e-5, catchments=["cat-2"])
    real = read_json(p.write(tmp_path / "run"))
    ovr = real["catchments"]["cat-2"]["formulations"][0]["params"]
    assert ovr["init_config"] == str(project_dir / "cfe/cat-2_cfe.txt")
    assert real["global"]["formulations"][0]["params"]["init_config"].endswith("{{id}}_cfe.txt")


def test_missing_config_key_is_reported(load, tmp_path, project_dir):
    p = load()
    p.module("cfe").set(soil_storage=0.5)                 # catalog has it; this config does not
    with pytest.raises(KeyError, match="soil_storage"):
        p.write(tmp_path / "run")


def test_topmodel_shared_run_file(tmp_path):
    from ngen_bmi import Hydrofabric, Project
    root = tmp_path / "tm"
    (root / "data").mkdir(parents=True)
    (root / "data/topmod.run").write_text("0\nTitle\ndata/inputs.dat\ndata/subcat.dat\n"
                                          "data/params.dat\ntopmod.out\nhyd.out\n")
    (root / "data/params.dat").write_text("Title\n0.032  5.0  50.  3600.0  3600.0  0.05  "
                                          "0.0000328  0.002  0  1.0  0.02  0.1\n")
    feats = [{"type": "Feature", "id": "cat-1", "properties": {}, "geometry": None}]
    (root / "c.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": feats}))
    real = single_realization("./data/topmod.run")
    real["global"]["formulations"][0]["params"]["model_type_name"] = "bmi_c_topmodel"
    p = Project(real, Hydrofabric(root / "c.geojson", root / "c.geojson"), root)
    p.module("topmodel").set(Q0=0.00005)                  # config only
    run = tmp_path / "run"
    p.write(run)
    run_lines = (run / "configs/topmodel/topmod.run").read_text().splitlines()
    assert run_lines[4] == str(run / "configs/topmodel/params.dat")   # outside root: absolute
    assert run_lines[2] == "data/inputs.dat"
    assert "5e-05" in (run / "configs/topmodel/params.dat").read_text()


# ------------------------------------------------------------------ validate()
def test_validate_opens_one_instance_per_distinct_config(load, fake_model, project_dir):
    p = load()
    p.module("cfe").set(satdk=2e-5, max_gw_storage=0.02)
    p.module("cfe").set(refkdt=4.0, catchments=["cat-3"])
    assert p.validate() == []
    opened = [(m.key, m.config.name) for m in fake_model.opened]
    assert opened == [("cfe", "cat-1_cfe.txt"), ("cfe", "cat-3_cfe.txt")]
    assert all(m.workdir == project_dir for m in fake_model.opened)
    assert fake_model.opened[1].values.keys() == {"satdk", "refkdt"}


def test_validate_reports_readback_mismatch(load, fake_model):
    p = load()
    p.module("cfe").set(satdk=2e-5)
    fake_model.readback_scale = 0.5
    with pytest.raises(ValidationError, match="reads back"):
        p.validate()


def test_validate_checks_config_route_through_bmi(load, fake_model, monkeypatch):
    p = load()
    p.module("cfe").set(max_gw_storage=0.02)
    assert p.validate() == []
    from ngen_bmi import project
    real_rewrite = project.Project._rewrite
    monkeypatch.setattr(project.Project, "_rewrite",
                        lambda self, m, src, dest, edits: real_rewrite(self, m, src, dest, {}))
    with pytest.raises(ValidationError, match="config max_gw_storage"):
        p.validate()


def test_validate_warns_for_unproven_parameters(load, fake_model):
    p = load()
    p.module("cfe").set(Klf=0.05)
    with pytest.warns(ValidationWarning, match="no observable effect"):
        notes = p.validate()
    assert notes == ["cfe.Klf has had no observable effect in the equivalence test"]
