"""``Project``: one realization, the changes asked for, and how they reach ngen.

Each parameter change goes one of two ways:

* **model_params**: written to the module's ``model_params``; ngen applies it
  with BMI ``SetValue`` right after ``initialize``. Used when the catalog says
  that matches a config edit (``equivalent``), or the BMI path works but no
  effect has been compared (``unexercised``, ``untested``; validate warns).
* **init_config**: the module's config files are copied into the run
  directory, edited with the ``bmi_setup`` codec, and ``init_config`` points at
  the copies. Used for config-only parameters and for ``differs`` ones.

Catchment-specific changes win over changes for every catchment.
"""

from __future__ import annotations

import copy
import json
import shutil
import tempfile
import warnings
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple, Union

import numpy as np
import pandas as pd

from bmi_setup import Catalog, Parameter, get_spec, load_catalog, open_config, open_model
from bmi_setup.config_files import TopmodelConfig

from .hydrofabric import Hydrofabric
from .localize import local_config_edits, localize_libraries
from .realization import (ID_PATTERN, ModuleRef, absolutize, catchment_override, get_at,
                          iter_modules, resolve_id)
from .registry import keys_for_model_type, load_registry
from .runner import RunResult, check_features, find_ngen, required_features, run_ngen

__all__ = ["MODEL_PARAMS", "INIT_CONFIG", "Change", "LocalizationWarning", "Module", "NotSettable",
           "Project", "ValidationError", "ValidationWarning", "choose_route"]

PathLike = Union[str, Path]
MODEL_PARAMS = "model_params"
INIT_CONFIG = "init_config"
_ROUTE_BY_STATUS = {"equivalent": MODEL_PARAMS, "unexercised": MODEL_PARAMS,
                    "untested": MODEL_PARAMS}
_UNPROVEN = {"unexercised": "has had no observable effect in the equivalence test",
             "untested": "has not been compared with a config edit"}


class NotSettable(ValueError):
    """The parameter cannot be set the way that was asked."""


class ValidationError(RuntimeError):
    def __init__(self, problems: Sequence[str]):
        self.problems = list(problems)
        super().__init__("validation failed:\n  " + "\n  ".join(self.problems))


class ValidationWarning(UserWarning):
    pass


class LocalizationWarning(UserWarning):
    """A path from another environment (e.g. NGIAB's /dmod) was mapped to a local one."""


def choose_route(param: Parameter, route: Optional[str] = None) -> str:
    """The route for ``param``; ``route`` forces one when it is possible."""
    if route is None:
        if param.set_value in _ROUTE_BY_STATUS:
            return MODEL_PARAMS
        if param.config_key:
            return INIT_CONFIG
        raise NotSettable(f"{param.name}: setting it after initialize gives results that differ "
                          f"from a config edit, and the catalog gives no config key to edit")
    if route == MODEL_PARAMS:
        if not param.bmi:
            raise NotSettable(f"{param.name} is not a BMI variable; it can only be set in the "
                              f"config file (key {param.config_key!r})")
        return route
    if route == INIT_CONFIG:
        if not param.config_key:
            raise NotSettable(f"{param.name} has no config key in the catalog")
        return route
    raise ValueError(f"route must be {MODEL_PARAMS!r} or {INIT_CONFIG!r}, got {route!r}")


def _normalize(param: Parameter, value) -> Union[int, float, List]:
    """A JSON-ready number or list, checked against the catalog's dtype and length."""
    array = np.asarray(value)
    if array.dtype.kind not in "iuf" or array.ndim > 1:
        raise TypeError(f"{param.name}: expected a number or a list of numbers, got {value!r}")
    if not np.all(np.isfinite(array)):
        raise ValueError(f"{param.name}: values must be finite, got {value!r}")
    if param.dtype and np.dtype(param.dtype).kind in "iu":
        if not np.all(array == np.round(array)):
            raise TypeError(f"{param.name} is an integer ({param.dtype}); got {value!r}")
        convert = int
    else:
        convert = float
    if array.ndim == 0:
        return convert(array.item())
    items = [convert(x) for x in array.tolist()]
    if isinstance(param.length, int) and len(items) != param.length:
        raise ValueError(f"{param.name} has {param.length} element(s); got {len(items)}")
    return items


