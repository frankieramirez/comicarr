#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Private reason classification and admission policy for Needs attention."""

from sqlalchemy import and_, not_, or_

from comicarr.app.downloads.journal import FAILED, MANUAL_REVIEW

ACTION_RETRY = "retry"
ACTION_SEARCH_AGAIN = "search_again"
ACTION_IMPORT = "import"
ACTION_STOP_WANTING = "stop_wanting"

TROUBLE_STAGES = (FAILED, MANUAL_REVIEW)
STAGE_ACTIONS = {
    FAILED: (ACTION_RETRY, ACTION_STOP_WANTING),
    MANUAL_REVIEW: (ACTION_IMPORT, ACTION_SEARCH_AGAIN, ACTION_STOP_WANTING),
}
ATTENTION_ACTIONS = frozenset(action for actions in STAGE_ACTIONS.values() for action in actions)

REASON_PHRASES = {
    "downloaded_invalid_artifact_command": "downloaded file failed post-process checks",
    "invalid_recovered_postprocess_command": "recovered download has a bad post-process command",
    "invalid_postprocess_command": "post-process command is invalid",
    "postprocess_error": "post-processing failed",
    "recovered_postprocess_error": "recovered download failed post-processing",
    "ddl_artifact_state_persistence_error": "could not save download state (direct download)",
    "torrent_artifact_state_persistence_error": "could not save download state (torrent)",
    "nzb_artifact_state_persistence_error": "could not save download state (NZB)",
    "reserved_without_persisted_acceptance": "download reserved but never fully accepted",
    "route_acceptance_missing_identity": "the downloader accepted it without identifying it",
    "submission_outcome_unknown": "submission result unknown — check the downloader",
    "route_not_restart_safe": "this route can't resume after a restart",
    "download_failed_no_auto_handling": "download failed and auto-handling is off",
    "submission_rejected": "the downloader rejected the submission",
}

UNMAPPED_REASON_PHRASE = "something went wrong"

NON_ACTIONABLE_FLAT = frozenset(
    {
        "download_gone",
        "download_failed_researching",
        "ddl_download_or_artifact_validation_failed",
        "ddl-worker-rejected",
        "torrent_hash_not_in_client",
        "legacy_downloading_without_correlation",
        "ambiguous_ddl_acceptance_after_restart",
    }
)

NON_ACTIONABLE_COMPOSITE = frozenset({"immutable_payload_conflict"})

RECONCILIATION = {
    "download_gone": "blocklist_and_rewant",
    "ddl_download_or_artifact_validation_failed": "blocklist_and_rewant",
    "ddl-worker-rejected": "rewant",
    "torrent_hash_not_in_client": "rewant",
    "ambiguous_ddl_acceptance_after_restart": "rewant",
    "immutable_payload_conflict": "rewant_and_log",
    "legacy_downloading_without_correlation": "rewant_if_issue",
    "download_failed_researching": "none",
}

KNOWN_BASE_TOKENS = frozenset(REASON_PHRASES) | NON_ACTIONABLE_FLAT | NON_ACTIONABLE_COMPOSITE


def base_reason(fail_reason):
    """Return the classifiable token before the first ``:``."""
    if fail_reason in (None, ""):
        return None
    token = str(fail_reason).strip()
    if not token:
        return None
    return token.split(":", 1)[0]


def reason_phrase(fail_reason):
    """Return operator-facing wording for a raw failure reason."""
    return REASON_PHRASES.get(base_reason(fail_reason) or "", UNMAPPED_REASON_PHRASE)


def is_actionable(fail_reason):
    """Admit unknown reasons and exclude only explicitly reconciled reasons."""
    token = base_reason(fail_reason)
    return token not in NON_ACTIONABLE_FLAT and token not in NON_ACTIONABLE_COMPOSITE


def reconciliation_for(fail_reason):
    """Return the reconciliation obligation for an excluded reason."""
    return RECONCILIATION.get(base_reason(fail_reason))


def actionable_reason_condition(column):
    """Build the portable, NULL-safe SQL admission clause."""
    non_actionable_tokens = sorted(NON_ACTIONABLE_FLAT | NON_ACTIONABLE_COMPOSITE)
    non_actionable = or_(
        column.in_(non_actionable_tokens),
        *[column.like("%s:%%" % base) for base in non_actionable_tokens],
    )
    return or_(column.is_(None), and_(column.isnot(None), not_(non_actionable)))
