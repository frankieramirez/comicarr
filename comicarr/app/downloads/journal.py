#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""
Forward-only durable pipeline journal facade.

This module is the single owner of:

  1. The legal stage lattice + the terminal predicate (is_terminal/mark_done),
     consumed by U4 (PP-consumer atomic claim) and U6 (startup replay).
  2. record_transition() — a monotonic, conditional advance-only write:
     UPDATE ... WHERE release_key=? AND stage_rank < :new_rank, plus an
     insert-if-absent, the pair run inside ONE begin() block so it is atomic
     against concurrent writers. A regressing or post-terminal write is a
     logged no-op (NOT db.upsert's blind ON CONFLICT DO UPDATE, which is
     last-writer-wins). The return value tells the caller whether it "won"
     the advance — the U4 atomic claim depends on this signal.
  3. The sole release_key derivation used by U2/U4/U6. Divergent derivation
     between the snatch seam and the PP-consumer guard silently voids
     exactly-once, so this is a hard cross-unit contract.
  4. read_open() / mark_failed() / mark_done() helpers.

Module boundary: this facade owns ONLY transitions, the monotonic guard,
release_key derivation, and the terminal predicate. Per-downloader
classification lives in U5's recovery_classify.py — it does NOT belong here.
"""

import hashlib
import json
import re
import time

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError, OperationalError

from comicarr import db, logger
from comicarr.tables import pipeline_journal

# ---------------------------------------------------------------------------
# Legal stage lattice
# ---------------------------------------------------------------------------
# stage is totally ordered. `failed` is terminal but ordered AFTER
# post_processed so that a post-terminal write (failed -> anything, or
# anything -> a regressing stage) is rejected by the monotonic guard.

SNATCHED = "snatched"
DOWNLOADED = "downloaded"
POST_PROCESSING = "post_processing"
MOVED = "moved"
POST_PROCESSED = "post_processed"
FAILED = "failed"

STAGE_RANK = {
    SNATCHED: 10,
    DOWNLOADED: 20,
    POST_PROCESSING: 30,
    MOVED: 40,
    POST_PROCESSED: 50,
    FAILED: 60,
}

# Stages considered terminal: no further forward transition is legal.
TERMINAL_STAGES = (POST_PROCESSED, FAILED)

# Open stages: rows replay must consider as still-in-flight obligations.
OPEN_STAGES = (SNATCHED, DOWNLOADED, POST_PROCESSING, MOVED)

# Synthetic one-off IssueIDs are an unpersisted CONFIG.HIGHCOUNT counter that
# starts at 900000 (see comicarr/updater.py:1214-1220). Such an IssueID is not
# reproducible across a restart, so it must NOT be part of the release_key.
HIGHCOUNT_FLOOR = 900000


# ---------------------------------------------------------------------------
# Terminal predicate
# ---------------------------------------------------------------------------


def is_terminal(stage):
    """Return True if the given stage is terminal (no legal forward move)."""
    return stage in TERMINAL_STAGES


def stage_rank(stage):
    """Return the integer rank for a stage, or None if the stage is unknown."""
    return STAGE_RANK.get(stage)


# ---------------------------------------------------------------------------
# release_key — the SOLE derivation. Consumed by U2/U4/U6.
# ---------------------------------------------------------------------------


def is_synthetic_oneoff(issueid):
    """A one-off carries a synthetic CONFIG.HIGHCOUNT IssueID (>= 900000)
    that is not persisted and diverges across restart."""
    if issueid is None:
        return True
    try:
        return int(str(issueid).strip()) >= HIGHCOUNT_FLOOR
    except (TypeError, ValueError):
        return False


def normalize_provider(provider):
    """Canonicalize a provider label so the SAME logical provider produces a
    byte-identical token at every seam.

    The snatch seam passes an RSS-stripped `tmpprov` (search.py:1678/1694) or a
    raw `nzbprov`; the downloaded seam reads `download_info['provider']` (the
    raw `nzbprov`); anchor reconstruction reads `snatched.Provider`. These can
    differ by an `[RSS]` suffix, surrounding whitespace, or case. Stripping the
    `[RSS]` marker, collapsing whitespace and lowercasing makes the four seams
    converge on one token. None/empty normalizes to "" (stable)."""
    if provider is None:
        return ""
    p = str(provider)
    p = re.sub(r"\[RSS\]", "", p, flags=re.IGNORECASE)
    p = re.sub(r"\s+", " ", p).strip()
    return p.lower()


def release_key(issueid, provider, nzbname=None, hash=None, discriminant=None):
    """Derive the stable release identity for a pipeline item.

    SINGLE-DERIVATION INVARIANT (P0-1): the key MUST be byte-identical at all
    four seams — the snatch seam (updater.foundsearch), the downloaded seam
    (cdh_monitor / worker_main / ddl_downloader), the PP-consumer atomic claim,
    and U6 anchor reconstruction. A divergence orphans the snatched row and
    voids exactly-once in the mid-pipeline crash window.

    The release NAME is NOT reproducible across those seams: the snatch seam
    has the search-time `nzbname`, while the NZB downloaded seam only has the
    SAB-reported `nzstat['name']` (a different string), the torrent
    SNATCHED_QUEUE item carries no name at all, and `snatched.FolderName` is
    never written. A perfectly byte-identical name is therefore genuinely
    unavailable at one seam, so per the plan's documented robust fallback the
    NON-one-off key drops the name component entirely and keys on
    f"{issueid}|{normalize_provider(provider)}" only — reproducible from
    durable storage (snatched.IssueID/Provider, nzblog (IssueID, PROVIDER)) at
    every seam.

    One-off fallback (synthetic-HIGHCOUNT / missing issueid — not reproducible
    across restart, see comicarr/updater.py:1214-1220): key on
    f"oneoff|{normalize_provider(provider)}|{nzbname-or-hash}|{discriminant}"
    where `discriminant` is a collision-resistant value (downloader id or a
    hash of the payload) supplied by the caller. This guarantees two distinct
    one-offs from the same provider with empty/equal nzbname produce DIFFERENT
    keys. An unavoidable collision (no discriminant available) is logged
    loudly — never silently coalesced.
    """
    prov = normalize_provider(provider)

    if is_synthetic_oneoff(issueid):
        rel = (nzbname or hash or "").strip()
        disc = _coerce_discriminant(discriminant)
        if not disc:
            logger.warn(
                "[JOURNAL] One-off release_key built with NO collision-resistant "
                "discriminant (provider=%s nzbname/hash=%r) — distinct one-offs "
                "from this provider with equal nzbname may collide onto one row." % (prov, rel)
            )
        return "oneoff|%s|%s|%s" % (prov, rel, disc)

    return "%s|%s" % (issueid, prov)


def _coerce_discriminant(discriminant):
    """Normalize a caller-supplied discriminant to a short stable token.

    Accepts a plain scalar (downloader id / hash string) or a dict (a queue
    payload) — for a dict we hash a stable JSON projection so two distinct
    payloads yield different tokens.
    """
    if discriminant is None:
        return ""
    if isinstance(discriminant, dict):
        try:
            blob = json.dumps(discriminant, sort_keys=True, default=str)
        except (TypeError, ValueError):
            blob = repr(sorted(discriminant.items(), key=lambda kv: str(kv[0])))
        return hashlib.sha1(blob.encode("utf-8", "replace")).hexdigest()[:16]
    return str(discriminant).strip()


def derive_release_key(item):
    """Convenience: derive release_key from a queue-item dict.

    Recognizes the common identity fields across SNATCHED_QUEUE / PP_QUEUE /
    torrent items. The discriminant for one-offs falls back to a hash of the
    whole item so two distinct one-off payloads cannot coalesce.
    """
    issueid = item.get("issueid") or item.get("IssueID") or item.get("ID")
    provider = item.get("provider") or item.get("Provider") or item.get("PROVIDER")
    nzbname = item.get("nzbname") or item.get("NZBName") or item.get("nzb_name")
    h = item.get("hash") or item.get("Hash")
    discriminant = h or item.get("downloader_id") or item
    return release_key(issueid, provider, nzbname=nzbname, hash=h, discriminant=discriminant)


# ---------------------------------------------------------------------------
# Internal: serialize payload
# ---------------------------------------------------------------------------


def _dump_payload(payload):
    if payload is None:
        return None
    if isinstance(payload, str):
        return payload
    try:
        return json.dumps(payload, default=str)
    except (TypeError, ValueError) as e:
        logger.warn("[JOURNAL] payload_json could not be serialized cleanly: %s" % e)
        return json.dumps({"_repr": repr(payload)})


def load_payload(payload_json):
    """Inverse of the internal payload serialization. Returns None on absence
    or any decode failure (a corrupt payload must not abort replay)."""
    if not payload_json:
        return None
    try:
        return json.loads(payload_json)
    except (TypeError, ValueError) as e:
        logger.warn("[JOURNAL] payload_json could not be decoded: %s" % e)
        return None


# ---------------------------------------------------------------------------
# record_transition — monotonic conditional advance-only write
# ---------------------------------------------------------------------------


def _now():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _try_reset_failed_to_snatched(conn, key, stage, new_rank, upd_values):
    """RE-SNATCH special case: a fresh `snatched` write observed against a
    terminal `failed` row is a NEW in-flight obligation that legitimately
    supersedes the closed failed attempt — reset the row to snatched.

    WHY this does NOT weaken the monotonic stale-replay guard: replay never
    issues a fresh `snatched` transition (the snatch seam updater.foundsearch
    does, only from a real new grab; replay re-enqueues `still` non-terminal
    items, never a `snatched` write). So a `snatched` write seen against a
    `failed` row is always a genuine new snatch obligation, never a stale
    replay — resetting is correct here and the monotonic guard is left fully
    intact for every other stage (only `failed`->`snatched` is special-cased).

    Returns True iff THIS call won the reset. The UPDATE is gated with
    `WHERE stage = FAILED` (the current terminal) so two concurrent snatched
    writers racing one failed row yield exactly one True — the loser's gated
    UPDATE matches 0 rows and it falls back to the monotonic no-op.
    """
    if stage != SNATCHED:
        return False

    reset = conn.execute(
        update(pipeline_journal)
        .where(pipeline_journal.c.release_key == key)
        .where(pipeline_journal.c.stage == FAILED)
        .values(fail_reason=None, **upd_values)
    )
    if reset.rowcount:
        logger.warn(
            "[JOURNAL] release_key=%s reset from terminal failed -> snatched "
            "(new snatch supersedes closed failed attempt)" % (key,)
        )
        return True
    return False


def _apply_transition(conn, key, stage, new_rank, fields, payload_json, when):
    """Run the UPDATE-then-conditional-INSERT pair on an open connection.

    Returns True iff this call advanced (won) the row. Atomicity vs concurrent
    writers comes from the caller running this inside a single transaction.
    """
    # 1. Conditional advance: only succeeds if the existing row is strictly
    #    behind the new rank. This is the monotonic guard AND (for the
    #    downloaded -> post_processing case) the U4 atomic claim.
    upd_values = {
        "stage": stage,
        "stage_rank": new_rank,
        "updated_date": when,
    }
    upd_values.update(fields)
    if payload_json is not None:
        upd_values["payload_json"] = payload_json

    result = conn.execute(
        update(pipeline_journal)
        .where(pipeline_journal.c.release_key == key)
        .where(pipeline_journal.c.stage_rank < new_rank)
        .values(**upd_values)
    )
    if result.rowcount:
        return True

    # 2. The UPDATE matched nothing: either the row is absent (first write) or
    #    it exists but is already at/ahead of new_rank (regression / terminal).
    existing = conn.execute(
        select(pipeline_journal.c.stage, pipeline_journal.c.stage_rank).where(pipeline_journal.c.release_key == key)
    ).fetchone()

    if existing is None:
        ins_values = {
            "release_key": key,
            "stage": stage,
            "stage_rank": new_rank,
            "updated_date": when,
            "payload_json": payload_json,
        }
        ins_values.update(fields)
        try:
            conn.execute(pipeline_journal.insert().values(**ins_values))
            return True
        except IntegrityError:
            # CONCURRENT FIRST-WRITER RACE (P1-2): SQLite begin() is DEFERRED,
            # so two threads for the same ABSENT release_key can both observe
            # UPDATE(0 rows) -> SELECT(None) and both attempt the INSERT; the
            # loser's INSERT violates uq_pipeline_journal_release_key. This is
            # NOT a fatal error — the row now exists (the other writer won the
            # insert). Re-run the conditional monotonic advance against the
            # now-present row and return rowcount>0: the loser correctly
            # returns False ("did not win" — the winner's stage equals ours so
            # stage_rank is NOT strictly less), or True if it legitimately
            # advances a row another writer already moved further behind. This
            # restores the CAS contract: exactly one of two concurrent
            # first-writers for the same absent key returns True.
            retry = conn.execute(
                update(pipeline_journal)
                .where(pipeline_journal.c.release_key == key)
                .where(pipeline_journal.c.stage_rank < new_rank)
                .values(**upd_values)
            )
            if retry.rowcount:
                return True
            # The now-present row may be a terminal `failed` row (a concurrent
            # writer inserted-then-failed it): the monotonic re-run matched 0,
            # so this is the absent-of-monotonic-match branch for the
            # failed-row case — apply the same gated re-snatch reset here so
            # the P1-2 race path composes with the failed->snatched rule.
            if _try_reset_failed_to_snatched(conn, key, stage, new_rank, upd_values):
                return True
            logger.fdebug(
                "[JOURNAL] first-writer race resolved: release_key=%s stage=%s "
                "(rank=%d) lost the INSERT to a concurrent writer; row already "
                "at/ahead — returning lost (CAS contract preserved)." % (key, stage, new_rank)
            )
            return False

    # Row exists and is at/ahead of new_rank. The ONE legal exception to the
    # monotonic no-op: a fresh `snatched` write against a terminal `failed`
    # row is a RE-SNATCH that supersedes the closed failed attempt.
    if existing[0] == FAILED and _try_reset_failed_to_snatched(conn, key, stage, new_rank, upd_values):
        return True

    # Row exists and is at/ahead of new_rank — a regressing or post-terminal
    # write. Logged no-op (NOT last-writer-wins).
    logger.fdebug(
        "[JOURNAL] no-op: release_key=%s requested stage=%s (rank=%d) but row "
        "is already at stage=%s (rank=%s) — monotonic guard rejected regression."
        % (key, stage, new_rank, existing[0], existing[1])
    )
    return False


def record_transition(release_key, stage, payload=None, conn=None, **fields):
    """Forward-only conditional advance for one release_key.

    Implemented as a monotonic conditional update plus insert-if-absent, the
    pair run atomically inside one transaction. A regressing or post-terminal
    write is a logged no-op.

    Return contract: returns True iff THIS call advanced the row (the caller
    "won"). False means the write was a no-op because the row was already at
    or beyond `stage` (a regression, a terminal row, or a concurrent winner).
    The U4 PP-consumer atomic claim relies on exactly one concurrent
    downloaded -> post_processing caller getting True.

    `conn`: optional caller-supplied Connection. When given, the write joins
    the caller's transaction (so it rolls back with it) — used by the DDL/PP
    sites that need the journal write inside their own explicit begin() block.
    When None, this opens its own transaction with the same 5-retry-on-locked
    -then-RAISES discipline as db.upsert (a write exhausting the retry cap
    surfaces; it is never silently swallowed).

    Optional `fields` (e.g. issueid, provider, downloader_type, nzbname, hash,
    fail_reason) are written alongside the stage so a row is reconstructable.
    """
    new_rank = STAGE_RANK.get(stage)
    if new_rank is None:
        raise ValueError("[JOURNAL] unknown stage %r — not in the legal lattice" % (stage,))

    payload_json = _dump_payload(payload)
    when = _now()

    # Caller-supplied connection: participate in the caller's transaction.
    if conn is not None:
        won = _apply_transition(conn, release_key, stage, new_rank, fields, payload_json, when)
        if won:
            logger.fdebug("[JOURNAL] advanced release_key=%s -> stage=%s (caller txn)" % (release_key, stage))
        return won

    # Own transaction with bounded retry-then-raise (mirrors db.upsert).
    attempt = 0
    while attempt < 5:
        try:
            with db.get_engine().begin() as own_conn:
                won = _apply_transition(own_conn, release_key, stage, new_rank, fields, payload_json, when)
            if won:
                logger.fdebug("[JOURNAL] advanced release_key=%s -> stage=%s" % (release_key, stage))
            return won
        except OperationalError as e:
            err_msg = str(e)
            if "locked" in err_msg or "unable to open" in err_msg:
                logger.warn(
                    "[JOURNAL] Database locked during transition (release_key=%s "
                    "stage=%s), retry %d: %s" % (release_key, stage, attempt + 1, e)
                )
                attempt += 1
                time.sleep(1)
            else:
                logger.error(
                    "[JOURNAL] Database error during transition (release_key=%s stage=%s): %s" % (release_key, stage, e)
                )
                raise
    # Retry cap exhausted — surface, never silently swallow (data-loss guard).
    logger.error(
        "[JOURNAL] transition write FAILED after 5 retries (release_key=%s "
        "stage=%s) — surfacing." % (release_key, stage)
    )
    raise OperationalError(
        "Journal transition on %s -> %s failed after 5 retries" % (release_key, stage),
        None,
        None,
    )


# ---------------------------------------------------------------------------
# Helpers built on the monotonic facade
# ---------------------------------------------------------------------------


def mark_failed(release_key, fail_reason, payload=None, conn=None, **fields):
    """Advance a row to the terminal `failed` stage, retaining payload/reason
    so a future manual-retry layer (R9) can act on it."""
    return record_transition(
        release_key,
        FAILED,
        payload=payload,
        conn=conn,
        fail_reason=fail_reason,
        **fields,
    )


def mark_done(release_key, payload=None, conn=None, **fields):
    """Advance a row to the terminal `post_processed` stage (idempotently —
    a row already terminal is a logged no-op)."""
    return record_transition(
        release_key,
        POST_PROCESSED,
        payload=payload,
        conn=conn,
        **fields,
    )


def read_open():
    """Return all journal rows still representing an in-flight obligation:
    stage in {snatched, downloaded, post_processing, moved}. Excludes
    post_processed and failed (terminal) rows.

    Ordered oldest-`updated_date`-first: the U6 inline-PP re-drive cap
    (_MAX_INLINE_PP_REDRIVE_PER_PASS) deterministically defers rows past the
    cap each pass; without a stable oldest-first order it would skip the SAME
    rows every restart (cap starvation). Oldest obligations drain first; the
    newest are deferred to the next pass."""
    rows = db.select_all(
        select(pipeline_journal)
        .where(pipeline_journal.c.stage.in_(OPEN_STAGES))
        .order_by(pipeline_journal.c.updated_date)
    )
    return rows


def read_one(release_key):
    """Cheap point lookup of a single journal row by release_key (used by the
    U6 replay snapshot-then-recheck), or None."""
    return db.select_one(select(pipeline_journal).where(pipeline_journal.c.release_key == release_key))
