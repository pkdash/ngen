"""Running the ngen binary and reading what it writes."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from collections import deque
from functools import lru_cache
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Union

import pandas as pd

from .registry import REPO_ROOT

__all__ = ["NgenRunError", "find_ngen", "ngen_info", "required_features", "check_features",
           "scan_log", "run_ngen", "RunResult"]

PathLike = Union[str, Path]

# Formulation name -> the `ngen --info` flag the binary needs for it.
_FEATURE_FOR_FORMULATION = {
    "bmi_c": "NGEN_WITH_BMI_C",
    "bmi_fortran": "NGEN_WITH_BMI_FORTRAN",
    "bmi_python": "NGEN_WITH_PYTHON",
}

# ngen catches SetValue failures and only logs these (Bmi_Module_Formulation.cpp,
# set_initial_bmi_parameters); left alone, the run would silently use the default.
_SKIPPED = re.compile(r"Skipping parameter: *(\S+)|Cannot pass .*?, skipping *(\S+)")


class NgenRunError(RuntimeError):
    """ngen failed, or ran but ignored a parameter it was given."""

    def __init__(self, message: str, log: Optional[Path] = None):
        super().__init__(message)
        self.log = log


def find_ngen(ngen: Optional[PathLike] = None) -> Path:
    """The binary: ``ngen`` argument, then ``$NGEN_BIN``, ``cmake_build/ngen``, ``PATH``."""
    def usable(p) -> bool:
        return bool(p) and Path(p).is_file() and os.access(p, os.X_OK)

    explicit = [("ngen=", ngen), ("NGEN_BIN", os.environ.get("NGEN_BIN"))]
    for label, value in explicit:
        if value:
            if not usable(value):
                raise FileNotFoundError(f"ngen binary from {label} not found or not executable: "
                                        f"{value}")
            return Path(value).resolve()
    for c in (REPO_ROOT / "cmake_build" / "ngen", shutil.which("ngen")):
        if usable(c):
            return Path(c).resolve()
    raise FileNotFoundError("no ngen binary: pass ngen=, set NGEN_BIN, build cmake_build/ngen, "
                            "or put ngen on PATH")


@lru_cache(maxsize=None)
def ngen_info(ngen: Path) -> Dict[str, str]:
    """The ``NAME: VALUE`` lines of ``ngen --info`` (e.g. ``NGEN_WITH_BMI_C: ON``)."""
    out = subprocess.run([str(ngen), "--info"], capture_output=True, text=True, timeout=60)
    info = {}
    for line in (out.stdout + out.stderr).splitlines():
        m = re.match(r"\s*(NGEN_\w+):\s*(\S+)", line)
        if m:
            info[m.group(1)] = m.group(2)
    if not info:
        raise NgenRunError(f"`{ngen} --info` printed no build flags; is it an ngen binary?")
    return info


def required_features(realization: Dict, hydrofabric_paths: Iterable[Path]) -> List[str]:
    """The ``ngen --info`` flags this realization and hydrofabric need."""
    need = set()

    def visit(formulations):
        for form in formulations:
            if form.get("name") == "bmi_multi":
                visit(form.get("params", {}).get("modules", []))
            elif form.get("name") in _FEATURE_FOR_FORMULATION:
                need.add(_FEATURE_FOR_FORMULATION[form["name"]])

    blocks = [realization.get("global", {})] + list(realization.get("catchments", {}).values())
    for block in blocks:
        visit(block.get("formulations", []))
        if (block.get("forcing") or {}).get("provider") == "NetCDF":
            need.add("NGEN_WITH_NETCDF")
    if "routing" in realization:
        need.add("NGEN_WITH_ROUTING")
    if any(Path(p).suffix.lower() == ".gpkg" for p in hydrofabric_paths):
        need.add("NGEN_WITH_SQLITE")
    return sorted(need)


def check_features(ngen: Path, needed: Sequence[str]) -> None:
    info = ngen_info(ngen)
    missing = [f for f in needed if info.get(f, "OFF").upper() != "ON"]
    if not missing:
        return
    msg = f"{ngen} was built without {', '.join(missing)}, which this realization needs"
    if "NGEN_WITH_ROUTING" in missing:
        msg += "; run(drop_routing=True) runs without the realization's routing block"
    raise NgenRunError(msg)


def scan_log(text: str) -> List[str]:
    """Parameter names ngen logged as skipped."""
    return [a or b for a, b in _SKIPPED.findall(text)]


def _tail(path: Path, n: int = 50) -> str:
    with open(path, errors="replace") as fh:
        return "".join(deque(fh, maxlen=n))


def run_ngen(ngen: Path, hydrofabric, realization_path: Path, log_path: Path, cwd: Path,
             timeout: Optional[float] = None) -> None:
    """Run ngen on every catchment and nexus; output and errors go to ``log_path``."""
    cmd = [str(ngen), str(hydrofabric.catchments), "all", str(hydrofabric.nexus), "all",
           str(realization_path)]
    with open(log_path, "w") as log:
        log.write("$ " + " ".join(cmd) + f"\n# cwd: {cwd}\n")
        log.flush()
        proc = subprocess.run(cmd, cwd=str(cwd), stdout=log, stderr=subprocess.STDOUT,
                              timeout=timeout)
    if proc.returncode != 0:
        raise NgenRunError(f"ngen exited with status {proc.returncode}; last lines of {log_path}:\n"
                           + _tail(log_path), log_path)
    skipped = scan_log(log_path.read_text(errors="replace"))
    if skipped:
        raise NgenRunError(f"ngen skipped parameter(s) {', '.join(sorted(set(skipped)))}: their "
                           f"values were not applied, so the results are not what was asked for. "
                           f"See {log_path}", log_path)


class RunResult:
    """The outputs of one run in ``run_dir``, read when asked for."""

    def __init__(self, run_dir: PathLike):
        self.run_dir = Path(run_dir)
        self.realization = self.run_dir / "realization.json"
        self.log = self.run_dir / "ngen.log"

    def __repr__(self) -> str:
        return f"<RunResult {self.run_dir}>"

    def catchment_ids(self) -> List[str]:
        return sorted(p.stem for p in self.run_dir.glob("cat-*.csv"))

    def nexus_ids(self) -> List[str]:
        return sorted(p.name[: -len("_output.csv")] for p in self.run_dir.glob("nex-*_output.csv"))

    def catchment(self, catchment_id: str) -> pd.DataFrame:
        """``<id>.csv``: a header row, then ``Time Step, Time`` and the output variables."""
        path = self.run_dir / f"{catchment_id}.csv"
        if not path.is_file():
            raise FileNotFoundError(f"no output for {catchment_id} in {self.run_dir}")
        df = pd.read_csv(path)
        df.columns = [c.strip() for c in df.columns]
        if "Time" in df.columns:
            df["Time"] = pd.to_datetime(df["Time"])
        return df

    def nexus(self, nexus_id: str) -> pd.DataFrame:
        """``<id>_output.csv``: no header; ``time_index, time, flow`` (SurfaceLayer.cpp)."""
        path = self.run_dir / f"{nexus_id}_output.csv"
        if not path.is_file():
            raise FileNotFoundError(f"no output for {nexus_id} in {self.run_dir}")
        df = pd.read_csv(path, header=None, names=["time_index", "time", "flow"],
                         skipinitialspace=True)
        df["time"] = pd.to_datetime(df["time"])
        return df
