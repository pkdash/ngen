#!/usr/bin/env python3
"""Report a BMI model's real input/output contract, and check it against an ngen
realization config.

The wrapper packages in this directory expose no static metadata: the only
authoritative source for what a model consumes and produces is the compiled
model itself, queried after ``initialize()``. So this tool instantiates the
model, asks it, and formats the answer.

See tools/bmi-wrappers/README.md for the install prerequisites.
"""

import argparse
import contextlib
import difflib
import importlib
import json
import os
import re
import sys
from pathlib import Path

def _flush_c_streams():
    """Flush libc's stdio buffers.

    The model writes through C stdio, which buffers when stdout is not a tty.
    Without this, its output is flushed at process exit -- after the redirect
    below has been undone -- and lands on the real stdout, after our JSON.
    """
    try:
        import ctypes
        ctypes.CDLL(None).fflush(None)
    except Exception:                                  # noqa: BLE001
        pass                                           # best effort only


@contextlib.contextmanager
def model_chatter_to_stderr():
    """Send anything the model writes on fd 1 to stderr instead.

    BMI models are C libraries that print diagnostics straight to stdout -- CFE
    emits a deprecation notice during initialize(), for instance. That is
    diagnostic output, and letting it share stdout with our report corrupts
    --json for any consumer. Redirect at the file-descriptor level, since the
    writes come from C and never pass through sys.stdout.
    """
    sys.stdout.flush()
    saved = os.dup(1)
    try:
        os.dup2(2, 1)
        yield
    finally:
        sys.stdout.flush()
        _flush_c_streams()
        os.dup2(saved, 1)
        os.close(saved)


REPO_ROOT = Path(__file__).resolve().parents[2]
REGISTRY_PATH = Path(__file__).resolve().parent / "wrappers.json"

# Where ngen defines the forcing identifiers the framework can supply. Parsed at
# runtime rather than copied, so this tool cannot drift from the C++ source.
FORCING_HEADER = REPO_ROOT / "include" / "forcing" / "AorcForcing.hpp"


# --------------------------------------------------------------------------
# Registry
# --------------------------------------------------------------------------

def load_registry():
    with open(REGISTRY_PATH) as fp:
        raw = json.load(fp)
    return {k: v for k, v in raw.items() if not k.startswith("_")}


def resolve_model_class(entry):
    module = importlib.import_module(entry["import_path"])
    return getattr(module, entry["class_name"])


# --------------------------------------------------------------------------
# Live BMI query
# --------------------------------------------------------------------------

def _grid_info(model, grid_id, cache):
    if grid_id not in cache:
        try:
            cache[grid_id] = {
                "type": model.get_grid_type(grid_id),
                "rank": model.get_grid_rank(grid_id),
                "size": model.get_grid_size(grid_id),
            }
        except Exception as exc:                       # noqa: BLE001
            cache[grid_id] = {"type": f"<error: {exc}>", "rank": None, "size": None}
    return cache[grid_id]


def describe(model, want_values=False):
    """Query every fact the BMI surface exposes about this model's variables."""
    import numpy as np

    inputs = [str(n) for n in model.get_input_var_names()]
    outputs = [str(n) for n in model.get_output_var_names()]

    grid_cache = {}
    variables = {}
    for name in dict.fromkeys(inputs + outputs):       # preserve order, dedupe
        roles = []
        if name in inputs:
            roles.append("input")
        if name in outputs:
            roles.append("output")

        itemsize = model.get_var_itemsize(name)
        nbytes = model.get_var_nbytes(name)
        grid_id = model.get_var_grid(name)
        info = {
            "role": "/".join(roles),
            "units": model.get_var_units(name),
            "type": model.get_var_type(name),
            "itemsize": itemsize,
            "nbytes": nbytes,
            "n_elements": nbytes // itemsize if itemsize else None,
            "location": model.get_var_location(name),
            "grid": grid_id,
            "grid_info": _grid_info(model, grid_id, grid_cache),
        }

        if want_values and "output" in roles:
            # get_value fills a caller-allocated buffer. The dtype must come from
            # get_var_type per variable -- CFE, for one, mixes float64 with an
            # int32 (SURF_RUNOFF_SCHEME), and assuming double would misread it.
            try:
                buf = np.empty(info["n_elements"], dtype=np.dtype(info["type"]))
                model.get_value(name, buf)
                info["value"] = buf.tolist()
            except Exception as exc:                   # noqa: BLE001
                info["value"] = f"<error: {exc}>"

        variables[name] = info

    return {
        "component_name": model.get_component_name(),
        "time": {
            "start": model.get_start_time(),
            "end": model.get_end_time(),
            "current": model.get_current_time(),
            "units": model.get_time_units(),
            "step": model.get_time_step(),
        },
        "inputs": inputs,
        "outputs": outputs,
        "variables": variables,
    }


