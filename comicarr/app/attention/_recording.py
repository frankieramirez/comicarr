#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Terminal recording implementation for Needs attention."""

import time
from collections.abc import Mapping

from sqlalchemy.exc import OperationalError

from comicarr import logger
from comicarr.app.attention._policy import base_reason, is_actionable
from comicarr.app.attention._reconciliation import reconcile_excluded
from comicarr.app.attention.contracts import Failure, ManualReview, RecordOutcome


def _record_on_connection(entry, conn, *, activity_sink=None):
    from comicarr.app.downloads import journal

    payload = dict(entry.payload) if isinstance(entry.payload, Mapping) else entry.payload
    fields = {
        "issueid": entry.issue_id,
        "provider": entry.provider,
        "downloader_type": entry.downloader_type,
        "nzbname": entry.nzb_name,
        "hash": entry.download_hash,
    }
    fields = {key: value for key, value in fields.items() if value not in (None, "")}

    if isinstance(entry, Failure):
        if entry.resolved_as is not None:
            fields["status"] = entry.resolved_as
        transitioned = journal.mark_failed(
            entry.release_key,
            entry.reason,
            payload=payload,
            conn=conn,
            _activity_sink=activity_sink,
            **fields,
        )
    elif isinstance(entry, ManualReview):
        transitioned = journal.mark_manual_review(
            entry.release_key,
            entry.reason,
            payload=payload,
            conn=conn,
            _activity_sink=activity_sink,
            **fields,
        )
    reconciliation = reconcile_excluded(
        entry.reason,
        issueid=entry.issue_id,
        provider=entry.provider,
        nzbname=entry.nzb_name,
        release_id=entry.release_id,
        hash=entry.download_hash,
        comicid=entry.comic_id,
        comicname=entry.comic_name,
        issue_number=entry.issue_number,
        payload=payload,
        conn=conn,
        strict=True,
    )
    return RecordOutcome(
        transition_won=bool(transitioned),
        base_reason=base_reason(entry.reason),
        actionable=is_actionable(entry.reason),
        reconciliation=reconciliation,
    )


def record(entry: Failure | ManualReview, *, conn=None) -> RecordOutcome:
    """Record one typed terminal transition and discharge its obligation.

    When no connection is supplied, Attention owns one transaction for the
    journal transition and all required reconciliation writes. A supplied
    connection remains caller-owned and is never committed here.
    """
    if not isinstance(entry, (Failure, ManualReview)):
        raise TypeError("entry must be Failure or ManualReview")
    if conn is not None:
        return _record_on_connection(entry, conn)

    from comicarr import db

    attempt = 0
    while attempt < 5:
        activity_payloads = []
        try:
            with db.get_engine().begin() as owned_conn:
                outcome = _record_on_connection(
                    entry,
                    owned_conn,
                    activity_sink=activity_payloads,
                )
            for payload in activity_payloads:
                try:
                    from comicarr.app.activity.events import publish_activity

                    publish_activity(payload)
                except Exception as e:
                    logger.fdebug("[ATTENTION] activity publish skipped: %s" % e)
            return outcome
        except OperationalError as e:
            message = str(e)
            if "locked" not in message and "unable to open" not in message:
                raise
            attempt += 1
            logger.warn(
                "[ATTENTION] Database locked while recording release_key=%s, retry %d: %s"
                % (entry.release_key, attempt, e)
            )
            time.sleep(1)

    raise OperationalError(
        "Attention record for %s failed after 5 retries" % entry.release_key,
        None,
        None,
    )
