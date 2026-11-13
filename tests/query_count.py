#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Count the SQL statements Comicarr's engine runs inside a block.

Used by the query-count budgets (``tests/unit/test_query_budgets.py``) to
catch an endpoint whose statement count grows, which wall-clock timing on a
shared CI runner is too noisy to see.
"""

from contextlib import contextmanager

from sqlalchemy import event


class StatementCounter:
    """The statements seen while counting, in execution order."""

    def __init__(self):
        self.statements = []

    @property
    def count(self):
        return len(self.statements)

    def _record(self, _conn, _cursor, statement, _parameters, _context, executemany):
        self.statements.append(statement)


@contextmanager
def count_statements(engine):
    """Yield a counter of every statement ``engine`` sends to the database.

    ``before_cursor_execute`` fires once per cursor call, so an
    ``executemany`` batch counts as one statement, as it costs one round trip.
    SQLite pragmas run on the raw connection at connect time and are not
    counted.
    """
    counter = StatementCounter()
    event.listen(engine, "before_cursor_execute", counter._record)
    try:
        yield counter
    finally:
        event.remove(engine, "before_cursor_execute", counter._record)
