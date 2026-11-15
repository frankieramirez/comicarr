#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  Comicarr is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with Comicarr.  If not, see <http://www.gnu.org/licenses/>.

"""Debug lines that let an operator find a search by its logged text (#1017).

Three fixed shapes, all at Debug::

    [SEARCH-QUERY] series=<id> issue=<id> number=<n> provider="<name>" source=<api|rss|experimental|getcomics> query="<text>" returned=<n> kept=<n>
    [EVALUATION] series=<id> issue=<id> provider="<name>" consumed=<n> accepted=<n> selected=<n> stopped=<end|preferred|error>
    [EVALUATION] candidate="<title>" verdict=<status> reason=<reason_code> kind=<match_kind>

Every function here only reads values its caller already holds. None of them
touches a provider, an iterator, or evaluation state, so the search behaves the
same at every log level. Provider names go through ``safe_provider_name`` and
free text through ``redact_sensitive_text``; no line carries a URL.
"""

from urllib.parse import unquote

from comicarr import logger
from comicarr.app.common.redaction import redact_sensitive_text

_URL_MARKERS = ("://", "@", "?", "apikey=", "token=")
_GENERIC_PROVIDER = {
    "ddl": "Direct-download provider",
    "torrent": "Torrent provider",
    "usenet": "Usenet provider",
}


def safe_provider_name(is_info, site=None):
    """The configured provider name and its source kind, never a host or URL."""
    info = is_info or {}
    nzbprov = str(info.get("nzbprov") or site or "Unknown")
    provider_stat = info.get("provider_stat") or {}
    if not isinstance(provider_stat, dict):
        provider_stat = {}
    provider_type = str(provider_stat.get("type") or "").lower()
    newznab_host = info.get("newznab_host")
    torznab_host = info.get("torznab_host")

    if newznab_host:
        provider = str(newznab_host[0] or "Newznab")
    elif torznab_host:
        provider = str(torznab_host[0] or "Torznab")
    else:
        provider = nzbprov

    if "ddl" in nzbprov.lower():
        source_kind = "ddl"
    elif provider_type in ("newznab", "usenet") or "newznab" in nzbprov.lower():
        source_kind = "usenet"
    elif provider_type in ("torznab", "torrent") or "torrent" in nzbprov.lower() or nzbprov == "32P":
        source_kind = "torrent"
    else:
        source_kind = "unknown"

    provider_lower = provider.lower()
    if any(marker in provider_lower for marker in _URL_MARKERS):
        provider = _GENERIC_PROVIDER.get(source_kind, "Search provider")
    return provider, source_kind


def quoted(text):
    """Double-quote free text so a field can hold spaces and still be found."""
    value = redact_sensitive_text(text)
    return '"%s"' % value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


def _identity(is_info):
    info = is_info or {}
    return "series=%s issue=%s" % (info.get("ComicID") or "-", info.get("IssueID") or "-")


def log_query(is_info, source, query, returned=None, kept=None):
    """One ``[SEARCH-QUERY]`` line for a provider request that already ran.

    ``returned`` and ``kept`` are counts of lists the caller already holds;
    leave them out when the caller has no complete list (GetComics iterates
    pages lazily), rather than estimating.
    """
    info = is_info or {}
    provider, _ = safe_provider_name(info)
    line = "[SEARCH-QUERY] %s number=%s provider=%s source=%s query=%s" % (
        _identity(info),
        info.get("IssueNumber") if info.get("IssueNumber") not in (None, "") else "-",
        quoted(provider),
        source,
        quoted(unquote(str(query or ""))),
    )
    if returned is not None:
        line += " returned=%d kept=%d" % (returned, returned if kept is None else kept)
    logger.fdebug(line)


def log_evaluation(is_info, outcomes, selected, stopped):
    """The ``[EVALUATION]`` summary and one verdict line per evaluated candidate.

    ``outcomes`` and ``selected`` are the sequences ``EvaluationSession.evaluate``
    already built; this reads them and nothing else.
    """
    info = is_info or {}
    provider, _ = safe_provider_name(info)
    accepted = sum(1 for outcome in outcomes if outcome.verdict.get("accepted"))
    logger.fdebug(
        "[EVALUATION] %s provider=%s consumed=%d accepted=%d selected=%d stopped=%s"
        % (_identity(info), quoted(provider), len(outcomes), accepted, len(selected), stopped)
    )
    for outcome in outcomes:
        verdict = outcome.verdict
        logger.fdebug(
            "[EVALUATION] candidate=%s verdict=%s reason=%s kind=%s"
            % (
                quoted(outcome.candidate.get("title")),
                verdict.get("status"),
                verdict.get("reason_code"),
                verdict.get("match_kind") or "none",
            )
        )
