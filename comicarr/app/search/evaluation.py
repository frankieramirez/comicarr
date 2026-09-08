# -*- coding: utf-8 -*-
#  Copyright (C) 2012–2024 Mylar3 contributors
#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#  Originally based on Mylar3 (https://github.com/mylar3/mylar3).
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

import datetime
import email.utils
import re
import time
from dataclasses import dataclass, field
from wsgiref.handlers import format_date_time

import comicarr
from comicarr import filechecker, helpers, logger
from comicarr.app.search import _pack_membership
from comicarr.app.search._release_identity import generate_id

__all__ = ["EvaluationSession", "EvaluationBatch", "ReleaseCandidateEvaluation"]

_REASON_DEFINITIONS = {
    "accepted.issue": ("Accepted issue match", False, "accepted"),
    "accepted.pack": ("Accepted pack match", False, "accepted"),
    "ignored.search_word": ("Contains a configured ignored word", True, "rejected"),
    "rejected.size_below_min": ("Below the configured minimum size", True, "rejected"),
    "rejected.size_above_max": ("Above the configured maximum size", True, "rejected"),
    "rejected.cover_only": ("Looks like a cover-only release", True, "rejected"),
    "invalid.pubdate_missing": ("Provider did not supply a publication date", False, "invalid"),
    "invalid.reference_date_missing": ("Tracked item has no usable reference date", False, "invalid"),
    "invalid.pubdate_unparseable": ("Provider publication date could not be parsed", False, "invalid"),
    "rejected.before_reference_date": ("Published before the tracked item", True, "rejected"),
    "error.matcher_exception": ("Title matcher failed", False, "error"),
    "rejected.series_mismatch": ("Series title does not match", True, "rejected"),
    "rejected.alternate_series": ("Matched only an alternate series name", True, "rejected"),
    "rejected.book_type": ("Publication format does not match", True, "rejected"),
    "rejected.unparseable_title": ("Release title could not be parsed", True, "rejected"),
    "rejected.year_mismatch": ("Series year does not match", True, "rejected"),
    "rejected.volume_mismatch": ("Series volume does not match", True, "rejected"),
    "rejected.pack_issue_absent": ("Pack does not contain the tracked item", True, "rejected"),
    "error.pack_lookup_exception": ("Pack contents could not be evaluated", False, "error"),
    "rejected.issue_mismatch": ("Issue or chapter number does not match", True, "rejected"),
    "blocked.duplicate": ("Duplicate candidate was suppressed", False, "blocked"),
    "error.evaluation_exception": ("Candidate evaluation failed", False, "error"),
}


class _EntryRejected(Exception):
    def __init__(self, reason_code):
        super().__init__(reason_code)
        self.reason_code = reason_code


@dataclass(frozen=True)
class _AcceptedMatch:
    _handoff: dict
    match_kind: str


@dataclass
class ReleaseCandidateEvaluation:
    """One sanitized provider candidate plus its structured match verdict.

    ``_handoff`` and ``exception`` stay server-side. ``as_dict`` is the
    credential-safe representation used by Interactive release search.
    """

    candidate: dict
    verdict: dict
    _handoff: dict | None = field(default=None, repr=False)
    exception: Exception | None = field(default=None, repr=False)
    reconstruction_hint: dict | None = field(default=None, repr=False)
    satisfies: list | None = None

    def as_dict(self):
        payload = {"candidate": dict(self.candidate), "verdict": dict(self.verdict)}
        if self.satisfies:
            payload["satisfies"] = [dict(item) for item in self.satisfies]
        return payload


@dataclass(frozen=True)
class EvaluationBatch:
    evaluations: tuple
    _selected: tuple
    _error: Exception | None = field(default=None, repr=False)

    @property
    def selected(self):
        """Candidates for selection/handoff, or the original collection error."""
        if self._error is not None:
            raise self._error
        return list(self._selected)


def manga_volume_satisfies(found_volume, wanted_number):
    """Does a matched manga volume satisfy the ledger row being searched?

    A manga volume release carries no issue number -- "One-Punch Man v01 (2014)
    (Digital)" -- so the issue-number acceptance arms can never accept it. The
    volume IS the unit being acquired, so the release satisfies the row when
    the two volume numbers agree.

    The comparison itself belongs to the ledger, which already owns what a
    volume number means; this only names the acceptance question.
    """
    from comicarr.app.manga.ledger import volume_numbers_match

    return volume_numbers_match(found_volume, wanted_number)


