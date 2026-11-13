#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""The shape comparison the nightly client contract job relies on."""

import copy

from tests.contract.test_client_contracts import _recordings
from tests.fakes import nzbget as nzbget_fake
from tests.fakes import sabnzbd as sab_fake
from tests.fakes.contract import compare_recordings, differences


def test_a_key_missing_from_the_live_response_is_a_difference():
    recorded = sab_fake.recording("history_completed")
    live = copy.deepcopy(recorded)
    del live["body"]["history"]["slots"][0]["storage"]

    assert differences(recorded, live) == [
        "$.body.history.slots[0].storage: in the recording, missing from the live response"
    ]


def test_a_comparison_names_the_recording_and_field_that_differ():
    recorded = {"queue_paused": sab_fake.recording("queue_paused")}
    live = copy.deepcopy(recorded)
    live["queue_paused"]["body"]["queue"].pop("noofslots")

    report = compare_recordings(recorded, live)

    assert report == {"queue_paused": ["$.body.queue.noofslots: in the recording, missing from the live response"]}


def test_a_new_key_in_the_live_response_is_a_difference():
    recorded = nzbget_fake.recording("version")
    live = {**recorded, "id": 7}

    assert differences(recorded, live) == ["$.id: in the live response, missing from the recording"]


def test_a_changed_type_or_status_code_is_a_difference():
    recorded = sab_fake.recording("wrong_apikey")
    live = {**copy.deepcopy(recorded), "status_code": 401, "body": {"error": "API Key Incorrect"}}

    assert differences(recorded, live) == [
        "$.body: recorded string, live object",
        "$.status_code: recorded 403, live 401",
    ]


def test_changed_values_of_the_same_shape_are_not_differences():
    recorded = nzbget_fake.recording("history")
    live = copy.deepcopy(recorded)
    for entry in live["result"]:
        entry.update(NZBID=entry["NZBID"] + 100, Name="Another.Release", FileSizeMB=512)

    assert differences(recorded, live) == []


def test_a_response_the_live_run_did_not_produce_is_reported():
    assert compare_recordings({"version": {"result": "26.3"}}, {}) == {
        "version": ["$: recorded, but the live run produced no response"]
    }


def test_every_recording_matches_itself():
    for fixtures in (sab_fake.FIXTURES, nzbget_fake.FIXTURES):
        recordings = _recordings(fixtures)
        assert recordings
        assert compare_recordings(recordings, copy.deepcopy(recordings)) == {}
