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

from sqlalchemy import and_, or_, select, update
from sqlalchemy.exc import IntegrityError, OperationalError

from comicarr import db, logger
from comicarr.app.common.dates import now
from comicarr.tables import pipeline_journal

# ---------------------------------------------------------------------------
# Legal stage lattice
# ---------------------------------------------------------------------------
# stage is totally ordered. `failed` is terminal but ordered AFTER
# post_processed so that a post-terminal write (failed -> anything, or
# anything -> a regressing stage) is rejected by the monotonic guard.

RESERVED = "reserved"
SNATCHED = "snatched"
DOWNLOADED = "downloaded"
POST_PROCESSING = "post_processing"
MOVED = "moved"
POST_PROCESSED = "post_processed"
MANUAL_REVIEW = "manual_review"
FAILED = "failed"
CANCELLED = "cancelled"

STAGE_RANK = {
    RESERVED: 5,
    SNATCHED: 10,
    DOWNLOADED: 20,
    POST_PROCESSING: 30,
    MOVED: 40,
    POST_PROCESSED: 50,
    MANUAL_REVIEW: 55,
    FAILED: 60,
    # Above every open stage so an operator cancel wins over a late monitor
    # write; a later RESERVED/SNATCHED still supersedes it.
    CANCELLED: 65,
}

# Stages considered terminal: no further forward transition is legal.
TERMINAL_STAGES = (POST_PROCESSED, MANUAL_REVIEW, FAILED, CANCELLED)

# Open stages: rows replay must consider as still-in-flight obligations.
OPEN_STAGES = (RESERVED, SNATCHED, DOWNLOADED, POST_PROCESSING, MOVED)

# Terminal stages eligible for low-level resolution stamps. Attention applies
# its own admission policy before exposing either stage to an operator.
BAND_STAGES = (FAILED, MANUAL_REVIEW)

# R9 resolution stamps — written by operator actions (and FAILED_AUTO retry)
# without rewriting stage / stage_rank. Rows with these statuses leave the band;
# ledger retention may age them out with other eligible terminals (#480).
STATUS_RETRIED = "retried"
STATUS_IGNORED = "ignored"
STATUS_IMPORTED = "imported"
RESOLVED_STATUSES = (STATUS_RETRIED, STATUS_IGNORED, STATUS_IMPORTED)

# Fresh re-snatch stages that may supersede a supersedable terminal row under
# the same release_key (same issue|provider). DDL handoff writes RESERVED
# first; NZB/torrent snatch (updater.foundsearch) writes SNATCHED directly.
_RESNATCH_STAGES = (RESERVED, SNATCHED)

