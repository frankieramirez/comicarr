#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""
Startup recovery replay orchestrator (U6).

Runs ONCE at startup, AFTER ``comicarr.start()`` returns (so ``INIT_LOCK``
is released — ``start()`` is one unbroken ``with INIT_LOCK:`` block) and
AFTER credential decryption (downloader-client creds are ciphertext until
``encrypt_items`` runs during ``comicarr.initialize()``), and BEFORE
``uvicorn.run()``. It re-drives every open pipeline_journal obligation
through its remaining stages, exactly once, with no operator action.

Orchestration ONLY. This module owns NO transition logic and NO
classification logic:

  * journal.py owns the monotonic stage lattice / release_key derivation /
    terminal predicate. Every journal write here goes through that
    forward-only facade, so a row a live worker concurrently advanced is
    never regressed.
  * recovery_classify.py (U5) owns the per-downloader verdict
    (still/complete/gone/unknown) and the GONE -> mark_failed mutation.

Snapshot-then-RECHECK-then-act:

  1. Anchor reconstruction first — rebuild a `snatched` journal row for the
     U2 residual window (snatch committed durably, journal write lost),
     but ONLY when the release has not already advanced (see the predicate
     in _reconstruct_anchors). This must NOT mass-re-drive every
     historically-snatched issue.
  2. journal.read_open() snapshot. For EACH row, RE-READ its current stage
     with a cheap point lookup immediately before acting (workers are live
     during replay — if it advanced past the snapshot stage, SKIP; this
     avoids creating a duplicate the U4 claim would then have to dedupe).
  3. Act on the (rechecked) stage:
       moved            -> finalize_post_processing: finish DB facts ONLY
                           (move physically committed, source maybe gone —
                           NEVER re-import). The `moved` marker is the SOLE
                           discriminator; no file probe anywhere.
       post_processing  -> finalize_post_processing: re-drive PP in FULL
                           (move not committed, source intact).
       else done-check  -> Status==Post-Processed / nzblog absent (one-off:
                           journal-authoritative, nzblog advisory) =>
                           journal.mark_done, skip.
       else classify    -> complete -> reconstruct payload + PP_QUEUE.put
                                       (stamp journal_release_key for U4).
                           still    -> reconstruct payload + re-enqueue onto
                                       SNATCHED_QUEUE (torrent) / NZB_QUEUE
                                       (SAB/NZBGet) so the live monitor
                                       (in-memory tracking did NOT survive
                                       restart) resumes.
                           gone     -> recovery_classify.apply_verdict
                                       (mark_failed, payload retained).
                           unknown  -> leave stage unchanged.

