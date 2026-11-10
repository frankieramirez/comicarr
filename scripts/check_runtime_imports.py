#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  Comicarr is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with Comicarr.  If not, see <http://www.gnu.org/licenses/>.

"""CI gate: every shipped module imports under a runtime-only install.

Run it in an environment built with ``uv sync --locked --no-dev``, which is
what the Docker image installs. The unit tests run with the ``dev`` extra, so a
package that reaches the environment only through a dev tool (``six`` via
``freezegun -> python-dateutil``) passes every test and still crashes a real
install at startup. That shipped in 0.50.4 and boot-looped Docker users
(#1154).

The gate imports ``Comicarr.py``'s package tree module by module and fails on
any ``ModuleNotFoundError`` for a module outside the ``comicarr`` package.
Optional integrations guard their imports with ``try``, so they do not raise
here. Other import errors (the inherited comictaggerlib import cycle) are not
dependency problems and are ignored.
"""

import importlib
import pkgutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Shipped but never imported by the app: the vendored client's own test module.
NOT_RUNTIME = {"comicarr._vendor.deluge_client.tests"}


def main() -> int:
    sys.path.insert(0, str(REPO_ROOT))
    missing = []

    def try_import(name):
        try:
            return importlib.import_module(name)
        except ModuleNotFoundError as e:
            if e.name and e.name.split(".")[0] != "comicarr":
                missing.append((name, e.name))
        except Exception:
            # Only missing packages fail this gate.
            pass
        return None

    # The package root is what Comicarr.py imports first; if it fails, every
    # submodule fails the same way, so report it once.
    comicarr = try_import("comicarr")
    if comicarr is not None:
        for module in pkgutil.walk_packages(comicarr.__path__, "comicarr."):
            if module.name not in NOT_RUNTIME:
                try_import(module.name)

    if missing:
        print("Modules import packages that a `uv sync --locked --no-dev` install does not provide:")
        for module_name, package in sorted(missing):
            print(f"  {module_name}: {package}")
        print("Declare the package in [project].dependencies, or stop importing it at runtime.")
        return 1
    print("Runtime import check passed: every comicarr module imports without dev dependencies.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
