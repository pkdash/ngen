"""The ngen-side model registry, ``tools/bmi-wrappers/wrappers.json``.

It maps a realization's ``model_type_name`` to a registry key, and the key to
its ``bmi_setup`` model (``bmi_setup_key``). Parameter metadata and routing
rules come from the ``bmi_setup`` catalog, not from here.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional, Union

__all__ = ["REPO_ROOT", "REGISTRY_PATH", "load_registry", "matches_model_type",
           "keys_for_model_type"]

# tools/ngen-bmi/ngen_bmi/registry.py -> the ngen checkout (editable install).
REPO_ROOT = Path(__file__).resolve().parents[3]
REGISTRY_PATH = REPO_ROOT / "tools" / "bmi-wrappers" / "wrappers.json"


def load_registry(path: Union[str, Path, None] = None) -> Dict[str, Dict]:
    """Registry entries by key; keys starting with ``_`` are comments."""
    path = Path(path) if path is not None else REGISTRY_PATH
    with open(path, encoding="utf-8") as fp:
        raw = json.load(fp)
    return {k: v for k, v in raw.items() if not k.startswith("_")}


def matches_model_type(model_type_name: Optional[str], entry: Dict) -> bool:
    """Whether a realization's ``model_type_name`` names this registry entry's model.

    The comparison is exact but ignores case: the gauge_01073000 example calls
    PET ``"PET"``. ``bmi_introspect.py`` uses the same rule.
    """
    if not model_type_name:
        return False
    wanted = str(model_type_name).lower()
    return wanted in {t.lower() for t in entry.get("realization_model_types", [])}


def keys_for_model_type(model_type_name: Optional[str], registry: Dict[str, Dict]) -> List[str]:
    """Registry keys whose ``realization_model_types`` include ``model_type_name``."""
    return [key for key, entry in registry.items() if matches_model_type(model_type_name, entry)]
