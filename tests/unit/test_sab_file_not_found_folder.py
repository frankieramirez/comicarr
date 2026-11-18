#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""A finished job Comicarr cannot see still records where it was expected."""

from comicarr.app.downloads import sabnzbd, service


def test_file_not_found_carries_the_expected_folder():
    status = sabnzbd._file_not_found("/completed/Saga.001/Saga 001.cbz")

    assert status["status"] == "file not found"
    assert status["expected_folder"] == "/completed/Saga.001"


def test_manual_review_records_the_expected_folder(monkeypatch):
    monkeypatch.setattr(service, "_cdh_resolve_release_key", lambda item, nzstat: "1001|nzbsite")
    monkeypatch.setattr(
        service,
        "_cdh_job_identity",
        lambda item, nzstat: {"issueid": "1001", "comicid": "C1", "provider": "nzbsite", "nzbname": "Saga.001"},
    )
    nzstat = sabnzbd._file_not_found("/completed/Saga.001/Saga 001.cbz")

    fields = service._cdh_manual_review_kwargs({"nzo_id": "n1"}, nzstat, "n1", "file not found")

    assert fields["payload"]["nzb_folder"] == "/completed/Saga.001"
