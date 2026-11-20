"""Map paths that only exist in another environment to this checkout's builds.

Realizations made by NGIAB_data_preprocess point at the NGIAB Docker image:
``library_file`` is ``/dmod/shared_libs/<lib>``, and Noah's ``parameter_dir``
is ``/dmod/datasets/static/``. Neither exists in the devcontainer. Only a path
that does not exist is replaced, so a realization that already works is left
as it is, and the input files are never edited: library paths are changed in
the in-memory realization, and model config keys are edited in the copies
``Project`` writes into the run directory.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Callable, Dict, Iterator, Optional

from .registry import REPO_ROOT

__all__ = ["LIBRARY_DIRS", "find_library", "localize_libraries", "local_config_edits"]

# Where the extern model libraries are built (extern/<model>/cmake_build, or one
# level deeper, e.g. extern/evapotranspiration/evapotranspiration/cmake_build).
LIBRARY_DIRS = ("extern/*/cmake_build", "extern/*/*/cmake_build")


def find_library(name: str, repo_root: Optional[Path] = None) -> Optional[Path]:
    """The built library called ``name`` in this checkout, if there is one."""
    root = Path(repo_root) if repo_root is not None else REPO_ROOT
    for pattern in LIBRARY_DIRS:
        found = sorted(p for p in root.glob(f"{pattern}/{name}") if p.is_file())
        if found:
            return found[0].resolve()
    return None


def _all_params(realization: Dict) -> Iterator[Dict]:
    blocks = [realization.get("global", {}), *realization.get("catchments", {}).values()]
    for block in blocks:
        for form in block.get("formulations", []):
            params = form.get("params", {})
            yield params
            for mod in params.get("modules", []):
                yield mod.get("params", {})


def localize_libraries(realization: Dict, repo_root: Optional[Path] = None) -> Dict[str, str]:
    """Point each missing absolute ``library_file`` at the local build of the same name.

    Changes ``realization`` in place; returns {old path: new path}. A library
    with no local build is left alone, so ngen reports it when it runs.
    """
    mapping: Dict[str, str] = {}
    for params in _all_params(realization):
        lib = params.get("library_file")
        if not isinstance(lib, str) or not os.path.isabs(lib) or os.path.exists(lib):
            continue
        local = mapping.get(lib) or find_library(Path(lib).name, repo_root)
        if local is not None:
            mapping[lib] = str(local)
            params["library_file"] = str(local)
    return mapping


def local_config_edits(entry: Dict, read_value: Callable[[str], Optional[str]], root: Path,
                       repo_root: Optional[Path] = None) -> Dict[str, str]:
    """Config edits that replace missing data directories with the local ones.

    ``entry`` is the module's registry entry; its ``local_config_dirs`` maps a
    config key to a directory relative to the repo root. ``read_value(key)``
    returns the key's value from one of the module's configs (``None`` if the
    key is absent); relative values are resolved from ``root``, ngen's working
    directory.
    """
    base = Path(repo_root) if repo_root is not None else REPO_ROOT
    edits: Dict[str, str] = {}
    for key, local in entry.get("local_config_dirs", {}).items():
        value = read_value(key)
        if value is None:
            continue
        value = value.strip().strip("'\"")
        if value and (Path(root) / value).is_dir():     # an absolute value replaces root
            continue
        local_dir = (base / local).resolve()
        if local_dir.is_dir():
            edits[key] = str(local_dir) + "/"
    return edits
