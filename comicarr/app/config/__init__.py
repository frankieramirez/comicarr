#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""The config key registry.

**Partial, and not yet wired in.** `registry.py` currently holds a 17-key
sample -- the shapes that would break a naive entry type -- and nothing in the
application imports it. `comicarr/config.py:_CONFIG_DEFINITIONS` remains the
live definition of all 411 keys until the bulk migration lands. Do not treat
`REGISTRY` as complete or authoritative before then.
"""

from comicarr.app.config.registry import ConfigKey

__all__ = ["ConfigKey"]
