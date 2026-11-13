"""A small synthetic ngen project on disk: no ngen binary or model library needed."""

import json
import os
import stat
import sys
import textwrap
from pathlib import Path

import pytest

CATS = ["cat-1", "cat-2", "cat-3"]

CFE_CONFIG = """\
forcing_file=BMI
soil_params.b=4.05[]
soil_params.satdk=0.00000338[m s-1]
soil_params.smcmax=0.439[m/m]
refkdt=3.0
max_gw_storage=0.0129[m]
gw_storage=0.35[m/m]
giuh_ordinates=0.6,0.4
"""

NOAH_CONFIG = """\
&timing
  dt                 = 3600.0                       ! timestep [seconds]
/

&structure
  isltyp           = 3              ! soil texture class
  nsoil            = {nsoil}              ! number of soil levels
/

&forcing
  ZREF               = 10.0
  rain_snow_thresh   = 1.0                          ! rain-snow temperature threshold
/
"""

PET_CONFIG = "verbose=0\nvegetation_height_m=16.0\nsite_elevation_m=100.0\n"


def _module(name, model_type, init_config, **extra):
    params = {"model_type_name": model_type, "library_file": f"./lib/lib{model_type}.so",
              "init_config": init_config, "main_output_variable": "out",
              "uses_forcing_file": False, **extra}
    return {"name": name, "params": params}


def multi_realization():
    return {
        "global": {
            "formulations": [{
                "name": "bmi_multi",
                "params": {
                    "model_type_name": "bmi_multi_noah_pet_cfe",
                    "init_config": "",
                    "main_output_variable": "Q_OUT",
                    "modules": [
                        _module("bmi_c", "PET", "./pet/{{id}}_pet.txt"),
                        _module("bmi_fortran", "bmi_fortran_noahowp", "./noah/{{id}}.input"),
                        _module("bmi_c", "bmi_c_cfe", "./cfe/{{id}}_cfe.txt",
                                model_params={"refkdt": {"source": "hydrofabric"}}),
                    ],
                },
            }],
            "forcing": {"file_pattern": ".*{{id}}.*.csv", "path": "./forcing/",
                        "provider": "CsvPerFeature"},
        },
        "time": {"start_time": "2015-12-01 00:00:00", "end_time": "2015-12-01 02:00:00",
                 "output_interval": 3600},
        "routing": {"t_route_config_file_with_path": "./routing.yaml"},
    }


def single_realization(init_config):
    real = multi_realization()
    real["global"]["formulations"] = [_module("bmi_c", "bmi_c_cfe", init_config)]
    real.pop("routing")
    return real


def _hydrofabric(root: Path):
    feats = [{"type": "Feature", "id": c, "properties": {}, "geometry": None} for c in CATS]
    (root / "catchments.geojson").write_text(json.dumps({"type": "FeatureCollection",
                                                         "features": feats}))
    nex = [{"type": "Feature", "id": "nex-1", "properties": {}, "geometry": None}]
    (root / "nexus.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": nex}))


@pytest.fixture
def project_dir(tmp_path):
    root = tmp_path / "proj"
    for sub in ("cfe", "noah", "pet", "forcing"):
        (root / sub).mkdir(parents=True)
    for c in CATS:
        (root / "cfe" / f"{c}_cfe.txt").write_text(CFE_CONFIG)
        (root / "noah" / f"{c}.input").write_text(NOAH_CONFIG.format(nsoil=4))
        (root / "pet" / f"{c}_pet.txt").write_text(PET_CONFIG)
    (root / "cfe" / "shared.txt").write_text(CFE_CONFIG)
    _hydrofabric(root)
    (root / "realization.json").write_text(json.dumps(multi_realization(), indent=1))
    return root


@pytest.fixture
def load(project_dir):
    from ngen_bmi import Project

    def _load(realization=None, **kw):
        path = project_dir / "realization.json"
        if realization is not None:
            path = project_dir / "custom_realization.json"
            path.write_text(json.dumps(realization))
        return Project.load(path, catchments=project_dir / "catchments.geojson",
                            nexus=project_dir / "nexus.geojson", root=project_dir, **kw)
    return _load


FAKE_NGEN = textwrap.dedent("""\
    #!{python}
    # Stand-in for ngen: --info flags, then writes outputs to the realization's output_root.
    import json, os, sys
    if sys.argv[1:] == ["--info"]:
        print(os.environ.get("FAKE_NGEN_INFO", "  NGEN_WITH_BMI_C: ON\\n  NGEN_WITH_BMI_FORTRAN: ON"))
        sys.exit(0)
    real = json.load(open(sys.argv[5]))
    out = real["output_root"]
    print("cwd=" + os.getcwd())
    print(os.environ.get("FAKE_NGEN_LOG", ""))
    for cat in ("cat-1", "cat-2", "cat-3"):
        with open(out + cat + ".csv", "w") as fh:
            fh.write("Time Step,Time,Q_OUT\\n0,2015-12-01 00:00:00,0.5\\n1,2015-12-01 01:00:00,0.25\\n")
    with open(out + "nex-1_output.csv", "w") as fh:
        fh.write("0, 2015-12-01 00:00:00, 1.5\\n1, 2015-12-01 01:00:00, 1.25\\n")
    sys.exit(int(os.environ.get("FAKE_NGEN_EXIT", "0")))
""")


@pytest.fixture
def fake_ngen(tmp_path, monkeypatch):
    from ngen_bmi import runner
    runner.ngen_info.cache_clear()
    path = tmp_path / "bin" / "ngen"
    path.parent.mkdir()
    path.write_text(FAKE_NGEN.format(python=sys.executable))
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    monkeypatch.setenv("NGEN_BIN", str(path))
    yield path
    runner.ngen_info.cache_clear()


class FakeModel:
    """Stands in for bmi_setup.Model in validate(): stores what is set."""

    readback_scale = 1.0
    opened = []

    def __init__(self, key, config, workdir=None, **_):
        self.key, self.config, self.workdir = key, Path(config), Path(workdir)
        self.values = {}
        FakeModel.opened.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return None

    def set(self, name, value):
        import numpy as np
        self.values[name] = np.atleast_1d(np.asarray(value, dtype="float64")) * self.readback_scale

    def get(self, name):
        import numpy as np
        if name in self.values:
            return self.values[name]
        if name == "max_gw_storage":                    # read from the (rewritten) config
            from bmi_setup import KeyValueConfig
            return np.array([float(KeyValueConfig.read(self.config).get(name))])
        return np.array([0.0])


@pytest.fixture
def fake_model(monkeypatch):
    from ngen_bmi import project
    FakeModel.opened = []
    FakeModel.readback_scale = 1.0
    monkeypatch.setattr(project, "open_model", FakeModel)
    return FakeModel


def read_json(path):
    with open(path) as fh:
        return json.load(fh)


def module_params(block, model_type):
    for form in block["formulations"]:
        mods = form["params"].get("modules")
        for m in (mods if mods is not None else [form]):
            if m["params"]["model_type_name"] == model_type:
                return m["params"]
    raise KeyError(model_type)


os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
