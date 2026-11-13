"""Reading and editing an ngen realization config (a plain JSON dict).

Locations are tuples of keys and indices relative to a block that holds
``formulations`` (``global`` or a ``catchments.<id>`` entry), e.g.
``("formulations", 0, "params", "modules", 3, "params")``.
"""

from __future__ import annotations

import copy
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterator, Tuple

__all__ = ["ID_PATTERN", "Location", "ModuleRef", "iter_modules", "get_at", "absolutize",
           "resolve_id", "catchment_override"]

ID_PATTERN = "{{id}}"
Location = Tuple[Any, ...]

# Formulation params holding paths that ngen resolves from its working directory.
_PARAM_PATH_KEYS = ("library_file", "init_config", "forcing_file")
_NOT_A_PATH = ("", "/dev/null")


@dataclass(frozen=True)
class ModuleRef:
    location: Location        # of the module's "params" dict, relative to the global block
    name: str                 # formulation name: bmi_c, bmi_fortran, ...
    model_type_name: str
    in_multi: bool            # inside a bmi_multi formulation


def iter_modules(block: Dict) -> Iterator[ModuleRef]:
    """Every BMI module in ``block``'s formulations, descending into ``bmi_multi``."""
    for i, form in enumerate(block.get("formulations", [])):
        params = form.get("params", {})
        if form.get("name") == "bmi_multi":
            for j, mod in enumerate(params.get("modules", [])):
                yield ModuleRef(("formulations", i, "params", "modules", j, "params"),
                                mod.get("name", ""), mod.get("params", {}).get("model_type_name", ""),
                                True)
        else:
            yield ModuleRef(("formulations", i, "params"), form.get("name", ""),
                            params.get("model_type_name", ""), False)


def get_at(obj: Any, location: Location) -> Any:
    for step in location:
        obj = obj[step]
    return obj


def _absolute(value: str, root: Path) -> str:
    if not isinstance(value, str) or value in _NOT_A_PATH or os.path.isabs(value):
        return value
    return os.path.normpath(os.path.join(str(root), value))


def _absolutize_params(params: Dict, root: Path) -> None:
    for key in _PARAM_PATH_KEYS:
        if key in params:
            params[key] = _absolute(params[key], root)
    for mod in params.get("modules", []):
        _absolutize_params(mod.get("params", {}), root)


def _absolutize_block(block: Dict, root: Path) -> None:
    for form in block.get("formulations", []):
        _absolutize_params(form.get("params", {}), root)
    forcing = block.get("forcing")
    if isinstance(forcing, dict) and "path" in forcing:
        forcing["path"] = _absolute(forcing["path"], root)


def absolutize(realization: Dict, root: Path) -> Dict:
    """A copy with every relative path made absolute against ``root``.

    ``{{id}}`` patterns are kept. ``/dev/null`` and empty strings are left alone.
    """
    out = copy.deepcopy(realization)
    root = Path(root)
    _absolutize_block(out.get("global", {}), root)
    for block in out.get("catchments", {}).values():
        _absolutize_block(block, root)
    routing = out.get("routing")
    if isinstance(routing, dict) and "t_route_config_file_with_path" in routing:
        routing["t_route_config_file_with_path"] = _absolute(
            routing["t_route_config_file_with_path"], root)
    return out


def resolve_id(value: str, catchment: str) -> str:
    return value.replace(ID_PATTERN, catchment)


def catchment_override(global_block: Dict, catchment: str) -> Dict:
    """A ``catchments.<id>`` entry that starts as a copy of ``global_block``.

    It carries its own ``forcing`` (ngen throws "No forcing definition" without
    one). ngen substitutes ``{{id}}`` only in ``global`` and inside ``bmi_multi``
    modules (``Formulation_Manager.hpp``, ``Bmi_Multi_Formulation.hpp``), so the
    ``init_config`` of a single-module formulation is resolved here.
    """
    entry = {"formulations": copy.deepcopy(global_block["formulations"])}
    if "forcing" in global_block:
        entry["forcing"] = copy.deepcopy(global_block["forcing"])
    for form in entry["formulations"]:
        params = form.get("params", {})
        if form.get("name") != "bmi_multi" and isinstance(params.get("init_config"), str):
            params["init_config"] = resolve_id(params["init_config"], catchment)
    return entry
