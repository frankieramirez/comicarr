#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""One-shot generator: `_CONFIG_DEFINITIONS` -> `ConfigKey` entries.

Run once for #362 and kept as the provenance of `comicarr/app/config/registry.py`.
Reads the literals out of `comicarr/config.py` and `comicarr/app/system/service.py`
with `ast` -- importing them would drag in the whole app -- and prints the
`_KEYS` tuple.

    python3 scripts/migrate_config_definitions.py > /tmp/keys.py

Duplicate names are expected: three keys are declared twice with different
sections and Python's dict literal keeps the last, so the last declaration is
the one that has always been in effect. This script keeps the last and reports
what it dropped.
"""

from __future__ import annotations

import ast
import re
import sys
from collections import OrderedDict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PY = ROOT / "comicarr" / "config.py"
SERVICE_PY = ROOT / "comicarr" / "app" / "system" / "service.py"


def _definitions(source: str) -> tuple[OrderedDict, list[str]]:
    """`_CONFIG_DEFINITIONS` as name -> (type, section, default), last-wins."""
    for node in ast.walk(ast.parse(source)):
        if not (isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "_CONFIG_DEFINITIONS"):
            continue
        literal = node.value.args[0]
        out: OrderedDict = OrderedDict()
        shadowed = []
        for key, value in zip(literal.keys, literal.values, strict=True):
            if key.value in out:
                shadowed.append("%s: %s shadowed by %s" % (key.value, out[key.value][1], ast.unparse(value)))
            kind, section, default = value.elts
            out[key.value] = (kind.id, ast.literal_eval(section), ast.unparse(default))
        return out, shadowed
    raise SystemExit("_CONFIG_DEFINITIONS not found")


def _names(source: str, pattern: str) -> set[str]:
    match = re.search(pattern, source, re.S)
    if not match:
        raise SystemExit("pattern not found: %s" % pattern)
    return set(re.findall(r'"([A-Z][A-Z0-9_]+)"', match.group(1)))


def _mapping(source: str, name: str) -> dict[str, str]:
    match = re.search(r"%s = \{(.*?)\n\}\n" % re.escape(name), source, re.S)
    return dict(re.findall(r'"([a-z_]+)": "([A-Z][A-Z0-9_]+)"', match.group(1)))


def main() -> int:
    config_src = CONFIG_PY.read_text()
    service_src = SERVICE_PY.read_text()

    definitions, shadowed = _definitions(config_src)
    readable = _names(service_src, r"    safe_keys = \[(.*?)\]\n")
    writable = _names(service_src, r"WRITABLE_CONFIG_KEYS = \{(.*?)\n\}\n")
    intervals = {key: job for job, key in _mapping(service_src, "SCHEDULER_JOB_INTERVALS").items()}
    gates = {key: job for job, key in _mapping(service_src, "SCHEDULER_JOB_REQUIRED_CONFIG").items()}
    provider_extras = set(ast.literal_eval(re.search(r"_PROVIDER_EXTRA_FIELDS = (\(.*?\))\n", config_src).group(1)))

    for label, keys in (("readable", readable), ("writable", writable)):
        stray = sorted(k for k in keys if k not in definitions)
        if stray:
            print("# WARNING: %s names undefined keys: %s" % (label, stray), file=sys.stderr)

    print("_KEYS: tuple[ConfigKey, ...] = (")
    for name, (kind, section, default) in definitions.items():
        parts = ['"%s"' % name, kind, '"%s"' % section, default]
        if name in readable:
            parts.append("readable=True")
        if name in writable:
            parts.append("writable=True")
        if name in intervals:
            parts.append('interval_for="%s"' % intervals[name])
        if name in gates:
            parts.append('gates="%s"' % gates[name])
        if name in provider_extras:
            parts.append("provider_extra=True")
        print("    ConfigKey(%s)," % ", ".join(parts))
    print(")")

    print(
        "\n# %d keys (%d literal entries, %d shadowed)\n# readable=%d writable=%d "
        "interval_for=%d gates=%d provider_extra=%d"
        % (
            len(definitions),
            len(definitions) + len(shadowed),
            len(shadowed),
            len(readable),
            len(writable),
            len(intervals),
            len(gates),
            len(provider_extras),
        ),
        file=sys.stderr,
    )
    for line in shadowed:
        print("# shadowed (kept the last, as Python does): %s" % line, file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
