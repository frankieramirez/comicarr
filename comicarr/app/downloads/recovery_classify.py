#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""
Per-downloader startup classification for the durable pipeline.

Module boundary: this module is PURE-VERDICT — ``classify()`` returns a
verdict (STILL/COMPLETE/GONE/UNKNOWN) and NEVER mutates the journal.
``classify_details()`` is the same decision plus any completion evidence
(location/name/failed) the SAB/NZBGet probe already resolved.
journal.py owns transitions; recovery.py owns replay orchestration.
``apply_verdict()`` is a thin optional helper mapping a GONE verdict to an
Attention failure record; it is a deliberate no-op for
STILL/COMPLETE/UNKNOWN.

"Absent from the client" is AMBIGUOUS, never authoritatively gone. SAB/NZBGet
history is finite and operator/auto-pruned: a release that completed and was
post-processed while the app was down, then had its history row evicted, reads
as absent. Before classifying any "absent" as GONE we cross-check the
authoritative done-signals (issues.Status == 'Post-Processed' / nzblog row
absent / journal stage already post_processing+).

One-off caveat: synthetic-HIGHCOUNT IssueID one-offs have a non-persisted
IssueID that diverges across restart, and nzblog() has a mid-flight
delete-then-reupsert window — so the nzblog-presence test is UNRELIABLE for
them. For those rows the journal release_key / stage is the AUTHORITATIVE
in-flight signal and nzblog-presence is ADVISORY only, so an in-flight one-off
is never misread as done / GONE.
"""

import requests
from sqlalchemy import or_, select

import comicarr
from comicarr import db, logger
from comicarr.app.attention import Failure, record
from comicarr.app.downloads import journal
from comicarr.tables import annuals, ddl_info, issues, nzblog, storyarcs

STILL = "still"
COMPLETE = "complete"
GONE = "gone"
UNKNOWN = "unknown"

VERDICTS = (STILL, COMPLETE, GONE, UNKNOWN)

FAIL_REASON_GONE = "download_gone"


def _journal_stage_done(row):
    """The journal itself can be an authoritative done-signal: if the row has
    already advanced to post_processing+ then the download obviously completed
    regardless of what the (now-evicted) client history says."""
    stage = (row or {}).get("stage")
    rank = journal.stage_rank(stage)
    pp_rank = journal.stage_rank(journal.POST_PROCESSING)
    return rank is not None and pp_rank is not None and rank >= pp_rank


def _issue_post_processed(issueid):
    """True iff issues.Status == 'Post-Processed' for this IssueID — an
    authoritative "already completed" signal that survives history eviction."""
    if issueid is None:
        return False
    try:
        rec = db.select_one(select(issues.c.Status).where(issues.c.IssueID == str(issueid)))
    except Exception as e:
        logger.warn("[RECOVERY-CLASSIFY] issues.Status lookup failed for %s: %s" % (issueid, e))
        return False
    return bool(rec) and rec["Status"] == "Post-Processed"


def _nzblog_present(issueid, provider, story_arc=None):
    """True iff an nzblog row still exists for (IssueID, PROVIDER). nzblog is
    DELETED on PP success (postprocessor.py:5084/3949/4302), so its ABSENCE is
    a done-signal. Returns None when the test is not answerable.

    Story-arc scoping (correctness completion of fix #2): the reference
    postprocessor.py ~3201-3213 only does the ``"S" + IssueArcID`` nzblog
    lookup inside the story-arc branch (paired with a SARC/StoryArc
    constraint) — it NEVER widens a plain-issue lookup to the "S" form.
    Mirror that scoping here so a plain issue whose id numerically equals an
    unrelated story-arc's IssueArcID under the SAME PROVIDER cannot read the
    arc's "S"+id row as its own presence (a false-presence that would keep a
    completed plain issue open, or — via the anchor gate — mis-skip it).

    `story_arc` signal (threaded by the caller; default None ⇒ unknown):
      * True  -> this obligation IS a story arc: match plain OR "S"+id.
      * False -> plain issue: match the plain id ONLY (never "S"+id).
      * None  -> caller could not determine arc-ness. Minimally-safe fallback
        (documented): prefer the EXACT plain row; only fall back to the
        "S"+id form when NO plain row exists for (IssueID, PROVIDER). A real
        plain issue with its own nzblog row therefore never consults the arc
        row; the residual ambiguous case (plain row already PP-deleted) is
        the same one the prior unconditional-OR already accepted, so no
        existing story-arc match regresses.
    """
    if issueid is None:
        return None
    try:
        if story_arc is False:
            stmt = select(nzblog.c.IssueID).where(nzblog.c.IssueID == str(issueid))
            if provider:
                stmt = stmt.where(nzblog.c.PROVIDER == provider)
            return db.select_one(stmt) is not None

        if story_arc is True:
            stmt = select(nzblog.c.IssueID).where(
                or_(
                    nzblog.c.IssueID == str(issueid),
                    nzblog.c.IssueID == "S" + str(issueid),
                )
            )
            if provider:
                stmt = stmt.where(nzblog.c.PROVIDER == provider)
            return db.select_one(stmt) is not None

        plain_stmt = select(nzblog.c.IssueID).where(nzblog.c.IssueID == str(issueid))
        if provider:
            plain_stmt = plain_stmt.where(nzblog.c.PROVIDER == provider)
        if db.select_one(plain_stmt) is not None:
            return True
        s_stmt = select(nzblog.c.IssueID).where(nzblog.c.IssueID == "S" + str(issueid))
        if provider:
            s_stmt = s_stmt.where(nzblog.c.PROVIDER == provider)
        return db.select_one(s_stmt) is not None
    except Exception as e:
        logger.warn("[RECOVERY-CLASSIFY] nzblog lookup failed for %s: %s" % (issueid, e))
        return None


_PLACED_STATUSES = ("Downloaded", "Post-Processed")


def _row_shows_placement(rec):
    if rec is None:
        return False
    if (rec["Status"] or "") in _PLACED_STATUSES:
        return True
    return bool(str(rec["Location"] or "").strip())


def _payload_story_arc(payload):
    """Tri-state arc signal from a journal payload: True (story arc), False
    (plain issue), or None when the payload carries no `mode`."""
    if isinstance(payload, dict) and "mode" in payload:
        return payload.get("mode") == "story_arc"
    return None


def _library_rows(issueid, story_arc):
    """The library rows that can carry placement evidence for an obligation
    (arc scoping as documented on has_library_placement): storyarcs unless the
    obligation is known-plain, issues/annuals unless it is known-arc. Returns
    a list of (Status, Location) rows, or None when a lookup failed — callers
    must treat None as "no evidence available", never fabricate."""
    recs = []
    try:
        if story_arc is not False:
            rec = db.select_one(
                select(storyarcs.c.Status, storyarcs.c.Location).where(storyarcs.c.IssueArcID == str(issueid))
            )
            if rec is not None:
                recs.append(rec)
        if story_arc is not True:
            for table in (issues, annuals):
                rec = db.select_one(select(table.c.Status, table.c.Location).where(table.c.IssueID == str(issueid)))
                if rec is not None:
                    recs.append(rec)
    except Exception as e:
        logger.warn("[RECOVERY-CLASSIFY] library row lookup failed for %s: %s" % (issueid, e))
        return None
    return recs


def has_library_placement(row, payload=None):
    """True iff the LIBRARY itself shows the import happened for this
    obligation (#734). A done-signal (nzblog absent / snatched history) only
    proves the DOWNLOAD finished; successful placement additionally writes
    Location + Status='Downloaded' onto the issues/annuals row (postprocessor
    ~3214/4052/4458) or Status='Downloaded' onto the storyarcs row
    (updater.foundsearch). Absent that evidence, "download complete" must not
    be conflated with "import complete".

    Arc scoping mirrors has_done_signal: payload["mode"]=="story_arc" means
    row.issueid is the IssueArcID and the storyarcs row is the authority.
    When mode is absent (e.g. a reconstructed anchor payload), check
    storyarcs first, then issues/annuals — evidence on any matching row
    counts. A lookup failure returns False (never fabricate placement)."""
    row = row or {}
    issueid = row.get("issueid")
    if issueid is None:
        return False
    if payload is None:
        payload = journal.load_payload(row.get("payload_json"))
    recs = _library_rows(issueid, _payload_story_arc(payload))
    if recs is None:
        return False
    return any(_row_shows_placement(rec) for rec in recs)


_REOPEN_SAFE_STATUSES = frozenset({"", "Snatched", "Wanted", "Failed"})


def false_terminal_reopen_candidate(row, payload=None):
    """#742: True iff a terminal ``post_processed`` journal row is safe to
    reopen for re-evaluation under the #736 placement contract. The pre-#736
    recovery could terminalize a row off a bare done-signal; such rows are
    structurally invisible to replay (read_open excludes terminals), so a
    startup backfill has to identify them from the library's own evidence.

    Reopenable ONLY when ALL hold:
      * the row is exactly at ``post_processed`` (never failed/manual_review/
        cancelled — those are other contracts);
      * the issueid is real (a synthetic-HIGHCOUNT one-off has no library row
        by design, so placement is unverifiable — leave terminal);
      * the library still tracks the obligation (a matching issues/annuals/
        storyarcs row exists — a removed series has nothing to recover into);
      * NO matching row shows placement evidence (same authority as
        has_library_placement); and
      * every matching row's status is placement-neutral (Snatched/Wanted/
        Failed/empty) — an operator-intent status stays untouched.

    Arc scoping mirrors has_library_placement. A lookup failure returns
    False — never reopen a terminal row on uncertainty."""
    row = row or {}
    if row.get("stage") != journal.POST_PROCESSED:
        return False
    issueid = row.get("issueid")
    if issueid is None or journal.is_synthetic_oneoff(issueid):
        return False
    if payload is None:
        payload = journal.load_payload(row.get("payload_json"))
    recs = _library_rows(issueid, _payload_story_arc(payload))
    if not recs:
        return False
    for rec in recs:
        if _row_shows_placement(rec):
            return False
        if (rec["Status"] or "") not in _REOPEN_SAFE_STATUSES:
            return False
    return True


def has_done_signal(row):
    """Cross-check the authoritative done-signals BEFORE any "absent" is
    allowed to become GONE.

    Returns True iff the release is authoritatively already complete:
      * journal stage is post_processing+, OR
      * issues.Status == 'Post-Processed', OR
      * nzblog row absent (deleted on PP success).

    One-off rule: for a synthetic-HIGHCOUNT one-off the nzblog-presence test
    is UNRELIABLE (non-persisted IssueID diverges across restart; mid-flight
    delete-reupsert window). For those rows the journal release_key/stage is
    AUTHORITATIVE and nzblog-presence is ADVISORY only — so we do NOT treat
    nzblog-absence as a done-signal for one-offs (an in-flight one-off must
    not be misread as done/GONE).
    """
    row = row or {}
    if _journal_stage_done(row):
        return True

    issueid = row.get("issueid")
    provider = row.get("provider")

    if _issue_post_processed(issueid):
        return True

    if journal.is_synthetic_oneoff(issueid):
        logger.fdebug(
            "[RECOVERY-CLASSIFY] one-off release_key=%s — nzblog-presence is "
            "ADVISORY only; journal stage is authoritative." % row.get("release_key")
        )
        return False

    story_arc = None
    try:
        pl = journal.load_payload(row.get("payload_json")) or {}
        if "mode" in pl:
            story_arc = pl.get("mode") == "story_arc"
    except Exception as e:
        logger.warn(
            "[RECOVERY-CLASSIFY] payload parse for arc-signal failed (%s) — using prefer-plain nzblog fallback." % e
        )

    present = _nzblog_present(issueid, provider, story_arc=story_arc)
    if present is False:
        return True
    return False


def _probe_torrent(row, payload=None):
    """Torrent: query torrentinfo() by hash. A hash NOT present in the client
    must now be an EXPLICIT NOT-FOUND ("absent") — see the service.py
    extension. A reachability failure is "unreachable". (payload accepted for
    a uniform probe signature; torrent identity is row['hash'], not payload.)"""
    h = row.get("hash")
    if not h:
        logger.warn("[RECOVERY-CLASSIFY] torrent row %s has no hash to probe." % row.get("release_key"))
        return "unreachable"
    try:
        from comicarr.app.search.service import torrentinfo

        snstat = torrentinfo(torrent_hash=h, monitor=False)
    except Exception as e:
        logger.warn("[RECOVERY-CLASSIFY] torrent client unreachable probing %s: %s" % (h, e))
        return "unreachable"

    if isinstance(snstat, dict) and snstat.get("snatch_status") == "NOT FOUND":
        return "absent"
    if not isinstance(snstat, dict):
        return "unreachable"

    status = snstat.get("snatch_status")
    if status == "IN PROGRESS":
        return "still"
    if status in ("MONITOR COMPLETE", "MONITOR STARTING"):
        return "complete"
    if status in ("MONITOR ERROR", "MONITOR FAIL"):
        return "unreachable"
    return "absent"


def _sab_history_or_queue(row, payload=None):
    """SAB: still in active queue ⇒ still; in history success ⇒ complete;
    not found in either ⇒ absent. Reuses sabnzbd.SABnzbd.historycheck()
    (history lookup by nzo_id) — the same path nzb_monitor/cdh use."""
    payload = payload if payload is not None else journal.load_payload(row.get("payload_json"))
    payload = payload or {}
    di = payload.get("download_info") or {}
    nzo_id = payload.get("nzo_id") or di.get("nzo_id") or row.get("nzo_id")
    if not nzo_id:
        logger.warn("[RECOVERY-CLASSIFY] SAB row %s has no nzo_id to probe." % row.get("release_key"))
        return "unreachable"
    try:
        from comicarr import sabnzbd

        nzbinfo = {
            "nzo_id": nzo_id,
            "issueid": row.get("issueid"),
            "comicid": payload.get("comicid"),
            "download_info": di,
            "queue": {
                "mode": "queue",
                "search": nzo_id,
                "output": "json",
                "apikey": comicarr.CONFIG.SAB_APIKEY,
            },
        }
        s = sabnzbd.SABnzbd({"queue": {"apikey": comicarr.CONFIG.SAB_APIKEY}})
        nzstat = s.historycheck(nzbinfo)
    except Exception as e:
        logger.warn("[RECOVERY-CLASSIFY] SAB unreachable probing %s: %s" % (nzo_id, e))
        return "unreachable"
    return nzstat


def _nzbget_history(row, payload=None):
    """NZBGet: history lookup by NZBID. Reuses nzbget.NZBGet.historycheck()."""
    payload = payload if payload is not None else journal.load_payload(row.get("payload_json"))
    payload = payload or {}
    di = payload.get("download_info") or {}
    nzbid = payload.get("NZBID") or di.get("NZBID") or row.get("NZBID")
    if not nzbid:
        logger.warn("[RECOVERY-CLASSIFY] NZBGet row %s has no NZBID to probe." % row.get("release_key"))
        return "unreachable"
    try:
        from comicarr import nzbget

        nzbinfo = {
            "NZBID": nzbid,
            "issueid": row.get("issueid"),
            "comicid": payload.get("comicid"),
            "download_info": di,
        }
        nz = nzbget.NZBGet()
        nzstat = nz.historycheck(nzbinfo)
    except Exception as e:
        logger.warn("[RECOVERY-CLASSIFY] NZBGet unreachable probing %s: %s" % (nzbid, e))
        return "unreachable"
    return nzstat


def _nzstat_to_raw(nzstat):
    """Map a SAB/NZBGet historycheck() return shape onto the raw probe
    vocabulary. (cdh_monitor's status mapping is the model here.)"""
    if not isinstance(nzstat, dict):
        return "unreachable"
    status = nzstat.get("status")
    if status is True:
        return "complete"
    if status in ("double-pp",):
        return "complete"
    if status in ("queue_paused",):
        return "still"
    if status is False:
        return "absent"
    return "complete"


_RAW_PROBE_STATES = frozenset(("still", "complete", "absent", "unreachable"))


def _probe_evidence(raw):
    """Normalize a probe return to (raw_state, location, name, failed).

    Test probes may return a raw state string. Built-in SAB/NZBGet probes
    (and richer test probes) may return a historycheck dict; location/name/
    failed are kept so recovery can stamp nzb_folder instead of discarding
    the path historycheck already resolved.
    """
    if isinstance(raw, str):
        return raw, None, None, None
    if not isinstance(raw, dict):
        return "unreachable", None, None, None
    location = raw.get("location")
    name = raw.get("name")
    failed = raw.get("failed")
    status = raw.get("status")
    if status in _RAW_PROBE_STATES:
        raw_state = status
    else:
        raw_state = _nzstat_to_raw(raw)
    return raw_state, location, name, failed


def _empty_details(verdict=UNKNOWN):
    return {"verdict": verdict, "location": None, "name": None, "failed": None}


def _probe_nzb(row, payload=None):
    if comicarr.USE_SABNZBD is True:
        return _sab_history_or_queue(row, payload=payload)
    if comicarr.USE_NZBGET is True:
        return _nzbget_history(row, payload=payload)
    logger.warn("[RECOVERY-CLASSIFY] No NZB client enabled — cannot probe %s." % row.get("release_key"))
    return "unreachable"


def _ddl_link_alive(link):
    """Recheck a DDL source link. Alive ⇒ the download could still resume;
    dead ⇒ (combined with status=Downloading) the source is GONE. A network
    error rechecking the link is treated as 'unreachable' (do not bury a
    recoverable item on a transient outage)."""
    if not link:
        return None
    try:
        resp = requests.head(link, allow_redirects=True, timeout=15)
        code = resp.status_code
        if code == 405:
            resp = requests.get(link, stream=True, timeout=15, headers={"Range": "bytes=0-0"})
            code = resp.status_code
    except requests.RequestException as e:
        logger.warn("[RECOVERY-CLASSIFY] DDL link recheck network error (%s): %s" % (link, e))
        return None
    return code < 400


def _probe_ddl(row, payload=None):
    """DDL: ddl_info.status + source-link recheck.

    * status == 'Completed'              ⇒ complete
    * status == 'Failed'                 ⇒ absent (no done-signal ⇒ GONE)
    * status == 'Downloading' + link OK  ⇒ still
    * status == 'Downloading' + dead link ⇒ absent (⇒ GONE)
    * ddl_info row missing               ⇒ absent
    * link recheck network error         ⇒ unreachable
    """
    payload = payload if payload is not None else journal.load_payload(row.get("payload_json"))
    payload = payload or {}
    di = payload.get("download_info") or {}
    ddl_id = payload.get("ddl_id") or payload.get("id") or di.get("id") or row.get("ddl_id")
    issueid = row.get("issueid")
    try:
        stmt = select(ddl_info)
        if ddl_id:
            stmt = stmt.where(ddl_info.c.ID == str(ddl_id))
        elif issueid is not None:
            stmt = stmt.where(ddl_info.c.issueid == str(issueid))
        else:
            return "absent"
        rec = db.select_one(stmt)
    except Exception as e:
        logger.warn("[RECOVERY-CLASSIFY] ddl_info lookup failed for %s: %s" % (row.get("release_key"), e))
        return "unreachable"

    if rec is None:
        return "absent"

    status = rec["status"]
    if status == "Completed":
        return "complete"
    if status == "Downloading":
        alive = _ddl_link_alive(rec["link"] or rec["mainlink"])
        if alive is None:
            return "unreachable"
        return "still" if alive else "absent"
    return "absent"


_DEFAULT_PROBES = {
    "torrent": _probe_torrent,
    "rtorrent": _probe_torrent,
    "deluge": _probe_torrent,
    "nzb": _probe_nzb,
    "sab": _sab_history_or_queue,
    "sabnzbd": _sab_history_or_queue,
    "nzbget": _nzbget_history,
    "ddl": _probe_ddl,
    "DDL": _probe_ddl,
}


def _resolve_downloader(row, payload=None):
    payload = payload if payload is not None else journal.load_payload((row or {}).get("payload_json"))
    payload = payload or {}
    route = str(payload.get("route") or "").strip().lower()
    if route in _DEFAULT_PROBES:
        return route
    dt = (row or {}).get("downloader_type")
    if dt:
        return dt
    if payload.get("ddl") is True:
        return "ddl"
    di = payload.get("download_info") or {}
    prov = (di.get("provider") or "").lower()
    if prov == "ddl":
        return "ddl"
    if row.get("hash"):
        return "torrent"
    return "nzb"


def classify_details(row, probes=None, payload=None):
    """Classify one open journal row and return completion evidence.

    Returns ``{verdict, location, name, failed}``. ``verdict`` is one of
    STILL/COMPLETE/GONE/UNKNOWN. ``location``/``name``/``failed`` come from a
    richer SAB/NZBGet probe result when present; they are None when the probe
    returned only a raw state string. PURE: never mutates the journal.

    `probes` (test seam): optional {downloader_type: callable(row)->raw}
    overriding the real client-query paths. `raw` is one of
    "still"/"complete"/"absent"/"unreachable", or a historycheck-shaped dict
    with ``status`` plus optional ``location``/``name``/``failed``.

    `payload` (efficiency): the already-decoded payload_json dict, parsed once
    per replay row by the caller and threaded in to avoid re-parsing it for
    _resolve_downloader / has_done_signal. Default None ⇒ parse internally so
    existing callers/tests still work. The injectable `probes` are still
    invoked as probe(row) (the test seam's contract); the built-in probes do
    their own single internal parse.
    """
    if not row:
        return _empty_details(UNKNOWN)
    if payload is None:
        payload = journal.load_payload(row.get("payload_json"))
    rkey = row.get("release_key")
    downloader = _resolve_downloader(row, payload=payload)
    probe = (probes or _DEFAULT_PROBES).get(downloader)
    if probe is None:
        logger.warn(
            "[RECOVERY-CLASSIFY] No probe for downloader_type=%r (release_key=%s) "
            "— UNKNOWN, journal left unchanged." % (downloader, rkey)
        )
        return _empty_details(UNKNOWN)

    try:
        raw = probe(row)
    except Exception as e:
        logger.warn("[RECOVERY-CLASSIFY] probe raised for %s (%s) — UNKNOWN: %s" % (rkey, downloader, e))
        return _empty_details(UNKNOWN)

    raw_state, location, name, failed = _probe_evidence(raw)
    details = {"verdict": UNKNOWN, "location": location, "name": name, "failed": failed}

    if raw_state == "still":
        logger.fdebug("[RECOVERY-CLASSIFY] %s -> still (in client)" % rkey)
        details["verdict"] = STILL
        return details
    if raw_state == "complete":
        logger.fdebug("[RECOVERY-CLASSIFY] %s -> complete (done at downloader)" % rkey)
        details["verdict"] = COMPLETE
        return details
    if raw_state == "unreachable":
        logger.warn(
            "[RECOVERY-CLASSIFY] %s -> UNKNOWN (downloader API unreachable / "
            "transient) — journal stage left unchanged." % rkey
        )
        details["verdict"] = UNKNOWN
        return details

    if has_done_signal(row):
        logger.fdebug(
            "[RECOVERY-CLASSIFY] %s absent in client BUT done-signal present "
            "(history likely evicted while down) -> complete, NOT gone." % rkey
        )
        details["verdict"] = COMPLETE
        return details

    logger.warn(
        "[RECOVERY-CLASSIFY] %s absent from a reachable client with NO "
        "done-signal -> GONE (will be marked failed, payload retained)." % rkey
    )
    details["verdict"] = GONE
    return details


def classify(row, probes=None, payload=None):
    """Classify one open journal row. Returns one of STILL/COMPLETE/GONE/
    UNKNOWN. PURE: never mutates the journal.

    Thin wrapper over :func:`classify_details` so existing callers and tests
    keep receiving the same verdict strings.
    """
    return classify_details(row, probes=probes, payload=payload)["verdict"]


def apply_verdict(row, verdict, conn=None):
    """Optional convenience for a caller (U6) that wants the single journal
    mutation U5 OWNS: GONE -> Attention failure (distinguishable
    fail_reason, payload retained for R9; replay never re-queues a failed
    row). For STILL/COMPLETE/UNKNOWN this is a deliberate NO-OP — those are
    the caller's / U6 replay's responsibility (re-enqueue / PP / leave
    unchanged). This keeps classify() pure and keeps replay orchestration
    OUT of this module.

    Returns True iff a journal write occurred.
    """
    if verdict != GONE:
        return False
    rkey = row.get("release_key")
    payload = journal.load_payload(row.get("payload_json"))

    di = (payload or {}).get("download_info") or {}
    ddl_id = di.get("id") or row.get("ddl_id")
    if ddl_id is not None:
        try:
            comicarr.DDL_STUCK_NOTIFIED.add(ddl_id)
        except Exception as e:
            logger.warn("[RECOVERY-CLASSIFY] could not reconcile DDL_STUCK_NOTIFIED for %s: %s" % (ddl_id, e))
        try:
            if conn is not None:
                db.upsert_conn(conn, "ddl_info", {"status": "Failed"}, {"ID": ddl_id})
            else:
                db.upsert("ddl_info", {"status": "Failed"}, {"ID": ddl_id})
        except Exception as e:
            logger.error("[RECOVERY-CLASSIFY] could not reconcile ddl_info terminal state for %s: %s" % (ddl_id, e))

    outcome = record(
        Failure(
            release_key=rkey,
            reason=FAIL_REASON_GONE,
            payload=payload,
            issue_id=row.get("issueid"),
            provider=row.get("provider"),
            downloader_type=row.get("downloader_type"),
            nzb_name=row.get("nzbname") or (payload or {}).get("nzbname") or (payload or {}).get("filename"),
            release_id=ddl_id,
            download_hash=row.get("hash"),
        ),
        conn=conn,
    )
    if outcome.transition_won:
        logger.warn(
            "[RECOVERY-CLASSIFY] %s marked failed (reason=%s) — release blocklisted and "
            "issue re-wanted when resolvable (#541); replay will NOT re-queue it." % (rkey, FAIL_REASON_GONE)
        )
    else:
        logger.fdebug(
            "[RECOVERY-CLASSIFY] %s not marked failed (reason=%s): the journal transition was "
            "already taken by another writer; no journal write occurred here." % (rkey, FAIL_REASON_GONE)
        )
    return outcome.transition_won
