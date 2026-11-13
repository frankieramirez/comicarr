# Comicarr domain context

## Import Inbox

The review queue of discovered files that are not yet durably associated with a Series. Records remain pending until an operator ignores, deletes, edits, or finalizes them.

## Manual import finalization

The operator-confirmed workflow that binds pending Import Inbox records to a Series, places or archives their files, rescans the library, and marks the records imported only after those steps succeed.

## Post-processing

The workflow that incorporates downloaded or manually supplied comic and manga files into their intended library destinations and records the resulting holdings. Download completion means the files have arrived; post-processing completion means their placement and library records are complete.

## Series

A monitored comic or manga title and its library directory, issues or chapters, metadata, and acquisition state.

## Content kind

An operator-controlled classification of a Series as `comic` or `manga`, independent of its Series provider and publication format. An operator-marked kind is authoritative; the ComicID prefix remains the fallback for unmarked rows, including legacy `md-`/`mal-` series that alembic 0002 restamped `comic`.

#686 declined a one-time ContentType restamp after auditing one library. #976 keeps that prefix fallback unless `ContentKindSetBy=operator` (the content-kind editor from #639). That partly reverses #686's "stored kind always wins" reading: unmarked prefixed rows stay in manga sync, RSS, dashboard stats, library scan, and post-processing. `comicarr.series_kind.manga_sql_clause` is the one SQL form of that rule.

_Avoid_: Content type, comic type, provider type

## Series provider

Who issued a Series' identifier: ComicVine, MangaDex (`md-` prefix), or MyAnimeList (`mal-` prefix). Distinct from whether the Series is manga — legacy manga rows predate the prefixes and are ComicVine-issued, so the provider answers routing questions while `ContentType` answers content questions. `comicarr/series_kind.py` reconciles the two.

## Chapter source

The MangaDex UUID a manga Series polls for new chapters. MangaDex Series carry it in their ComicID; MyAnimeList Series supply metadata from MAL but keep the chapter source in `MangaDexID`, and have none until it is resolved.

## Chapter ledger

The complete, language-unfiltered list of chapters MangaDex knows for a Series. It is not a language-filtered reading list.

_Avoid_: Chapter list (when the filtered English subset is meant)

## Volume ledger

The complete roster of released volumes for a manga Series, taken from MangaDex cover art. A volume's date is a known-to-exist bound, not a street date.

_Avoid_: Volume entity inside issues, street date

## Covered-by-volume

The chapter fulfillment that means a physically owned volume lists that chapter. It is not Have, not Downloaded, and not Missing.

_Avoid_: Have, downloaded-via-volume

## Last released volume

The highest volume number present on the Volume ledger. Volumes up to this number are the released set; chapters beyond it are the chapter frontier.

## Blended frontier

The default acquisition surface for a manga Series: missing released volumes, plus missing chapters beyond the last released volume.

_Avoid_: Missing issues (unqualified, for manga)

## Release candidate

A provider result considered for acquiring one tracked issue, chapter, annual, or story-arc item. Its match verdict explains whether automatic search would accept it, whether an operator may override that decision, and every reason for rejection.

_Avoid_: Search result, NZB result, torrent result

## Interactive release search

An operator-initiated review of release candidates for one tracked acquisition item, or for the eligible missing issues on a Series. A series-scoped review can surface packs and show which missing issues each release would satisfy, then optionally perform a deliberate manual grab. It is distinct from metadata search, which finds a Series to add to the library, and from Search all missing, which queues automatic acquisition.

_Avoid_: Manual search, interactive search

## Search provider

A configured acquisition source Comicarr queries for release candidates: a Newznab or Torznab indexer, a DDL site, a torrent site, or the experimental source. Distinct from a Series provider, which answers who issued a Series' identifier — a Search provider answers where releases are found.

_Avoid_: Indexer (as the umbrella term), provider (unqualified where either meaning could apply)

## Acquisition route

The delivery channel a Search provider serves: `ddl`, `nzb`, or `torrent`. Every Search provider serves exactly one route. Route readiness — whether Comicarr can currently acquire through a channel end to end, including its downstream client — is a property of the route, not of any one provider.

_Avoid_: Search route, download method

## Needs attention

The work queue of unresolved, actionable acquisition obligations that Comicarr cannot finish without operator information, authority, or judgment. It excludes trouble Comicarr can reconcile itself.

_Avoid_: Attention band (for the complete work queue), failure list

## Log level

Comicarr's single verbosity dial, named by the severity it admits: `0` warning, `1` info, `2` debug. Level `0` means warnings and errors, not silence, which is why it is never called "quiet" — `--quiet` and `--verbose` are flag spellings, not level names.

Subsystem diagnostics, including folder-scan diagnostics, are Debug entries rather than independent verbosity controls. High-volume operations summarize their diagnostics instead of introducing another dial.

## Support bundle

A downloadable archive of allowlisted diagnostic data, engineered for public issue attachment after operator review. If its contents appear sensitive, the operator shares it privately with maintainers instead; CarePackage is the legacy implementation name, not the user-facing term.

## Legacy module

A root-level `comicarr/*.py` module inherited from Mylar3 that carries business logic. ADR-0005 names three groups: Infrastructure (shared plumbing, not legacy), Foundations legacy (reachable from `comicarr/app/` only through a Seam module), and Deferred legacy (baselined, shrink-only).

_Avoid_: Old code, Mylar code

## Seam module

The one module under `comicarr/app/` allowed to import a given Legacy module. It exposes typed functions to modern callers and hides Mylar3 calling conventions such as status strings and queues. Putting a module behind its seam does not require rewriting it.

_Avoid_: Facade (reserved for the legacy `PostProcessor` class being retired), wrapper, adapter (reserved for download and torrent clients)

## Series add

Creating a Series in the library from a metadata provider, and refreshing it later. This is what the legacy `importer.py` does. It is unrelated to the Import Inbox and Manual import finalization, which deal with files.

_Avoid_: Import (for adding a Series)

## Deprecation notice

The announcement that a feature will be removed, made through the deprecation registry described in ADR-0006. A feature is deprecated only when it has a registry entry. Frozen features keep working, get no new features, and have no removal date.

_Avoid_: Sunset, retired (reserved for names guarded by `RETIRED_GLOBALS`)

