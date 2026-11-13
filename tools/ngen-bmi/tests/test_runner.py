"""Runner and RunResult, with a stand-in ngen script."""

import pandas as pd
import pytest

from ngen_bmi import NgenRunError, find_ngen
from ngen_bmi.runner import check_features, ngen_info, required_features, scan_log

LOG = """\
NGen Framework 0.3.0
Exception setting parameter value: bad
Skipping parameter: satdk
Cannot pass parameter of type String as a BMI parameter, skipping refkdt
Cannot pass non-numeric lists as a BMI parameter, skipping SMCMAX
"""


def test_scan_log():
    assert scan_log(LOG) == ["satdk", "refkdt", "SMCMAX"]
    assert scan_log("all good\n") == []


def test_find_ngen(fake_ngen, monkeypatch, tmp_path):
    assert find_ngen() == fake_ngen
    assert find_ngen(fake_ngen) == fake_ngen
    with pytest.raises(FileNotFoundError, match="ngen="):
        find_ngen(tmp_path / "missing")
    monkeypatch.setenv("NGEN_BIN", str(tmp_path / "missing"))
    with pytest.raises(FileNotFoundError, match="NGEN_BIN"):
        find_ngen()


def test_required_and_checked_features(fake_ngen, monkeypatch, load):
    p = load()
    need = required_features(p.realization, ["a.gpkg"])
    assert need == ["NGEN_WITH_BMI_C", "NGEN_WITH_BMI_FORTRAN", "NGEN_WITH_ROUTING",
                    "NGEN_WITH_SQLITE"]
    assert ngen_info(fake_ngen) == {"NGEN_WITH_BMI_C": "ON", "NGEN_WITH_BMI_FORTRAN": "ON"}
    with pytest.raises(NgenRunError, match="drop_routing=True"):
        check_features(fake_ngen, need)
    check_features(fake_ngen, ["NGEN_WITH_BMI_C"])


def test_run_writes_reads_and_uses_root_as_cwd(load, fake_ngen, project_dir, tmp_path):
    p = load()
    p.module("cfe").set(satdk=2e-5)
    run = p.run(tmp_path / "run", validate=False, drop_routing=True)
    assert f"cwd={project_dir}" in run.log.read_text()
    assert run.catchment_ids() == ["cat-1", "cat-2", "cat-3"]
    assert run.nexus_ids() == ["nex-1"]
    cat = run.catchment("cat-2")
    assert list(cat.columns) == ["Time Step", "Time", "Q_OUT"]
    assert cat["Time"].dtype.kind == "M" and cat["Q_OUT"].tolist() == [0.5, 0.25]
    nex = run.nexus("nex-1")
    assert list(nex.columns) == ["time_index", "time", "flow"]
    assert nex["flow"].tolist() == [1.5, 1.25]
    assert nex["time"].iloc[1] == pd.Timestamp("2015-12-01 01:00:00")
    with pytest.raises(FileNotFoundError):
        run.catchment("cat-9")


def test_run_dir_protection(load, fake_ngen, tmp_path):
    p = load()
    p.run(tmp_path / "run", validate=False, drop_routing=True)
    with pytest.raises(FileExistsError, match="overwrite=True"):
        p.run(tmp_path / "run", validate=False, drop_routing=True)
    p.run(tmp_path / "run", validate=False, drop_routing=True, overwrite=True)
    other = tmp_path / "precious"
    other.mkdir()
    (other / "notes.txt").write_text("keep")
    with pytest.raises(FileExistsError, match="not removing"):
        p.run(other, validate=False, drop_routing=True, overwrite=True)
    assert (other / "notes.txt").read_text() == "keep"


def test_routing_needs_the_feature(load, fake_ngen, tmp_path):
    with pytest.raises(NgenRunError, match="NGEN_WITH_ROUTING"):
        load().run(tmp_path / "run", validate=False)


def test_nonzero_exit_raises_with_log_tail(load, fake_ngen, monkeypatch, tmp_path):
    monkeypatch.setenv("FAKE_NGEN_EXIT", "3")
    monkeypatch.setenv("FAKE_NGEN_LOG", "something broke")
    with pytest.raises(NgenRunError, match="status 3(.|\n)*something broke") as err:
        load().run(tmp_path / "run", validate=False, drop_routing=True)
    assert err.value.log == tmp_path / "run/ngen.log"


def test_skipped_parameter_raises(load, fake_ngen, monkeypatch, tmp_path):
    monkeypatch.setenv("FAKE_NGEN_LOG", "Skipping parameter: satdk")
    with pytest.raises(NgenRunError, match="skipped parameter.*satdk"):
        load().run(tmp_path / "run", validate=False, drop_routing=True)


def test_run_validates_first(load, fake_ngen, fake_model, tmp_path):
    p = load()
    p.module("cfe").set(satdk=2e-5)
    fake_model.readback_scale = 2.0
    from ngen_bmi import ValidationError
    with pytest.raises(ValidationError):
        p.run(tmp_path / "run", drop_routing=True)
    assert not (tmp_path / "run/ngen.log").exists()