@dataclass(frozen=True)
class Change:
    module: str
    name: str
    value: Any
    catchments: Optional[Tuple[str, ...]]   # None: every catchment
    route: str
    param: Parameter = field(repr=False, compare=False)

    def as_dict(self) -> Dict:
        return {"module": self.module, "name": self.name, "value": self.value,
                "catchments": list(self.catchments) if self.catchments else "all",
                "route": self.route, "catalog_status": self.param.set_value,
                "config_key": self.param.config_key}


@dataclass
class _Check:
    """One wrapper instance to open during validation."""
    module: "Module"
    catchment: str
    config: Path
    model_params: Dict[str, Any]
    config_changes: List[Change]


class Module:
    """One BMI module of the realization, found through the registry."""

    def __init__(self, project: "Project", key: str, ref: ModuleRef, entry: Dict):
        self.project = project
        self.key = key
        self.ref = ref
        self.entry = entry
        self._local_edits: Optional[Dict[str, str]] = None
        self.bmi_setup_key = entry.get("bmi_setup_key")
        if not self.bmi_setup_key:
            raise KeyError(f"registry entry {key!r} has no bmi_setup_key, so ngen_bmi cannot "
                           f"set its parameters")
        self.spec = get_spec(self.bmi_setup_key)
        if not self.spec.catalog:
            raise KeyError(f"bmi_setup has no parameter catalog for {self.bmi_setup_key!r}")
        self.catalog: Catalog = load_catalog(self.bmi_setup_key)

    def __repr__(self) -> str:
        return f"<Module {self.key} ({self.ref.model_type_name}) at {self.ref.location}>"

    @property
    def params(self) -> Dict:
        """The module's params dict in the project's (absolute-path) realization."""
        return get_at(self.project.realization["global"], self.ref.location)

    @property
    def init_config(self) -> str:
        value = self.params.get("init_config")
        if not isinstance(value, str) or value in ("", "/dev/null"):
            raise ValueError(f"{self.key}: the realization gives no init_config")
        return value

    def config_for(self, catchment: str) -> Path:
        return Path(resolve_id(self.init_config, catchment))

    def read_config(self, path: PathLike):
        return open_config(self.spec.codec, path, self.project.root)

    @property
    def local_edits(self) -> Dict[str, str]:
        """Config edits that point missing data directories at this checkout.

        Found from the first catchment's config, using the registry entry's
        ``local_config_dirs`` (for Noah, ``parameter_dir``); see
        :func:`ngen_bmi.localize.local_config_edits`. ``Project`` applies them
        to the config copies it writes, never to the input files.
        """
        if self._local_edits is None:
            self._local_edits = {}
            if self.entry.get("local_config_dirs"):
                try:
                    config = self.config_for(self.project.catchment_ids()[0])
                except ValueError:                        # no init_config
                    config = None
                if config is not None and config.is_file():
                    cfg = self.read_config(config)
                    self._local_edits = local_config_edits(
                        self.entry, lambda key: cfg.get(key) if key in cfg else None,
                        self.project.root)
                    if self._local_edits:
                        warnings.warn(f"{self.key}: {config} names directories that do not exist; "
                                      f"the configs written for ngen use "
                                      f"{self._local_edits}", LocalizationWarning, stacklevel=3)
        return self._local_edits

    def route(self, name: str) -> str:
        return choose_route(self.catalog[name])

    @property
    def changes(self) -> List[Change]:
        return [c for c in self.project.changes if c.module == self.key]

    def set(self, catchments: Optional[Iterable[str]] = None, route: Optional[str] = None,
            **values) -> "Module":
        """Change parameters, for every catchment or only ``catchments``.

        Names are catalog names (BMI names, or config keys for config-only
        entries). A scalar for a multi-element parameter is broadcast when
        written. ``route`` forces ``"model_params"`` or ``"init_config"``.
        """
        if not values:
            raise TypeError("set() needs at least one name=value")
        cats = self.project._check_catchments(catchments)
        new = []
        for name, value in values.items():
            param = self.catalog[name]
            chosen = choose_route(param, route)
            new.append(Change(self.key, name, _normalize(param, value), cats, chosen, param))
        self.project._changes.extend(new)
        return self

    def parameters(self, catchment: Optional[str] = None) -> pd.DataFrame:
        """The catalog with current values, read live for BMI parameters.

        Values come from ``catchment``'s config (the first catchment by
        default), before any pending change.
        """
        catchment = catchment or self.project.catchment_ids()[0]
        config = self.config_for(catchment)
        rows = OrderedDict()
        with tempfile.TemporaryDirectory(prefix="ngen_bmi_params_") as tmp:
            opened = config
            if self.local_edits:
                opened = self.project._rewrite(self, config, Path(tmp) / config.name,
                                               self.local_edits)
            with open_model(self.spec.key, opened, workdir=self.project.root) as m:
                for name, row in m.parameters().items():
                    rows[name] = row
        cfg = self.read_config(config)
        for name, row in rows.items():
            param = self.catalog[name]
            if "value" not in row and param.config_key and param.config_key in cfg:
                row["value"] = cfg.get(param.config_key).strip()
            value = row.get("value")
            if isinstance(value, np.ndarray) and value.size == 1:
                row["value"] = value.item()
            try:
                row["route"] = choose_route(param)
            except NotSettable:
                row["route"] = None
        df = pd.DataFrame.from_dict(rows, orient="index")
        df.index.name = "name"
        return df.drop(columns=["name"], errors="ignore")


