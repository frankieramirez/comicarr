#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Characterization: the outgoing request each notifier makes for a snatch and a download.

Each case calls a notifier exactly the way its production caller does: the snatch
calls mirror ``search.notify_snatch`` and the download calls mirror
``PostProcessor._run_notifiers``. HTTP and SMTP are mocked; the assertions pin the
URL and payload that leave the process, so moving the module cannot change them.
"""

import importlib
import json
import urllib.parse
from unittest.mock import MagicMock

import pytest
import requests

NOTIFIERS_MODULE = "comicarr.app.notifications.service"

SNATCHED = "Spider-Man (2020) #1"
PROV = "NZBGeek"
SENT_TO = "SABnzbd"
SNLINE = "Issue snatched!"
PRLINE = "Spider-Man (2020) 1"
PRLINE2 = "Comicarr has downloaded and post-processed: Spider-Man (2020) 1"
MODULE = "[POST-PROCESSING]"


@pytest.fixture
def notifiers(mock_notifier_config):
    return importlib.import_module(NOTIFIERS_MODULE)


def _ok(status=200, body=None):
    response = MagicMock()
    response.status_code = status
    response.text = ""
    response.json.return_value = body or {}
    return response


@pytest.fixture
def post(mocker):
    return mocker.patch("requests.post", return_value=_ok())


@pytest.fixture
def session_post(mocker):
    return mocker.patch.object(requests.Session, "post", return_value=_ok())


# -- Prowl ------------------------------------------------------------------


def _prowl_body(mock_https_connection):
    connection = mock_https_connection["connection"]
    method, path = connection.request.call_args.args
    assert (method, path) == ("POST", "/publicapi/add")
    mock_https_connection["class"].assert_called_once_with("api.prowlapp.com")
    return urllib.parse.parse_qs(connection.request.call_args.kwargs["body"])


def test_prowl_snatch(notifiers, mock_https_connection):
    notifiers.PROWL().notify(SNATCHED, "Download started using %s" % SENT_TO)
    body = _prowl_body(mock_https_connection)
    assert body["apikey"] == ["test_prowl_key"]
    assert body["event"] == ["Download started using SABnzbd"]
    assert body["description"] == [SNATCHED]


def test_prowl_download(notifiers, mock_https_connection):
    notifiers.PROWL().notify(PRLINE, "Download and Postprocessing completed", module=MODULE)
    body = _prowl_body(mock_https_connection)
    assert body["event"] == ["Download and Postprocessing completed"]
    assert body["description"] == [PRLINE]


# -- Pushover ---------------------------------------------------------------


def test_pushover_snatch(notifiers, session_post):
    notifiers.PUSHOVER().notify(SNLINE, snatched_nzb=SNATCHED, prov=PROV, sent_to=SENT_TO)
    url = session_post.call_args.args[0]
    data = session_post.call_args.kwargs["data"]
    assert url == "https://api.pushover.net/1/messages.json"
    assert data["token"] == "test_pushover_apikey"
    assert data["user"] == "test_pushover_userkey"
    assert data["title"] == SNLINE
    assert data["message"] == b"Comicarr has snatched: Spider-Man (2020) #1 from NZBGeek and SABnzbd"
    assert session_post.call_args.kwargs["files"] is None


def test_pushover_download(notifiers, session_post):
    notifiers.PUSHOVER().notify(PRLINE, PRLINE2, module=MODULE, imageFile=None)
    data = session_post.call_args.kwargs["data"]
    assert data["title"] == PRLINE
    assert data["message"] == PRLINE2.encode("utf-8")


# -- Boxcar -----------------------------------------------------------------


def _boxcar_sent(mock_urllib):
    request, data = mock_urllib["urlopen"].call_args.args
    assert request.full_url == "https://new.boxcar.io/api/notifications"
    return urllib.parse.parse_qs(data)


def test_boxcar_snatch(notifiers, mock_urllib):
    notifiers.BOXCAR().notify(snatched_nzb=SNATCHED, sent_to=SENT_TO, snline=SNLINE)
    sent = _boxcar_sent(mock_urllib)
    assert sent["user_credentials"] == ["test_boxcar_token"]
    assert sent["notification[title]"] == [SNLINE]
    assert sent["notification[long_message]"] == ["Comicarr has snatched: %s and %s" % (SNATCHED, SENT_TO)]


def test_boxcar_download(notifiers, mock_urllib):
    notifiers.BOXCAR().notify(prline=PRLINE, prline2=PRLINE2, module=MODULE)
    sent = _boxcar_sent(mock_urllib)
    assert sent["notification[title]"] == [PRLINE]
    assert sent["notification[long_message]"] == [PRLINE2]


# -- Pushbullet -------------------------------------------------------------


def test_pushbullet_snatch(notifiers, session_post):
    notifiers.PUSHBULLET().notify(snline=SNLINE, snatched=SNATCHED, sent_to=SENT_TO, prov=PROV, method="POST")
    url = session_post.call_args.args[0]
    data = json.loads(session_post.call_args.kwargs["data"])
    assert url == "https://api.pushbullet.com/v2/pushes"
    assert data == {
        "type": "note",
        "title": SNLINE,
        "body": "Comicarr has snatched: Spider-Man (2020) #1 from NZBGeek and SABnzbd",
    }


def test_pushbullet_download(notifiers, session_post):
    notifiers.PUSHBULLET().notify(prline=PRLINE, prline2=PRLINE2, module=MODULE)
    data = json.loads(session_post.call_args.kwargs["data"])
    assert data == {"type": "note", "title": PRLINE + " complete!", "body": PRLINE2}


# -- Telegram ---------------------------------------------------------------


def test_telegram_snatch(notifiers, post):
    notifiers.TELEGRAM().notify("%s - %s - Comicarr %s" % (SNLINE, SNATCHED, SENT_TO))
    assert post.call_args.args[0] == "https://api.telegram.org/bottest_telegram_token/sendMessage"
    assert post.call_args.kwargs["json"] == {
        "chat_id": "123456789",
        "text": "Issue snatched! - Spider-Man (2020) #1 - Comicarr SABnzbd",
    }


def test_telegram_download(notifiers, post, sample_image_base64):
    notifiers.TELEGRAM().notify(PRLINE2, sample_image_base64)
    assert post.call_args.args[0] == "https://api.telegram.org/bottest_telegram_token/sendPhoto"
    assert post.call_args.args[1] == {"chat_id": "123456789", "caption": PRLINE2}
    assert "photo" in post.call_args.kwargs["files"]


# -- Email ------------------------------------------------------------------


def _email_sent(mock_smtp):
    mock_smtp["SMTP"].assert_called_once_with("smtp.example.com", "587")
    smtp = mock_smtp["smtp_instance"]
    smtp.starttls.assert_called_once()
    smtp.login.assert_called_once_with("smtp_user", "smtp_pass")
    sender, recipient, raw = smtp.sendmail.call_args.args
    assert (sender, recipient) == ("comicarr@example.com", "user@example.com")
    return raw


def test_email_snatch(notifiers, mock_smtp):
    notifiers.EMAIL().notify(SNLINE + " - " + SNATCHED, "Comicarr notification - Snatch", module="[SEARCH]")
    raw = _email_sent(mock_smtp)
    assert "Subject: Comicarr notification - Snatch" in raw
    assert "Issue snatched! - Spider-Man (2020) #1" in raw


def test_email_download(notifiers, mock_smtp):
    notifiers.EMAIL().notify(PRLINE2, "Comicarr notification - Processed", module=MODULE)
    raw = _email_sent(mock_smtp)
    assert "Subject: Comicarr notification - Processed" in raw
    assert PRLINE2 in raw


# -- Slack ------------------------------------------------------------------


def test_slack_snatch(notifiers, post):
    notifiers.SLACK().notify("Snatched", SNLINE, snatched_nzb=SNATCHED, sent_to=SENT_TO, prov=PROV)
    assert post.call_args.args[0] == "https://hooks.slack.com/services/test/webhook"
    assert post.call_args.kwargs["json"] == {
        "text": "Issue snatched!: Spider-Man (2020) #1 from NZBGeek and SABnzbd",
    }


def test_slack_download(notifiers, post):
    notifiers.SLACK().notify("Download and Postprocessing completed", PRLINE2, module=MODULE)
    assert post.call_args.kwargs["json"] == {"text": PRLINE2}


# -- Mattermost -------------------------------------------------------------

METADATA = {"series": "Spider-Man", "issue": "1", "year": "2020", "issueid": "12345"}


def test_mattermost_snatch(notifiers, post):
    # Nothing sends Mattermost a snatch today; this pins the snatch-text branch.
    notifiers.MATTERMOST().notify(
        "Snatched", SNLINE, snatched_nzb=SNATCHED, sent_to=SENT_TO, prov=PROV, metadata=METADATA
    )
    assert post.call_args.args[0] == "https://mattermost.example.com/hooks/test"
    payload = post.call_args.kwargs["json"]
    assert payload["text"] == "Issue snatched!: Spider-Man (2020) #1 from NZBGeek and SABnzbd"
    assert payload["username"] == "Comicarr"


def test_mattermost_download(notifiers, post):
    notifiers.MATTERMOST().notify(
        "Downloading and Postprocessing completed", PRLINE2, metadata=METADATA, imageFile=None, module=MODULE
    )
    payload = post.call_args.kwargs["json"]
    assert payload["text"] == PRLINE2
    assert payload["attachments"][0]["title"] == "Spider-Man (2020) - Issue 1"
    assert payload["attachments"][0]["fields"][0] == {"short": True, "title": "Series", "value": "Spider-Man"}


# -- Discord ----------------------------------------------------------------


def test_discord_snatch(notifiers, post):
    notifiers.DISCORD().notify("Snatched", SNLINE, snatched_nzb=SNATCHED, sent_to=SENT_TO, prov=PROV)
    assert post.call_args.args[0] == "https://discord.com/api/webhooks/test/webhook"
    payload = json.loads(post.call_args.kwargs["data"])
    assert payload["content"] == "Issue snatched!: Spider-Man (2020) #1 from NZBGeek and SABnzbd"
    embed = payload["embeds"][0]
    assert embed["author"] == {"name": "Grabbed by Comicarr"}
    assert [(f["name"], f["value"]) for f in embed["fields"] if f["name"] != chr(173)] == [
        ("Series", "Spider-Man (2020)"),
        ("Issue", "#1"),
        ("Indexer", PROV),
        ("Sent to", SENT_TO),
    ]


def test_discord_download(notifiers, post):
    notifiers.DISCORD().notify("Download and Postprocessing completed", PRLINE2, module=MODULE, imageFile=None)
    payload = json.loads(post.call_args.kwargs["data"])
    assert payload["content"] == PRLINE2
    embed = payload["embeds"][0]
    assert embed["author"] == {"name": "Downloaded by Comicarr"}
    # The series is sliced from a fixed offset into prline2, which is three characters
    # short of the real prefix. Pinned as is: this move must not change payloads.
    assert [(f["name"], f["value"]) for f in embed["fields"]] == [("Series", "d: Spider-Man (2020)"), ("Issue", "1")]


# -- Gotify -----------------------------------------------------------------


def test_gotify_snatch(notifiers, post):
    notifiers.GOTIFY().notify("Snatched", SNLINE, snatched_nzb=SNATCHED, sent_to=SENT_TO, prov=PROV)
    assert post.call_args.args[0] == "https://gotify.example.com/message?token=test_gotify_token"
    assert post.call_args.kwargs["json"] == {
        "title": "Snatched",
        "message": "Issue snatched!: Spider-Man (2020) #1 from NZBGeek and SABnzbd",
    }


def test_gotify_download(notifiers, post, sample_image_base64):
    notifiers.GOTIFY().notify(
        "Download and Postprocessing completed",
        PRLINE2,
        module=MODULE,
        imageFile=sample_image_base64,
        metadata=METADATA,
    )
    payload = post.call_args.kwargs["json"]
    assert payload["title"] == "Download and Postprocessing completed"
    assert payload["message"].startswith(PRLINE2 + "\n\n![](data:image/jpeg;base64,")
    assert payload["extras"]["client::notification"]["click"]["url"] == (
        "https://comicvine.gamespot.com/issue/4000-12345/"
    )


# -- Matrix -----------------------------------------------------------------


@pytest.fixture
def put(mocker):
    mocker.patch("time.time", return_value=1700000000.0)
    return mocker.patch("requests.put", return_value=_ok())


MATRIX_URL = (
    "https://matrix.example.com/_matrix/client/r0/rooms/!test_room:example.com/send/m.room.message/1700000000000"
)


def test_matrix_snatch(notifiers, put):
    notifiers.MATRIX().notify("Snatched", SNLINE, snatched_nzb=SNATCHED, sent_to=SENT_TO, prov=PROV)
    assert put.call_args.args[0] == MATRIX_URL
    assert put.call_args.kwargs["headers"]["Authorization"] == "Bearer test_matrix_token"
    assert put.call_args.kwargs["json"] == {
        "msgtype": "m.text",
        "body": "Issue snatched!: Spider-Man (2020) #1 from NZBGeek and SABnzbd",
    }


def test_matrix_download(notifiers, put):
    notifiers.MATRIX().notify("Download and Postprocessing completed", PRLINE2, module=MODULE)
    assert put.call_args.kwargs["json"] == {"msgtype": "m.text", "body": PRLINE2}
