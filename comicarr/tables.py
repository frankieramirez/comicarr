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

# ---------------------------------------------------------------------------
# comics
# ---------------------------------------------------------------------------
comics = Table(
    "comics",
    metadata,
    Column("ComicID", Text, unique=True),
    Column("ComicName", Text),
    Column("ComicSortName", Text),
    Column("ComicYear", Text),
    Column("DateAdded", Text),
    Column("Status", Text),
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
    Column("ContentType", Text, server_default="comic"),
    Column("ReadingDirection", Text, server_default="ltr"),
    Column("MetadataSource", Text),
    Column("ExternalID", Text),
)

# ---------------------------------------------------------------------------
# issues
# ---------------------------------------------------------------------------
issues = Table(
    "issues",
    metadata,
    Column("IssueID", Text),
    Column("ComicName", Text),
    Column("IssueName", Text),
    Column("Issue_Number", Text),
    Column("DateAdded", Text),
    Column("Status", Text),
    Column("Type", Text),
    Column("ComicID", Text),
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
    Column("IssueID", Text),
    Column("Issue_Number", Text),
    Column("IssueName", Text),
    Column("IssueDate", Text),
    Column("Status", Text),
    Column("ComicID", Text),
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
    Column("IssueID", Text),
    Column("ComicName", Text),
    Column("Issue_Number", Text),
    Column("Size", Integer),
    Column("DateAdded", Text),
    Column("Status", Text),
    Column("FolderName", Text),
    Column("ComicID", Text),
    Column("Provider", Text),
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
    Column("StoryArcID", Text),
    Column("ComicName", Text),
    Column("IssueNumber", Text),
    Column("SeriesYear", Text),
    Column("IssueYEAR", Text),
    Column("StoryArc", Text),
    Column("TotalIssues", Text),
    Column("Status", Text),
    Column("inCacheDir", Text),
    Column("Location", Text),
    Column("IssueArcID", Text),
    Column("ReadingOrder", Integer),
    Column("IssueID", Text),
    Column("ComicID", Text),
    Column("ReleaseDate", Text),
    Column("IssueDate", Text),
    Column("Publisher", Text),
    Column("IssuePublisher", Text),
    Column("IssueName", Text),
    Column("CV_ArcID", Text),
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
    Column("IssueNumber", Text),
    Column("ComicID", Text),
    Column("IssueID", Text),
    Column("IssueDate", Text),
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
    Column("IssueID", Text),
    Column("NZBName", Text),
    Column("SARC", Text),
    Column("PROVIDER", Text),
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
    Column("ComicID", Text),
    Column("IssueID", Text),
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
    Column("impID", Text),
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
    Column("IssueID", Text),
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
    Column("IssueID", Text),
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
    Column("ID", Text),
    Column("Status", Text),
    Column("ComicID", Text),
    Column("IssueID", Text),
    Column("Provider", Text),
    Column("ComicName", Text),
    Column("Issue_Number", Text),
    Column("NZBName", Text),
    Column("DateFailed", Text),
    UniqueConstraint("ID", "Provider", "NZBName", name="uq_failed_id_provider_nzbname"),
)

# ---------------------------------------------------------------------------
# rssdb
# ---------------------------------------------------------------------------
rssdb = Table(
    "rssdb",
    metadata,
    Column("Title", Text, unique=True),
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
    Column("ComicID", Text, unique=True),
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
    Column("ComicID", Text),
    Column("IssueID", Text),
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
    Column("JobName", Text),
    Column("prev_run_datetime", Text),
    Column("prev_run_timestamp", Float),
    Column("next_run_datetime", Text),
    Column("next_run_timestamp", Float),
    Column("last_run_completed", Text),
    Column("successful_completions", Text),
    Column("failed_completions", Text),
    Column("status", Text),
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
    Column("ID", Text, unique=True),
    Column("series", Text),
    Column("year", Text),
    Column("filename", Text),
    Column("size", Text),
    Column("issueid", Text),
    Column("comicid", Text),
    Column("link", Text),
    Column("status", Text),
    Column("remote_filesize", Text),
    Column("updated_date", Text),
    Column("mainlink", Text),
    Column("issues", Text),
    Column("site", Text),
    Column("submit_date", Text),
    Column("pack", Integer),
    Column("link_type", Text),
    Column("tmp_filename", Text),
)

# ---------------------------------------------------------------------------
# exceptions_log
# ---------------------------------------------------------------------------
exceptions_log = Table(
    "exceptions_log",
    metadata,
    Column("date", Text, unique=True),
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
    Column("date", Text, primary_key=True),
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
    Column("provider", Text, unique=True),
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
    Column("timestamp", Text),
    Column("feature_type", Text),  # parsing|search|enrichment|reconciliation|insights|chat|arc|pulllist
    Column("action_description", Text),
    Column("model", Text),
    Column("prompt_tokens", Integer),
    Column("completion_tokens", Integer),
    Column("latency_ms", Integer),
    Column("success", Text),  # true|false
    Column("error_message", Text),
    Column("entity_type", Text),  # comic|issue|storyarc
    Column("entity_id", Text),
)

# ---------------------------------------------------------------------------
# ai_metadata_history
# ---------------------------------------------------------------------------
ai_metadata_history = Table(
    "ai_metadata_history",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("entity_type", Text),  # issue|comic
    Column("entity_id", Text),
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
    Column("cache_key", Text, unique=True),
    Column("cache_type", Text),  # insights|suggestions|expansion
    Column("data", Text),  # JSON blob
    Column("created_at", Text),
    Column("expires_at", Text),
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
