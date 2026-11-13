#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Do the recorded SABnzbd and NZBGet responses still match the real clients?

Run by `.github/workflows/client-contracts.yml` against containers at the
versions the recordings name. Each test drives the client through the same
calls the recorder makes and compares every response with its recording by
shape (see ``tests/fakes/contract.py``). Without the environment variables
below the tests are skipped, so an ordinary test run never needs a client.

- ``SAB_CONTRACT_URL``, ``SAB_CONTRACT_APIKEY``
- ``NZBGET_CONTRACT_URL``, ``NZBGET_CONTRACT_USERNAME``, ``NZBGET_CONTRACT_PASSWORD``
- ``CONTRACT_NNTP_HOST``: the address the containers use to reach this machine
"""

import json
import os
from pathlib import Path

import pytest

from tests.fakes import nzbget as nzbget_fake
from tests.fakes import sabnzbd as sab_fake
from tests.fakes.contract import compare_recordings

NNTP_HOST = os.environ.get("CONTRACT_NNTP_HOST", "172.17.0.1")


def _recordings(directory: Path) -> dict[str, dict]:
    return {path.stem: json.loads(path.read_text(encoding="utf-8")) for path in sorted(directory.glob("*.json"))}


def _report(client, version, report):
    lines = ["%s %s no longer matches its recordings:" % (client, version)]
    for name, found in report.items():
        lines.append("  %s.json" % name)
        lines.extend("    %s" % line for line in found)
    return "\n".join(lines)


@pytest.mark.skipif(not os.environ.get("SAB_CONTRACT_URL"), reason="SAB_CONTRACT_URL is not set")
def test_sabnzbd_matches_its_recordings():
    from tests.fakes.record_sabnzbd import capture

    live = capture(os.environ["SAB_CONTRACT_URL"], os.environ["SAB_CONTRACT_APIKEY"], NNTP_HOST, 1119)

    assert live["version"]["body"]["version"] == sab_fake.VERSION
    report = compare_recordings(_recordings(sab_fake.FIXTURES), live)
    assert not report, _report("SABnzbd", sab_fake.VERSION, report)


@pytest.mark.skipif(not os.environ.get("NZBGET_CONTRACT_URL"), reason="NZBGET_CONTRACT_URL is not set")
def test_nzbget_matches_its_recordings():
    from tests.fakes.record_nzbget import capture

    live = capture(
        os.environ["NZBGET_CONTRACT_URL"],
        os.environ["NZBGET_CONTRACT_USERNAME"],
        os.environ["NZBGET_CONTRACT_PASSWORD"],
        NNTP_HOST,
        1120,
    )

    assert live["version"]["result"] == nzbget_fake.VERSION
    report = compare_recordings(_recordings(nzbget_fake.FIXTURES), live)
    assert not report, _report("NZBGet", nzbget_fake.VERSION, report)