class Project:
    """A realization to change and run. The input files are never written."""

    def __init__(self, realization: Dict, hydrofabric: Hydrofabric, root: PathLike,
                 registry: Optional[Dict[str, Dict]] = None, source: Optional[Path] = None):
        if "catchments" in realization and realization["catchments"]:
            raise NotImplementedError("realizations with a 'catchments' block are not supported "
                                      "yet; ngen_bmi writes catchment overrides itself")
        self.root = Path(root).resolve()
        self.realization = absolutize(realization, self.root)
        self.localized = localize_libraries(self.realization)
        if self.localized:
            warnings.warn("library_file not found, using the local build: " + "; ".join(
                f"{old} -> {new}" for old, new in self.localized.items()),
                LocalizationWarning, stacklevel=3)
        self.hydrofabric = hydrofabric
        self.registry = registry if registry is not None else load_registry()
        self.source = source
        self._changes: List[Change] = []
        self._catchment_ids: Optional[List[str]] = None

    @classmethod
    def load(cls, realization: PathLike, hydrofabric: Optional[PathLike] = None, *,
             catchments: Optional[PathLike] = None, nexus: Optional[PathLike] = None,
             root: Optional[PathLike] = None, registry: Optional[Dict[str, Dict]] = None
             ) -> "Project":
        """Load a realization file.

        ``root`` is the directory its relative paths are relative to, i.e. where
        ngen would be started (default: the current directory). ngen runs there,
        because model configs hold paths relative to it too.
        """
        path = Path(realization).resolve()
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(data, Hydrofabric.from_args(hydrofabric, catchments, nexus),
                   root if root is not None else Path.cwd(), registry, path)

    def __repr__(self) -> str:
        return f"<Project {self.source or '(dict)'} changes={len(self._changes)}>"

    # ------------------------------------------------------------ modules
    def catchment_ids(self) -> List[str]:
        if self._catchment_ids is None:
            self._catchment_ids = self.hydrofabric.catchment_ids()
            if not self._catchment_ids:
                raise ValueError(f"no catchments in {self.hydrofabric.catchments}")
        return list(self._catchment_ids)

    def _check_catchments(self, catchments) -> Optional[Tuple[str, ...]]:
        if catchments is None:
            return None
        if isinstance(catchments, str):
            catchments = [catchments]
        cats = tuple(dict.fromkeys(catchments))
        known = set(self.catchment_ids())
        unknown = [c for c in cats if c not in known]
        if unknown:
            raise KeyError(f"not in the hydrofabric: {', '.join(unknown)}")
        if not cats:
            raise ValueError("catchments is empty")
        return cats

    def _matches(self) -> List[Tuple[str, ModuleRef]]:
        out = []
        for ref in iter_modules(self.realization["global"]):
            for key in keys_for_model_type(ref.model_type_name, self.registry):
                out.append((key, ref))
        return out

    def modules(self) -> Dict[str, str]:
        """Registry key -> model_type_name for every recognized module."""
        return {key: ref.model_type_name for key, ref in self._matches()}

    def module(self, key: str) -> Module:
        found = [ref for k, ref in self._matches() if k == key]
        if not found:
            raise KeyError(f"no module for {key!r} in the realization; found "
                           f"{self.modules() or 'none'}")
        if len(found) > 1:
            raise KeyError(f"{key!r} matches {len(found)} modules; ngen_bmi needs exactly one")
        return Module(self, key, found[0], self.registry[key])

    @property
    def changes(self) -> List[Change]:
        return list(self._changes)

    def clear_changes(self) -> None:
        self._changes.clear()

    # ------------------------------------------------------------ writing
    def _changed_modules(self) -> List[Module]:
        return [self.module(key) for key in dict.fromkeys(c.module for c in self._changes)]

    def _modules_to_write(self) -> List[Module]:
        """Changed modules, plus unchanged ones whose configs need local paths."""
        modules = self._changed_modules()
        seen = {m.key for m in modules}
        for key in dict.fromkeys(k for k, _ in self._matches()):
            if key in seen:
                continue
            try:
                module = self.module(key)
            except KeyError:                  # ambiguous, or no bmi_setup catalog
                continue
            if module.local_edits:
                modules.append(module)
        return modules

    def _effective(self, module: Module):
        """(changes for every catchment, {catchment: changes}) by name; later wins."""
        glob: Dict[str, Change] = OrderedDict()
        per: Dict[str, Dict[str, Change]] = {}
        for c in module.changes:
            if c.catchments is None:
                glob[c.name] = c
            else:
                for cat in c.catchments:
                    per.setdefault(cat, OrderedDict())[c.name] = c
        return glob, per

    def _length(self, module: Module, param: Parameter, configs: Sequence[Path]) -> Optional[int]:
        if param.length is None or isinstance(param.length, int):
            return param.length
        lengths = {int(float(module.read_config(p).get(param.length))) for p in configs}
        if len(lengths) != 1:
            raise ValueError(f"{module.key}: {param.name} has length {param.length!r}, which "
                             f"differs between catchments ({sorted(lengths)}); set it per catchment")
        return lengths.pop()

    def _expand(self, module: Module, change: Change, configs: Sequence[Path]):
        """The model_params value: a full-length list when the parameter has length > 1."""
        n = self._length(module, change.param, configs)
        value = change.value
        if n is None or (n == 1 and not isinstance(value, list)):
            return value
        if isinstance(value, list):
            if len(value) != n:
                raise ValueError(f"{module.key}: {change.name} has {n} element(s); got {len(value)}")
            return value
        return [value] * n

    def _rewrite(self, module: Module, src: Path, dest: Path, edits: Dict[str, Any]) -> Path:
        if not src.is_file():
            raise FileNotFoundError(f"{module.key}: config file not found: {src}")
        cfg = module.read_config(src)
        for key, value in edits.items():
            try:
                cfg.set(key, value)
            except KeyError as err:
                raise KeyError(f"{module.key}: {src}: {err.args[0]}") from None
        dest.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(cfg, TopmodelConfig):
            cfg.write(dest, dest.parent / Path(cfg.params_file).name, self.root)
        else:
            cfg.write(dest)
        return dest

    def _build(self, run_dir: Path, drop_routing: bool) -> Tuple[Path, Dict, List[_Check]]:
        """Write configs and realization.json into ``run_dir``; return what to validate."""
        run_dir.mkdir(parents=True, exist_ok=True)
        real = copy.deepcopy(self.realization)
        glob_block = real["global"]
        cats = self.catchment_ids()
        overrides: Dict[str, List[Tuple[ModuleRef, Dict, Optional[str], List[str]]]] = {}
        checks: List[_Check] = []

        for module in self._modules_to_write():
            params = get_at(glob_block, module.ref.location)
            glob, per = self._effective(module)
            cfg_glob = {**module.local_edits,
                        **{c.param.config_key: c.value for c in glob.values()
                           if c.route == INIT_CONFIG}}
            cfg_per = {cat: {c.param.config_key: c.value for c in d.values() if c.route == INIT_CONFIG}
                       for cat, d in per.items()}
            cfg_per = {cat: e for cat, e in cfg_per.items() if e}
            template = module.init_config
            config_of = {cat: Path(resolve_id(template, cat)) for cat in cats}
            cat_config: Dict[str, str] = {}                    # override init_config paths

            if cfg_glob or cfg_per:
                dest_dir = run_dir / "configs" / module.key
                if ID_PATTERN in template:
                    name = Path(template).name
                    new_template = str(dest_dir / (name if ID_PATTERN in name else
                                                   f"{ID_PATTERN}/{name}"))
                    for cat in cats:
                        dest = Path(resolve_id(new_template, cat))
                        self._rewrite(module, Path(resolve_id(template, cat)), dest,
                                      {**cfg_glob, **cfg_per.get(cat, {})})
                        config_of[cat] = dest
                    params["init_config"] = new_template
                else:
                    if cfg_glob:
                        dest = self._rewrite(module, Path(template), dest_dir / Path(template).name,
                                             cfg_glob)
                        params["init_config"] = str(dest)
                        config_of = {cat: dest for cat in cats}
                    for cat, edits in cfg_per.items():
                        dest = self._rewrite(module, Path(template),
                                             dest_dir / cat / Path(template).name,
                                             {**cfg_glob, **edits})
                        cat_config[cat] = str(dest)
                        config_of[cat] = dest

            mp_glob = {n: c for n, c in glob.items() if c.route == MODEL_PARAMS}
            if mp_glob:
                mp = params.setdefault("model_params", {})
                for name, c in mp_glob.items():
                    mp[name] = self._expand(module, c, list(config_of.values()))

            for cat in sorted(set(per) | set(cat_config)):
                changes = per.get(cat, {})
                mp_cat = {n: self._expand(module, c, [config_of[cat]])
                          for n, c in changes.items() if c.route == MODEL_PARAMS}
                # A catchment's config edit must not be undone by a model_params value
                # for every catchment, which ngen applies after initialize.
                drop = [n for n, c in changes.items() if c.route == INIT_CONFIG and n in mp_glob]
                if mp_cat or drop or cat in cat_config:
                    overrides.setdefault(cat, []).append(
                        (module.ref, mp_cat, cat_config.get(cat), drop))

            check_cats = ([cats[0]] if glob else []) + sorted(per)
            for cat in dict.fromkeys(check_cats):
                changes = OrderedDict(glob)
                changes.update(per.get(cat, {}))
                mp_values = {n: self._expand(module, c, [config_of[cat]])
                             for n, c in changes.items() if c.route == MODEL_PARAMS}
                checks.append(_Check(module, cat, config_of[cat], mp_values,
                                     [c for c in changes.values() if c.route == INIT_CONFIG]))

        if overrides:
            real["catchments"] = {}
            for cat in sorted(overrides):
                entry = catchment_override(glob_block, cat)
                for ref, mp_cat, init_config, drop in overrides[cat]:
                    p = get_at(entry, ref.location)
                    if init_config:
                        p["init_config"] = init_config
                    mp = p.setdefault("model_params", {})
                    for n in drop:
                        mp.pop(n, None)
                    mp.update(mp_cat)
                    if not mp:
                        del p["model_params"]
                real["catchments"][cat] = entry

        real["output_root"] = str(run_dir) + "/"
        if drop_routing:
            real.pop("routing", None)
        path = run_dir / "realization.json"
        path.write_text(json.dumps(real, indent=2) + "\n", encoding="utf-8")
        (run_dir / "changes.json").write_text(
            json.dumps([c.as_dict() for c in self._changes], indent=2) + "\n", encoding="utf-8")
        return path, real, checks

    def write(self, run_dir: PathLike, drop_routing: bool = False) -> Path:
        """Write ``realization.json`` and edited configs into ``run_dir``; return the realization."""
        return self._build(Path(run_dir).resolve(), drop_routing)[0]

    # ------------------------------------------------------------ validation
    def _validate_checks(self, checks: List[_Check]) -> List[str]:
        problems, notes = [], []
        for c in self._changes:
            if c.route == MODEL_PARAMS and c.param.set_value in _UNPROVEN:
                notes.append(f"{c.module}.{c.name} {_UNPROVEN[c.param.set_value]}")
            if c.route == MODEL_PARAMS and c.param.set_value == "differs":
                notes.append(f"{c.module}.{c.name}: model_params was forced, but setting it after "
                             f"initialize is known to differ from a config edit")
        for chk in checks:
            where = f"{chk.module.key} ({chk.catchment}, {chk.config})"
            try:
                with open_model(chk.module.spec.key, chk.config, workdir=self.root) as m:
                    for name, value in chk.model_params.items():
                        m.set(name, value)
                        self._compare(m, name, value, f"{where}: model_params {name}", problems)
                    for c in chk.config_changes:
                        if c.param.bmi:
                            self._compare(m, c.name, c.value, f"{where}: config {c.param.config_key}",
                                          problems)
            except Exception as err:                      # noqa: BLE001
                problems.append(f"{where}: {type(err).__name__}: {err}")
        if problems:
            raise ValidationError(problems)
        for note in dict.fromkeys(notes):
            warnings.warn(note, ValidationWarning, stacklevel=3)
        return list(dict.fromkeys(notes))

    @staticmethod
    def _compare(m, name: str, value, what: str, problems: List[str]) -> None:
        got = m.get(name)
        want = np.broadcast_to(np.asarray(value, dtype=got.dtype), got.shape)
        if not np.array_equal(got, want):
            problems.append(f"{what}: wrote {value!r}, the model reads back {got.tolist()!r}")

    def validate(self) -> List[str]:
        """Open each changed module's wrapper and check every change reads back.

        Opens one instance per distinct config: the first catchment's for changes
        to every catchment, plus each catchment with its own changes. Raises
        :class:`ValidationError`; returns (and warns) the notes for parameters
        whose effect is unproven.
        """
        with tempfile.TemporaryDirectory(prefix="ngen_bmi_validate_") as tmp:
            _, _, checks = self._build(Path(tmp), drop_routing=False)
            return self._validate_checks(checks)

    # ------------------------------------------------------------ running
    def run(self, run_dir: PathLike, *, validate: bool = True, drop_routing: bool = False,
            ngen: Optional[PathLike] = None, overwrite: bool = False,
            timeout: Optional[float] = None) -> RunResult:
        """Write the run into ``run_dir``, validate it, and run ngen.

        ngen runs with :attr:`root` as its working directory; its output and
        ``ngen.log`` go to ``run_dir``. ``overwrite=True`` replaces an earlier run
        there (a directory holding ``realization.json``).
        """
        run_dir = Path(run_dir).resolve()
        if run_dir.exists() and any(run_dir.iterdir()):
            if not overwrite:
                raise FileExistsError(f"{run_dir} is not empty; pass overwrite=True to replace "
                                      f"an earlier run")
            if not (run_dir / "realization.json").is_file():
                raise FileExistsError(f"{run_dir} does not look like an ngen_bmi run "
                                      f"(no realization.json); not removing it")
            shutil.rmtree(run_dir)
        binary = find_ngen(ngen)
        path, real, checks = self._build(run_dir, drop_routing)
        check_features(binary, required_features(
            real, {self.hydrofabric.catchments, self.hydrofabric.nexus}))
        if validate:
            self._validate_checks(checks)
        run_ngen(binary, self.hydrofabric, path, run_dir / "ngen.log", self.root, timeout)
        return RunResult(run_dir)