def print_table(report, model_key, config_path):
    t = report["time"]
    print(f"model      : {model_key}  ({report['component_name']})")
    print(f"config     : {config_path}")
    print(f"time       : start={t['start']} end={t['end']} current={t['current']} "
          f"units={t['units']} step={t['step']}")
    print()

    for role, names in (("INPUT", report["inputs"]), ("OUTPUT", report["outputs"])):
        print(f"--- {role} ({len(names)}) ---")
        if not names:
            print("  (none)")
        width = max((len(n) for n in names), default=0)
        for name in names:
            v = report["variables"][name]
            g = v["grid_info"]
            line = (f"  {name:<{width}}  {v['units']:<12} {v['type']:<8} "
                    f"n={v['n_elements']:<3} loc={v['location']:<6} "
                    f"grid={v['grid']}({g['type']})")
            if "value" in v:
                line += f"  = {v['value']}"
            print(line)
        print()


# --------------------------------------------------------------------------
# ngen realization cross-check
# --------------------------------------------------------------------------

def load_forcing_identifiers():
    """Identifiers the framework can supply: CSDMS standard names plus the
    forcing-column aliases ngen maps onto them."""
    if not FORCING_HEADER.is_file():
        return set(), set()

    text = FORCING_HEADER.read_text()
    std_names = set(re.findall(r'#define\s+(?:CSDMS|NGEN)_STD_NAME_\w+\s+"([^"]+)"', text))
    # e.g.  {"TMP_2maboveground", { CSDMS_STD_NAME_SURFACE_TEMP, "K" } },
    aliases = set(re.findall(r'\{\s*"([^"]+)"\s*,\s*\{\s*(?:CSDMS|NGEN)_STD_NAME_', text))
    return std_names, aliases


def iter_formulations(realization):
    """Yield (scope, formulation) for the global block and every catchment."""
    if "global" in realization:
        for f in realization["global"].get("formulations", []):
            yield "global", f
    for cat_id, cat in (realization.get("catchments") or {}).items():
        for f in cat.get("formulations", []):
            yield cat_id, f


def iter_modules(formulation):
    """Yield every leaf module: a bmi_multi's nested modules, or the formulation."""
    params = formulation.get("params", {})
    modules = params.get("modules")
    if modules:
        for m in modules:
            yield m
    else:
        yield formulation


def matches_model(module, entry):
    wanted = {w.lower() for w in entry.get("realization_model_types", [])}
    mtn = str(module.get("params", {}).get("model_type_name", "")).lower()
    return mtn in wanted or any(w in mtn for w in wanted)


