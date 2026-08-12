#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""
SQLAlchemy Core table definitions for Comicarr.

Purely declarative — table definitions, indexes, and constraints only.
No functions, no logic, no imports beyond SQLAlchemy.

Column types mapped from SQLite:
  TEXT        -> Text
  INTEGER/INT -> Integer
  REAL        -> Float
  NUMERIC     -> Numeric
  CLOB        -> Text
  VARCHAR(n)  -> String(n)

Design decisions:
  - No FOREIGN KEY constraints (orphaned records may exist in production)
  - Integer used for flag columns (ForceContinuing, IgnoreType, etc.)
  - UNIQUE constraints added for tables receiving upserts
  - SQLite COLLATE NOCASE handled via column-level collation
"""

from sqlalchemy import (
    Column,
    Float,
    Index,
    Integer,
    MetaData,
    Numeric,
    String,
    Table,
    Text,
    UniqueConstraint,
)

metadata = MetaData()

# MySQL cannot index TEXT values without a prefix length. Keep the unbounded
# storage used by SQLite/PostgreSQL while compiling schema keys to a bounded
# VARCHAR on MySQL so uniqueness and index semantics remain portable.
MYSQL_KEY_TEXT = Text().with_variant(String(255), "mysql")

# ---------------------------------------------------------------------------
# comics
# ---------------------------------------------------------------------------
comics = Table(
    "comics",
    metadata,
    Column("ComicID", MYSQL_KEY_TEXT, unique=True),
    Column("ComicName", Text),
    Column("ComicSortName", Text),
    Column("ComicYear", Text),
    Column("DateAdded", Text),
    Column("Status", MYSQL_KEY_TEXT),
    Column("IncludeExtras", Integer),
    Column("Have", Integer),
    Column("Total", Integer),
    Column("ComicImage", Text),
    Column("FirstImageSize", Integer),
    Column("ComicPublisher", Text),
    Column("PublisherImprint", Text),
    Column("ComicLocation", Text),
    Column("ComicPublished", Text),
    Column("NewPublish", Text),
    Column("LatestIssue", Text),
    Column("intLatestIssue", Integer),
    Column("LatestDate", Text),
    Column("Description", Text),
    Column("DescriptionEdit", Text),
    Column("QUALalt_vers", Text),
    Column("QUALtype", Text),
    Column("QUALscanner", Text),
    Column("QUALquality", Text),
    Column("LastUpdated", Text),
    Column("AlternateSearch", Text),
    Column("UseFuzzy", Text),
    Column("ComicVersion", Text),
    Column("SortOrder", Integer),
    Column("DetailURL", Text),
    Column("ForceContinuing", Integer),
    Column("ComicName_Filesafe", Text),
    Column("AlternateFileName", Text),
    Column("ComicImageURL", Text),
    Column("ComicImageALTURL", Text),
    Column("DynamicComicName", Text),
    Column("AllowPacks", Text),
    Column("Type", Text),
    Column("Corrected_SeriesYear", Text),
    Column("Corrected_Type", Text),
    Column("TorrentID_32P", Text),
    Column("LatestIssueID", Text),
    Column("Collects", Text),  # was CLOB
    Column("IgnoreType", Integer),
    Column("AgeRating", Text),
    Column("FilesUpdated", Text),
    Column("seriesjsonPresent", Integer),
    Column("dirlocked", Integer),
    Column("cv_removed", Integer),
    Column("not_updated_db", Text),
    # MySQL does not permit defaults on TEXT columns; these bounded enum-like
    # values need portable server defaults for the baseline migration.
    Column("ContentType", String(16), server_default="comic"),
    Column("ReadingDirection", String(16), server_default="ltr"),
    Column("MetadataSource", Text),
    Column("ExternalID", Text),
    Column("MangaDexID", Text),
    Column("MalID", Text),
)

# ---------------------------------------------------------------------------
# issues
# ---------------------------------------------------------------------------
issues = Table(
    "issues",
    metadata,
    Column("IssueID", MYSQL_KEY_TEXT),
    Column("ComicName", MYSQL_KEY_TEXT),
    Column("IssueName", Text),
    Column("Issue_Number", Text),
    Column("DateAdded", Text),
    Column("Status", MYSQL_KEY_TEXT),
    # Nullable by design. A NULL value means no auditable explicit intent is
    # known; compatibility reads derive policy intent without mutating rows.
    Column("AcquisitionIntent", String(16)),
    Column("Type", Text),
    Column("ComicID", MYSQL_KEY_TEXT),
    Column("ArtworkURL", Text),
    Column("ReleaseDate", Text),
    Column("Location", Text),
    Column("IssueDate", Text),
    Column("DigitalDate", Text),
    Column("Int_IssueNumber", Integer),
    Column("ComicSize", Text),
    Column("AltIssueNumber", Text),
    Column("IssueDate_Edit", Text),
    Column("ImageURL", Text),
    Column("ImageURL_ALT", Text),
    Column("forced_file", Integer),
    Column("inCacheDIR", Text),
    Column("ChapterNumber", Text),
    Column("VolumeNumber", Text),
    UniqueConstraint("IssueID", name="uq_issues_issueid"),
)

# ---------------------------------------------------------------------------
# annuals
# ---------------------------------------------------------------------------
annuals = Table(
    "annuals",
    metadata,
    Column("IssueID", MYSQL_KEY_TEXT),
    Column("Issue_Number", Text),
    Column("IssueName", Text),
    Column("IssueDate", Text),
    Column("Status", Text),
    Column("AcquisitionIntent", String(16)),
    Column("ComicID", MYSQL_KEY_TEXT),
    Column("GCDComicID", Text),
    Column("Location", Text),
    Column("ComicSize", Text),
    Column("Int_IssueNumber", Integer),
    Column("ComicName", Text),
    Column("ReleaseDate", Text),
    Column("DigitalDate", Text),
    Column("ReleaseComicID", Text),
    Column("ReleaseComicName", Text),
    Column("IssueDate_Edit", Text),
    Column("DateAdded", Text),
    Column("Deleted", Integer, server_default="0"),
    UniqueConstraint("IssueID", name="uq_annuals_issueid"),
)

# ---------------------------------------------------------------------------
# snatched
# ---------------------------------------------------------------------------
snatched = Table(
    "snatched",
    metadata,
    Column("IssueID", MYSQL_KEY_TEXT),
    Column("ComicName", Text),
    Column("Issue_Number", Text),
    Column("Size", Integer),
    Column("DateAdded", Text),
    Column("Status", MYSQL_KEY_TEXT),
    Column("FolderName", Text),
    Column("ComicID", MYSQL_KEY_TEXT),
    Column("Provider", MYSQL_KEY_TEXT),
    Column("Hash", Text),
    Column("crc", Text),
    UniqueConstraint("IssueID", "Status", "Provider", name="uq_snatched_issue_status_provider"),
)

# ---------------------------------------------------------------------------
# storyarcs
# ---------------------------------------------------------------------------
storyarcs = Table(
    "storyarcs",
    metadata,
    Column("StoryArcID", MYSQL_KEY_TEXT),
    Column("ComicName", MYSQL_KEY_TEXT),
    Column("IssueNumber", Text),
    Column("SeriesYear", Text),
    Column("IssueYEAR", Text),
    Column("StoryArc", MYSQL_KEY_TEXT),
    Column("TotalIssues", Text),
    Column("Status", MYSQL_KEY_TEXT),
    Column("inCacheDir", Text),
    Column("Location", Text),
    Column("IssueArcID", MYSQL_KEY_TEXT),
    Column("ReadingOrder", Integer),
    Column("IssueID", Text),
    Column("ComicID", MYSQL_KEY_TEXT),
    Column("ReleaseDate", Text),
    Column("IssueDate", Text),
    Column("Publisher", Text),
    Column("IssuePublisher", Text),
    Column("IssueName", Text),
    Column("CV_ArcID", MYSQL_KEY_TEXT),
    Column("Int_IssueNumber", Integer),
    Column("DynamicComicName", Text),
    Column("Volume", Text),
    Column("Manual", Text),
    Column("DateAdded", Text),
    Column("DigitalDate", Text),
    Column("Type", Text),
    Column("Aliases", Text),
    Column("ArcImage", Text),
    Column("StoreDate", Text),
    UniqueConstraint("IssueArcID", name="uq_storyarcs_issuearcid"),
)

# ---------------------------------------------------------------------------
# upcoming
# ---------------------------------------------------------------------------
upcoming = Table(
    "upcoming",
    metadata,
    Column("ComicName", Text),
    Column("IssueNumber", MYSQL_KEY_TEXT),
    Column("ComicID", MYSQL_KEY_TEXT),
    Column("IssueID", MYSQL_KEY_TEXT),
    Column("IssueDate", MYSQL_KEY_TEXT),
    Column("Status", Text),
    Column("DisplayComicName", Text),
    UniqueConstraint("ComicID", "IssueNumber", name="uq_upcoming_comicid_issuenum"),
)

# ---------------------------------------------------------------------------
# nzblog
# ---------------------------------------------------------------------------
nzblog = Table(
    "nzblog",
    metadata,
    Column("IssueID", MYSQL_KEY_TEXT),
    Column("NZBName", Text),
    Column("SARC", Text),
    Column("PROVIDER", MYSQL_KEY_TEXT),
    Column("ID", Text),
    Column("AltNZBName", Text),
    Column("OneOff", Text),
    UniqueConstraint("IssueID", "PROVIDER", name="uq_nzblog_issueid_provider"),
)

# ---------------------------------------------------------------------------
# weekly
# ---------------------------------------------------------------------------
weekly = Table(
    "weekly",
    metadata,
    Column("SHIPDATE", Text),
    Column("PUBLISHER", Text),
    Column("ISSUE", Text),
    Column("COMIC", String(150)),
    Column("EXTRA", Text),
    Column("STATUS", Text),
    Column("ComicID", MYSQL_KEY_TEXT),
    Column("IssueID", MYSQL_KEY_TEXT),
    Column("CV_Last_Update", Text),
    Column("DynamicName", Text),
    Column("weeknumber", Text),
    Column("year", Text),
    Column("volume", Text),
    Column("seriesyear", Text),
    Column("annuallink", Text),
    Column("format", Text),
    Column("rowid", Integer, primary_key=True, autoincrement=True),
    UniqueConstraint("ComicID", "IssueID", name="uq_weekly_comicid_issueid"),
)

# ---------------------------------------------------------------------------
# importresults
# ---------------------------------------------------------------------------
importresults = Table(
    "importresults",
    metadata,
    Column("impID", MYSQL_KEY_TEXT),
    Column("ComicName", Text),
    Column("ComicYear", Text),
    Column("Status", Text),
    Column("ImportDate", Text),
    Column("ComicFilename", Text),
    Column("ComicLocation", Text),
    Column("WatchMatch", Text),
    Column("DisplayName", Text),
    Column("SRID", Text),
    Column("ComicID", Text),
    Column("IssueID", MYSQL_KEY_TEXT),
    Column("Volume", Text),
    Column("IssueNumber", Text),
    Column("DynamicName", Text),
    Column("IssueCount", Text),
    Column("implog", Text),
    Column("MatchConfidence", Integer),
    Column("SuggestedComicID", Text),
    Column("SuggestedComicName", Text),
    Column("SuggestedIssueID", Text),
    Column("IgnoreFile", Integer, server_default="0"),
    Column("MatchSource", Text),
    UniqueConstraint("impID", name="uq_importresults_impid"),
)

# ---------------------------------------------------------------------------
# readlist
# ---------------------------------------------------------------------------
readlist = Table(
    "readlist",
    metadata,
    Column("IssueID", MYSQL_KEY_TEXT),
    Column("ComicName", Text),
    Column("Issue_Number", Text),
    Column("Status", Text),
    Column("DateAdded", Text),
    Column("Location", Text),
    Column("inCacheDir", Text),
    Column("SeriesYear", Text),
    Column("ComicID", Text),
    Column("StatusChange", Text),
    Column("IssueDate", Text),
    UniqueConstraint("IssueID", name="uq_readlist_issueid"),
)

# ---------------------------------------------------------------------------
# failed
# ---------------------------------------------------------------------------
failed = Table(
    "failed",
    metadata,
    Column("ID", MYSQL_KEY_TEXT),
    Column("Status", Text),
    Column("ComicID", Text),
    Column("IssueID", MYSQL_KEY_TEXT),
    Column("Provider", MYSQL_KEY_TEXT),
    Column("ComicName", Text),
    Column("Issue_Number", Text),
    Column("NZBName", MYSQL_KEY_TEXT),
    Column("DateFailed", Text),
    UniqueConstraint("ID", "Provider", "NZBName", name="uq_failed_id_provider_nzbname"),
)

# ---------------------------------------------------------------------------
# rssdb
# ---------------------------------------------------------------------------
rssdb = Table(
    "rssdb",
    metadata,
    Column("Title", MYSQL_KEY_TEXT, unique=True),
    Column("Link", Text),
    Column("Pubdate", Text),
    Column("Site", Text),
    Column("Size", Text),
    Column("Issue_Number", Text),
    Column("ComicName", Text),
)

# ---------------------------------------------------------------------------
# futureupcoming
# ---------------------------------------------------------------------------
futureupcoming = Table(
    "futureupcoming",
    metadata,
    Column("ComicName", Text),
    Column("IssueNumber", Text),
    Column("ComicID", Text),
    Column("IssueID", Text),
    Column("IssueDate", Text),
    Column("Publisher", Text),
    Column("Status", Text),
    Column("DisplayComicName", Text),
    Column("weeknumber", Text),
    Column("year", Text),
)

# ---------------------------------------------------------------------------
# searchresults
# ---------------------------------------------------------------------------
searchresults = Table(
    "searchresults",
    metadata,
    Column("SRID", Text),
    Column("results", Numeric),
    Column("Series", Text),
    Column("publisher", Text),
    Column("haveit", Text),
    Column("name", Text),
    Column("deck", Text),
    Column("url", Text),
    Column("description", Text),
    Column("comicid", Text),
    Column("comicimage", Text),
    Column("issues", Text),
    Column("comicyear", Text),
    Column("ogcname", Text),
    Column("sresults", Text),
)

# ---------------------------------------------------------------------------
# ref32p
# ---------------------------------------------------------------------------
ref32p = Table(
    "ref32p",
    metadata,
    Column("ComicID", MYSQL_KEY_TEXT, unique=True),
    Column("ID", Text),
    Column("Series", Text),
    Column("Updated", Text),
)

# ---------------------------------------------------------------------------
# oneoffhistory
# ---------------------------------------------------------------------------
oneoffhistory = Table(
    "oneoffhistory",
    metadata,
    Column("ComicName", Text),
    Column("IssueNumber", Text),
    Column("ComicID", MYSQL_KEY_TEXT),
    Column("IssueID", MYSQL_KEY_TEXT),
    Column("Status", Text),
    Column("weeknumber", Text),
    Column("year", Text),
    UniqueConstraint("ComicID", "IssueID", name="uq_oneoffhistory_comicid_issueid"),
)

# ---------------------------------------------------------------------------
# jobhistory
# ---------------------------------------------------------------------------
jobhistory = Table(
    "jobhistory",
    metadata,
    Column("JobName", MYSQL_KEY_TEXT),
    Column("prev_run_datetime", Text),
    Column("prev_run_timestamp", Float),
    Column("next_run_datetime", Text),
    Column("next_run_timestamp", Float),
    Column("last_run_completed", Text),
    Column("successful_completions", Text),
    Column("failed_completions", Text),
    Column("status", Text),
    Column("last_success_timestamp", Float),
    Column("last_failure_timestamp", Float),
    Column("last_error", Text),
    Column("last_date", Text),
    UniqueConstraint("JobName", name="uq_jobhistory_jobname"),
)

# ---------------------------------------------------------------------------
# manualresults
# ---------------------------------------------------------------------------
manualresults = Table(
    "manualresults",
    metadata,
    Column("provider", Text),
    Column("id", Text),
    Column("kind", Text),
    Column("comicname", Text),
    Column("volume", Text),
    Column("oneoff", Text),
    Column("fullprov", Text),
    Column("issuenumber", Text),
    Column("modcomicname", Text),
    Column("name", Text),
    Column("link", Text),
    Column("size", Text),
    Column("pack_numbers", Text),
    Column("pack_issuelist", Text),
    Column("comicyear", Text),
    Column("issuedate", Text),
    Column("tmpprov", Text),
    Column("pack", Text),
    Column("issueid", Text),
    Column("comicid", Text),
    Column("sarc", Text),
    Column("issuearcid", Text),
)

# ---------------------------------------------------------------------------
# ddl_info
# ---------------------------------------------------------------------------
ddl_info = Table(
    "ddl_info",
    metadata,
    Column("ID", MYSQL_KEY_TEXT, unique=True),
    Column("series", Text),
    Column("year", Text),
    Column("filename", Text),
    Column("size", Text),
    Column("issueid", Text),
    Column("comicid", Text),
    Column("link", Text),
    Column("status", MYSQL_KEY_TEXT),
    Column("remote_filesize", Text),
    Column("updated_date", MYSQL_KEY_TEXT),
    Column("mainlink", Text),
    Column("issues", Text),
    Column("site", Text),
    Column("submit_date", Text),
    Column("pack", Integer),
    Column("link_type", Text),
    Column("tmp_filename", Text),
    Column("oneoff", Integer),
    Column("resume", Integer),
    Column("comicinfo", Text),
    Column("packinfo", Text),
)

# ---------------------------------------------------------------------------
# exceptions_log
# ---------------------------------------------------------------------------
exceptions_log = Table(
    "exceptions_log",
    metadata,
    Column("date", MYSQL_KEY_TEXT, unique=True),
    Column("comicname", Text),
    Column("issuenumber", Text),
    Column("seriesyear", Text),
    Column("issueid", Text),
    Column("comicid", Text),
    Column("booktype", Text),
    Column("searchmode", Text),
    Column("error", Text),
    Column("error_text", Text),
    Column("filename", Text),
    Column("line_num", Text),
    Column("func_name", Text),
    Column("traceback", Text),
)

# ---------------------------------------------------------------------------
# tmp_searches
# ---------------------------------------------------------------------------
tmp_searches = Table(
    "tmp_searches",
    metadata,
    Column("query_id", Integer, primary_key=True),
    Column("comicid", Integer, primary_key=True),
    Column("comicname", Text),
    Column("publisher", Text),
    Column("publisherimprint", Text),
    Column("comicyear", Text),
    Column("issues", Text),
    Column("volume", Text),
    Column("deck", Text),
    Column("url", Text),
    Column("type", Text),
    Column("cvarcid", Text),
    Column("arclist", Text),
    Column("description", Text),
    Column("haveit", Text),
    Column("mode", Text),
    Column("searchtype", Text),
    Column("comicimage", Text),
    Column("thumbimage", Text),
)

# ---------------------------------------------------------------------------
# notifs
# ---------------------------------------------------------------------------
notifs = Table(
    "notifs",
    metadata,
    Column("session_id", Integer, primary_key=True),
    Column("date", MYSQL_KEY_TEXT, primary_key=True),
    Column("event", Text),
    Column("comicid", Text),
    Column("comicname", Text),
    Column("issuenumber", Text),
    Column("seriesyear", Text),
    Column("status", Text),
    Column("message", Text),
)

# ---------------------------------------------------------------------------
# provider_searches
# ---------------------------------------------------------------------------
provider_searches = Table(
    "provider_searches",
    metadata,
    Column("id", Integer, unique=True),
    Column("provider", MYSQL_KEY_TEXT, unique=True),
    Column("type", Text),
    Column("lastrun", Integer),
    Column("active", Text),
    Column("hits", Integer, server_default="0"),
)

# ---------------------------------------------------------------------------
# mylar_info
# ---------------------------------------------------------------------------
mylar_info = Table(
    "mylar_info",
    metadata,
    Column("DatabaseVersion", Integer, primary_key=True),
)

# ---------------------------------------------------------------------------
# ai_activity_log
# ---------------------------------------------------------------------------
ai_activity_log = Table(
    "ai_activity_log",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("timestamp", MYSQL_KEY_TEXT),
    Column("feature_type", Text),  # parsing|search|enrichment|reconciliation|insights|chat|arc|pulllist
    Column("action_description", Text),
    Column("model", Text),
    Column("prompt_tokens", Integer),
    Column("completion_tokens", Integer),
    Column("latency_ms", Integer),
    Column("success", Text),  # true|false
    Column("error_message", Text),
    Column("entity_type", Text),  # comic|issue|storyarc
    Column("entity_id", MYSQL_KEY_TEXT),
)

# ---------------------------------------------------------------------------
# ai_metadata_history
# ---------------------------------------------------------------------------
ai_metadata_history = Table(
    "ai_metadata_history",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("entity_type", MYSQL_KEY_TEXT),  # issue|comic
    Column("entity_id", MYSQL_KEY_TEXT),
    Column("field_name", Text),
    Column("original_value", Text),
    Column("ai_value", Text),
    Column("source", Text),  # enrichment|reconciliation
    Column("provider", Text),  # cv|metron|comicinfo
    Column("created_at", Text),
)

# ---------------------------------------------------------------------------
# ai_cache
# ---------------------------------------------------------------------------
ai_cache = Table(
    "ai_cache",
    metadata,
    Column("cache_key", MYSQL_KEY_TEXT, unique=True),
    Column("cache_type", Text),  # insights|suggestions|expansion
    Column("data", Text),  # JSON blob
    Column("created_at", Text),
    Column("expires_at", Text),
)

# ---------------------------------------------------------------------------
# ai_chat_threads / ai_chat_messages / ai_chat_attachments
# ---------------------------------------------------------------------------
ai_chat_threads = Table(
    "ai_chat_threads",
    metadata,
    Column("id", String(64), primary_key=True),
    Column("username", String(255), nullable=False),
    Column("title", Text, nullable=False),
    Column("created_at", String(40), nullable=False),
    Column("updated_at", String(40), nullable=False),
)

ai_chat_messages = Table(
    "ai_chat_messages",
    metadata,
    Column("id", String(64), primary_key=True),
    Column("thread_id", String(64), nullable=False),
    Column("parent_message_id", String(64)),
    Column("role", String(16), nullable=False),
    Column("content", Text, nullable=False),
    Column("status", String(16), nullable=False),
    Column("results", Text),
    Column("prompt_tokens", Integer, nullable=False, server_default="0"),
    Column("completion_tokens", Integer, nullable=False, server_default="0"),
    Column("created_at", String(40), nullable=False),
    # Monotonic within a thread: clock resolution can tie two created_at values,
    # and a random uuid tiebreak would then order the conversation arbitrarily.
    Column("seq", Integer, nullable=False, server_default="0"),
)

ai_chat_attachments = Table(
    "ai_chat_attachments",
    metadata,
    Column("id", String(64), primary_key=True),
    Column("thread_id", String(64), nullable=False),
    Column("message_id", String(64), nullable=False),
    Column("filename", Text, nullable=False),
    Column("media_type", String(64), nullable=False),
    Column("byte_size", Integer, nullable=False),
    Column("width", Integer, nullable=False),
    Column("height", Integer, nullable=False),
    Column("relative_path", Text, nullable=False),
    Column("created_at", String(40), nullable=False),
)

# ---------------------------------------------------------------------------
# activity_events
# ---------------------------------------------------------------------------
# Append-only Activity Center narrative rows (Activity Center ADR).
# Derived live state stays on acquisition_runs / acquisition_run_items /
# pipeline_journal; this table only stores timestamped history the ledgers
# cannot express. Retention: comicarr.app.activity.retention (90-day age purge).
# Read APIs live under comicarr.app.activity; sole writer is
# comicarr.app.activity.events.record_activity (#479).
activity_events = Table(
    "activity_events",
    metadata,
    Column("event_id", Integer, primary_key=True, autoincrement=True),
    Column("created_at", String(40), nullable=False),
    Column("activity", String(32), nullable=False),
    Column("status", String(32), nullable=False),
    Column("subject_type", String(32), nullable=False),
    Column("subject_id", String(255), nullable=False),
    Column("subject_label", Text, nullable=False),
    Column("reason_code", String(64)),
    Column("reason_detail", Text),
    Column("provider", String(64)),
    Column("run_id", String(64)),
    Column("release_key", String(255)),
    Column("parent_series_id", String(255)),
    Column("scope_type", String(32)),
    Column("scope_id", String(255)),
)

# ---------------------------------------------------------------------------
# pipeline_journal
# ---------------------------------------------------------------------------
# Durable, forward-only transition record for the snatch -> download ->
# post-process pipeline. One row per release_key. Survives process restart so
# an in-flight item completes exactly once. stage is totally ordered via
# stage_rank (the conditional advance-only WHERE + the PP-consumer atomic
# claim). status/retry_count/next_retry_at are R9 resolution columns: operator
# band exits and FAILED_AUTO stamp status without rewriting stage (#483).
pipeline_journal = Table(
    "pipeline_journal",
    metadata,
    Column("release_key", MYSQL_KEY_TEXT, nullable=False),
    Column("issueid", Text),
    Column("provider", Text),
    Column("downloader_type", Text),
    Column("nzbname", Text),
    Column("hash", Text),
    Column("stage", MYSQL_KEY_TEXT, nullable=False),  # snatched|downloaded|post_processing|moved|post_processed|failed
    Column("stage_rank", Integer, nullable=False),  # derived from stage; drives the monotonic guard
    Column("payload_json", Text),  # reconstruct the SNATCHED_QUEUE/PP_QUEUE item
    Column("fail_reason", Text),  # nullable
    # MYSQL_KEY_TEXT: retention index (stage, updated_date) must stay portable.
    Column("updated_date", MYSQL_KEY_TEXT, nullable=False),
    # Reserved-nullable (R9) — unpopulated now:
    Column("status", Text),
    Column("retry_count", Integer),
    Column("next_retry_at", Text),
    UniqueConstraint("release_key", name="uq_pipeline_journal_release_key"),
)

# ---------------------------------------------------------------------------
# acquisition schema + durable command ledgers
# ---------------------------------------------------------------------------

acquisition_schema_versions = Table(
    "acquisition_schema_versions",
    metadata,
    Column("component", String(64), nullable=False),
    Column("version", Integer, nullable=False),
    Column("applied_at", String(40), nullable=False),
    UniqueConstraint("component", "version", name="uq_acquisition_schema_component_version"),
)

acquisition_runs = Table(
    "acquisition_runs",
    metadata,
    Column("run_id", String(64), primary_key=True),
    Column("command_kind", String(32), nullable=False),
    Column("trigger", String(64), nullable=False),
    Column("scope_type", String(32)),
    Column("scope_id", String(255)),
    Column("dispatch_state", String(32), nullable=False),
    Column("completion_state", String(32), nullable=False),
    Column("accepted_count", Integer, nullable=False, server_default="0"),
    Column("terminal_count", Integer, nullable=False, server_default="0"),
    Column("succeeded_count", Integer, nullable=False, server_default="0"),
    Column("no_match_count", Integer, nullable=False, server_default="0"),
    Column("blocked_count", Integer, nullable=False, server_default="0"),
    Column("failed_count", Integer, nullable=False, server_default="0"),
    Column("created_at", String(40), nullable=False),
    Column("updated_at", String(40), nullable=False),
    Column("completed_at", String(40)),
)

acquisition_run_items = Table(
    "acquisition_run_items",
    metadata,
    Column("item_id", Integer, primary_key=True, autoincrement=True),
    Column("run_id", String(64), nullable=False),
    Column("command_kind", String(32), nullable=False),
    Column("entity_type", String(32), nullable=False),
    Column("entity_id", String(255), nullable=False),
    Column("state", String(32), nullable=False),
    # Queue handoff state is independent of the worker lifecycle. A durable
    # item can be accepted but not yet handed to the in-memory worker queue.
    Column("dispatch_state", String(32), nullable=False, server_default="pending"),
    Column("queue_priority", String(16), nullable=False, server_default="routine"),
    # Validated, bounded JSON containing only the command-kind allowlist. It
    # must never contain provider credentials or downloader secrets.
    Column("payload_json", Text),
    Column("attempt_count", Integer, nullable=False, server_default="0"),
    # How many times crash recovery has re-driven this item. Distinct from
    # attempt_count, which counts worker claims: an item can be re-driven
    # without ever being claimed. This is the bound that stops a permanently
    # stuck obligation from being replayed forever (#555).
    Column("recovery_count", Integer, nullable=False, server_default="0"),
    Column("next_attempt_at", String(40)),
    Column("reason", Text),
    Column("created_at", String(40), nullable=False),
    Column("updated_at", String(40), nullable=False),
    Column("completed_at", String(40)),
    UniqueConstraint(
        "run_id",
        "command_kind",
        "entity_type",
        "entity_id",
        name="uq_acquisition_run_item_identity",
    ),
)

# A Search all missing preview is an authenticated, short-lived intent to
# create exactly one durable series-scoped search run.  It intentionally keeps
# only a bounded canonical issue selection and token digest; request cookies,
# provider configuration, and any downloader payload remain outside this
# operational ledger.
acquisition_search_previews = Table(
    "acquisition_search_previews",
    metadata,
    Column("preview_id", String(64), primary_key=True),
    Column("series_id", String(255), nullable=False),
    Column("actor_id", String(255), nullable=False),
    Column("session_digest", String(64), nullable=False),
    Column("token_digest", String(64), nullable=False),
    Column("fingerprint", String(64), nullable=False),
    Column("eligible_json", Text, nullable=False),
    Column("state", String(32), nullable=False),
    Column("run_id", String(64)),
    Column("created_at", String(40), nullable=False),
    Column("expires_at", String(40), nullable=False),
    Column("confirmed_at", String(40)),
    Column("updated_at", String(40), nullable=False),
    UniqueConstraint("token_digest", name="uq_acquisition_search_preview_token"),
)

# An Interactive release search session is authenticated browser-owned state,
# not a serialized provider response.  The public candidate projection and the
# credential-free reconstruction allowlist live separately on the candidate
# row; raw links, provider tuples, cookies, and API credentials are forbidden.
interactive_search_sessions = Table(
    "interactive_search_sessions",
    metadata,
    Column("session_id", String(64), primary_key=True),
    Column("slot_digest", String(64), nullable=False),
    Column("actor_digest", String(64), nullable=False),
    Column("browser_digest", String(64), nullable=False),
    Column("entity_type", String(32), nullable=False),
    Column("entity_id", String(255), nullable=False),
    Column("series_id", String(255)),
    Column("state", String(32), nullable=False),
    Column("candidate_count", Integer, nullable=False, server_default="0"),
    Column("provider_total", Integer, nullable=False, server_default="0"),
    Column("provider_completed", Integer, nullable=False, server_default="0"),
    Column("current_provider", String(255)),
    Column("provider_failures_json", String(8192), nullable=False, server_default="[]"),
    Column("created_at", String(40), nullable=False),
    Column("updated_at", String(40), nullable=False),
    Column("expires_at", String(40), nullable=False),
    UniqueConstraint("slot_digest", name="uq_interactive_search_session_slot"),
)

interactive_search_candidates = Table(
    "interactive_search_candidates",
    metadata,
    Column("candidate_id", String(64), primary_key=True),
    Column("session_id", String(64), nullable=False),
    Column("ordinal", Integer, nullable=False),
    Column("state", String(32), nullable=False),
    Column("public_json", Text, nullable=False),
    Column("reconstruction_json", Text, nullable=False),
    Column("fingerprint", String(64), nullable=False),
    Column("created_at", String(40), nullable=False),
    Column("updated_at", String(40), nullable=False),
    Column("expires_at", String(40), nullable=False),
    UniqueConstraint(
        "session_id",
        "ordinal",
        name="uq_interactive_search_candidate_ordinal",
    ),
)

# Migration completion is not enough to resume acquisition. This one-row
# durable control records the operator-visible reconciliation gate across
# container restarts.
acquisition_reconciliation = Table(
    "acquisition_reconciliation",
    metadata,
    Column("control_id", String(64), primary_key=True),
    Column("state", String(32), nullable=False),
    Column("reason", String(255)),
    Column("updated_at", String(40), nullable=False),
)

# A repair canary is distinct from a repair-item canary: it authorizes exactly
# one named external handoff while global maintenance remains active.
acquisition_canary_permits = Table(
    "acquisition_canary_permits",
    metadata,
    Column("permit_id", String(64), primary_key=True),
    Column("repair_run_id", String(64), nullable=False),
    Column("release_key", String(512), nullable=False),
    Column("route", String(32), nullable=False),
    Column("actor_id", String(255), nullable=False),
    Column("session_digest", String(64), nullable=False),
    Column("state", String(32), nullable=False),
    Column("created_at", String(40), nullable=False),
    Column("expires_at", String(40), nullable=False),
    Column("lease_id", String(64)),
    Column("claimed_at", String(40)),
    Column("completed_at", String(40)),
    Column("outcome", String(64)),
    UniqueConstraint("repair_run_id", "release_key", name="uq_acq_canary_repair_release"),
)

acquisition_maintenance = Table(
    "acquisition_maintenance",
    metadata,
    Column("control_id", String(64), primary_key=True),
    Column("epoch", Integer, nullable=False, server_default="0"),
    Column("active", Integer, nullable=False, server_default="0"),
    Column("owner", String(255)),
    Column("run_id", String(64)),
    Column("reason", Text),
    Column("acquired_at", String(40)),
    Column("heartbeat_at", String(40)),
    Column("released_at", String(40)),
)

acquisition_maintenance_leases = Table(
    "acquisition_maintenance_leases",
    metadata,
    Column("lease_id", String(64), primary_key=True),
    Column("epoch", Integer, nullable=False),
    Column("owner", String(255), nullable=False),
    Column("work_kind", String(64), nullable=False),
    Column("entity_type", String(32)),
    Column("entity_id", String(255)),
    Column("acquired_at", String(40), nullable=False),
    Column("heartbeat_at", String(40), nullable=False),
    Column("released_at", String(40)),
)

acquisition_maintenance_events = Table(
    "acquisition_maintenance_events",
    metadata,
    Column("event_id", Integer, primary_key=True, autoincrement=True),
    Column("epoch", Integer, nullable=False),
    Column("action", String(32), nullable=False),
    Column("actor", String(255), nullable=False),
    Column("run_id", String(64)),
    Column("reason", Text, nullable=False),
    Column("created_at", String(40), nullable=False),
)

# ---------------------------------------------------------------------------
# acquisition repair manifests
# ---------------------------------------------------------------------------
# Repair is deliberately modelled separately from acquisition command runs.
# A preview creates one durable run plus a complete ordered set of items;
# confirmation freezes that set into a manifest.  JSON columns are never
# indexed and contain bounded, canonical projections written by the repair
# service.  Every identifier participating in a key/index uses a bounded
# String so the schema remains portable to MySQL as well as SQLite/PostgreSQL.

acquisition_repair_runs = Table(
    "acquisition_repair_runs",
    metadata,
    Column("run_id", String(64), primary_key=True),
    Column("scope_type", String(32), nullable=False),
    Column("scope_id", String(255), nullable=False),
    Column("state", String(32), nullable=False),
    Column("actor_id", String(255), nullable=False),
    Column("session_digest", String(64), nullable=False),
    Column("preview_token_digest", String(64), nullable=False),
    Column("token_expires_at", String(40), nullable=False),
    Column("token_consumed_at", String(40)),
    Column("preview_fingerprint", String(64), nullable=False),
    Column("manifest_id", String(64)),
    Column("maintenance_epoch", Integer),
    Column("item_count", Integer, nullable=False, server_default="0"),
    Column("selected_count", Integer, nullable=False, server_default="0"),
    Column("applied_count", Integer, nullable=False, server_default="0"),
    Column("conflict_count", Integer, nullable=False, server_default="0"),
    Column("rollback_count", Integer, nullable=False, server_default="0"),
    Column("rollback_conflict_count", Integer, nullable=False, server_default="0"),
    Column("last_sequence", Integer, nullable=False, server_default="0"),
    Column("created_at", String(40), nullable=False),
    Column("confirmed_at", String(40)),
    Column("started_at", String(40)),
    Column("updated_at", String(40), nullable=False),
    Column("completed_at", String(40)),
)

acquisition_repair_manifests = Table(
    "acquisition_repair_manifests",
    metadata,
    Column("manifest_id", String(64), primary_key=True),
    Column("run_id", String(64), nullable=False),
    Column("preview_fingerprint", String(64), nullable=False),
    Column("fingerprint", String(64), nullable=False),
    Column("item_count", Integer, nullable=False),
    Column("selected_count", Integer, nullable=False),
    Column("frozen_by", String(255), nullable=False),
    Column("frozen_at", String(40), nullable=False),
    UniqueConstraint("run_id", name="uq_acq_repair_manifest_run"),
)

acquisition_repair_items = Table(
    "acquisition_repair_items",
    metadata,
    Column("item_id", Integer, primary_key=True, autoincrement=True),
    Column("run_id", String(64), nullable=False),
    Column("sequence", Integer, nullable=False),
    Column("entity_type", String(32), nullable=False),
    Column("entity_id", String(255), nullable=False),
    Column("series_id", String(255), nullable=False),
    Column("intent", String(16), nullable=False),
    Column("fulfillment", String(32), nullable=False),
    Column("reason", String(64), nullable=False),
    Column("date_source", String(32)),
    Column("selected_date", String(10)),
    Column("evidence_json", Text, nullable=False),
    Column("before_json", Text, nullable=False),
    Column("proposed_json", Text, nullable=False),
    Column("optional", Integer, nullable=False, server_default="0"),
    Column("selected", Integer, nullable=False, server_default="0"),
    Column("apply_state", String(32), nullable=False),
    Column("apply_reason", String(255)),
    Column("applied_json", Text),
    Column("rollback_state", String(32), nullable=False),
    Column("rollback_reason", String(255)),
    Column("created_at", String(40), nullable=False),
    Column("updated_at", String(40), nullable=False),
    Column("applied_at", String(40)),
    Column("rolled_back_at", String(40)),
    UniqueConstraint("run_id", "sequence", name="uq_acq_repair_item_sequence"),
    UniqueConstraint(
        "run_id",
        "entity_type",
        "entity_id",
        name="uq_acq_repair_item_entity",
    ),
)

acquisition_repair_series = Table(
    "acquisition_repair_series",
    metadata,
    Column("series_item_id", Integer, primary_key=True, autoincrement=True),
    Column("run_id", String(64), nullable=False),
    Column("series_id", String(255), nullable=False),
    Column("state", String(32), nullable=False),
    Column("dirty", Integer, nullable=False, server_default="0"),
    Column("aggregate_selected", Integer, nullable=False, server_default="0"),
    Column("before_have", Integer),
    Column("before_total", Integer),
    Column("final_have", Integer),
    Column("final_total", Integer),
    Column("conflict_reason", String(255)),
    Column("updated_at", String(40), nullable=False),
    UniqueConstraint("run_id", "series_id", name="uq_acq_repair_series_run"),
)

acquisition_repair_events = Table(
    "acquisition_repair_events",
    metadata,
    Column("event_id", Integer, primary_key=True, autoincrement=True),
    Column("run_id", String(64), nullable=False),
    Column("sequence", Integer),
    Column("action", String(32), nullable=False),
    Column("actor_id", String(255), nullable=False),
    Column("entity_type", String(32)),
    Column("entity_id", String(255)),
    Column("reason", String(255), nullable=False),
    Column("created_at", String(40), nullable=False),
)

acquisition_repair_canaries = Table(
    "acquisition_repair_canaries",
    metadata,
    Column("canary_id", String(64), primary_key=True),
    Column("run_id", String(64), nullable=False),
    Column("entity_type", String(32), nullable=False),
    Column("entity_id", String(255), nullable=False),
    Column("owner_id", String(255), nullable=False),
    Column("session_digest", String(64), nullable=False),
    Column("state", String(32), nullable=False),
    Column("confirmed_at", String(40), nullable=False),
    Column("consumed_at", String(40)),
    UniqueConstraint("run_id", name="uq_acq_repair_canary_run"),
)

# ---------------------------------------------------------------------------
# Indexes
# ---------------------------------------------------------------------------

# Standard indexes
Index("issues_id", issues.c.IssueID)
Index("comics_id", comics.c.ComicID)
Index("issues_comicid", issues.c.ComicID)
Index("issues_status", issues.c.Status)
Index("annuals_comicid", annuals.c.ComicID)
Index("comics_status", comics.c.Status)
Index("snatched_issueid", snatched.c.IssueID)
Index("weekly_comicid", weekly.c.ComicID)
Index("storyarcs_comicid", storyarcs.c.ComicID)
Index("storyarcs_storyarcid", storyarcs.c.StoryArcID)
Index("storyarcs_cv_arcid", storyarcs.c.CV_ArcID)
Index("failed_issueid", failed.c.IssueID)
Index("upcoming_issuedate", upcoming.c.IssueDate)
Index("upcoming_issueid", upcoming.c.IssueID)
Index("pipeline_journal_stage", pipeline_journal.c.stage)
# Retention eligibility + age predicates (see #478). Keep pipeline_journal_stage.
Index("pipeline_journal_stage_updated", pipeline_journal.c.stage, pipeline_journal.c.updated_date)
Index("activity_events_created_at", activity_events.c.created_at)
Index("activity_events_parent_series_id", activity_events.c.parent_series_id)
Index(
    "activity_events_subject",
    activity_events.c.subject_type,
    activity_events.c.subject_id,
)
Index("issues_acquisition_intent", issues.c.AcquisitionIntent)
Index("annuals_acquisition_intent", annuals.c.AcquisitionIntent)
Index("acquisition_runs_state", acquisition_runs.c.completion_state)
Index(
    "acquisition_runs_state_completed",
    acquisition_runs.c.completion_state,
    acquisition_runs.c.completed_at,
)
Index("acquisition_run_items_run_state", acquisition_run_items.c.run_id, acquisition_run_items.c.state)
Index(
    "acquisition_run_items_state_completed",
    acquisition_run_items.c.state,
    acquisition_run_items.c.completed_at,
)
Index(
    "acquisition_run_items_entity",
    acquisition_run_items.c.command_kind,
    acquisition_run_items.c.entity_type,
    acquisition_run_items.c.entity_id,
)
Index("acq_search_preview_series_state", acquisition_search_previews.c.series_id, acquisition_search_previews.c.state)
Index("acq_search_preview_run", acquisition_search_previews.c.run_id)
Index(
    "interactive_search_sessions_expiry",
    interactive_search_sessions.c.expires_at,
)
Index(
    "interactive_search_sessions_scope",
    interactive_search_sessions.c.entity_type,
    interactive_search_sessions.c.entity_id,
)
Index(
    "interactive_search_candidates_session",
    interactive_search_candidates.c.session_id,
    interactive_search_candidates.c.ordinal,
)
Index(
    "interactive_search_candidates_expiry",
    interactive_search_candidates.c.expires_at,
)
Index("acq_reconciliation_state", acquisition_reconciliation.c.state)
Index("acq_canary_permit_state", acquisition_canary_permits.c.state, acquisition_canary_permits.c.expires_at)
Index("acq_canary_permit_release", acquisition_canary_permits.c.release_key)
Index(
    "acquisition_maintenance_leases_active",
    acquisition_maintenance_leases.c.released_at,
    acquisition_maintenance_leases.c.epoch,
)
Index("acquisition_maintenance_events_epoch", acquisition_maintenance_events.c.epoch)
Index("acquisition_maintenance_events_created", acquisition_maintenance_events.c.created_at)
Index("acq_repair_runs_state", acquisition_repair_runs.c.state)
Index("acq_repair_manifest_run", acquisition_repair_manifests.c.run_id)
Index(
    "acq_repair_items_run_state",
    acquisition_repair_items.c.run_id,
    acquisition_repair_items.c.apply_state,
)
Index(
    "acq_repair_items_entity",
    acquisition_repair_items.c.entity_type,
    acquisition_repair_items.c.entity_id,
)
Index(
    "acq_repair_series_run_state",
    acquisition_repair_series.c.run_id,
    acquisition_repair_series.c.state,
)
Index("acq_repair_events_run", acquisition_repair_events.c.run_id, acquisition_repair_events.c.event_id)
Index("acq_repair_canary_run", acquisition_repair_canaries.c.run_id)
ddl_info_status_updated = Index("ddl_info_status_updated", ddl_info.c.status, ddl_info.c.updated_date)

# Case-insensitive indexes (SQLite uses COLLATE NOCASE on column definition;
# PostgreSQL functional indexes are created separately in db.py)
Index("issues_status_comicname", issues.c.Status, issues.c.ComicName)
Index("issues_comicname", issues.c.ComicName)
Index("storyarcs_status_comicname", storyarcs.c.Status, storyarcs.c.ComicName)
Index("storyarcs_status_storyarc", storyarcs.c.Status, storyarcs.c.StoryArc)

# AI indexes
Index("ai_activity_timestamp", ai_activity_log.c.timestamp)
Index("ai_activity_entity_id", ai_activity_log.c.entity_id)
Index("ai_metadata_entity", ai_metadata_history.c.entity_type, ai_metadata_history.c.entity_id)
Index("ai_chat_threads_owner_updated", ai_chat_threads.c.username, ai_chat_threads.c.updated_at)
Index("ai_chat_messages_thread_created", ai_chat_messages.c.thread_id, ai_chat_messages.c.created_at)
Index("ai_chat_attachments_message", ai_chat_attachments.c.message_id)
Index("ai_chat_attachments_thread_created", ai_chat_attachments.c.thread_id, ai_chat_attachments.c.created_at)

# Lookup table: table name -> Table object (used by upsert shim)
TABLE_MAP = {
    "comics": comics,
    "issues": issues,
    "annuals": annuals,
    "snatched": snatched,
    "storyarcs": storyarcs,
    "upcoming": upcoming,
    "nzblog": nzblog,
    "weekly": weekly,
    "importresults": importresults,
    "readlist": readlist,
    "failed": failed,
    "rssdb": rssdb,
    "futureupcoming": futureupcoming,
    "searchresults": searchresults,
    "ref32p": ref32p,
    "oneoffhistory": oneoffhistory,
    "jobhistory": jobhistory,
    "manualresults": manualresults,
    "ddl_info": ddl_info,
    "exceptions_log": exceptions_log,
    "tmp_searches": tmp_searches,
    "notifs": notifs,
    "provider_searches": provider_searches,
    "mylar_info": mylar_info,
    "ai_activity_log": ai_activity_log,
    "ai_metadata_history": ai_metadata_history,
    "ai_cache": ai_cache,
    "ai_chat_threads": ai_chat_threads,
    "ai_chat_messages": ai_chat_messages,
    "ai_chat_attachments": ai_chat_attachments,
    "activity_events": activity_events,
    "pipeline_journal": pipeline_journal,
    "acquisition_schema_versions": acquisition_schema_versions,
    "acquisition_runs": acquisition_runs,
    "acquisition_run_items": acquisition_run_items,
    "acquisition_search_previews": acquisition_search_previews,
    "interactive_search_sessions": interactive_search_sessions,
    "interactive_search_candidates": interactive_search_candidates,
    "acquisition_reconciliation": acquisition_reconciliation,
    "acquisition_canary_permits": acquisition_canary_permits,
    "acquisition_maintenance": acquisition_maintenance,
    "acquisition_maintenance_leases": acquisition_maintenance_leases,
    "acquisition_maintenance_events": acquisition_maintenance_events,
    "acquisition_repair_runs": acquisition_repair_runs,
    "acquisition_repair_manifests": acquisition_repair_manifests,
    "acquisition_repair_items": acquisition_repair_items,
    "acquisition_repair_series": acquisition_repair_series,
    "acquisition_repair_events": acquisition_repair_events,
    "acquisition_repair_canaries": acquisition_repair_canaries,
}


# Upsert key columns per table (derived from UniqueConstraint / unique=True metadata)
def _derive_upsert_keys():

    keys = {}
    for name, table in TABLE_MAP.items():
        # Prefer named UniqueConstraints
        for constraint in table.constraints:
            if isinstance(constraint, UniqueConstraint) and constraint.name:
                keys[name] = [col.name for col in constraint.columns]
                break
        # Fall back to unique=True on individual columns
        if name not in keys:
            for col in table.columns:
                if col.unique:
                    keys[name] = [col.name]
                    break
        # Fall back to composite primary keys (for tables like notifs, tmp_searches)
        if name not in keys:
            pk_cols = [col.name for col in table.primary_key.columns]
            if len(pk_cols) > 1:
                keys[name] = pk_cols
    return keys


UPSERT_KEYS = _derive_upsert_keys()
