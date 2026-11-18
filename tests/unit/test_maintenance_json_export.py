#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""``Comicarr.py maintenance --exportjson`` writes the series list as JSON.

The export opened its file in binary mode, which ``json.dump`` cannot write
to on Python 3, so every export failed with a TypeError.
"""

import json
import sqlite3

from comicarr.app.core import runtime
from comicarr.app.system.maintenance import Maintenance


def test_json_export_writes_every_series_id(tmp_path, monkeypatch):
    database = tmp_path / "comicarr.db"
    with sqlite3.connect(database) as conn:
        conn.execute("CREATE TABLE comics (ComicID TEXT)")
        conn.executemany("INSERT INTO comics VALUES (?)", [("4050-1",), ("4050-2",)])
    monkeypatch.setattr(runtime.current(), "data_dir", str(tmp_path))
    monkeypatch.setattr(runtime.current(), "db_file", str(database))
    output = tmp_path / "export.json"

    Maintenance("json-export", output=str(output)).json_export()

    assert json.loads(output.read_text(encoding="utf-8")) == [{"ComicID": "4050-1"}, {"ComicID": "4050-2"}]