def _display_path(path):
    """Repo-relative when possible; absolute otherwise (configs may live in /tmp)."""
    try:
        return str(Path(path).relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _near_miss(name, candidates, cutoff=0.85):
    """Return the one candidate `name` is probably a misspelling of, else None.

    The cutoff is deliberately high: a loose match would turn legitimate
    differences into false accusations, which is worse than staying silent.
    """
    matches = difflib.get_close_matches(name, sorted(candidates), n=1, cutoff=cutoff)
    return matches[0] if matches else None


def cross_check(report, realization_path, entry, catchment=None):
    """Compare the model's real I/O against how a realization config wires it up.

    Returns (findings, had_error). Severity is deliberate:
      ERROR   an input no identifier can satisfy -- the run would fail or read garbage
      WARN    a variables_names_map key naming no real variable -- dead config
    """
    with open(realization_path) as fp:
        realization = json.load(fp)

    std_names, aliases = load_forcing_identifiers()
    forcing_ids = std_names | aliases

    findings = []
    had_error = False
    checked_any = False

    for scope, formulation in iter_formulations(realization):
        if catchment and scope not in ("global", catchment):
            continue

        leaves = list(iter_modules(formulation))
        target = [m for m in leaves if matches_model(m, entry)]
        if not target:
            continue

        # Identifiers every *other* module in this formulation publishes.
        #
        # Only the target model is introspectable here, so a sibling's real
        # output list is unknown. We collect the identifiers a config can
        # declare: its main_output_variable, any aliased name, and any variable
        # synthesised via model_params (how SLoTH publishes, for instance
        # "sloth_smp(1,double,1,node)": 0.0). That is an approximation, tracked
        # by `opaque_siblings` so unresolved inputs are not over-reported.
        sibling_outputs = set()
        opaque_siblings = []
        for m in leaves:
            if m in target:
                continue
            p = m.get("params", {})
            vmap = p.get("variables_names_map", {}) or {}
            mov = p.get("main_output_variable")
            if mov:
                sibling_outputs.add(vmap.get(mov, mov))
            # model_params keys are "name(size,type,units,location)".
            for decl in (p.get("model_params") or {}):
                sibling_outputs.add(str(decl).split("(", 1)[0].strip())
            opaque_siblings.append(p.get("model_type_name", "?"))

        for module in target:
            checked_any = True
            p = module.get("params", {})
            vmap = p.get("variables_names_map", {}) or {}
            label = f"{scope}/{p.get('model_type_name', '?')}"

            # 1. Every input must resolve to some identifier.
            for name in report["inputs"]:
                ident = vmap.get(name, name)
                if ident in sibling_outputs:
                    source = "module output"
                elif ident in forcing_ids:
                    source = "forcing"
                elif (near := _near_miss(ident, sibling_outputs | forcing_ids)):
                    # Close to a real identifier -- almost certainly a typo, so
                    # report it confidently rather than hedging.
                    findings.append(
                        ("ERROR", label,
                         f"input '{name}' resolves to identifier '{ident}', which nothing "
                         f"provides. Did you mean '{near}'?"))
                    had_error = True
                    continue
                elif opaque_siblings:
                    # Cannot prove this is missing: a sibling module we cannot
                    # introspect may well publish it under this identifier.
                    findings.append(
                        ("WARN", label,
                         f"input '{name}' resolves to identifier '{ident}', which no "
                         f"forcing name and no declared output of "
                         f"{', '.join(opaque_siblings)} provides -- unverifiable, since "
                         f"those modules are not introspectable from here"))
                    continue
                else:
                    findings.append(
                        ("ERROR", label,
                         f"input '{name}' resolves to identifier '{ident}', which is "
                         f"neither a forcing name nor any other module's output"))
                    had_error = True
                    continue
                findings.append(("ok", label, f"input '{name}' <- {source} '{ident}'"))

            # 2. Map keys that name no real variable are dead config (usually
            #    copy-paste between modules). Harmless at runtime, so not fatal.
            known = set(report["variables"])
            for key in vmap:
                if key in known:
                    continue
                near = _near_miss(key, known)
                if near:
                    # A key one edit away from a real variable is a typo, and a
                    # typo here silently drops a mapping the run depends on.
                    findings.append(
                        ("ERROR", label,
                         f"variables_names_map key '{key}' is not a variable of this "
                         f"model. Did you mean '{near}'?"))
                    had_error = True
                else:
                    findings.append(
                        ("WARN", label,
                         f"variables_names_map key '{key}' is not a variable of this "
                         f"model -- the entry has no effect"))

            # 3. main_output_variable must actually be an output.
            mov = p.get("main_output_variable")
            if mov and mov not in report["outputs"]:
                findings.append(
                    ("ERROR", label,
                     f"main_output_variable '{mov}' is not an output of this model"))
                had_error = True

    if not checked_any:
        findings.append(
            ("WARN", str(realization_path),
             "no formulation in this realization matches "
             f"{entry.get('realization_model_types')} -- nothing to check"))

    return findings, had_error


def print_findings(findings, verbose):
    errors = [f for f in findings if f[0] == "ERROR"]
    warns = [f for f in findings if f[0] == "WARN"]
    oks = [f for f in findings if f[0] == "ok"]

    if verbose:
        for _, label, msg in oks:
            print(f"  ok    [{label}] {msg}")
    for level, label, msg in warns + errors:
        print(f"  {level:<5} [{label}] {msg}")

    print()
    print(f"resolved: {len(oks)}   warnings: {len(warns)}   errors: {len(errors)}")


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def cmd_list(registry):
    # Importing a wrapper can make its C library print on stdout.
    print(f"{'model':<10} {'distribution':<16} {'installed':<10} {'lib built':<10} description")
    for key, entry in sorted(registry.items()):
        try:
            with model_chatter_to_stderr():
                resolve_model_class(entry)
            installed = "yes"
        except Exception:                              # noqa: BLE001
            installed = "no"
        lib = REPO_ROOT / entry["lib_file"]
        print(f"{key:<10} {entry['distribution']:<16} {installed:<10} "
              f"{('yes' if lib.is_file() else 'no'):<10} {entry.get('description', '')}")
    return 0


def main(argv=None):
    registry = load_registry()

    parser = argparse.ArgumentParser(
        prog="bmi_introspect",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("model", nargs="?",
                        help=f"model key, or 'list'. Known: {', '.join(sorted(registry))}")
    parser.add_argument("--config", help="BMI init config (default: registry sample_config)")
    parser.add_argument("--realization", help="ngen realization config to cross-check against")
    parser.add_argument("--catchment", help="restrict the cross-check to one catchment id")
    parser.add_argument("--json", action="store_true", help="emit JSON instead of a table")
    parser.add_argument("--values", action="store_true", help="also read current output values")
    parser.add_argument("--verbose", action="store_true", help="show resolved inputs too")
    args = parser.parse_args(argv)

    if args.model in (None, "list"):
        return cmd_list(registry)

    if args.model not in registry:
        parser.error(f"unknown model '{args.model}'. Known: {', '.join(sorted(registry))}")
    entry = registry[args.model]

    config = args.config or entry.get("sample_config")
    if not config:
        parser.error(f"no --config given and no sample_config registered for '{args.model}'")
    config_path = Path(config)
    if not config_path.is_absolute():
        config_path = REPO_ROOT / config_path
    if not config_path.is_file():
        print(f"ERROR: BMI config not found: {config_path}", file=sys.stderr)
        return 1

    try:
        cls = resolve_model_class(entry)
    except ImportError as exc:
        print(f"ERROR: cannot import {entry['import_path']}: {exc}", file=sys.stderr)
        print("Install the wrappers first:  make -C commands install-bmi-wrappers",
              file=sys.stderr)
        return 1

    # Model configs reference their inputs by relative path.
    os.chdir(REPO_ROOT)

    with model_chatter_to_stderr():
        model = cls()
        model.initialize(str(config_path))
        try:
            report = describe(model, want_values=args.values)
        finally:
            try:
                model.finalize()
            except Exception:                          # noqa: BLE001
                pass

    exit_code = 0
    if args.realization:
        realization_path = Path(args.realization)
        if not realization_path.is_absolute():
            realization_path = REPO_ROOT / realization_path
        if not realization_path.is_file():
            print(f"ERROR: realization not found: {realization_path}", file=sys.stderr)
            return 1
        findings, had_error = cross_check(report, realization_path, entry, args.catchment)
        exit_code = 1 if had_error else 0
        if args.json:
            print(json.dumps(
                {"report": report,
                 "findings": [{"level": l, "scope": s, "message": m} for l, s, m in findings]},
                indent=2))
        else:
            print_table(report, args.model, config_path)
            print(f"--- cross-check against {_display_path(realization_path)} ---")
            print_findings(findings, args.verbose)
    elif args.json:
        print(json.dumps(report, indent=2))
    else:
        print_table(report, args.model, config_path)

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