class EvaluationSession:
    """Evaluate one search's candidates without shared match state.

    Batch evaluation resets duplicate history. Preferred selection retains
    the preceding batch's history, as GetComics did, and only consumes as
    much of a provider iterator as its search mode requires.
    """

    def __init__(self, *, review=False, override_reason=None, searched_item=None, eligible=None):
        if override_reason is not None:
            definition = _REASON_DEFINITIONS.get(str(override_reason))
            if definition is None or not definition[1]:
                raise ValueError("release candidate rejection is not overrideable")
        self.review = review
        self._override_reason = override_reason
        self._accepted = []
        self.matches = []
        self.evaluations = []
        self._searched_item = searched_item
        self._eligible = eligible

    def _reject(self, reason_code, *, cause=None):
        if self._override_reason == reason_code:
            return
        rejection = _EntryRejected(reason_code)
        if cause is not None:
            raise rejection from cause
        raise rejection

    def start_search(self):
        """Start a new provider search while retaining collected review results."""
        self._accepted = []
        self.matches = []

    def evaluate(self, entries, is_info=None, *, prefer_pack=None):
        """Return ordered verdicts and selected candidates for one collection.

        With no preference, select every accepted candidate and reset batch
        duplicate history. A preference selects one candidate, consuming the
        complete iterator only in review mode. Selection raises the original
        evaluator exception in the same modes as the historical callers.
        """
        batch = prefer_pack is None
        if batch:
            self._accepted = []
            self.matches = []
        elif self.review:
            # GetComics materialized its iterator before evaluating entries.
            entries = list(entries)
        outcomes = []
        selected = []
        error = None
        fallback = None
        for entry in entries:
            evaluation = self._evaluate_entry(entry, is_info)
            if self._searched_item is not None:
                evaluation.satisfies = self._satisfies(evaluation)
            outcomes.append(evaluation)
            if evaluation.exception is not None and (batch or not self.review):
                error = evaluation.exception
                break
            if evaluation._handoff is None:
                continue
            if batch:
                self._accepted.append(evaluation._handoff)
                self.matches.append(evaluation)
                selected.append(evaluation)
            elif self.review:
                selected.append(evaluation)
            elif bool(evaluation._handoff["pack"]) is bool(prefer_pack):
                selected = [evaluation]
                break
            else:
                fallback = evaluation
        if not batch:
            if self.review:
                preferred = [e for e in selected if bool(e._handoff["pack"]) is bool(prefer_pack)]
                selected = (preferred or selected)[:1]
            elif not selected and fallback is not None:
                selected = [fallback]
        if self.review and error is None:
            self.evaluations.extend(outcomes)
        return EvaluationBatch(tuple(outcomes), tuple(selected), error)

    def _satisfies(self, evaluation):
        match_data = evaluation._handoff or {}
        pack_info = match_data.get("pack_issuelist")
        found = []
        eligible = self._eligible or {}
        if match_data.get("pack") and isinstance(pack_info, dict):
            for issue in pack_info.get("issues") or []:
                issue_id = str(issue.get("issueid") or issue.get("IssueID") or "")
                match = eligible.get(("issue", issue_id))
                if match is not None:
                    found.append(
                        {
                            "entity_type": "issue",
                            "entity_id": issue_id,
                            "issue_number": match.get("issue_number") or issue.get("issuenumber"),
                        }
                    )
            if found:
                return found
        searched = self._searched_item
        match = eligible.get((searched["entity_type"], str(searched["entity_id"])))
        if match is None:
            return []
        return [
            {
                "entity_type": match["entity_type"],
                "entity_id": match["entity_id"],
                "issue_number": match.get("issue_number"),
            }
        ]

    @staticmethod
    def _entry_value(entry, key, default=None):
        try:
            return entry.get(key, default)
        except AttributeError:
            try:
                return entry[key]
            except Exception:
                return default

    def _normalized_candidate(self, entry, is_info):
        info = is_info or {}
        nzbprov = str(info.get("nzbprov") or self._entry_value(entry, "site") or "Unknown")
        provider_stat = info.get("provider_stat") or {}
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
        if any(marker in provider_lower for marker in ("://", "@", "?", "apikey=", "token=")):
            provider = {
                "ddl": "Direct-download provider",
                "torrent": "Torrent provider",
                "usenet": "Usenet provider",
            }.get(source_kind, "Search provider")

        raw_size = self._entry_value(entry, "length")
        if raw_size in (None, "", "0", 0):
            raw_size = self._entry_value(entry, "size")
        try:
            size_bytes = int(raw_size)
        except (TypeError, ValueError):
            try:
                size_bytes = helpers.human2bytes(str(raw_size))
            except (AssertionError, TypeError, ValueError):
                size_bytes = None

        metrics = {}
        for key in ("seeders", "peers", "leechers", "grabs", "files"):
            value = self._entry_value(entry, key)
            if value not in (None, ""):
                try:
                    metrics[key] = int(value)
                except (TypeError, ValueError):
                    continue

        return {
            "title": str(self._entry_value(entry, "title") or "Untitled release"),
            "provider": provider,
            "source_kind": source_kind,
            "published_at": self._entry_value(entry, "updated") or self._entry_value(entry, "pubdate"),
            "size_bytes": size_bytes,
            "pack": bool(self._entry_value(entry, "pack", False)),
            "metrics": metrics,
        }

    @staticmethod
    def _verdict(reason_code, match_kind="none"):
        message, overrideable, status = _REASON_DEFINITIONS[reason_code]
        return {
            "status": status,
            "accepted": status == "accepted",
            "overrideable": overrideable,
            "reason_code": reason_code,
            "reasons": [{"code": reason_code, "message": message}],
            "match_kind": match_kind,
        }

    def _reconstruction_hint(self, entry, is_info):
        """Retain only the raw identity inputs needed for safe persistence.

        The persistence module still validates and hashes these values before
        writing them. Keeping this hint private lets overrideable rejections be
        found again even though they never produce an accepted legacy match.
        """

        info = is_info or {}
        provider_stat = info.get("provider_stat") or {}
        if not isinstance(provider_stat, dict):
            provider_stat = {}
        raw_identity = self._entry_value(entry, "id")
        if raw_identity in (None, ""):
            raw_identity = self._entry_value(entry, "link")
        return {
            "provider_config_id": provider_stat.get("id"),
            "provider_type": provider_stat.get("type"),
            "provider_item_id": raw_identity,
        }

    def _evaluate_entry(self, entry, is_info=None):
        """Evaluate one raw provider entry without exposing provider secrets."""

        candidate = self._normalized_candidate(entry, is_info)
        reconstruction_hint = self._reconstruction_hint(entry, is_info)
        try:
            accepted = self._match_entry(entry, is_info)
        except _EntryRejected as rejection:
            return ReleaseCandidateEvaluation(
                candidate,
                self._verdict(rejection.reason_code),
                reconstruction_hint=reconstruction_hint,
            )
        except Exception as e:
            return ReleaseCandidateEvaluation(
                candidate,
                self._verdict("error.evaluation_exception"),
                exception=e,
                reconstruction_hint=reconstruction_hint,
            )

        match = accepted._handoff
        identity_entry = match.get("entry") or {}
        raw_identity = self._entry_value(identity_entry, "id")
        if reconstruction_hint.get("provider_item_id") in (None, ""):
            reconstruction_hint["provider_item_id"] = raw_identity or match.get("nzbid") or match.get("link")
        provider_stat = match.get("provider_stat") or {}
        reconstruction_hint["provider_type"] = provider_stat.get("type") or reconstruction_hint.get("provider_type")
        if provider_stat.get("id") is not None:
            reconstruction_hint["provider_config_id"] = provider_stat["id"]
        reason_code = "accepted.pack" if accepted.match_kind == "pack" else "accepted.issue"
        return ReleaseCandidateEvaluation(
            candidate,
            self._verdict(reason_code, match_kind=accepted.match_kind),
            _handoff=accepted._handoff,
            reconstruction_hint=reconstruction_hint,
        )

    def _match_entry(self, entry, is_info):
        if is_info:
            ComicName = is_info["ComicName"]
            # A manga volume pass searches "<series> v01", but the release
            # parses as the plain series name, so comparing against the query
            # would fail every result. Match against the real name instead.
            match_name = is_info.get("manga_match_name") or ComicName
            manga_volume_pass = bool(is_info.get("manga_match_name"))
            nzbprov = is_info["nzbprov"]
            RSS = is_info["RSS"]
            UseFuzzy = is_info["UseFuzzy"]
            StoreDate = is_info["StoreDate"]
            IssueDate = is_info["IssueDate"]
            digitaldate = is_info["digitaldate"]
            booktype = is_info["booktype"]
            ignore_booktype = is_info["ignore_booktype"]
            SeriesYear = is_info["SeriesYear"]
            ComicVersion = is_info["ComicVersion"]
            IssDateFix = is_info["IssDateFix"]
            ComicYear = comyear = is_info["ComicYear"]
            IssueID = is_info["IssueID"]
            ComicID = is_info["ComicID"]
            IssueNumber = is_info["IssueNumber"]
            manual = is_info["manual"]
            newznab_host = is_info["newznab_host"]
            torznab_host = is_info["torznab_host"]
            oneoff = is_info["oneoff"]
            tmpprov = is_info["tmpprov"]
            SARC = is_info["SARC"]
            IssueArcID = is_info["IssueArcID"]
            cmloopit = is_info["cmloopit"]
            findcomiciss = is_info["findcomiciss"]
            intIss = is_info["intIss"]
            chktpb = is_info["chktpb"]
            provider_stat = is_info["provider_stat"]
            allow_packs = is_info.get("allow_packs") in (1, "1", True)

        try:
            pack = entry["pack"]
        except Exception:
            pack = False
        detected_pack = None

        alt_match = False

        logger.fdebug("checking search result: %s" % entry["title"])
        except_list = [
            "releases",
            "gold line",
            "distribution",
            "0-day",
            "0 day",
        ]
        splitTitle = entry["title"].split('"')
        _digits = re.compile(r"\d")

        ComicTitle = entry["title"]
        for subs in splitTitle:
            logger.fdebug("sub: %s" % subs)
            try:
                if (
                    len(subs) >= len(ComicName)
                    and not any(d in subs.lower() for d in except_list)
                    and bool(_digits.search(subs)) is True
                ):
                    if subs.lower().startswith("for"):
                        if ComicName.lower().startswith("for"):
                            pass
                        else:
                            continue
                        logger.fdebug(
                            "Detected crap within header. Ignoring this portion"
                            " of the result in order to see if it's a valid"
                            " match."
                        )
                    ComicTitle = subs
                    break
            except Exception:
                break

        ignored = []
        for x in comicarr.CONFIG.IGNORE_SEARCH_WORDS:
            if x.lower() in ComicTitle.lower():
                ignored.append(x)

        if ignored:
            logger.fdebug(
                "[IGNORE_SEARCH_WORDS] %s exists within the search result (%s). Ignoring this result."
                % (ignored, ComicTitle)
            )
            self._reject("ignored.search_word")

        comsize_m = 0
        if nzbprov != "dognzb":
            if RSS == "yes":
                comsize_b = entry["length"]
            else:
                if nzbprov == "experimental":
                    comsize_b = entry["length"]
                else:
                    try:
                        if entry["site"] == "DDL(GetComics)":
                            comsize_b = entry["size"]
                            if comsize_b is not None:
                                cb2 = re.sub(r"[^0-9]", "", comsize_b).strip()
                                if cb2 == "":
                                    logger.warn("Invalid filesize encountered. Ignoring")
                                    comsize_b = None
                                else:
                                    comsize_b = helpers.human2bytes(entry["size"])
                        elif entry["site"] == "DDL(External)":
                            comsize_b = "0"
                    except Exception:
                        tmpsz = entry.enclosures[0]
                        comsize_b = tmpsz["length"]

            logger.fdebug("comsize_b: %s" % comsize_b)

            if comsize_b is None or comsize_b == "0":
                logger.fdebug("Size of file cannot be retrieved. Ignoring size-comparison and continuing.")
            else:
                if entry["title"][:17] != "0-Day Comics Pack":
                    comsize_m = helpers.human_size(comsize_b)
                    logger.fdebug("size given as: %s" % comsize_m)
                    if comicarr.CONFIG.USE_MINSIZE:
                        conv_minsize = helpers.human2bytes(comicarr.CONFIG.MINSIZE + "M")
                        logger.fdebug("comparing Min threshold %s .. to .. nzb %s" % (conv_minsize, comsize_b))
                        if int(conv_minsize) > int(comsize_b):
                            logger.fdebug("Failure to meet the Minimum size threshold - skipping")
                            self._reject("rejected.size_below_min")
                    if comicarr.CONFIG.USE_MAXSIZE:
                        conv_maxsize = helpers.human2bytes(comicarr.CONFIG.MAXSIZE + "M")
                        logger.fdebug("comparing Max threshold %s .. to .. nzb %s" % (conv_maxsize, comsize_b))
                        if int(comsize_b) > int(conv_maxsize):
                            logger.fdebug("Failure to meet the Maximium size threshold - skipping")
                            self._reject("rejected.size_above_max")

        if comicarr.CONFIG.IGNORE_COVERS is True:
            cvrchk = re.sub(r"[\s\s+\_\.]", "", entry["title"]).lower()
            if any(["coversonly" in cvrchk, "coveronly" in cvrchk]):
                logger.fdebug("Cover(s) only detected. Ignoring result.")
                self._reject("rejected.cover_only")

        if nzbprov == "experimental":
            pubdate = entry["pubdate"]
        else:
            try:
                pubdate = entry["updated"]
            except Exception:
                try:
                    pubdate = entry["pubdate"]
                except Exception as e:
                    logger.fdebug("Invalid date found. Unable to continue - skipping result. Error returned: %s" % e)
                    self._reject("invalid.pubdate_missing", cause=e)

        if UseFuzzy == "1" or manga_volume_pass:
            if manga_volume_pass:
                # The store-date comparison exists because a periodical's issue
                # NUMBER recycles across runs -- #6 of a 2016 run and #6 of a
                # 1998 one are both "6" -- so the street date is the tiebreak.
                # A volume number does not recycle, and manga_volume_satisfies()
                # below still has to match it, so here the date adds no
                # disambiguation and only subtracts: digital manga is routinely
                # posted BEFORE the street date ComicVine records (which for a
                # manga volume is often weeks late), and the gate then throws
                # away the one correct file. Observed: "One-Punch Man v06 (2015)
                # (Digital) (BlackManta-Empire)", posted 2016-04-13, rejected
                # against a store date of 2016-04-27.
                logger.fdebug(
                    "[MANGA] Volume pass - the volume number identifies the book,"
                    " ignoring store date comparison entirely."
                )
            else:
                logger.fdebug("Year has been fuzzied for this series, ignoring store date comparison entirely.")
            postdate_int = None
            issuedate_int = None
        else:
            if StoreDate is None or StoreDate == "0000-00-00":
                if IssueDate is None or IssueDate == "0000-00-00":
                    logger.fdebug(
                        "Invalid store date & issue date detected - you"
                        " probably should refresh the series or wait for CV"
                        " to correct the data"
                    )
                    self._reject("invalid.reference_date_missing")
                else:
                    stdate = IssueDate
                logger.fdebug("issue date used is : %s" % stdate)
            else:
                stdate = StoreDate
                logger.fdebug("store date used is : %s" % stdate)
            logger.fdebug("date used is : %s" % stdate)

            postdate_int = None
            if all(["DDL" in nzbprov, len(pubdate) == 10]):
                postdate_int = pubdate
                logger.fdebug("[%s] postdate_int (%s): %s" % (nzbprov, type(postdate_int), postdate_int))
            if any([postdate_int is None, type(postdate_int) != int]) or not RSS == "no":
                dateconv = email.utils.parsedate_tz(pubdate)

                try:
                    dateconv2 = datetime.datetime(*dateconv[:6])
                except TypeError as e:
                    logger.warn("Unable to convert timestamp from : %s [%s]" % ((dateconv,), e))
                try:
                    if dateconv[-1] is not None:
                        postdate_int = time.mktime(dateconv[: len(dateconv) - 1]) - dateconv[-1]
                    else:
                        postdate_int = time.mktime(dateconv[: len(dateconv) - 1])
                except Exception as e:
                    logger.warn(
                        "Unable to parse posting date from provider result set"
                        " for : %s. Error returned: %s" % (entry["title"], e)
                    )
                    self._reject("invalid.pubdate_unparseable", cause=e)

            if all([digitaldate != "0000-00-00", digitaldate is not None]):
                i = 0
            else:
                digitaldate_int = "00000000"
                i = 1

            while i <= 1:
                if i == 0:
                    usedate = digitaldate
                else:
                    usedate = stdate
                logger.fdebug("usedate: %s" % usedate)
                issue_converted = datetime.datetime.strptime(usedate.rstrip(), "%Y-%m-%d")
                issue_convert = issue_converted + datetime.timedelta(days=-1)
                try:
                    stamp = time.mktime(issue_convert.timetuple())
                    issconv = format_date_time(stamp)
                except OverflowError as e:
                    logger.fdebug("Error converting the timestamp into a generic format: %s" % e)
                    issconv = issue_convert.strftime("%a, %d %b %Y %H:%M:%S")
                econv = email.utils.parsedate_tz(issconv)
                econv2 = datetime.datetime(*econv[:6])
                try:
                    usedate_int = time.mktime(econv[: len(econv) - 1])
                except OverflowError:
                    logger.fdebug("Unable to convert timestamp to integer format. Forcing things through.")
                    isyear = econv[1]
                    epochyr = "1970"
                    if int(isyear) <= int(epochyr):
                        tm = datetime.datetime(1970, 1, 1)
                        try:
                            usedate_int = int(time.mktime(tm.timetuple()))
                        except Exception as e:
                            logger.warn("[%s] Failed to convert tm of [%s]" % (e, tm))
                            logger.fdebug("issconv: %s" % issconv)
                            diff = issue_convert - tm
                            logger.fdebug("diff: %s" % diff)
                            usedate_int = diff.total_seconds()
                    else:
                        continue
                if i == 0:
                    digitaldate_int = usedate_int
                    digconv2 = econv2
                else:
                    issuedate_int = usedate_int
                    issconv2 = econv2
                i += 1

            try:
                if digitaldate != "0000-00-00" and dateconv2.date() >= digconv2.date():
                    logger.fdebug("%s is after DIGITAL store date of %s" % (pubdate, digitaldate))
                elif dateconv2.date() < issconv2.date():
                    logger.fdebug("[CONV] pubdate: %s  < storedate: %s" % (dateconv2.date(), issconv2.date()))
                    logger.fdebug(
                        "%s is before store date of %s. Ignoring search result"
                        " as this is not the right issue." % (pubdate, stdate)
                    )
                    self._reject("rejected.before_reference_date")
                else:
                    logger.fdebug("[CONV] %s is after store date of %s" % (pubdate, stdate))
            except _EntryRejected:
                raise
            except Exception:
                if digitaldate is not None and all([digitaldate != "0000-00-00", postdate_int >= digitaldate_int]):
                    logger.fdebug("%s is after DIGITAL store date of %s" % (pubdate, digitaldate))
                elif postdate_int < issuedate_int:
                    logger.fdebug("[INT]pubdate: %s  < storedate: %s" % (postdate_int, issuedate_int))
                    logger.fdebug(
                        "%s is before store date of %s. Ignoring search result"
                        " as this is not the right issue." % (pubdate, stdate)
                    )
                    self._reject("rejected.before_reference_date")
                else:
                    logger.fdebug("[INT] %s is after store date of %s" % (pubdate, stdate))
        if "(digital first)" in ComicTitle.lower():
            dig_moving = re.sub(r"\(digital first\)", "", ComicTitle.lower()).strip()
            dig_moving = re.sub(r"[\s+]", " ", dig_moving)
            dig_mov_end = "%s (Digital First)" % dig_moving
            thisentry = dig_mov_end
        else:
            thisentry = ComicTitle

        logger.fdebug("Entry: %s" % thisentry)
        cleantitle = thisentry

        if "mixed format" in cleantitle.lower():
            cleantitle = re.sub("mixed format", "", cleantitle).strip()
            logger.fdebug("removed extra information after issue # that is not necessary: %s" % cleantitle)
        if pack is True and "DDL" in entry["site"]:
            logger.fdebug("parsing pack...")
            ffc = filechecker.FileChecker()
            dnr = ffc.dynamic_replace(entry["series"])
            parsed_comic = {
                "booktype": entry["gc_booktype"],
                "comicfilename": entry["filename"],
                "series_name": entry["series"],
                "series_name_decoded": entry["series"],
                "issueid": None,
                "dynamic_name": dnr["mod_seriesname"],
                "issues": entry["issues"],
                "series_volume": None,
                "alt_series": None,
                "alt_issue": None,
                "issue_year": entry["year"],
                "issue_number": None,
                "scangroup": None,
                "reading_order": None,
                "sub": None,
                "comiclocation": None,
                "parse_status": "success",
            }

        else:
            if pack is not True and allow_packs and "DDL" not in nzbprov:
                from comicarr.app.manga.acquisition import booktype_bypasses_format_gates as _manga_bypass
                from comicarr.app.search.packs import parse_pack_title, parse_series_pack_title

                detected_pack = parse_pack_title(ComicTitle)
                if detected_pack is not None and detected_pack["kind"] == "volume":
                    volume_ok = booktype in ("TPB", "HC", "GN", "TPB/GN/HC/One-Shot") or _manga_bypass(booktype)
                    if not volume_ok:
                        detected_pack = None
                if detected_pack is None and _manga_bypass(booktype):
                    detected_pack = parse_series_pack_title(ComicTitle)
            if detected_pack is not None:
                logger.fdebug(
                    "[PACK-DETECT] %s detected as a multi-%s release covering %s"
                    % (ComicTitle, detected_pack["kind"], detected_pack["issues"])
                )
                pack = True
                entry["pack"] = True
                entry["issues"] = detected_pack["issues"]
                entry["series"] = detected_pack["series"]
                entry["year"] = detected_pack["year"]
                if "filename" not in entry:
                    entry["filename"] = entry["title"]
                ffc = filechecker.FileChecker()
                dnr = ffc.dynamic_replace(detected_pack["series"])
                parsed_comic = {
                    "booktype": detected_pack["booktype"],
                    "comicfilename": entry["title"],
                    "series_name": detected_pack["series"],
                    "series_name_decoded": detected_pack["series"],
                    "issueid": None,
                    "dynamic_name": dnr["mod_seriesname"],
                    "issues": detected_pack["issues"],
                    "series_volume": None,
                    "alt_series": None,
                    "alt_issue": None,
                    "issue_year": detected_pack["year"],
                    "issue_number": None,
                    "scangroup": None,
                    "reading_order": None,
                    "sub": None,
                    "comiclocation": None,
                    "parse_status": "success",
                }
            else:
                p_comic = filechecker.FileChecker(file=ComicTitle, watchcomic=match_name)
                parsed_comic = p_comic.listFiles()

        logger.fdebug("parsed_info: %s" % parsed_comic)
        logger.fdebug(
            "booktype: %s / parsed_booktype: %s [ignore_booktype: %s]"
            % (booktype, parsed_comic["booktype"], ignore_booktype)
        )
        from comicarr.app.manga.acquisition import booktype_bypasses_format_gates

        manga_booktype = booktype_bypasses_format_gates(booktype) or booktype_bypasses_format_gates(
            parsed_comic.get("booktype")
        )
        if parsed_comic["parse_status"] == "success" and (
            all([booktype is None, parsed_comic["booktype"] == "issue"])
            or all([booktype == "Print", parsed_comic["booktype"] == "issue"])
            or all(
                [
                    booktype == "One-Shot",
                    any([parsed_comic["booktype"] == "issue", "One-Shot" in parsed_comic["booktype"]]),
                ]
            )
            or manga_booktype
            or all([booktype != parsed_comic["booktype"], ignore_booktype is True])
            or re.sub("None", "issue", str(booktype)) in parsed_comic["booktype"]
        ):
            try:
                fcomic = filechecker.FileChecker(watchcomic=match_name)
                filecomic = fcomic.matchIT(parsed_comic)
            except Exception as e:
                logger.error("[PARSE-ERROR]: %s" % e)
                self._reject("error.matcher_exception", cause=e)
            else:
                logger.fdebug("match_check: %s" % filecomic)
                if filecomic["process_status"] == "fail":
                    logger.fdebug("%s was not a match to %s (%s)" % (cleantitle, ComicName, SeriesYear))
                    self._reject("rejected.series_mismatch")
                elif filecomic["process_status"] == "alt_match":
                    logger.fdebug(
                        "%s was a match due to alternate matching.  Continuing"
                        " to search, but retaining this result just in case." % ComicTitle
                    )
                    alt_match = True
        elif booktype != parsed_comic["booktype"] and ignore_booktype is False:
            logger.fdebug(
                "Booktypes do not match. Looking for %s, this is a %s."
                " Ignoring this result." % (booktype, parsed_comic["booktype"])
            )
            self._reject("rejected.book_type")
        else:
            logger.fdebug("Unable to parse name properly: %s. Ignoring this result" % parsed_comic)
            self._reject("rejected.unparseable_title")

        vers4year = "no"
        vers4vol = "no"
        versionfound = "no"

        if ComicVersion:
            ComVersChk = re.sub("[^0-9]", "", ComicVersion)
            if ComVersChk == "" or ComVersChk == "1":
                ComVersChk = 0
        else:
            ComVersChk = 0

        fndcomicversion = None

        if parsed_comic["series_volume"] is not None:
            versionfound = "yes"
            if len(parsed_comic["series_volume"][1:]) == 4 and (parsed_comic["series_volume"][1:].isdigit()):
                logger.fdebug("[Vxxxx] Version detected as %s" % (parsed_comic["series_volume"]))
                vers4year = "yes"
                fndcomicversion = parsed_comic["series_volume"]
            elif len(parsed_comic["series_volume"][1:]) == 1 and (parsed_comic["series_volume"][1:].isdigit()):
                logger.fdebug("[Vx] Version detected as %s" % parsed_comic["series_volume"])
                vers4vol = parsed_comic["series_volume"]
                fndcomicversion = parsed_comic["series_volume"]
            # Digits AFTER the v, matching the two arms above. Measuring the
            # whole string here made `v100` 4 characters, so it failed `< 4`
            # although its 3 digits are plainly a volume and not a year. It
            # then matched no arm at all, left fndcomicversion None and lost
            # the year bypass -- One Piece v100, labelled 2021 against a 1997
            # series year, was rejected for it. Four digits after the v is
            # still a year, and is still claimed by the [Vxxxx] arm above.
            elif parsed_comic["series_volume"][1:].isdigit() and len(parsed_comic["series_volume"][1:]) < 4:
                logger.fdebug("[Vxxx] Version detected as %s" % parsed_comic["series_volume"])
                vers4vol = parsed_comic["series_volume"]
                fndcomicversion = parsed_comic["series_volume"]
            elif parsed_comic["series_volume"].isdigit() and len(parsed_comic["series_volume"]) <= 4:
                if len(parsed_comic["series_volume"]) == 4:
                    vers4year = "yes"
                    fndcomicversion = parsed_comic["series_volume"]
                elif len(parsed_comic["series_volume"]) == 1:
                    vers4vol = parsed_comic["series_volume"]
                    fndcomicversion = parsed_comic["series_volume"]
                elif len(parsed_comic["series_volume"]) < 4:
                    vers4vol = parsed_comic["series_volume"]
                    fndcomicversion = parsed_comic["series_volume"]
                else:
                    logger.fdebug("error - unknown length for : %s" % parsed_comic["series_volume"])

        yearmatch = False
        if vers4vol != "no" or vers4year != "no":
            logger.fdebug(
                "Series Year not provided but Series Volume detected of %s. Bypassing Year Match." % fndcomicversion
            )
            yearmatch = True
        elif ComVersChk == 0 and parsed_comic["issue_year"] is None:
            logger.fdebug(
                "Series version detected as V1 (only series in existance with that title). Bypassing Year/Volume check"
            )
            yearmatch = True
        elif (
            any(
                [
                    UseFuzzy == "0",
                    UseFuzzy == "2",
                    UseFuzzy is None,
                    IssDateFix != "no",
                ]
            )
            and parsed_comic["issue_year"] is not None
        ):
            if any(
                [
                    parsed_comic["issue_year"][:-2] == "19",
                    parsed_comic["issue_year"][:-2] == "20",
                ]
            ):
                if str(comyear) == parsed_comic["issue_year"]:
                    logger.fdebug("%s - right years match baby!" % comyear)
                    yearmatch = True
                else:
                    logger.fdebug("%s - not right - years do not match" % comyear)
                    yearmatch = False
                    if UseFuzzy == "2":
                        ComUp = int(ComicYear) + 1
                        ComDwn = int(ComicYear) - 1
                        if str(ComUp) in parsed_comic["issue_year"] or str(ComDwn) in parsed_comic["issue_year"]:
                            logger.fdebug(
                                "Fuzzy Logicd the Year and matched to a year of %s" % parsed_comic["issue_year"]
                            )
                            yearmatch = True
                        else:
                            logger.fdebug("%s Fuzzy logicd the Year and year still did not match." % comyear)
                    if IssDateFix != "no" and UseFuzzy != "2":
                        if IssDateFix == "01" or IssDateFix == "02" or IssDateFix == "03":
                            ComicYearFix = int(ComicYear) - 1
                            if str(ComicYearFix) in parsed_comic["issue_year"]:
                                logger.fdebug(
                                    "Further analysis reveals this was"
                                    " published inbetween Nov-Jan, decreasing"
                                    " year to %s has resulted in a match!" % ComicYearFix
                                )
                                yearmatch = True
                            else:
                                logger.fdebug("%s- not the right year." % comyear)
                        else:
                            ComicYearFix = int(ComicYear) + 1
                            if str(ComicYearFix) in parsed_comic["issue_year"]:
                                logger.fdebug(
                                    "Further analysis reveals this was"
                                    " published inbetween Nov-Jan, incrementing"
                                    " year to %s has resulted in a match!" % ComicYearFix
                                )
                                yearmatch = True
                            else:
                                logger.fdebug("%s - not the right year." % comyear)
        elif UseFuzzy == "1":
            yearmatch = True

        if yearmatch is False and pack is False:
            self._reject("rejected.year_mismatch")

        annualize = False
        if "annual" in ComicName.lower():
            logger.fdebug("IssueID of : %s This is an annual...let's adjust." % IssueID)
            annualize = True

        D_ComicVersion = 1
        F_ComicVersion = None

        if versionfound == "yes" or annualize is True:
            logger.fdebug("volume detection commencing - adjusting length.")
            logger.fdebug("watch comicversion is %s" % ComicVersion)
            logger.fdebug("version found: %s" % fndcomicversion)
            logger.fdebug("vers4year: %s" % vers4year)
            logger.fdebug("vers4vol: %s" % vers4vol)

            if vers4year != "no" or vers4vol != "no":
                if ComVersChk == 0:
                    D_ComicVersion = 1
                else:
                    D_ComicVersion = ComVersChk

            S_ComicVersion = 0
            if all([SeriesYear is not None, annualize is False]):
                S_ComicVersion = str(SeriesYear)

            if fndcomicversion:
                F_ComicVersion = re.sub("[^0-9]", "", fndcomicversion)
                if F_ComicVersion == "0":
                    if annualize is True:
                        F_ComicVersion = parsed_comic["issue_year"]
                    else:
                        F_ComicVersion = "1"
            else:
                F_ComicVersion = "1"

            logger.fdebug("FCVersion: %s" % F_ComicVersion)
            logger.fdebug("DCVersion: %s" % D_ComicVersion)
            logger.fdebug("SCVersion: %s" % S_ComicVersion)
            logger.fdebug("ComicYear: %s" % ComicYear)

            # fndcomicversion or the parsed volume: the version arms above only
            # recognise an all-digit vNN, so a FRACTIONAL volume leaves
            # fndcomicversion None even though FileChecker parsed `v01.5`
            # perfectly well. The comparison then failed and the half volume
            # this branch exists to accept was rejected before the post-gate
            # fallback could run.
            parsed_volume = fndcomicversion or parsed_comic.get("series_volume")
            if manga_volume_pass and manga_volume_satisfies(parsed_volume, findcomiciss):
                # "vNN" means different things in the two formats. In a comic
                # release it is which RUN of the series this is (Amazing
                # Spider-Man v2), which is why the arms below compare it to the
                # series' ComicVersion or year. In manga it is which BOOK --
                # volume 30 of one continuous series -- so the only meaningful
                # comparison is against the volume being searched for.
                #
                # Without this, a manga volume matches only when the series'
                # ComicVersion happens to equal the volume number, i.e. volume 1
                # of a v1 series, and every later volume is discarded with
                # "Versions wrong" despite being the exact release requested.
                logger.fdebug("[MANGA] volume %s matches the volume searched for" % fndcomicversion)
            elif all(
                [
                    annualize is True,
                    parsed_comic["issue_number"] is not None,
                ]
            ) and any(
                [
                    int(ComicYear) == int(F_ComicVersion),
                    int(ComicYear) == int(parsed_comic["issue_number"]),
                ]
            ):
                logger.fdebug(
                    "We matched on versions for annuals %s (%s = %s = %s)"
                    % (ComicYear, fndcomicversion, F_ComicVersion, parsed_comic["issue_number"])
                )
            elif all(
                [
                    booktype != "TPB",
                    booktype != "HC",
                    booktype != "GN",
                    booktype != "TPB/GN/HC/One-Shot",
                ]
            ) and (int(F_ComicVersion) == int(D_ComicVersion) or int(F_ComicVersion) == int(S_ComicVersion)):
                logger.fdebug("We matched on versions...%s" % fndcomicversion)
            else:
                if any(
                    [
                        booktype == "TPB",
                        booktype == "HC",
                        booktype == "GN",
                        booktype == "TPB/GN/HC/One-Shot",
                    ]
                ) and any(
                    [
                        all([int(F_ComicVersion) == int(findcomiciss) and filecomic["justthedigits"] is None]),
                        all([int(F_ComicVersion) == int(findcomiciss) and ComicYear == parsed_comic["issue_year"]]),
                    ]
                ):
                    logger.fdebug(
                        "%s detected - reassigning volume %s to match as the"
                        " issue number based on Volume" % (booktype, fndcomicversion)
                    )
                elif all(
                    [
                        booktype == "TPB",
                        booktype == "HC",
                        booktype == "GN",
                        booktype == "TPB/GN/HC/One-Shot",
                    ]
                ) and all(
                    [
                        int(F_ComicVersion) == int(findcomiciss),
                        fndcomicversion is not None,
                        booktype in filecomic["booktype"],
                        filecomic["justthedigits"] is None,
                    ]
                ):
                    logger.fdebug(
                        "%s detected - reassigning volume %s to match as the issue number" % (booktype, fndcomicversion)
                    )
                else:
                    logger.fdebug("Versions wrong. Ignoring possible match.")
                    self._reject("rejected.volume_mismatch")

        downloadit = False

        if pack is True and any(["DDL" in nzbprov, detected_pack is not None]):
            logger.fdebug("[PACK-QUEUE] %s Pack detected for %s." % (nzbprov, entry["filename"]))

            pack_issuelist = None
            issueid_info = None
            try:
                if not entry["title"].startswith("0-Day Comics Pack"):
                    pack_issuelist = entry["issues"]
                    pack_kind = detected_pack["kind"] if detected_pack is not None else "issue"
                    pack_ref = entry["id"] if "id" in entry else entry["link"]
                    issueid_info = _pack_membership.issue_find_ids(
                        ComicName,
                        ComicID,
                        pack_issuelist,
                        IssueNumber,
                        pack_ref,
                        kind=pack_kind,
                        span_end=(detected_pack or {}).get("year_end"),
                    )
                    if issueid_info["valid"] is True:
                        logger.info("Issue Number %s exists within pack. Continuing." % IssueNumber)
                    else:
                        logger.fdebug("Issue Number %s does NOT exist within this pack. Skipping" % IssueNumber)
                        self._reject("rejected.pack_issue_absent")
            except _EntryRejected:
                raise
            except Exception as e:
                logger.error("Unable to identify pack range for %s. Error returned: %s" % (entry["title"], e))
                self._reject("error.pack_lookup_exception", cause=e)
            nowrite = False
            if "DDL" in nzbprov:
                if "GetComics" in nzbprov and RSS == "yes":
                    entry["id"] = entry["link"]
                    entry["link"] = "https://getcomics.info/?p=" + str(entry["id"])
                    entry["filename"] = entry["title"]
                nzbid = entry["id"]
            else:
                nzbid = generate_id(provider_stat, entry["link"], ComicName)
            if all([manual is not True, alt_match is False]):
                downloadit = True
            else:
                for x in self._accepted:
                    if (
                        all(
                            [
                                x["link"] == entry["link"],
                                x["tmpprov"] == tmpprov,
                            ]
                        )
                        or all([x["nzbid"] == nzbid, x["newznab"] == newznab_host])
                        or all([x["nzbid"] == nzbid, x["torznab"] == torznab_host])
                    ):
                        nowrite = True
                        break

            if nowrite is False:
                if any(
                    [
                        nzbprov == "experimental",
                        "newznab" in nzbprov,
                    ]
                ):
                    tprov = nzbprov
                    kind = "usenet"
                    if newznab_host is not None:
                        tprov = newznab_host[0]
                else:
                    tprov = nzbprov
                    kind = "torrent"
                    if torznab_host is not None:
                        tprov = torznab_host[0]

                return _AcceptedMatch(
                    {
                        "ComicName": ComicName,
                        "ComicID": ComicID,
                        "IssueID": IssueID,
                        "ComicVolume": ComicVersion,
                        "IssueNumber": IssueNumber,
                        "IssueDate": IssueDate,
                        "comyear": comyear,
                        "pack": True,
                        "pack_numbers": pack_issuelist,
                        "pack_issuelist": issueid_info,
                        "modcomicname": entry["title"],
                        "oneoff": oneoff,
                        "nzbprov": nzbprov,
                        "nzbtitle": entry["title"],
                        "nzbid": nzbid,
                        "provider": tprov,
                        "link": entry["link"],
                        "pubdate": pubdate,
                        "size": comsize_m,
                        "tmpprov": tmpprov,
                        "kind": kind,
                        "SARC": SARC,
                        "booktype": booktype,
                        "IssueArcID": IssueArcID,
                        "newznab": newznab_host,
                        "torznab": torznab_host,
                        "downloadit": downloadit,
                        "ComicTitle": ComicTitle,
                        "entry": entry,
                        "provider_stat": provider_stat,
                    },
                    "pack",
                )
            self._reject("blocked.duplicate")
        else:
            if filecomic["process_status"] == "match":
                if cmloopit != 4:
                    logger.fdebug("issue we are looking for is : %s" % findcomiciss)
                    logger.fdebug("integer value of issue we are looking for : %s" % intIss)
                else:
                    if intIss is None and all(
                        [
                            booktype == "One-Shot",
                            helpers.issuedigits(parsed_comic["issue_number"]) == 1000,
                        ]
                    ):
                        intIss = 1000
                    else:
                        if annualize is True:
                            if parsed_comic["issue_number"] is None:
                                intIss = 1000
                            elif len(re.sub("[^0-9]", "", parsed_comic["issue_number"]).strip()) == 4:
                                intIss = 1000
                            elif parsed_comic["issue_number"] is not None:
                                intIss = helpers.issuedigits(parsed_comic["issue_number"])
                        else:
                            intIss = 9999999999
                if filecomic["justthedigits"] is not None:
                    logger.fdebug("issue we found for is : %s" % filecomic["justthedigits"])
                    if annualize is True and len(re.sub("[^0-9]", "", filecomic["justthedigits"]).strip()) == 4:
                        comintIss = 1000
                    else:
                        comintIss = helpers.issuedigits(filecomic["justthedigits"])
                    logger.fdebug("integer value of issue we have found : %s" % comintIss)
                else:
                    comintIss = 11111111111

                if filecomic["justthedigits"] is None:
                    pc_in = None
                else:
                    pc_in = helpers.issuedigits(filecomic["justthedigits"])
                if (
                    all([intIss is not None, comintIss is not None])
                    and int(intIss) == int(comintIss)
                    or (
                        any(
                            [
                                filecomic["booktype"] == "TPB",
                                filecomic["booktype"] == "GN",
                                filecomic["booktype"] == "HC",
                                filecomic["booktype"] == "TPB/GN/HC/One-Shot",
                            ]
                        )
                        and all(
                            [
                                chktpb != 0,
                                pc_in is None,
                                helpers.issuedigits(F_ComicVersion) == intIss,
                            ]
                        )
                    )
                    or (
                        any(
                            [
                                filecomic["booktype"] == "TPB",
                                filecomic["booktype"] == "GN",
                                filecomic["booktype"] == "HC",
                                filecomic["booktype"] == "TPB/GN/HC/One-Shot",
                            ]
                        )
                        and all(
                            [
                                chktpb == 2,
                                pc_in is None,
                                cmloopit == 1,
                            ]
                        )
                    )
                    or all([cmloopit == 4, findcomiciss is None, pc_in is None])
                    or all([cmloopit == 4, findcomiciss is None, pc_in == 1])
                    or all([cmloopit == 4, findcomiciss == 1, pc_in is None])
                    or all(
                        [
                            manga_volume_pass,
                            pc_in is None,
                            manga_volume_satisfies(
                                filecomic.get("volume") or filecomic.get("series_volume"),
                                findcomiciss,
                            ),
                        ]
                    )
                ):
                    nowrite = False
                    logger.info(
                        "[nzbprov:%s] provider_stat: %s"
                        % (
                            nzbprov,
                            provider_stat,
                        )
                    )
                    if nzbprov == "torznab" or provider_stat["type"] == "torznab":
                        nzbid = generate_id(provider_stat, entry["id"], ComicName)
                    elif "DDL" in nzbprov:
                        if "GetComics" in nzbprov:
                            if RSS == "yes":
                                entry["id"] = entry["link"]
                                entry["link"] = "https://getcomics.info/?p=" + str(entry["id"])
                                entry["filename"] = entry["title"]
                            else:
                                nzbid = entry["id"]
                            if "/cat/" in entry["link"]:
                                entry["link"] = "https://getcomics.info/?p=%s" % entry["id"]
                        entry["title"] = entry["filename"]
                        nzbid = entry["id"]
                    else:
                        try:
                            logger.fdebug("title_id: %s" % (entry["id"],))
                            if "details" in entry["id"]:
                                nzbid = generate_id(provider_stat, entry["id"], ComicName)
                            else:
                                nzbid = generate_id(provider_stat, entry["link"], ComicName)
                        except Exception:
                            nzbid = generate_id(provider_stat, entry["link"], ComicName)
                    if all([manual is not True, alt_match is False]):
                        downloadit = True
                    else:
                        for x in self._accepted:
                            if (
                                all(
                                    [
                                        x["link"] == entry["link"],
                                        x["tmpprov"] == tmpprov,
                                    ]
                                )
                                or all(
                                    [
                                        x["nzbid"] == nzbid,
                                        x["newznab"] == newznab_host,
                                    ]
                                )
                                or all(
                                    [
                                        x["nzbid"] == nzbid,
                                        x["torznab"] == torznab_host,
                                    ]
                                )
                            ):
                                nowrite = True
                                break

                    if annualize is True:
                        modcomicname = "%s Annual" % ComicName
                    else:
                        modcomicname = ComicName

                    if IssueID is None:
                        cyear = ComicYear
                    else:
                        cyear = comyear

                    if nowrite is False:
                        if any(
                            [
                                nzbprov == "experimental",
                                "newznab" in nzbprov,
                                provider_stat["type"] == "newznab",
                            ]
                        ):
                            tprov = nzbprov
                            kind = "usenet"
                            if newznab_host is not None:
                                tprov = newznab_host[0]
                        else:
                            kind = "torrent"
                            tprov = nzbprov
                            if torznab_host is not None:
                                tprov = torznab_host[0]

                        return _AcceptedMatch(
                            {
                                "ComicName": ComicName,
                                "ComicID": ComicID,
                                "IssueID": IssueID,
                                "ComicVolume": ComicVersion,
                                "IssueNumber": IssueNumber,
                                "IssueDate": IssueDate,
                                "comyear": cyear,
                                "pack": False,
                                "pack_numbers": None,
                                "pack_issuelist": None,
                                "modcomicname": modcomicname,
                                "oneoff": oneoff,
                                "nzbprov": nzbprov,
                                "provider": tprov,
                                "nzbtitle": entry["title"],
                                "nzbid": nzbid,
                                "link": entry["link"],
                                "pubdate": pubdate,
                                "size": comsize_m,
                                "tmpprov": tmpprov,
                                "kind": kind,
                                "booktype": booktype,
                                "SARC": SARC,
                                "IssueArcID": IssueArcID,
                                "newznab": newznab_host,
                                "torznab": torznab_host,
                                "downloadit": downloadit,
                                "ComicTitle": ComicTitle,
                                "entry": entry,
                                "provider_stat": provider_stat,
                            },
                            "standard",
                        )
                    self._reject("blocked.duplicate")
                else:
                    downloadit = False
        if alt_match:
            self._reject("rejected.alternate_series")
        self._reject("rejected.issue_mismatch")
