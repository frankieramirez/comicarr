#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.


"""MCP server: the agent interface to Comicarr (docs/architecture/mcp-server.md).

Only ``comicarr.app.main`` imports this package. Tools follow the router rule
of ADR-0005: they call domain services and import no root module outside
Infrastructure.
"""
