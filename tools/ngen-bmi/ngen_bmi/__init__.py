"""Set up, parameterize and run ngen realizations from Python.

The pymt_* wrappers, through ``bmi_setup``, are the authority on what a
parameter is called, its type and its length; ngen does the simulation.

The public names are imported on first use. That way ``ngen_bmi.registry``,
which ``tools/bmi-wrappers/bmi_introspect.py`` uses, needs only the standard
library: it works in a venv without ``bmi_setup`` or pandas.
"""

from importlib import import_module

_EXPORTS = {
    "Hydrofabric": "hydrofabric",
    "Project": "project",
    "Module": "project",
    "Change": "project",
    "MODEL_PARAMS": "project",
    "INIT_CONFIG": "project",
    "choose_route": "project",
    "NotSettable": "project",
    "ValidationError": "project",
    "ValidationWarning": "project",
    "LocalizationWarning": "project",
    "RunResult": "runner",
    "NgenRunError": "runner",
    "find_ngen": "runner",
}

__all__ = list(_EXPORTS)


def __getattr__(name):
    if name in _EXPORTS:
        value = getattr(import_module(f".{_EXPORTS[name]}", __name__), name)
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__():
    return sorted(set(globals()) | set(__all__))


try:
    from importlib.metadata import version

    __version__ = version("ngen-bmi")
except Exception:                                       # noqa: BLE001
    __version__ = "0+unknown"