# Terminal stages a re-snatch may supersede. `failed` is always supersedable:
# the attempt is closed and nothing is outstanding at the download client.
#
# `manual_review` is supersedable ONLY once an operator has resolved it (#562).
# The asymmetry is deliberate. An unresolved manual_review row is an OPEN
# obligation — it means "the client may already have this, go look" — and it is
# on the needs-attention band precisely so a human does. Letting an automatic
# re-snatch reset it would both hide the row and re-deliver a release the client
# may already hold; on routes like watchdir, where every acceptance is manual
# review by construction, every sweep would deliver another copy. Once the
# operator has acted (retry / search again / import — the R9 stamp that takes
# the row off the band), the obligation is discharged and the next grab must be
# able to proceed. Before #562 it could not: the row stayed terminal, so the
# operator's own retry wedged at reservation for that issue+provider forever.
#
# This widens the *stage gate* only. The reset is still reachable exclusively
# from a fresh RESERVED/SNATCHED write, so it does not become an operator exit —
# the boundary docs/architecture/activity-center.md draws is intact.
_SUPERSEDABLE_TERMINALS = (FAILED, MANUAL_REVIEW, CANCELLED)

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
    differ by an `[RSS]` suffix, a `(newznab)`/`(torznab)` type-label suffix
    (search.py's `tmpprov` carries it, the raw `nzbprov` does not — #745),
    surrounding whitespace, or case. Stripping the `[RSS]` marker and the
    trailing type label, collapsing whitespace and lowercasing makes the four
    seams converge on one token. None/empty normalizes to "" (stable)."""
    if provider is None:
        return ""
    p = str(provider)
    p = re.sub(r"\[RSS\]", "", p, flags=re.IGNORECASE)
    # `+` so a provider literally NAMED "Foo (newznab)" converges with its own
    # tmpprov form "Foo (newznab) (newznab)" instead of drifting by one label.
    p = re.sub(r"(\s*\((?:newznab|torznab)\))+\s*$", "", p, flags=re.IGNORECASE)
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

    # DDL commands are independently durable obligations: two provider
    # results for the same issue may both be queued and must never collapse
    # onto one journal row. Their durable command id is available before the
    # side effect, unlike downloader-generated NZB/torrent ids.
    if "ddl" in prov and discriminant:
        return "%s|%s|ddl:%s" % (issueid, prov, _coerce_discriminant(discriminant))
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
# Internal: sanitize, merge and serialize payload
# ---------------------------------------------------------------------------

# The journal is a reconstruction contract, not a request/response archive.
# Keep this allowlist intentionally small: anything that can grant access or
# replay a provider request belongs in the downloader's own protected config,
# never in the operational database.
_PAYLOAD_KEYS = frozenset(
    {
        "issueid",
        "comicid",
        "provider",
        "downloader_type",
        "route",
        "client",
        "clientmode",
        "nzo_id",
        "NZBID",
        "hash",
        "ddl_id",
        "id",
        "nzbname",
        "nzb_name",
        "nzb_folder",
        "filename",
        "series",
        "site",
        "mode",
        "comicname",
        "issuenumber",
        "failed",
        "apicall",
        "ddl",
        "oneoff",
        "journal_release_key",
        "download_info",
        # Sanitised diagnostic text for fail_reason detail / narrative
        # reason_detail (#430 A5). Never a credential; redacted at write sites.
        "fail_detail",
    }
)
_DOWNLOAD_INFO_KEYS = frozenset({"provider", "id", "nzo_id", "NZBID", "hash", "nzbname", "clientmode"})
_IMMUTABLE_PAYLOAD_KEYS = frozenset(
    {
        "issueid",
        "comicid",
        "provider",
        "downloader_type",
        "route",
        "client",
        "clientmode",
        "nzo_id",
        "NZBID",
        "hash",
        "ddl_id",
        "id",
    }
)
_MAX_PAYLOAD_STRING = 2048
_MAX_PAYLOAD_BYTES = 16 * 1024


def _bounded_scalar(value):
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)[:_MAX_PAYLOAD_STRING]


def sanitize_payload(payload):
    """Return the bounded, secret-safe reconstruction projection.

    Unknown keys are discarded rather than recursively persisted. This makes
    API keys, cookies, authorization headers, signed URLs, provider links and
    raw sender responses non-persistable by construction.
    """
    if payload is None:
        return None
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except (TypeError, ValueError):
            logger.warn("[JOURNAL] discarded non-object payload string")
            return {}
    if not isinstance(payload, dict):
        logger.warn("[JOURNAL] discarded non-object payload of type %s" % type(payload).__name__)
        return {}

    clean = {}
    for key, value in payload.items():
        if key not in _PAYLOAD_KEYS:
            continue
        if key == "download_info":
            if not isinstance(value, dict):
                continue
            nested = {
                nested_key: _bounded_scalar(nested_value)
                for nested_key, nested_value in value.items()
                if nested_key in _DOWNLOAD_INFO_KEYS
            }
            if nested:
                clean[key] = nested
            continue
        clean[key] = _bounded_scalar(value)
    # Bound the complete encoded object as well as each scalar. Keep keys in
    # insertion order and stop before the cap; reconstruction-critical callers
    # put identity first and later transitions merge additional fields.
    bounded = {}
    for key, value in clean.items():
        candidate = {**bounded, key: value}
        if len(json.dumps(candidate, default=str).encode("utf-8")) > _MAX_PAYLOAD_BYTES:
            logger.warn("[JOURNAL] payload reached the %d-byte reconstruction cap" % _MAX_PAYLOAD_BYTES)
            break
        bounded[key] = value
    return bounded


def _merge_payload(existing, incoming):
    merged = dict(existing or {})
    for key, value in (incoming or {}).items():
        old = merged.get(key)
        values_match = normalize_provider(old) == normalize_provider(value) if key == "provider" else old == value
        if key in _IMMUTABLE_PAYLOAD_KEYS and old not in (None, "") and value not in (None, "") and not values_match:
            return merged, key
        if key == "download_info" and isinstance(value, dict):
            nested = dict(merged.get(key) or {})
            for nested_key, nested_value in value.items():
                old_nested = nested.get(nested_key)
                values_match = (
                    normalize_provider(old_nested) == normalize_provider(nested_value)
                    if nested_key == "provider"
                    else old_nested == nested_value
                )
                if (
                    nested_key in _IMMUTABLE_PAYLOAD_KEYS
                    and old_nested not in (None, "")
                    and nested_value not in (None, "")
                    and not values_match
                ):
                    return merged, "download_info.%s" % nested_key
                nested[nested_key] = nested_value
            merged[key] = nested
        elif value is not None:
            merged[key] = value
    return merged, None


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
    return now()


def _try_reset_terminal_attempt(conn, key, stage, new_rank, upd_values):
    """RE-SNATCH special case: a fresh RESERVED or SNATCHED write observed
    against a supersedable terminal row is a NEW in-flight obligation that
    legitimately supersedes the closed attempt — reset the row.

    Supersedable means a terminal `failed` row, or a `manual_review` row an
    operator has already resolved. See ``_SUPERSEDABLE_TERMINALS`` for why the
    two differ; an unresolved manual_review row is left terminal on purpose.

    WHY this does NOT weaken the monotonic stale-replay guard: replay never
    issues a fresh RESERVED/SNATCHED transition (the snatch seam and DDL
    handoff do, only from a real new grab; replay re-enqueues still
    non-terminal items, never a first-stage write). So a re-snatch stage
    seen against a terminal row is always a genuine new obligation, never a
    stale replay — resetting is correct here and the monotonic guard is left
    fully intact for every other stage.

    SNATCHED is included because the NZB/torrent snatch path
    (updater.foundsearch) writes SNATCHED directly against
    ``issueid|provider`` without an intervening RESERVED. Without that gate,
    a same-provider operator/auto retry returns ``won=False`` and narrates
    nothing (#483 / #437 amendment).

    This helper remains the re-snatch path only — operator band exits stamp
    R9 status without calling it (#437 / #483). Widening the stage gate does
    not change that: nothing but a fresh RESERVED/SNATCHED write reaches here.

    Returns True iff THIS call won the reset. The UPDATE carries the same
    stage/status predicate the caller matched on, so two concurrent re-snatch
    writers racing one terminal row yield exactly one True — the loser's gated
    UPDATE matches 0 rows and it falls back to the monotonic no-op.
    """
    if stage not in _RESNATCH_STAGES:
        return False

    previous = conn.execute(select(pipeline_journal.c.stage).where(pipeline_journal.c.release_key == key)).scalar()
    reset = conn.execute(
        update(pipeline_journal)
        .where(pipeline_journal.c.release_key == key)
        .where(_supersedable_terminal_predicate())
        .values(fail_reason=None, status=None, hash=None, **upd_values)
    )
    if reset.rowcount:
        logger.warn(
            "[JOURNAL] release_key=%s reset from terminal %s -> %s "
            "(new submission supersedes closed attempt)" % (key, previous, stage)
        )
        return True
    return False


def _supersedable_terminal_predicate():
    """SQL for "this terminal row may be superseded by a fresh re-snatch"."""

    return or_(
        pipeline_journal.c.stage == FAILED,
        and_(
            pipeline_journal.c.stage == MANUAL_REVIEW,
            pipeline_journal.c.status.in_(RESOLVED_STATUSES),
        ),
    )


def _is_supersedable_terminal(mapping):
    """Python mirror of :func:`_supersedable_terminal_predicate`."""

    stage = mapping.get("stage")
    if stage == FAILED:
        return True
    return stage == MANUAL_REVIEW and mapping.get("status") in RESOLVED_STATUSES


def _apply_transition(conn, key, stage, new_rank, fields, payload, when):
    """Run the UPDATE-then-conditional-INSERT pair on an open connection.

    Returns True iff this call advanced (won) the row. Atomicity vs concurrent
    writers comes from the caller running this inside a single transaction.
    """
    # 1. Conditional advance: only succeeds if the existing row is strictly
    #    behind the new rank. This is the monotonic guard AND (for the
    #    downloaded -> post_processing case) the U4 atomic claim.
    existing_row = conn.execute(select(pipeline_journal).where(pipeline_journal.c.release_key == key)).fetchone()
    existing_payload = (
        sanitize_payload(load_payload(existing_row._mapping.get("payload_json"))) if existing_row is not None else None
    )
    new_attempt = (
        existing_row is not None and _is_supersedable_terminal(existing_row._mapping) and stage in _RESNATCH_STAGES
    )
    if new_attempt:
        # A new attempt must not inherit the previous client's acceptance id,
        # route or hash. Retain only stable release identity/context; otherwise
        # a legitimate new nzo_id/NZBID conflicts and is quarantined.
        existing_payload = {
            key_name: value
            for key_name, value in (existing_payload or {}).items()
            if key_name in {"issueid", "comicid", "provider", "nzbname", "comicname", "issuenumber", "mode"}
        }
    merged_payload, conflict = _merge_payload(existing_payload, payload)
    if existing_row is not None and not conflict:
        values = existing_row._mapping
        conflict_fields = (
            ("issueid", "provider")
            if new_attempt
            else (
                "issueid",
                "provider",
                "downloader_type",
                "hash",
            )
        )
        for field_name in conflict_fields:
            incoming = fields.get(field_name)
            current = values.get(field_name)
            values_match = (
                normalize_provider(incoming) == normalize_provider(current)
                if field_name == "provider"
                else str(incoming) == str(current)
            )
            if incoming not in (None, "") and current not in (None, "") and not values_match:
                conflict = field_name
                break
    payload_json = _dump_payload(merged_payload) if merged_payload is not None else None

    # Immutable identity disagreement means we cannot prove which external
    # obligation the row represents. Quarantine it atomically and require an
    # operator decision; never guess and never blind-replay it.
    if conflict and existing_row is not None:
        reason = "immutable_payload_conflict:%s" % conflict
        quarantined = conn.execute(
            update(pipeline_journal)
            .where(pipeline_journal.c.release_key == key)
            .where(pipeline_journal.c.stage.notin_(TERMINAL_STAGES))
            .values(
                stage=MANUAL_REVIEW,
                stage_rank=STAGE_RANK[MANUAL_REVIEW],
                status=MANUAL_REVIEW,
                fail_reason=reason,
                updated_date=when,
                payload_json=_dump_payload(existing_payload),
            )
        )
        if quarantined.rowcount:
            # Clause 2 (#541): re-want + log loudly. This transition cannot
            # call Attention.record recursively, so it invokes Attention's
            # private post-transition reconciliation hook.
            from comicarr.app.attention._reconciliation import reconcile_excluded

            mapping = existing_row._mapping
            # `strict=True` so a reconciliation failure is loud, but caught so
            # it cannot veto the quarantine. `conn` here is the CALLER's
            # transaction (post-processing), and postprocess_pipeline re-raises
            # when `conn is not None` — letting this propagate would roll back
            # the quarantine UPDATE above and leave the row non-terminal, i.e.
            # blind-replayable, which is exactly what this block exists to
            # prevent. The asymmetry with `attention.record()`'s owned
            # transaction (all-or-nothing, lock-retried) is deliberate: there
            # the exclusion and its reconciliation are the same durable fact,
            # whereas here the quarantine is the safety property and has no
            # catch-up mechanism, while the reconciliation obligation does —
            # `recovery.reconcile_existing_excluded_rows()` re-scans unresolved
            # failed/manual_review rows every boot and re-discharges them
            # idempotently, and a MANUAL_REVIEW row carrying
            # `immutable_payload_conflict:*` is inside that scan set.
            try:
                reconcile_excluded(
                    reason,
                    issueid=mapping.get("issueid") or fields.get("issueid"),
                    provider=mapping.get("provider") or fields.get("provider"),
                    nzbname=mapping.get("nzbname") or fields.get("nzbname"),
                    hash=mapping.get("hash") or fields.get("hash"),
                    payload=existing_payload,
                    conn=conn,
                    strict=True,
                )
            except Exception as e:
                logger.error("[JOURNAL] band reconciliation after immutable conflict %s: %s" % (key, e))
            logger.error("[JOURNAL] quarantined release_key=%s: %s" % (key, reason))
        return False

    # Same-stage calls are not a new side-effect claim, but may safely fill in
    # reconstruction fields learned after submission (notably client ids).
    # Persist the enrichment while preserving the False/"lost claim" return
    # contract used by postprocess_main.
    if existing_row is not None and int(existing_row._mapping["stage_rank"]) == new_rank:
        if existing_row._mapping.get("stage") in TERMINAL_STAGES:
            return False
        previous_json = _dump_payload(existing_payload) if existing_payload is not None else None
        if payload_json != previous_json:
            conn.execute(
                update(pipeline_journal)
                .where(pipeline_journal.c.release_key == key)
                .where(pipeline_journal.c.stage_rank == new_rank)
                .values(payload_json=payload_json, updated_date=when)
            )
            logger.fdebug("[JOURNAL] enriched same-stage payload for release_key=%s stage=%s" % (key, stage))
        return False

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
        .where(pipeline_journal.c.stage.notin_(TERMINAL_STAGES))
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
                .where(pipeline_journal.c.stage.notin_(TERMINAL_STAGES))
                .where(pipeline_journal.c.stage_rank < new_rank)
                .values(**upd_values)
            )
            if retry.rowcount:
                return True
            # The now-present row may be a supersedable terminal row (a
            # concurrent writer inserted-then-terminalised it): the monotonic
            # re-run matched 0, so this is the absent-of-monotonic-match branch
            # for that case — apply the same gated re-snatch reset here so the
            # P1-2 race path composes with the terminal->snatched rule.
            if _try_reset_terminal_attempt(conn, key, stage, new_rank, upd_values):
                return True
            logger.fdebug(
                "[JOURNAL] first-writer race resolved: release_key=%s stage=%s "
                "(rank=%d) lost the INSERT to a concurrent writer; row already "
                "at/ahead — returning lost (CAS contract preserved)." % (key, stage, new_rank)
            )
            return False

    # Row exists and is at/ahead of new_rank. The ONE legal exception to the
    # monotonic no-op: a fresh RESERVED/SNATCHED write against a supersedable
    # terminal row is a RE-SNATCH that supersedes the closed attempt. The
    # status half of "supersedable" is enforced by the helper's own gated
    # UPDATE, so this stage check only avoids a pointless statement.
    if existing[0] in _SUPERSEDABLE_TERMINALS and _try_reset_terminal_attempt(conn, key, stage, new_rank, upd_values):
        return True

    # Row exists and is at/ahead of new_rank — a regressing or post-terminal
    # write. Logged no-op (NOT last-writer-wins).
    logger.fdebug(
        "[JOURNAL] no-op: release_key=%s requested stage=%s (rank=%d) but row "
        "is already at stage=%s (rank=%s) — monotonic guard rejected regression."
        % (key, stage, new_rank, existing[0], existing[1])
    )
    return False


def _prior_context(conn, release_key):
    """Return (stage_rank, issueid, provider) for an existing journal row, or Nones."""
    row = conn.execute(
        select(
            pipeline_journal.c.stage_rank,
            pipeline_journal.c.issueid,
            pipeline_journal.c.provider,
        ).where(pipeline_journal.c.release_key == release_key)
    ).fetchone()
    if row is None:
        return None, None, None
    m = row._mapping
    return m.get("stage_rank"), m.get("issueid"), m.get("provider")


def _emit_activity_for_won_transition(
    stage,
    release_key,
    fields,
    payload,
    *,
    prior_rank,
    prior_issueid,
    prior_provider,
    conn=None,
):
    """Best-effort narrative emit after a won journal advance (#484).

    Returns the activity payload (or None). Never raises into the journal path
    — a narrative failure must not undo a durable stage transition. When
    ``conn`` is supplied the insert co-commits; the caller publishes after
    their commit (or the facade-owned path publishes after its begin() exits).
    """
    try:
        from comicarr.app.activity.producers import emit_for_journal_stage

        issueid = fields.get("issueid") if fields else None
        if issueid in (None, ""):
            issueid = prior_issueid
        if issueid in (None, "") and isinstance(payload, dict):
            issueid = payload.get("issueid")
        provider = fields.get("provider") if fields else None
        if provider in (None, ""):
            provider = prior_provider
        if provider in (None, "") and isinstance(payload, dict):
            provider = payload.get("provider")
        fail_reason = fields.get("fail_reason") if fields else None

        return emit_for_journal_stage(
            stage,
            release_key=release_key,
            issueid=issueid,
            provider=provider,
            fail_reason=fail_reason,
            payload=payload,
            prior_stage_rank=prior_rank,
            conn=conn,
            won=True,
        )
    except Exception as e:
        logger.fdebug("[JOURNAL] activity emit skipped for release_key=%s stage=%s: %s" % (release_key, stage, e))
        return None


def record_transition(release_key, stage, payload=None, conn=None, _activity_sink=None, **fields):
    """Forward-only conditional advance for one release_key.

    Implemented as a monotonic conditional update plus insert-if-absent, the
    pair run atomically inside one transaction. A regressing or post-terminal
    write is a logged no-op.

    Return contract: returns True iff THIS call advanced the row (the caller
    "won"). False means the write was a no-op because the row was already at
    or beyond `stage` (a regression, a terminal row, or a concurrent winner).
    The U4 PP-consumer atomic claim relies on exactly one concurrent
    downloaded -> post_processing caller getting True.

    When this call wins, the matching Activity Center cell is co-committed
    (or written in the same own-transaction) and published after durability
    on the facade-owned path (#484 / ADR §7).

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

    payload = sanitize_payload(payload)
    when = _now()

    # Caller-supplied connection: participate in the caller's transaction.
    if conn is not None:
        prior_rank, prior_issueid, prior_provider = _prior_context(conn, release_key)
        won = _apply_transition(conn, release_key, stage, new_rank, fields, payload, when)
        if won:
            logger.fdebug("[JOURNAL] advanced release_key=%s -> stage=%s (caller txn)" % (release_key, stage))
            # Co-commit narrative; SSE publish is left to the transaction owner
            # (or the next query-backed refetch — best-effort contract).
            activity_payload = _emit_activity_for_won_transition(
                stage,
                release_key,
                fields,
                payload,
                prior_rank=prior_rank,
                prior_issueid=prior_issueid,
                prior_provider=prior_provider,
                conn=conn,
            )
            if activity_payload is not None and _activity_sink is not None:
                _activity_sink.append(activity_payload)
        return won

    # Own transaction with bounded retry-then-raise (mirrors db.upsert).
    attempt = 0
    while attempt < 5:
        try:
            activity_payload = None
            with db.get_engine().begin() as own_conn:
                prior_rank, prior_issueid, prior_provider = _prior_context(own_conn, release_key)
                won = _apply_transition(own_conn, release_key, stage, new_rank, fields, payload, when)
                if won:
                    # Co-commit activity inside the same transaction so the
                    # narrative row is durable with the stage advance.
                    activity_payload = _emit_activity_for_won_transition(
                        stage,
                        release_key,
                        fields,
                        payload,
                        prior_rank=prior_rank,
                        prior_issueid=prior_issueid,
                        prior_provider=prior_provider,
                        conn=own_conn,
                    )
            if won:
                logger.fdebug("[JOURNAL] advanced release_key=%s -> stage=%s" % (release_key, stage))
                if activity_payload:
                    try:
                        from comicarr.app.activity.events import publish_activity

                        publish_activity(activity_payload)
                    except Exception as e:
                        logger.fdebug("[JOURNAL] activity publish skipped: %s" % e)
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


def mark_failed(release_key, fail_reason, payload=None, conn=None, _activity_sink=None, **fields):
    """Advance a row to the terminal `failed` stage, retaining payload/reason
    so a future manual-retry layer (R9) can act on it."""
    return record_transition(
        release_key,
        FAILED,
        payload=payload,
        conn=conn,
        _activity_sink=_activity_sink,
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


def mark_manual_review(release_key, reason, payload=None, conn=None, _activity_sink=None, **fields):
    """Quarantine an obligation whose safe automatic continuation is unknown."""
    return record_transition(
        release_key,
        MANUAL_REVIEW,
        payload=payload,
        conn=conn,
        _activity_sink=_activity_sink,
        status=MANUAL_REVIEW,
        fail_reason=str(reason)[:1000],
        **fields,
    )


def read_open():
    """Return all journal rows still representing an in-flight obligation:
    stage in {reserved, snatched, downloaded, post_processing, moved}. Excludes
    post_processed, manual_review and failed (terminal) rows.

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


def migrate_release_key_provider_format():
    """One-shot #745 key-format reconciliation (idempotent, safe every boot).

    normalize_provider now strips the trailing `(newznab)`/`(torznab)` type
    label, so keys derived BEFORE the fix (snatch seam passed the labelled
    `tmpprov`) no longer reproduce from the same durable inputs: anchor
    reconstruction and the downloaded-seam fallback would re-derive the new
    form, miss the existing row, and either duplicate or re-drive an
    obligation that already advanced. Rewrite the provider segment of every
    stored key (terminal rows included — read_one on a terminal row is what
    stops a re-drive) through the current normalizer.

    A collision (old-form and new-form rows both present) is left alone and
    logged loudly — never silently coalesced. Post-fix derivations cannot
    produce a labelled segment, so after the first pass this is a no-op scan.

    Returns the number of rewritten rows.
    """
    try:
        rows = db.select_all(select(pipeline_journal.c.release_key))
    except Exception as e:
        logger.error("[JOURNAL] #745 key migration could not read journal rows: %s" % type(e).__name__)
        return 0
    renames = []
    for row in rows:
        key = row.get("release_key") or ""
        parts = key.split("|")
        if len(parts) < 2:
            continue
        new_prov = normalize_provider(parts[1])
        if new_prov == parts[1]:
            continue
        renames.append((key, "|".join([parts[0], new_prov] + parts[2:])))
    migrated = 0
    for old_key, new_key in renames:
        try:
            with db.get_engine().begin() as conn:
                collision = conn.execute(
                    select(pipeline_journal.c.release_key).where(pipeline_journal.c.release_key == new_key)
                ).fetchone()
                if collision is not None:
                    logger.warn(
                        "[JOURNAL] #745 key migration collision: %r already exists — "
                        "leaving %r unmigrated (operator attention may be required)." % (new_key, old_key)
                    )
                    continue
                result = conn.execute(
                    update(pipeline_journal)
                    .where(pipeline_journal.c.release_key == old_key)
                    .values(release_key=new_key)
                )
                migrated += int(bool(result.rowcount))
        except Exception as e:
            logger.error(
                "[JOURNAL] #745 key migration failed for %r — SKIPPED (resumable next start): %s"
                % (old_key, type(e).__name__)
            )
    if migrated:
        logger.info("[JOURNAL] #745 key migration rewrote %d journal release_key(s)." % migrated)
    return migrated


def stamp_resolution(release_key, status, *, increment_retry=False, conn=None):
    """Stamp an R9 resolution status without rewriting stage / stage_rank.

    Legal only on band stages (``failed`` / ``manual_review``) that are not
    already resolved. Returns True iff this call wrote the stamp.
    """
    if status not in RESOLVED_STATUSES:
        raise ValueError("[JOURNAL] unknown resolution status %r" % (status,))
    if release_key in (None, ""):
        return False

    when = _now()

    def _write(active_conn):
        row = active_conn.execute(
            select(pipeline_journal).where(pipeline_journal.c.release_key == release_key)
        ).fetchone()
        if row is None:
            return False
        mapping = row._mapping
        if mapping.get("stage") not in BAND_STAGES:
            return False
        if mapping.get("status") in RESOLVED_STATUSES:
            return False
        values = {"status": status, "updated_date": when}
        if increment_retry:
            current = mapping.get("retry_count")
            try:
                values["retry_count"] = int(current or 0) + 1
            except (TypeError, ValueError):
                values["retry_count"] = 1
        result = active_conn.execute(
            update(pipeline_journal)
            .where(pipeline_journal.c.release_key == release_key)
            .where(pipeline_journal.c.stage.in_(BAND_STAGES))
            .where(
                or_(
                    pipeline_journal.c.status.is_(None),
                    pipeline_journal.c.status.notin_(RESOLVED_STATUSES),
                )
            )
            .values(**values)
        )
        return bool(result.rowcount)

    if conn is not None:
        return _write(conn)

    attempt = 0
    while attempt < 5:
        try:
            with db.get_engine().begin() as own_conn:
                return _write(own_conn)
        except OperationalError as e:
            err_msg = str(e)
            if "locked" in err_msg or "unable to open" in err_msg:
                logger.warn(
                    "[JOURNAL] Database locked during stamp_resolution "
                    "(release_key=%s status=%s), retry %d: %s" % (release_key, status, attempt + 1, e)
                )
                attempt += 1
                time.sleep(1)
            else:
                raise
    logger.error("[JOURNAL] stamp_resolution FAILED after 5 retries (release_key=%s status=%s)" % (release_key, status))
    raise OperationalError(
        "Journal stamp_resolution on %s -> %s failed after 5 retries" % (release_key, status),
        None,
        None,
    )
