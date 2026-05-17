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
owns the per-downloader verdict and the GONE -> mark_failed mutation.

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
from comicarr.app.downloads import journal, recovery_classify
from comicarr.tables import nzblog, snatched, storyarcs

# Small inter-enqueue pause so the replay burst does not contend the SQLite
# single-writer against the concurrent PP workers and exhaust the journal's
# 5-retry cap (modelled on the throttling in job_management/ddl_health_check).
_ENQUEUE_THROTTLE_SECONDS = 0.05

# Startup availability cap: finalize_post_processing re-drives a
# `post_processing`-stage row by running a FULL process.Process INLINE and
# synchronously, inside replay_pipeline() which runs BEFORE uvicorn binds. A
# large backlog of post_processing rows would each run a full PP serially
# before the web server is reachable (unbounded by count). Cap the number of
# inline post_processing re-drives per replay pass; the remainder are SKIPPED
# this pass and resume next startup (the design is idempotent/re-runnable, so
# this is safe and only defers, never drops). `moved`/done/still/gone paths
# are cheap and NOT capped.
_MAX_INLINE_PP_REDRIVE_PER_PASS = 5


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

            # The durable name lives in nzblog.NZBName keyed by
            # (IssueID, PROVIDER) — NOT snatched.FolderName (a column that is
            # never written, so the prior derivation here always passed None
            # and produced a phantom key). Read the real name from nzblog so a
            # reconstructed STILL item can be re-driven with a usable nzbname,
            # and so a one-off discriminant has something durable to anchor on.
            # Story-arc scoping (fix #2 completion): the reference
            # postprocessor.py ~3201-3213 only matches the
            # IssueID == "S"+IssueArcID nzblog row inside the story-arc
            # branch (paired with a SARC constraint), NEVER for a plain
            # issue. Determine arc-ness from the durable `storyarcs` table
            # (the snatched row has no mode/SARC column) and only widen to
            # the "S"+id form for a real story-arc obligation. For a plain
            # issue, match the plain id ONLY — so a plain issue whose id
            # numerically equals an unrelated arc's IssueArcID under the
            # SAME PROVIDER cannot pick the arc's "S"+id NZBName. When
            # arc-ness is unanswerable, fall back minimally-safely: prefer
            # the exact plain row and only consult "S"+id if no plain row
            # exists.
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
                    # Unknown: prefer the exact plain row; only fall back to
                    # the "S"+id form when no plain row exists.
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

            # release_key is byte-identical with the snatch/downloaded seams:
            # for non-one-offs it is issueid|normalize(provider) (the name is
            # NOT part of the key — see journal.release_key's single-derivation
            # docstring), so it reproduces exactly from the durable
            # snatched.IssueID/Provider here. For synthetic-HIGHCOUNT one-offs
            # the journal row is authoritative (plan); the discriminant is
            # best-effort from durable nzblog/snatched data.
            rkey = journal.release_key(
                issueid,
                provider,
                nzbname=durable_nzbname,
                hash=srow.get("Hash"),
                discriminant=srow.get("Hash") or durable_nzbname or dict(srow),
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

            oneoff = journal.is_synthetic_oneoff(issueid)
            # ANCHOR-RECONSTRUCTION (conservative): a lookup error from
            # recovery_classify._nzblog_present returns None, and `not None` is
            # True — identical to this site's prior `return False` semantics:
            # on an unanswerable nzblog test for a non-one-off we do NOT
            # reconstruct (a missed reconstruction is recoverable next start;
            # a spurious re-drive of a completed item is not).
            # Thread the same story-arc signal so the presence gate scopes
            # the "S"+id arm exactly as the NZBName lookup above (fix #2
            # completion): a plain issue's gate never reads an unrelated
            # arc's "S"+id row as present.
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

            # Preserve the downloader IDENTITY when synthesizing the anchor.
            # updater.foundsearch writes a `snatched` row for a DDL snatch too
            # (search.py ~1712, provider="DDL(GetComics)"/"DDL(External)",
            # Hash=None), so a lost-journal DDL snatch surfaces here. The prior
            # unconditional `nzb` hardcode + DDL-marker-less payload routed it
            # through the NZB probe / NZB_QUEUE instead of _probe_ddl /
            # DDL_QUEUE, breaking DDL restart recovery. Derive: torrent if a
            # Hash is present, else ddl if the durable provider is a DDL
            # provider (substring — the snatched.Provider column carries the
            # raw "DDL(GetComics)"/"DDL(External)" name, not the normalized
            # "DDL"), else nzb. For DDL, also stamp the markers
            # _resolve_downloader / _resume_item_from_row key off so the
            # reconstructed row classifies and resumes onto DDL_QUEUE.
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
                # _resume_item_from_row keys off payload["ddl"] /
                # download_info.provider == "DDL"; _probe_ddl falls back to
                # ddl_info.issueid (durably upserted by getcomics.py before
                # DDL_QUEUE.put, so it survives the lost-journal window).
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
            # A single bad anchor must never abort reconstruction.
            logger.error("[RECOVERY] anchor reconstruction error for %s: %s" % (srow, e))
            continue

    if reconstructed:
        logger.info("[RECOVERY] anchor reconstruction rebuilt %d row(s)." % reconstructed)
    return reconstructed


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

    # P2-5(a): a `still` DDL row must re-enqueue onto DDL_QUEUE — NOT fall
    # through to the NZB_QUEUE branch (cdh/nzb_monitor cannot historycheck a
    # DDL item; it would strand with no owner). Detect DDL via the journal
    # downloader_type, the payload `ddl:true` flag, or a DDL provider.
    di = payload.get("download_info") or {}
    is_ddl = (
        downloader == "ddl"
        or payload.get("ddl") is True
        or str(payload.get("provider") or row.get("provider") or "").upper() == "DDL"
        or str(di.get("provider") or "").upper() == "DDL"
    )
    if is_ddl:
        ddl_id = payload.get("id") or di.get("id") or row.get("ddl_id")
        return "ddl", {
            "id": ddl_id,
            "issueid": payload.get("issueid") or row.get("issueid"),
            "comicid": payload.get("comicid"),
            "series": payload.get("series"),
            "filename": payload.get("filename") or payload.get("nzb_name"),
            "site": payload.get("site"),
            "link": payload.get("link"),
            "ddl": True,
        }

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
    # payload is parsed ONCE per replay row by the caller and threaded in;
    # default None ⇒ parse internally so existing direct callers/tests work.
    if payload is None:
        payload = journal.load_payload(row.get("payload_json"))

    if stage == journal.MOVED:
        issueid = row.get("issueid")
        provider = row.get("provider")
        # One begin() block: nzblog-delete co-commits with the journal
        # post_processed marker (conn-mode record_transition participates in
        # this txn and rolls back with it), so nzblog is never deleted while
        # the journal still says `moved`. Status=Post-Processed stays on its
        # existing separate-transaction foundsearch path; the journal marker
        # is the durable completion fact replay guarantees.
        # Story-arc scoping (fix #2 completion). The reference
        # postprocessor.py ~3201-3213 only deletes the IssueID=="S"+IssueArcID
        # nzblog row inside the story-arc branch (and additionally constrains
        # it by SARC). Mirror that: only delete the "S"+id form for a real
        # story-arc obligation; a plain issue deletes the plain id ONLY, so a
        # plain finalize cannot over-delete an unrelated arc's "S"+id row
        # under the SAME PROVIDER. The arc signal is the durable
        # payload["mode"] updater.foundsearch stamps on the snatch journal
        # row. When mode is absent/unparseable (unknown), the minimally-safe
        # fallback applies: still allow the "S"+id form BUT additionally
        # constrain the delete by the matched NZBName (the SARC analogue
        # available here) so a cross-obligation over-delete is impossible.
        story_arc = None
        if isinstance(payload, dict) and "mode" in payload:
            story_arc = payload.get("mode") == "story_arc"
        if story_arc is None:
            # Payload carried no `mode` — fall back to the durable
            # `storyarcs` discriminator (same signal _reconstruct_anchors
            # uses): for a story-arc obligation row.issueid IS the
            # IssueArcID, so a matching storyarcs row proves arc-ness; a
            # plain issue has no such row.
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
                # Unknown arc-ness: keep the "S"+id form reachable (so a real
                # story-arc row is not orphaned) but pin the delete to the
                # matched NZBName so it can never consume an unrelated
                # obligation's row. If no durable NZBName is available, fall
                # back to the plain id ONLY (conservative — an orphaned arc
                # nzblog row is recoverable; an over-delete is not).
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
        except Exception as e:
            logger.fdebug("[RECOVERY] 8-arg process.Process construction failed, using fallback: %s" % e)
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
    # Parse payload_json ONCE per row, thread it everywhere below (classify,
    # the probes via classify, and the item-builders) instead of re-parsing
    # it 3-6x. None ⇒ no payload (callees treat as {}).
    payload = journal.load_payload(row.get("payload_json"))

    # --- two-marker finalizer (moved / post_processing) -------------------
    # moved -> cheap DB-facts only (NOT capped). post_processing -> a FULL
    # inline process.Process; capped per pass so a large backlog cannot delay
    # the web server bind unboundedly (idempotent ⇒ deferral is safe).
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

    # --- authoritative done-check (history-eviction safe) -----------------
    if recovery_classify.has_done_signal(row):
        logger.info("[RECOVERY] %s authoritatively done (Status/nzblog) — mark_done, skip." % rkey)
        journal.mark_done(
            rkey,
            issueid=row.get("issueid"),
            provider=row.get("provider"),
        )
        return "done-check"

    # --- per-downloader classification (U5) -------------------------------
    # classify() accepts an optional payload= for direct callers, but we do
    # NOT pass it here: the recovery_classify.classify symbol is a test
    # monkeypatch seam whose stubs take (row, probes=) only. classify's own
    # single internal parse covers _resolve_downloader/has_done_signal; the
    # bigger re-parse wins (item-builders, finalizer) are already threaded.
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

    if verdict == recovery_classify.COMPLETE:
        # Advance to `downloaded` BEFORE the PP enqueue. classify() can return
        # COMPLETE while this journal row is still `snatched` (the row was
        # rebuilt by anchor reconstruction, or the original downloaded-stage
        # write was the one lost). The U4 PP consumer only claims a
        # `downloaded -> post_processing` row, so enqueuing a still-`snatched`
        # row would make it lose the claim and silently drop. The monotonic
        # guard makes this a safe no-op when the row is already >= downloaded;
        # it only advances a still-`snatched` recovered row so the U4 claim
        # works. release_key (rkey) is authoritative and is what the PP item
        # carries as journal_release_key (the U3/U4/U6 propagated-key
        # contract — never re-derived).
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
            # P2-5(a): DDL `still` resumes on DDL_QUEUE (the ddl_downloader
            # worker), NOT NZB_QUEUE — cdh/nzb_monitor cannot historycheck a
            # DDL item and the item would otherwise strand with no owner.
            comicarr.DDL_QUEUE.put(item)
            logger.info(
                "[RECOVERY] %s -> STILL (downloading) — re-enqueued onto "
                "DDL_QUEUE so the ddl_downloader worker resumes." % rkey
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

    # Per-pass cap on INLINE post_processing re-drives (each is a full
    # synchronous process.Process before the web server binds). Mutable so
    # _resolve_row can increment it across rows.
    pp_cap = {"count": 0}

    # 3. Per-row recheck-then-act. A failing row is logged LOUDLY and SKIPPED
    #    (resumable next start) — NEVER aborts the loop.
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
        # Throttle the enqueue burst so replay does not contend the SQLite
        # single-writer against concurrent PP workers and exhaust the
        # journal's 5-retry cap (modelled on job_management/ddl_health_check).
        if action in ("complete-pp-enqueued", "still-reenqueued", "post_processing-redrive"):
            time.sleep(_ENQUEUE_THROTTLE_SECONDS)

    logger.info("[RECOVERY] Startup recovery replay complete: %s" % summary)
    return summary