Per-row try/except: a failing row logs ``[RECOVERY]`` LOUDLY and is SKIPPED
(resumable next start), NEVER aborts the loop. The enqueue burst is
throttled (a small sleep between enqueues, modelled on
``helpers.job_management(startup=True)`` / ``ddl_health_check``) so replay
does not exhaust the SQLite 5-retry write cap against concurrent PP workers.
Idempotent and re-runnable.
"""

import time

from sqlalchemy import and_, delete, select

import comicarr
from comicarr import db, logger
from comicarr.app.downloads import journal, recovery_classify
from comicarr.tables import nzblog, snatched

# Small inter-enqueue pause so the replay burst does not contend the SQLite
# single-writer against the concurrent PP workers and exhaust the journal's
# 5-retry cap (modelled on the throttling in job_management/ddl_health_check).
_ENQUEUE_THROTTLE_SECONDS = 0.05


# ---------------------------------------------------------------------------
# Anchor reconstruction (corrected — see Key Technical Decisions)
# ---------------------------------------------------------------------------


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
        # On a lookup failure, be conservative: assume advanced so we do NOT
        # mass-re-drive (a missed reconstruction is recoverable next start; a
        # spurious re-drive of a completed item is not).
        return True
    return rec is not None


def _nzblog_present(issueid, provider):
    """True iff an nzblog row still exists for (IssueID, PROVIDER). nzblog is
    deleted on PP success, so its presence means PP did not complete."""
    try:
        rec = db.select_one(
            select(nzblog.c.IssueID).where(and_(nzblog.c.IssueID == str(issueid), nzblog.c.PROVIDER == provider))
        )
    except Exception as e:
        logger.warn("[RECOVERY] nzblog lookup failed for %s/%s: %s" % (issueid, provider, e))
        return False
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

            rkey = journal.release_key(
                issueid,
                provider,
                nzbname=srow.get("FolderName"),
                hash=srow.get("Hash"),
                discriminant=srow.get("Hash") or srow.get("FolderName") or dict(srow),
            )

            # Already journaled? Then there is no residual window for it.
            if journal.read_one(rkey) is not None:
                continue

            if _has_advanced_sibling(issueid, provider):
                logger.fdebug(
                    "[RECOVERY] anchor skip %s/%s — Downloaded/Post-Processed "
                    "sibling present (release already advanced)." % (issueid, provider)
                )
                continue

            oneoff = journal._is_synthetic_oneoff(issueid)
            if not oneoff and not _nzblog_present(issueid, provider):
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

            payload = {
                "issueid": issueid,
                "comicid": srow.get("ComicID"),
                "provider": provider,
                "hash": srow.get("Hash"),
                "nzbname": srow.get("FolderName"),
                "comicname": srow.get("ComicName"),
                "issuenumber": srow.get("Issue_Number"),
            }
            journal.record_transition(
                rkey,
                journal.SNATCHED,
                payload=payload,
                issueid=issueid,
                provider=provider,
                downloader_type="torrent" if srow.get("Hash") else "nzb",
                nzbname=srow.get("FolderName"),
                hash=srow.get("Hash"),
            )
            reconstructed += 1
            logger.info(
                "[RECOVERY] reconstructed missing snatched journal row %s "
                "(IssueID=%s provider=%s) from durable snatched/nzblog." % (rkey, issueid, provider)
            )
        except Exception as e:
            # A single bad anchor must never abort reconstruction.
            logger.error("[RECOVERY] anchor reconstruction error for %s: %s" % (srow, e))
            continue

    if reconstructed:
        logger.info("[RECOVERY] anchor reconstruction rebuilt %d row(s)." % reconstructed)
    return reconstructed


# ---------------------------------------------------------------------------
# Authoritative done-check (before classification)
# ---------------------------------------------------------------------------


def _authoritatively_done(row):
    """Authoritative "already complete" check that survives downloader-history
    eviction: reuse U5's cross-check (issues.Status==Post-Processed / nzblog
    absent — but for synthetic-HIGHCOUNT one-offs nzblog-presence is advisory
    only and the journal stage is authoritative)."""
    return recovery_classify._has_done_signal(row)


# ---------------------------------------------------------------------------
# Payload reconstruction for re-enqueue
# ---------------------------------------------------------------------------


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
    if downloader == "torrent" or row.get("hash"):
        return "torrent", {
            "issueid": payload.get("issueid") or row.get("issueid"),
            "comicid": payload.get("comicid"),
            "hash": payload.get("hash") or row.get("hash"),
            "provider": payload.get("provider") or row.get("provider"),
            "nzbname": payload.get("nzbname") or row.get("nzbname"),
        }
    # SAB / NZBGet: re-feed the identity so cdh/nzb_monitor can historycheck.
    item = dict(payload)
    item.setdefault("issueid", row.get("issueid"))
    item.setdefault("comicid", payload.get("comicid"))
    item.setdefault("apicall", True)
    item.setdefault("download_info", payload.get("download_info") or {"provider": row.get("provider")})
    return "nzb", item


# ---------------------------------------------------------------------------
# Finalizer — the two-marker decision (moved vs post_processing) ONLY
# ---------------------------------------------------------------------------


def finalize_post_processing(row):
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

    if stage == journal.MOVED:
        issueid = row.get("issueid")
        provider = row.get("provider")
        payload = journal.load_payload(row.get("payload_json"))
        # One begin() block: nzblog-delete co-commits with journal
        # post_processed (mirrors U9's c255b716 atomic DB-fact path). conn-mode
        # record_transition participates in this transaction and rolls back
        # with it, so nzblog is never deleted while the journal still says
        # `moved`. The Status=Post-Processed write stays in its existing
        # foundsearch(down=…) separate-transaction path (out of scope to fold
        # here per the plan); the journal post_processed marker is the durable
        # completion fact replay guarantees, and the residual Status window is
        # explicitly covered by the moved marker + this finalizer (C3).
        with db.get_engine().begin() as conn:
            stmt = delete(nzblog).where(nzblog.c.IssueID == str(issueid))
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
        payload = journal.load_payload(row.get("payload_json")) or {}
        item = _pp_item_from_row(row, payload)
        logger.info(
            "[RECOVERY] %s was `post_processing` (no `moved` — move did NOT "
            "commit, source intact) — re-driving PP in full." % rkey
        )
        from comicarr import process

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
        except Exception:
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
        return "post_processing-redrive"

    # Caller only routes `moved`/`post_processing` here; anything else is a
    # programming error in the caller — log and no-op (never raise into the
    # per-row loop's flow on a misroute).
    logger.warn("[RECOVERY] finalize_post_processing called for %s with non-PP stage=%s — ignored." % (rkey, stage))
    return "ignored"


# ---------------------------------------------------------------------------
# Per-row resolution
# ---------------------------------------------------------------------------


def _resolve_row(snapshot_row, probes=None):
    """Resolve ONE open obligation. RECHECKS the row's current stage with a
    cheap point lookup before acting (workers are live; skip if it advanced
    past the snapshot). Returns a short action string for logging/tests."""
    rkey = snapshot_row.get("release_key")

    # --- snapshot-then-RECHECK: re-read current stage before acting --------
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

    # --- two-marker finalizer (moved / post_processing) -------------------
    if cur_stage == journal.MOVED:
        return finalize_post_processing(row)
    if cur_stage == journal.POST_PROCESSING:
        return finalize_post_processing(row)

    # --- authoritative done-check (history-eviction safe) -----------------
    if _authoritatively_done(row):
        logger.info("[RECOVERY] %s authoritatively done (Status/nzblog) — mark_done, skip." % rkey)
        journal.mark_done(
            rkey,
            issueid=row.get("issueid"),
            provider=row.get("provider"),
        )
        return "done-check"

    # --- per-downloader classification (U5) -------------------------------
    verdict = recovery_classify.classify(row, probes=probes)

    if verdict == recovery_classify.GONE:
        recovery_classify.apply_verdict(row, verdict)
        return "gone-failed"

    if verdict == recovery_classify.UNKNOWN:
        logger.warn(
            "[RECOVERY] %s -> UNKNOWN (transient downloader outage) — stage "
            "left UNCHANGED, reclassified next start." % rkey
        )
        return "unknown-unchanged"

    payload = journal.load_payload(row.get("payload_json"))

    if verdict == recovery_classify.COMPLETE:
        item = _pp_item_from_row(row, payload)
        comicarr.PP_QUEUE.put(item)
        logger.info(
            "[RECOVERY] %s -> COMPLETE (done at downloader) — re-enqueued for "
            "PP (journal_release_key stamped for the U4 atomic claim)." % rkey
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
        else:
            comicarr.NZB_QUEUE.put(item)
            logger.info(
                "[RECOVERY] %s -> STILL (downloading) — re-enqueued onto "
                "NZB_QUEUE so the live NZB monitor resumes." % rkey
            )
        return "still-reenqueued"

    logger.warn("[RECOVERY] %s -> unrecognized verdict %r — left unchanged." % (rkey, verdict))
    return "unknown-unchanged"


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def replay_pipeline(probes=None):
    """Idempotent, re-runnable startup recovery replay. Invoked from
    Comicarr.py AFTER comicarr.start() returns (INIT_LOCK released) and AFTER
    credential decryption, BEFORE uvicorn.run(). Does NOT acquire INIT_LOCK
    (so it can never deadlock/starve a concurrent SIGTERM halt()).

    `probes` (test seam): forwarded verbatim to recovery_classify.classify so
    integration tests can inject fake downloader clients without network.

    Returns a small summary dict (counts) for logging/tests.
    """
    logger.info("[RECOVERY] Startup recovery replay starting (post-start, lock-free).")

    summary = {"reconstructed": 0, "open": 0, "actions": {}}

    # 1. Anchor reconstruction FIRST (U2 residual window).
    try:
        summary["reconstructed"] = _reconstruct_anchors()
    except Exception as e:
        logger.error("[RECOVERY] anchor reconstruction phase failed: %s — continuing with open rows." % e)

    # 2. Snapshot the open obligations.
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

    # 3. Per-row recheck-then-act. A failing row is logged LOUDLY and SKIPPED
    #    (resumable next start) — NEVER aborts the loop.
    for snapshot_row in snapshot:
        rkey = snapshot_row.get("release_key")
        try:
            action = _resolve_row(snapshot_row, probes=probes)
        except Exception as e:
            logger.error(
                "[RECOVERY] row %s raised during replay — SKIPPED (resumable "
                "next start), loop continues: %s" % (rkey, e)
            )
            summary["actions"]["error"] = summary["actions"].get("error", 0) + 1
            continue
        summary["actions"][action] = summary["actions"].get(action, 0) + 1
        # Throttle the enqueue burst so replay does not contend the SQLite
        # single-writer against concurrent PP workers and exhaust the
        # journal's 5-retry cap (modelled on job_management/ddl_health_check).
        if action in ("complete-pp-enqueued", "still-reenqueued", "post_processing-redrive"):
            time.sleep(_ENQUEUE_THROTTLE_SECONDS)

    logger.info("[RECOVERY] Startup recovery replay complete: %s" % summary)
    return summary
