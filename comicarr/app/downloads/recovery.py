#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""
Startup recovery replay orchestrator.

Runs ONCE at startup, AFTER ``comicarr.start()`` returns (INIT_LOCK released)
and AFTER credential decryption, and BEFORE ``uvicorn.run()``. Re-drives every
open pipeline_journal obligation through its remaining stages, exactly once,
with no operator action. Idempotent and re-runnable.

Module boundary: orchestration ONLY. journal.py owns the monotonic stage
lattice / release_key derivation / terminal predicate; recovery_classify.py
owns the per-downloader verdict and records the GONE failure through Attention.

Snapshot-then-RECHECK-then-act: anchor reconstruction first (rebuild a
`snatched` journal row for the residual window where the snatch committed
durably but the strictly-last journal write was lost — only when the release
has NOT already advanced, so this never mass-re-drives every
historically-snatched issue), then a read_open() snapshot, then for each row
re-read its current stage with a cheap point lookup before acting (workers are
live; skip if it advanced past the snapshot). The enqueue burst is throttled
so replay does not exhaust the SQLite 5-retry write cap against concurrent PP
workers; a failing row is logged LOUDLY and SKIPPED (resumable next start),
never aborting the loop.
"""

import time

from sqlalchemy import and_, delete, or_, select

import comicarr
from comicarr import db, logger
from comicarr.app.attention import ManualReview, record
from comicarr.app.downloads import journal, recovery_classify
from comicarr.app.downloads.ddl_commands import DDLCommand, DDLCommandError
from comicarr.app.downloads.pp_commands import PostProcessCommandError, validate_postprocess_item
from comicarr.tables import ddl_info, nzblog, pipeline_journal, snatched, storyarcs

_ENQUEUE_THROTTLE_SECONDS = 0.05

_MAX_INLINE_PP_REDRIVE_PER_PASS = 5


def _reconcile_legacy_ddl_downloading():
    """Quarantine legacy Downloading rows that have no exact journal anchor."""
    rows = db.select_all(select(ddl_info).where(ddl_info.c.status == "Downloading")) or []
    reviewed = 0
    for ddl_row in rows:
        ddl_id = ddl_row.get("ID")
        candidates = db.select_all(
            select(pipeline_journal).where(
                pipeline_journal.c.issueid == str(ddl_row.get("issueid")),
                pipeline_journal.c.downloader_type == "ddl",
            )
        )
        anchored = False
        for candidate in candidates or []:
            payload = journal.load_payload(candidate.get("payload_json")) or {}
            di = payload.get("download_info") or {}
            if str(payload.get("ddl_id") or payload.get("id") or di.get("id") or "") == str(ddl_id):
                anchored = True
                break
        if anchored:
            continue

        rkey = journal.release_key(
            ddl_row.get("issueid"),
            "DDL",
            nzbname=ddl_row.get("filename"),
            discriminant=ddl_id,
        )
        legacy_payload = {
            "issueid": ddl_row.get("issueid"),
            "comicid": ddl_row.get("comicid"),
            "provider": "DDL",
            "ddl_id": ddl_id,
            "filename": ddl_row.get("filename"),
            "ddl": True,
        }
        record(
            ManualReview(
                release_key=rkey,
                reason="legacy_downloading_without_correlation",
                payload=legacy_payload,
                issue_id=ddl_row.get("issueid"),
                provider="DDL",
                downloader_type="ddl",
                nzb_name=ddl_row.get("filename"),
                release_id=ddl_id,
                comic_id=ddl_row.get("comicid"),
            )
        )
        db.upsert("ddl_info", {"status": "Manual Review"}, {"ID": ddl_id})
        reviewed += 1
    return reviewed


def _has_advanced_sibling(issueid, provider):
    """True iff, for this (IssueID, Provider), a `Downloaded` or
    `Post-Processed` sibling `snatched` row exists. The snatched table keys on
    (IssueID, Status, Provider), so a COMPLETED item keeps its original
    Status='Snatched' row forever ALONGSIDE a Downloaded/Post-Processed row —
    presence of such a sibling means the release already advanced and must NOT
    be reconstructed as an open obligation."""
    try:
        rec = db.select_one(
            select(snatched.c.IssueID).where(
                and_(
                    snatched.c.IssueID == str(issueid),
                    snatched.c.Provider == provider,
                    snatched.c.Status.in_(("Downloaded", "Post-Processed")),
                )
            )
        )
    except Exception as e:
        logger.warn("[RECOVERY] advanced-sibling lookup failed for %s/%s: %s" % (issueid, provider, e))
        return True
    return rec is not None


def _is_story_arc_obligation(issueid):
    """Story-arc discriminator for a `snatched`/recovery row (the snatched
    table has NO `mode`/SARC column, so the payload-`mode` signal used on
    journal rows is unavailable here). updater.foundsearch ALWAYS upserts a
    `storyarcs` row keyed IssueArcID and writes the snatched row with
    IssueID == that IssueArcID for a story-arc snatch (updater.py
    ~1307/1327-1357). So: a `storyarcs` row whose IssueArcID equals this
    snatched IssueID ⇒ this is a story-arc obligation; otherwise it is a
    plain issue. Returns True/False, or None when the lookup is unanswerable
    (caller then uses the minimally-safe prefer-plain fallback)."""
    if issueid is None:
        return None
    try:
        rec = db.select_one(select(storyarcs.c.IssueArcID).where(storyarcs.c.IssueArcID == str(issueid)))
    except Exception as e:
        logger.warn("[RECOVERY] story-arc discriminator lookup failed for %s: %s" % (issueid, e))
        return None
    return rec is not None


def _reconstruct_anchors():
    """Rebuild a missing `snatched` journal row for the U2 residual window
    (snatch committed durably but the strictly-last journal write was lost).

    Predicate (corrected): reconstruct ONLY when, for that (IssueID,
    Provider), there is NO Downloaded/Post-Processed sibling `snatched` row
    AND `nzblog` is still present. For synthetic-HIGHCOUNT one-off IssueIDs
    the nzblog test is unreliable (non-persisted IssueID diverges across
    restart; nzblog mid-flight delete/reupsert window) — for those the
    journal release_key is authoritative and nzblog-presence is ADVISORY
    only, so an in-flight one-off is still reconstructed even if its nzblog
    row is not matchable. Otherwise the release already advanced — do NOT
    reconstruct (this prevents mass re-drive of every historically-snatched
    issue)."""
    try:
        live_snatched = db.select_all(select(snatched).where(snatched.c.Status == "Snatched"))
    except Exception as e:
        logger.error("[RECOVERY] anchor scan failed (snatched): %s — skipping reconstruction." % e)
        return 0

    reconstructed = 0
    for srow in live_snatched or []:
        try:
            issueid = srow.get("IssueID")
            provider = srow.get("Provider")
            if issueid is None or provider is None:
                continue

            is_arc = _is_story_arc_obligation(issueid)
            nzbrow = None
            try:
                if is_arc is True:
                    nzbrow = db.select_one(
                        select(nzblog).where(
                            and_(
                                or_(
                                    nzblog.c.IssueID == str(issueid),
                                    nzblog.c.IssueID == "S" + str(issueid),
                                ),
                                nzblog.c.PROVIDER == provider,
                            )
                        )
                    )
                elif is_arc is False:
                    nzbrow = db.select_one(
                        select(nzblog).where(
                            and_(
                                nzblog.c.IssueID == str(issueid),
                                nzblog.c.PROVIDER == provider,
                            )
                        )
                    )
                else:
                    nzbrow = db.select_one(
                        select(nzblog).where(
                            and_(
                                nzblog.c.IssueID == str(issueid),
                                nzblog.c.PROVIDER == provider,
                            )
                        )
                    )
                    if nzbrow is None:
                        nzbrow = db.select_one(
                            select(nzblog).where(
                                and_(
                                    nzblog.c.IssueID == "S" + str(issueid),
                                    nzblog.c.PROVIDER == provider,
                                )
                            )
                        )
            except Exception as e:
                logger.warn("[RECOVERY] nzblog lookup failed for %s/%s: %s" % (issueid, provider, e))
            durable_nzbname = nzbrow.get("NZBName") if nzbrow else srow.get("FolderName")

            rkey = journal.release_key(
                issueid,
                provider,
                nzbname=durable_nzbname,
                hash=srow.get("Hash"),
                discriminant=srow.get("Hash") or durable_nzbname or dict(srow),
            )

            if journal.read_one(rkey) is not None:
                continue

            if _has_advanced_sibling(issueid, provider):
                logger.fdebug(
                    "[RECOVERY] anchor skip %s/%s — Downloaded/Post-Processed "
                    "sibling present (release already advanced)." % (issueid, provider)
                )
                continue

            oneoff = journal.is_synthetic_oneoff(issueid)
            if not oneoff and not recovery_classify._nzblog_present(issueid, provider, story_arc=is_arc):
                logger.fdebug(
                    "[RECOVERY] anchor skip %s/%s — nzblog absent (PP completed; "
                    "live Snatched row is the never-deleted original)." % (issueid, provider)
                )
                continue
            if oneoff:
                logger.fdebug(
                    "[RECOVERY] anchor %s/%s is a synthetic-HIGHCOUNT one-off — "
                    "nzblog-presence ADVISORY only; journal release_key "
                    "authoritative; reconstructing as in-flight." % (issueid, provider)
                )

            is_ddl = "DDL" in str(provider or "").upper()
            if srow.get("Hash"):
                downloader_type = "torrent"
            elif is_ddl:
                downloader_type = "ddl"
            else:
                downloader_type = "nzb"

            payload = {
                "issueid": issueid,
                "comicid": srow.get("ComicID"),
                "provider": provider,
                "hash": srow.get("Hash"),
                "nzbname": durable_nzbname,
                "comicname": srow.get("ComicName"),
                "issuenumber": srow.get("Issue_Number"),
            }
            if is_ddl:
                payload["ddl"] = True
                payload["download_info"] = {"provider": "DDL"}
            journal.record_transition(
                rkey,
                journal.SNATCHED,
                payload=payload,
                issueid=issueid,
                provider=provider,
                downloader_type=downloader_type,
                nzbname=srow.get("FolderName"),
                hash=srow.get("Hash"),
            )
            reconstructed += 1
            logger.info(
                "[RECOVERY] reconstructed missing snatched journal row %s "
                "(IssueID=%s provider=%s) from durable snatched/nzblog." % (rkey, issueid, provider)
            )
        except Exception as e:
            logger.error("[RECOVERY] anchor reconstruction error for %s: %s" % (srow, e))
            continue

    if reconstructed:
        logger.info("[RECOVERY] anchor reconstruction rebuilt %d row(s)." % reconstructed)
    return reconstructed


def _reclassify_false_terminal_imports():
    """#742 backfill (idempotent, safe every boot): rows the pre-#736 recovery
    marked ``post_processed`` off a bare done-signal are terminal, so
    read_open() never revisits them — the false "import / succeeded" is
    permanent and the files stay stranded in the download directory. Scan the
    terminal ``post_processed`` rows, and for each one the LIBRARY contradicts
    (no placement evidence, still tracked, no operator-intent status — the
    recovery_classify.false_terminal_reopen_candidate contract), demote it
    back to ``snatched`` via the journal's single sanctioned backward write.
    The reopened rows join THIS pass's read_open() snapshot, where the fixed
    #736 path re-drives the import or quarantines to needs_attention.

    Rows that end the pass at manual_review/failed/post_processed-with-
    placement are never re-scanned; a row left open (UNKNOWN) is a normal
    obligation from then on. Returns the number of reopened rows."""
    try:
        rows = db.select_all(select(pipeline_journal).where(pipeline_journal.c.stage == journal.POST_PROCESSED)) or []
    except Exception as e:
        logger.error("[RECOVERY] #742 backfill could not read terminal rows: %s" % type(e).__name__)
        return 0

    reopened = 0
    for row in rows:
        rkey = row.get("release_key")
        try:
            payload = journal.load_payload(row.get("payload_json"))
            if not recovery_classify.false_terminal_reopen_candidate(row, payload=payload):
                continue
            if journal.reopen_false_terminal(rkey):
                reopened += 1
                logger.warn(
                    "[RECOVERY] %s was terminal `post_processed` but the library "
                    "shows NO placement evidence (pre-#736 false done-signal) — "
                    "reopened for re-evaluation this pass (#742)." % rkey
                )
        except Exception as e:
            logger.error("[RECOVERY] #742 backfill error for %s — SKIPPED: %s" % (rkey, type(e).__name__))
            continue
    if reopened:
        logger.info("[RECOVERY] #742 backfill reopened %d falsely-terminal row(s)." % reopened)
    return reopened


def _merge_completion_evidence(payload, details):
    """Copy probe-reported completion location/name into the journal payload.

    SAB/NZBGet snatch payloads have no nzb_folder (addfile returns nzo_ids
    only). Recovery already resolved the folder via historycheck; keep it.
    Do not invent a path the probe did not return.
    """
    merged = dict(payload or {})
    details = details or {}
    location = details.get("location")
    if location:
        merged["nzb_folder"] = str(location)
    name = details.get("name")
    if name and not merged.get("nzb_name") and not merged.get("nzbname"):
        merged["nzb_name"] = name
    if details.get("failed") is not None:
        merged["failed"] = bool(details.get("failed"))
    return merged


def _pp_item_from_row(row, payload):
    """Reconstruct a PP_QUEUE item dict from a journal row's payload. The
    authoritative release_key is stamped as `journal_release_key` so the U4
    atomic claim (downloaded -> post_processing) advances THIS row (same
    propagation contract U3/U4 established — never re-derived)."""
    payload = payload or {}
    nzb_name = payload.get("nzb_name") or payload.get("nzbname") or row.get("nzbname")
    nzb_folder = payload.get("nzb_folder")
    return {
        "nzb_name": nzb_name,
        "nzb_folder": nzb_folder,
        "failed": bool(payload.get("failed", False)),
        "issueid": payload.get("issueid") or row.get("issueid"),
        "comicid": payload.get("comicid"),
        "apicall": payload.get("apicall", True),
        "ddl": bool(payload.get("ddl", False)),
        "download_info": payload.get("download_info"),
        "journal_release_key": row.get("release_key"),
    }


def _resume_item_from_row(row, payload):
    """Reconstruct the SNATCHED_QUEUE / NZB_QUEUE item so the live monitor
    (whose in-memory tracking did NOT survive the restart) re-owns a `still`
    download. SNATCHED_QUEUE (torrent) items are {issueid, comicid, hash};
    NZB_QUEUE items are the SAB/NZBGet sender dict shape — we rebuild the
    identity fields from the journal payload (the U2 snatch payload)."""
    payload = payload or {}
    downloader = (row.get("downloader_type") or "").lower()

    di = payload.get("download_info") or {}
    is_ddl = (
        downloader == "ddl"
        or payload.get("ddl") is True
        or str(payload.get("provider") or row.get("provider") or "").upper() == "DDL"
        or str(di.get("provider") or "").upper() == "DDL"
    )
    if is_ddl:
        ddl_id = payload.get("ddl_id") or payload.get("id") or di.get("id") or row.get("ddl_id")
        try:
            command = DDLCommand.from_mapping(payload).to_queue_item()
            if row.get("release_key"):
                command["journal_release_key"] = row.get("release_key")
            return "ddl", command
        except DDLCommandError:
            pass
        if ddl_id:
            try:
                from comicarr.app.downloads import queries as dl_queries

                durable = dl_queries.get_ddl_item(ddl_id)
                if durable:
                    command = DDLCommand.from_mapping(durable).to_queue_item()
                    if row.get("release_key"):
                        command["journal_release_key"] = row.get("release_key")
                    return "ddl", command
            except DDLCommandError:
                pass
            except Exception as e:
                logger.fdebug("[RECOVERY] Unable to rebuild DDL command %s from ddl_info: %s" % (ddl_id, e))
        return "ddl", {
            "id": ddl_id,
            "issueid": payload.get("issueid") or row.get("issueid"),
            "comicid": payload.get("comicid"),
            "series": payload.get("series"),
            "filename": payload.get("filename") or payload.get("nzb_name"),
            "site": payload.get("site"),
            "link": payload.get("link"),
            "ddl": True,
            "journal_release_key": row.get("release_key"),
        }

    if downloader == "torrent" or row.get("hash"):
        return "torrent", {
            "issueid": payload.get("issueid") or row.get("issueid"),
            "comicid": payload.get("comicid"),
            "hash": payload.get("hash") or row.get("hash"),
            "provider": payload.get("provider") or row.get("provider"),
            "nzbname": payload.get("nzbname") or row.get("nzbname"),
            "journal_release_key": row.get("release_key"),
            "clientmode": downloader,
        }
    route = str(payload.get("route") or downloader or "").lower()
    item = {
        "issueid": payload.get("issueid") or row.get("issueid"),
        "comicid": payload.get("comicid"),
        "apicall": True,
        "download_info": payload.get("download_info") or {"provider": row.get("provider")},
        "journal_release_key": row.get("release_key"),
        "clientmode": route,
    }
    if route in {"sab", "sabnzbd"}:
        nzo_id = payload.get("nzo_id") or di.get("nzo_id")
        item.update(
            {
                "nzo_id": nzo_id,
                "clientmode": "sabnzbd",
                "queue": {
                    "mode": "queue",
                    "search": nzo_id,
                    "output": "json",
                    "apikey": comicarr.CONFIG.SAB_APIKEY,
                },
            }
        )
    elif route == "nzbget":
        item["NZBID"] = payload.get("NZBID") or di.get("NZBID")
    return "nzb", item


def finalize_post_processing(row, payload=None):
    """Resolve a row already inside post-processing using the `moved` marker
    as the SOLE discriminator — NO file probe anywhere on this path (a probe
    is undecidable in copy/hardlink/softlink FILE_OPTS modes where the source
    is never deleted):

      * stage `moved`           -> the destructive move physically committed
        (source may already be gone). Finish the DB facts ONLY — mirror the
        U9 atomic block (single begin(): nzblog-delete + journal
        post_processed). NEVER re-import / re-move.
      * stage `post_processing` -> the move did NOT commit (source intact).
        Re-drive PP in FULL by invoking process.Process DIRECTLY, threading
        the authoritative release_key so the postprocessor markers advance
        THIS row. NOT via PP_QUEUE: the U4 claim is a downloaded ->
        post_processing advance and a row already at post_processing would
        LOSE that claim and be dropped — so the finalizer bypasses it.

    Returns a short string describing the action taken (for logging/tests).
    """
    rkey = row.get("release_key")
    stage = row.get("stage")
    if payload is None:
        payload = journal.load_payload(row.get("payload_json"))

    if stage == journal.MOVED:
        issueid = row.get("issueid")
        provider = row.get("provider")
        story_arc = None
        if isinstance(payload, dict) and "mode" in payload:
            story_arc = payload.get("mode") == "story_arc"
        if story_arc is None:
            story_arc = _is_story_arc_obligation(issueid)
        nzbname = (payload or {}).get("nzbname") if isinstance(payload, dict) else None
        with db.get_engine().begin() as conn:
            if story_arc is False:
                id_pred = nzblog.c.IssueID == str(issueid)
            elif story_arc is True:
                id_pred = or_(
                    nzblog.c.IssueID == str(issueid),
                    nzblog.c.IssueID == "S" + str(issueid),
                )
            else:
                if nzbname:
                    id_pred = and_(
                        or_(
                            nzblog.c.IssueID == str(issueid),
                            nzblog.c.IssueID == "S" + str(issueid),
                        ),
                        nzblog.c.NZBName == nzbname,
                    )
                else:
                    id_pred = nzblog.c.IssueID == str(issueid)
            stmt = delete(nzblog).where(id_pred)
            if provider:
                stmt = stmt.where(nzblog.c.PROVIDER == provider)
            conn.execute(stmt)
            journal.record_transition(
                rkey,
                journal.POST_PROCESSED,
                payload=payload,
                conn=conn,
                issueid=issueid,
                provider=provider,
            )
        logger.info(
            "[RECOVERY] %s was `moved` (physical move committed) — finished DB "
            "facts only (nzblog-delete + journal post_processed); did NOT "
            "re-import." % rkey
        )
        return "moved-finish-dbfacts"

    if stage == journal.POST_PROCESSING:
        item = _pp_item_from_row(row, payload or {})
        from comicarr.app.downloads.service import _configured_postprocess_roots

        try:
            item = validate_postprocess_item(
                item,
                roots=_configured_postprocess_roots(),
            )
        except PostProcessCommandError as e:
            record(
                ManualReview(
                    release_key=rkey,
                    reason="invalid_recovered_postprocess_command:%s" % type(e).__name__,
                    payload=payload,
                    issue_id=row.get("issueid"),
                    provider=row.get("provider"),
                )
            )
            logger.error("[RECOVERY] %s PP command is unsafe; quarantined: %s" % (rkey, e))
            return "post_processing-manual-review"
        logger.info(
            "[RECOVERY] %s was `post_processing` (no `moved` — move did NOT "
            "commit, source intact) — re-driving PP in full." % rkey
        )
        from comicarr import process
        from comicarr.app.acquisition.maintenance import MaintenanceController

        controller = MaintenanceController()
        try:
            with controller.lease(
                "startup-recovery",
                "postprocess-redrive",
                entity_type="release",
                entity_id=rkey,
            ) as lease:
                controller.assert_lease_current(lease)
                try:
                    pprocess = process.Process(
                        item["nzb_name"],
                        item["nzb_folder"],
                        item["failed"],
                        item["issueid"],
                        item["comicid"],
                        item["apicall"],
                        item["ddl"],
                        item["download_info"],
                        journal_release_key=rkey,
                    )
                except (KeyError, TypeError) as e:
                    logger.fdebug("[RECOVERY] extended process.Process construction failed, using fallback: %s" % e)
                    pprocess = process.Process(
                        item["nzb_name"],
                        item["nzb_folder"],
                        item["failed"],
                        item["issueid"],
                        item["comicid"],
                        item["apicall"],
                        journal_release_key=rkey,
                    )
                pprocess.post_process()
        except Exception as e:
            record(
                ManualReview(
                    release_key=rkey,
                    reason="recovered_postprocess_error:%s" % type(e).__name__,
                    payload=payload,
                    issue_id=row.get("issueid"),
                    provider=row.get("provider"),
                )
            )
            logger.error("[RECOVERY] %s PP redrive failed and was quarantined: %s" % (rkey, type(e).__name__))
            return "post_processing-manual-review"
        return "post_processing-redrive"

    logger.warn("[RECOVERY] finalize_post_processing called for %s with non-PP stage=%s — ignored." % (rkey, stage))
    return "ignored"


def _resolve_row(snapshot_row, probes=None, pp_cap=None):
    """Resolve ONE open obligation. RECHECKS the row's current stage with a
    cheap point lookup before acting (workers are live; skip if it advanced
    past the snapshot). Returns a short action string for logging/tests.

    `pp_cap` (startup availability cap): a mutable {"count": int} threaded by
    replay_pipeline. Each INLINE `post_processing` re-drive increments it; once
    it reaches _MAX_INLINE_PP_REDRIVE_PER_PASS the remaining post_processing
    rows are SKIPPED this pass (loud log) and resume next startup. `moved`
    (cheap DB-facts only) and all other paths are NOT capped."""
    rkey = snapshot_row.get("release_key")

    current = journal.read_one(rkey)
    if current is None:
        logger.fdebug("[RECOVERY] %s vanished from journal between snapshot and act — skip." % rkey)
        return "skip-vanished"
    cur_stage = current.get("stage")
    if journal.is_terminal(cur_stage):
        logger.fdebug("[RECOVERY] %s already terminal (%s) — skip." % (rkey, cur_stage))
        return "skip-terminal"
    snap_rank = journal.stage_rank(snapshot_row.get("stage"))
    cur_rank = journal.stage_rank(cur_stage)
    if snap_rank is not None and cur_rank is not None and cur_rank > snap_rank:
        logger.info(
            "[RECOVERY] %s advanced %s -> %s between snapshot and act (live "
            "worker) — skip (no redundant re-enqueue)." % (rkey, snapshot_row.get("stage"), cur_stage)
        )
        return "skip-advanced"

    row = current
    payload = journal.load_payload(row.get("payload_json"))

    if cur_stage == journal.RESERVED:
        record(
            ManualReview(
                release_key=rkey,
                reason="reserved_without_persisted_acceptance",
                payload=payload,
                issue_id=row.get("issueid"),
                provider=row.get("provider"),
                downloader_type=row.get("downloader_type"),
            )
        )
        return "reserved-manual-review"

    if cur_stage == journal.MOVED:
        return finalize_post_processing(row, payload=payload)
    if cur_stage == journal.POST_PROCESSING:
        if pp_cap is not None and pp_cap.get("count", 0) >= _MAX_INLINE_PP_REDRIVE_PER_PASS:
            logger.warn(
                "[RECOVERY] %s is `post_processing` but the inline PP re-drive "
                "cap (%d) for this replay pass is reached — DEFERRING; it "
                "resumes next startup (replay is idempotent/re-runnable)." % (rkey, _MAX_INLINE_PP_REDRIVE_PER_PASS)
            )
            return "skip-pp-cap-deferred"
        if pp_cap is not None:
            pp_cap["count"] = pp_cap.get("count", 0) + 1
        return finalize_post_processing(row, payload=payload)

    if cur_stage == journal.DOWNLOADED:
        item = _pp_item_from_row(row, payload)
        from comicarr.app.downloads.service import _configured_postprocess_roots

        try:
            item = validate_postprocess_item(item, roots=_configured_postprocess_roots())
        except PostProcessCommandError as e:
            record(
                ManualReview(
                    release_key=rkey,
                    reason="downloaded_invalid_artifact_command:%s" % type(e).__name__,
                    payload=payload,
                    issue_id=row.get("issueid"),
                    provider=row.get("provider"),
                )
            )
            logger.error("[RECOVERY] %s downloaded artifact command is unsafe; quarantined: %s" % (rkey, e))
            return "downloaded-manual-review"
        comicarr.PP_QUEUE.put(item)
        logger.info("[RECOVERY] %s has a durable downloaded artifact; enqueued directly for PP." % rkey)
        return "downloaded-pp-enqueued"

    done_without_placement = False
    if recovery_classify.has_done_signal(row):
        if recovery_classify.has_library_placement(row, payload=payload):
            logger.info("[RECOVERY] %s authoritatively done (Status/nzblog) — mark_done, skip." % rkey)
            journal.mark_done(
                rkey,
                issueid=row.get("issueid"),
                provider=row.get("provider"),
            )
            return "done-check"
        done_without_placement = True
        logger.warn(
            "[RECOVERY] %s has a done-signal (Status/nzblog) but NO library "
            "placement evidence — download complete is not import complete "
            "(#734); NOT marking post_processed. Classifying so the import "
            "can be re-driven." % rkey
        )

    details = recovery_classify.classify_details(row, probes=probes, payload=payload)
    verdict = details.get("verdict")

    if verdict == recovery_classify.GONE:
        recovery_classify.apply_verdict(row, verdict)
        return "gone-failed"

    if verdict == recovery_classify.UNKNOWN:
        if done_without_placement:
            record(
                ManualReview(
                    release_key=rkey,
                    reason="done_signal_without_library_placement",
                    payload=payload,
                    issue_id=row.get("issueid"),
                    provider=row.get("provider"),
                    downloader_type=row.get("downloader_type"),
                    nzb_name=row.get("nzbname") or (payload or {}).get("nzbname") or (payload or {}).get("nzb_name"),
                )
            )
            logger.warn(
                "[RECOVERY] %s -> MANUAL REVIEW (download reported done but "
                "never imported and the completed folder is unresolvable); "
                "files remain in the download directory (#734)." % rkey
            )
            return "done-unplaced-manual-review"
        logger.warn(
            "[RECOVERY] %s -> UNKNOWN (transient downloader outage) — stage "
            "left UNCHANGED, reclassified next start." % rkey
        )
        return "unknown-unchanged"

    if verdict == recovery_classify.COMPLETE:
        payload = _merge_completion_evidence(payload, details)
        journal.record_transition(
            rkey,
            journal.DOWNLOADED,
            payload=payload,
            issueid=row.get("issueid"),
            provider=row.get("provider"),
            downloader_type=row.get("downloader_type"),
        )
        item = _pp_item_from_row(row, payload)
        comicarr.PP_QUEUE.put(item)
        logger.info(
            "[RECOVERY] %s -> COMPLETE (done at downloader) — recorded "
            "`downloaded` then re-enqueued for PP (journal_release_key stamped "
            "for the U4 atomic claim)." % rkey
        )
        return "complete-pp-enqueued"

    if verdict == recovery_classify.STILL:
        kind, item = _resume_item_from_row(row, payload)
        if kind == "torrent":
            comicarr.SNATCHED_QUEUE.put(item)
            logger.info(
                "[RECOVERY] %s -> STILL (downloading) — re-enqueued onto "
                "SNATCHED_QUEUE so the live torrent monitor resumes." % rkey
            )
        elif kind == "ddl":
            ddl_id = item.get("id")
            record(
                ManualReview(
                    release_key=rkey,
                    reason="ambiguous_ddl_acceptance_after_restart",
                    payload=payload,
                    issue_id=row.get("issueid"),
                    provider=row.get("provider"),
                    downloader_type="ddl",
                    nzb_name=row.get("nzbname") or (payload or {}).get("filename") or (payload or {}).get("nzbname"),
                    release_id=ddl_id,
                )
            )
            if ddl_id:
                from comicarr.app.downloads import queries as dl_queries

                dl_queries.update_ddl_status(ddl_id, "Manual Review")
            logger.warn(
                "[RECOVERY] %s -> MANUAL REVIEW (ambiguous DDL acceptance after restart); "
                "no duplicate sender call; issue re-wanted when resolvable (#541)." % rkey
            )
        else:
            comicarr.NZB_QUEUE.put(item)
            logger.info(
                "[RECOVERY] %s -> STILL (downloading) — re-enqueued onto "
                "NZB_QUEUE so the live NZB monitor resumes." % rkey
            )
        return "still-reenqueued"

    logger.warn("[RECOVERY] %s -> unrecognized verdict %r — left unchanged." % (rkey, verdict))
    return "unknown-unchanged"


def replay_pipeline(probes=None):
    """Idempotent, re-runnable startup recovery replay. Invoked from
    Comicarr.py AFTER comicarr.start() returns (INIT_LOCK released) and AFTER
    credential decryption, BEFORE uvicorn.run(). Does NOT acquire INIT_LOCK
    (so it can never deadlock/starve a concurrent SIGTERM halt()).

    `probes` (test seam): forwarded verbatim to recovery_classify.classify so
    integration tests can inject fake downloader clients without network.

    Returns a small summary dict (counts) for logging/tests.
    """
    summary = {
        "key_migration": 0,
        "reconstructed": 0,
        "legacy_ddl_review": 0,
        "reopened_false_terminal": 0,
        "band_reconcile": None,
        "open": 0,
        "actions": {},
    }

    if getattr(comicarr, "ACQUISITION_WORKERS_BLOCKED", False):
        summary["actions"]["blocked"] = 1
        logger.warn("[RECOVERY] Startup recovery replay skipped because acquisition workers are fenced.")
        return summary

    logger.info("[RECOVERY] Startup recovery replay starting (post-start, lock-free).")

    try:
        summary["key_migration"] = journal.migrate_release_key_provider_format()
    except Exception as e:
        logger.error("[RECOVERY] #745 key-format migration failed; continuing: %s" % type(e).__name__)

    try:
        summary["legacy_ddl_review"] = _reconcile_legacy_ddl_downloading()
    except Exception as e:
        logger.error("[RECOVERY] legacy DDL reconciliation failed; continuing: %s" % type(e).__name__)

    try:
        from comicarr.app.attention._reconciliation import reconcile_existing_excluded_rows

        summary["band_reconcile"] = reconcile_existing_excluded_rows()
    except Exception as e:
        logger.error("[RECOVERY] band actionability one-shot failed; continuing: %s" % type(e).__name__)

    try:
        summary["reopened_false_terminal"] = _reclassify_false_terminal_imports()
    except Exception as e:
        logger.error("[RECOVERY] #742 false-terminal backfill failed; continuing: %s" % type(e).__name__)

    try:
        summary["reconstructed"] = _reconstruct_anchors()
    except Exception as e:
        logger.error("[RECOVERY] anchor reconstruction phase failed: %s — continuing with open rows." % e)

    try:
        snapshot = journal.read_open()
    except Exception as e:
        logger.error("[RECOVERY] could not read open journal rows: %s — replay aborted (resumable next start)." % e)
        return summary

    if not snapshot:
        logger.info("[RECOVERY] No open journal obligations — replay is a fast no-op.")
        return summary

    summary["open"] = len(snapshot)
    logger.info("[RECOVERY] %d open obligation(s) to resolve." % len(snapshot))

    pp_cap = {"count": 0}

    for snapshot_row in snapshot:
        rkey = snapshot_row.get("release_key")
        try:
            action = _resolve_row(snapshot_row, probes=probes, pp_cap=pp_cap)
        except Exception as e:
            logger.error(
                "[RECOVERY] row %s raised during replay — SKIPPED (resumable "
                "next start), loop continues: %s" % (rkey, e)
            )
            summary["actions"]["error"] = summary["actions"].get("error", 0) + 1
            continue
        summary["actions"][action] = summary["actions"].get(action, 0) + 1
        if action in (
            "complete-pp-enqueued",
            "downloaded-pp-enqueued",
            "still-reenqueued",
            "post_processing-redrive",
        ):
            time.sleep(_ENQUEUE_THROTTLE_SECONDS)

    logger.info("[RECOVERY] Startup recovery replay complete: %s" % summary)
    return summary
