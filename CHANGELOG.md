# Changelog

## 0.35.0

### Minor Changes

- 749d01f: Settings → Logs has a new **New log** button. It starts a fresh `comicarr.log` so the viewer shows only what happens after you click — useful when reproducing an issue. The previous log is kept as a rotated archive under your existing retention settings, and a confirmation is asked first.

## 0.34.2

### Patch Changes

- 5cf461b: "Review missing" no longer downgrades a grabbable pack to "Not a match" when the same release was found for several missing issues. When one issue's search rejected a pack (for example because that issue is outside the pack's range) and another issue's search accepted it, the review sheet could keep whichever verdict arrived first — hiding a pack you could grab, or anchoring the grab on an issue the pack does not contain. The accepted verdict now always wins, and the grab anchors on an issue the pack actually covers.

## 0.34.1

### Patch Changes

- 835c307: Usenet downloads are no longer quarantined at completion with "immutable_payload_conflict:provider". The download pipeline recorded the provider two different ways for the same download — as "DrunkenSlug (newznab)" when the release was grabbed and as plain "DrunkenSlug" when the download finished — so the safety check that guards against a download changing identity mid-flight fired on every completed NZBGet download, sending it to Needs attention instead of importing it. Both spellings now resolve to the same provider, and existing pipeline records written under the old spelling are reconciled automatically on the next startup.
- 0bbc620: Downloads that were falsely marked as imported before v0.34.0's recovery fix are now healed automatically. That fix stopped startup recovery from reporting *import / succeeded* for downloads that were never actually moved into the library, but rows already corrupted by earlier versions stayed permanently stuck: the pipeline considered them finished, so no future startup would ever look at them again, while the files sat stranded in the download directory. On the next startup, recovery now re-examines finished pipeline records that the library itself contradicts — no stored file location, no Downloaded status, and no operator decision such as Ignored or Archived — and puts them back through the normal recovery path. When the completed download folder can still be resolved, the import runs for real; otherwise the item lands in Needs attention as "download finished but was never imported into the library", with the files still in the download directory ready for a manual import. Genuinely imported items, one-off downloads, and issues from removed series are left untouched.

## 0.34.0

### Minor Changes

- 48383ed: Searches can now match pack releases from any indexer, not just DDL. When a series has *Allow packs* enabled (which still requires torrent search to be on), a result like `Solo Leveling v01-14` or `Invincible #001-144` is recognized as a multi-volume or multi-issue pack instead of being thrown away for having no single issue number. Comicarr checks the pack against what the series is missing, and one grab marks every issue it covers as Snatched — so during "Search all missing", the queued searches for the rest of those issues stop instead of hunting for each one individually. A volume pack covers every chapter belonging to its volumes, and only ever matches volume-tracked series, so a `v01-14` release can never claim issues 1–14 of an issue-tracked comic.
- cf8638c: The series page now has **Review missing**, an Interactive release search for the series' eligible missing issues. Results include packs, show which missing issues each release would satisfy, and a single grab can cover more than one issue. Per-issue Interactive release search is unchanged.

### Patch Changes

- 882db3b: The web UI stays responsive while "Override and grab this release" is processing. The grab's revalidation and download-client handoff now run off the server's request loop, so other tabs and pages load normally instead of hanging until the grab finishes or fails. The same fix covers starting an Interactive release search, series "Search all missing", single-issue search, and AI story arc generation. Grabbing a release while another grab is still processing now answers immediately with "Another release grab is already being processed" instead of silently waiting its turn.
- 533a106: Refreshing a manga series rematches the folder with the series' bare-number setting, so a volume file like `Naruto 12.cbr` marks the chapters in volume 12 instead of being read as issue 12.
- 05d7e98: Manga series now actually refresh on the database-update schedule, search only the blended frontier (or the per-series volumes/chapters toggle), and interpret bare filenames like `Naruto 12.cbr` using the series setting on import, scan, and post-process.
- 7d67f3e: Startup recovery no longer reports *import / succeeded* for downloads that were never actually moved into the library. Previously, recovery could trust old download-history state as proof of completion and mark an item post-processed without running file placement, leaving the files stranded in the download directory while activity claimed a successful import. Recovery now also checks the library itself (the issue's stored location or Downloaded status) before closing an item out. When the download really did finish but was never imported, recovery re-runs the import if it can resolve the completed folder; otherwise the item lands in Needs attention as "download finished but was never imported into the library", with the files still in the download directory ready for a manual import.

## 0.33.0

### Minor Changes

- 315b4b6: Torznab indexers can now be added, edited, and removed in Settings → Search, next to the existing Newznab editor. You no longer have to hand-edit `extra_torznabs` in `config.ini` to manage torrent indexers.

### Patch Changes

- 8ab35db: Adding a manga now returns immediately and populates chapters in the background, the same way adding a comic does. Failures show up in Activity instead of hanging or silently dying in the request.
- 9176fe5: Manga filenames with a bare number (`Naruto 12.cbr`) can now be treated as a volume, a chapter, or auto — auto compares the folder's numbers to the series' known volume and chapter counts. Prefixed names like `One Piece v10.cbz` stay volumes.
- c14fbdc: Library and series-detail covers now load from Comicarr's local cache (or a same-origin fallback) instead of hotlinking MangaDex, so manga series no longer show the "You can read this at MANGADEX" placeholder.
- 6654ea1: Searching a manga series now targets the blended frontier by default — missing released volumes plus chapters beyond the last volume — with per-series volumes-only and chapters-only modes.
- 0d5c41e: Manga series now have a defined chapter and volume ledger: owning a volume covers the chapters it is known to contain (without counting them as individually owned), and the default missing set is released volumes plus chapters beyond the last released volume.
- 551140d: Manga series now refresh on a schedule: empty chapter ledgers are healed in place (no re-add), new MangaDex chapters are polled, and wanted chapters are searched. Prefix-stamped series stay visible even if ContentType was backfilled as comic.
- 9b236be: The series-detail header now shows a real last-refresh time (or "unsynced" when there isn't one) and renders the series description instead of leaving every title looking unsynced.

## 0.32.0

### Minor Changes

- 09984d7: Each issue on a series page (and the matching annual and story-arc rows) now has an Interactive Search action that opens the release picker for that issue, so you do not have to leave the page and find it again under Releases.
- c7fa5ad: The series page now has a "View on ComicVine", "View on MangaDex", or "View on MyAnimeList" link for the catalog that issued the series. MyAnimeList series also get a MangaDex link when that chapter source is known.
- 33c0d16: You can stop an in-flight search or an open download/post-processing item from Activity. The status bar's in-flight list now has a Stop action that moves that item to cancelled instead of leaving you to wait for it to finish or fail.

### Patch Changes

- 1efbdf4: The status bar's "N in flight" count now opens Activity on exactly those items — running searches and open download/post-processing rows — instead of a generic unfiltered Activity page.
- 334abb9: The Settings → Logs console now uses the available page width and wraps long lines, so debug output no longer requires sideways scrolling in a narrow centered column.
- e35ed19: Completed NZBGet downloads are imported from the files actually sitting in the job folder. Comicarr used to look for a file with the same name as the release inside that folder, miss the real `.cbr`/`.cbz`, and mark a successful download as failed.
- d4b4d73: Restart recovery of a finished SABnzbd or NZBGet download now keeps the completed folder the downloader already reported. Comicarr used to throw away that path and then fail post-processing with "nzb_folder is required", leaving a successful download stuck after a restart.
- acf1db1: Coded Settings dropdowns (for example NZB client) now show the option name on first load. They used to show the raw stored value until you opened the menu once.

## 0.31.0

### Minor Changes

- d41ab03: Needs attention now uses one actionable work queue everywhere. The Activity
  preview, Dashboard count, triage view, and resolution actions share the same
  membership and action rules, so self-recoverable failures no longer appear in
  one place while disappearing from another.

  Custom integrations should move to `GET /api/attention` and
  `POST /api/attention/resolve`. The existing Activity preview and Downloads
  resolution routes remain available for this release and will be removed in the
  next release. `GET /api/downloads/needs-attention` is already gone in this
  release with no deprecation window — scripts polling it should switch to
  `GET /api/attention` now.

## 0.30.1

### Patch Changes

- 1dd8dc7: The Newznab categories you set are now the categories Comicarr searches. Whatever you typed into **Settings → Search → Categories** was being folded into a legacy field that also carries the indexer's RSS user ID, and the searcher could not tell the two apart — so it fell back to its built-in comics category on every Usenet query, and the Settings page displayed the value you entered as though it were in use. Restricting or widening your categories had no effect, and no error said so.

  The RSS user ID now has its own field beside Categories, so each means one thing. Existing indexers are re-read on upgrade: if the box shows fewer categories than you remember typing, that is the part that was actually reaching your indexer, and you can now correct it. Newly added indexers default to `7030` (Books/Comics) instead of `5030`, which is a TV category and was never right for this application.

  Two related fixes to how providers are stored. An indexer whose _verify TLS_ or _enabled_ field was written as `True`/`False` rather than `1`/`0` — the shape produced when a legacy `torznab_*` block is absorbed, and present in some configs inherited from Mylar3 — was reported as enabled on the Acquisition tab while the searcher skipped it entirely, or took the search down with an error when it tried to read the TLS setting. Both fields are now normalised wherever configuration is read or written, so every part of Comicarr agrees on what a provider is set to. And an absorbed `torznab_*` entry now verifies TLS certificates by default rather than silently arriving with verification off.

  Finally, the log messages about inert `torznab_*` fields no longer point you at a Settings UI that cannot edit Torznab providers. They now name `extra_torznabs` under `[Torznab]` in `config.ini` and show the entry format.

## 0.30.0

### Minor Changes

- 97b1687: Add issue-scoped interactive release search with explainable candidates and deliberate, safely revalidated grabs.

### Patch Changes

- 1f1dd78: Let operators classify any series as comic or manga from its detail page, independent of metadata provider. Honor that stored classification during search, refresh, and post-processing.

## 0.29.1

### Patch Changes

- a5a7dc1: Hand-edited legacy `torznab_*` fields under `[Torznab]` in config.ini no longer sit silently inert. A complete legacy entry (name, host, API key, category) is folded into the real multi-provider `extra_torznabs` list on startup and the stale keys are removed; an incomplete one is called out in the log with a pointer to the Settings UI instead of being ignored. (#631)
- a5a7dc1: Pack and bundle releases can now actually be matched. Each series page has two new Search options — **Allow packs** accepts multi-issue/volume bundle releases (the norm for manga and manhwa torrents), and **Ignore book type** lets results through when the release's book type (TPB, GN, …) differs from the series. These per-series flags existed in the database but had no way to be set, so packs were rejected for every series. Pack matching also no longer requires the 32P tracker to be enabled — any torrent or Torznab provider qualifies once torrent search is on. (#632, #633)

## 0.29.0

### Minor Changes

- c5b7cd4: Read your logs without leaving Comicarr. Settings has a new **Logs** section: the tail of `comicarr.log` in a console you can filter by severity and copy straight into a bug report, with the log level dial sitting right above it. Raise the level, reproduce the problem, and read what happened — without a shell, a `docker exec`, or a restart.

  The dial is honest about who is in charge. If a `--log-level` flag or `COMICARR_LOG_LEVEL` is setting the level, the page says so, names the level actually running and the one the next restart will bring back, and explains that the value you save here applies immediately but will not survive that restart until the pin is removed. When nothing overrides it, the page stays quiet and the dial simply is what runs.

  The header shows where the log file lives and how much history is kept (`10 MB × 5 files`) so you can see the ceiling before turning verbosity up. You can pull the last 200, 1,000, or 5,000 lines. Provider secrets are still redacted before any line leaves the server, and only the current log file is read — rotated files stay where they are.

### Patch Changes

- 08e1f54: Docker containers now log normally. The image used to start Comicarr with `--quiet` hardcoded, so `docker logs` showed almost nothing and no setting could raise it — the level you chose in Settings was overruled on every start. That argument is gone: containers now run at the normal level, `docker logs` shows what the server is doing, and the level is yours to set. Change it in Settings, or set `COMICARR_LOG_LEVEL` to `0`, `1`, or `2` in your compose file when you want it fixed regardless of Settings. The container banner says which of the two is in effect at startup.

  Expect more output than before after upgrading — that is the fix, not a side effect. Turn it down in Settings if you want less.

- 173d9f9: Debug logging now includes useful folder-scan diagnostics without a second hidden switch. Comicarr removes the legacy `folder_scan_log_verbose` setting during the configuration upgrade; set the single Log level to `2 · Debug` when diagnosing scan matching. Candidate-heavy scans now summarize their work per input file instead of flooding the log with one line for every comparison.
- 90e19a0: The logging level you save in Settings now takes effect immediately, with no restart. Previously the new level was written to the config file and then ignored until the server came back up — which is exactly the wrong moment, since you usually turn verbosity up to catch a problem that is happening right now, and restarting throws away the state you were trying to capture. Turn the dial up, reproduce the problem, read the logs. Out-of-range numbers are clamped to `0`–`2` as they are everywhere else, and a value that is not a number is refused rather than saved and silently dropped at the next start.
- 25f839b: You can now set the logging verbosity without editing the config file. `--log-level 0|1|2` on the command line and the `COMICARR_LOG_LEVEL` environment variable both set it, and each is honoured only when you actually supply it — a startup argument wins over the environment variable, which wins over the level saved in Settings. An out-of-range number is clamped instead of refusing to start, an unreadable one is reported and skipped, and whichever source wins says on startup what it overrode. `--quiet` still works as before but now prints a deprecation notice pointing at `--log-level 0`.
- 955504e: Changing the logging level now does what you asked for. Raising verbosity no longer silences console output — under Docker it previously did exactly that, so there was no way to get more detail out of a container. Lowering it now takes effect immediately instead of leaving the previous, noisier level in place. Quiet mode means warnings and errors only rather than near-total silence, so a failure still reaches you with the dial turned down.
- 16fe65d: The log level can now be set by name as well as by number. `warning`, `info`, and `debug` work anywhere the number did — `--log-level debug` on the command line, `COMICARR_LOG_LEVEL=debug` in your compose file, or `LOG_LEVEL = debug` in `config.ini`. Numbers are unchanged, so nothing you already have needs editing, and capitalisation does not matter.

  The names describe what each level actually does: level `0` is `warning` because it emits warnings and errors. It was previously described as "quiet", which suggested silence and was never true — turning the dial down has always kept failures visible.

  Startup messages now name the level both ways, so it is obvious which setting produced it: `Log level 2 (debug) from startup argument overrides 1 (info) from the config file`.

  `--verbose` and `-v` are now deprecated aliases for `--log-level debug`, joining `--quiet` and `-q` (aliases for `--log-level warning`). All four keep working and will continue to — they print a note pointing at `--log-level`, which is the one flag that sets the level directly.

- 22098c1: Warnings and errors now reach your logs on Docker. Comicarr chose between two different logging implementations based on your system locale, and the one containers ended up on was missing pieces: certain warnings — "No COMIC*DIR configured", "Cannot find import directory", and others like them — raised an internal error instead of being written down, and unexpected failures were dropped entirely while the server tried to record them. Startup even announced it: *"errors WILL NOT be captured in the logs"\_. There is one logging implementation now, the same for every locale, so those messages appear in `comicarr.log`, in `docker logs`, and in the log list in the Web UI like everything else.

  Two things to expect after upgrading. Log lines from containers change shape slightly — `INFO :: comicarr.backup_files.539 : MainThread` in place of `INFO :: MainThread : maintenance.py:backup_files:539 :` — so an existing log file will show both styles either side of the upgrade. And with the dial turned all the way down, `docker logs` now shows warnings and errors rather than nothing at all, which is what level 0 was always meant to mean.

## 0.28.0

### Minor Changes

- 047e8a8: Settings → About can create a Support bundle for troubleshooting. Review the three files in the ZIP before attaching it to a public issue; share it privately with a maintainer if anything looks sensitive.

## 0.27.1

### Patch Changes

- ef8f7cc: Make blocked Usenet searches actionable with editable Newznab and SABnzbd settings, clearer route diagnostics, and credential-safe configuration updates.

## 0.27.0

### Minor Changes

- 86da2af: The dashboard now surfaces what needs your attention, not just whether the machinery is up. Below the health band it lists the same needs-attention groups the Activity Center already knows about — the series, the reason in plain language, and the actions that clear them — and when nothing is waiting it says so with a single quiet line: **Nothing needs you**.

  That sentence is only trustworthy next to the health band's last-successful-search line. Together they close the gap that let downloads stay broken for weeks while the dashboard looked fine: the health band catches a stalled pipeline, and this one catches the specific releases that already need a human decision. Actions taken here (retry, search again, import, stop wanting) are the same exits as on the full triage route, and the count updates as soon as they land — no manual refresh.

- 0d1105c: The dashboard now reads top to bottom in the order the questions actually matter: is the automation healthy, what needs you, what is happening, and only then what your library is. Health leads the page, needs-attention and in-flight sit together on the row beneath it, and recent activity and this week's releases follow. On a narrow window those two stack in the same order rather than reshuffling.

  **Library statistics are no longer the hero of the page.** The three large tiles at the top are gone, replaced by a single line of numbers below the timeline — series, issues held, and completion, now labelled **of known issues held** and marked _not a health metric_. Completion counts what is on disk against what Comicarr knows exists; it says nothing about whether downloading works, and it no longer sits next to the health band where it looked like it did.

  **Ask moves to the bottom of the page** and loses its suggestion chips. It is a way into chat, not an answer to any of the questions above it, and chips like "Anything stuck in the queue?" were making health claims that the health band now reports properly. The recent-chats card that sat beside "This week" goes with it; chat is reachable from the sidebar and the Ask bar.

- 38eda3c: The dashboard now says how much work is moving right now, across every download route — one line reading "12 in flight", and "12 in flight (3 recovered from a restart)" when some of that work has already survived a restart. The two figures are never added together: the recovered ones are part of the total, not extra.

  The **Queue** tile is gone. It counted direct downloads only, so an operator running SABnzbd saw "0 queued" while SABnzbd was actively downloading — a claim the dashboard could not back. The in-flight line answers the same question honestly for every route, and it reads the same source as the status indicator in the footer, so the two can never disagree. If that source cannot be read, the line says so instead of reporting a quiet system.

- 1445a9a: The dashboard's **Recent activity** panel now reads the same narrative stream as the Activity Center, so a failed grab or blocked download appears in the timeline instead of vanishing because it never reached the snatched table. That is the failure mode that let a broken downloader look like a quiet week: the old panel could only list things that had already been snatched.

  Each row uses the same sentence voice and deep-links as the Activity Center — failures read "Couldn't grab…", successes read "Grabbed…", and the subject links through to the issue or series. When nothing has happened, the empty state says **No activity in the last 30 days** and links into the full activity view, not the download-history table.

### Patch Changes

- 35415e3: The dashboard now opens with a health band that answers the only question worth opening it for: is anything broken right now? It reports whether a download route is usable, how many indexers are responding, and whether the workers are running — one quiet line when everything is fine, amber naming the specific component when it is not, and red with a link straight to the settings page that fixes it when nothing can get through.

  Alongside those it carries a **last successful search** line, which is the one that matters most. Every other signal reports the state of a component; this one reports whether searching has actually produced anything lately, and it goes amber once nothing has run for twice your search interval. That is the reading that catches the failure the rest of the page cannot: for weeks, downloads could be completely broken while every component reported itself fine and the dashboard looked like a quiet week. This line would have read "11 days ago".

  The band never guesses in your favour. If the health check itself cannot be reached, it says "Cannot determine health" rather than going quiet — an unanswered question is not good news. And the last-successful-search line is never hidden, at any age, including when nothing has ever run.

- ebef755: The dashboard no longer goes blank when one thing behind it breaks. Every panel — the library figures, the queue, recent activity, this week's releases, recent chats — now loads on its own. If one of them cannot be answered, that panel alone says "unavailable" and offers a retry next to it, and everything else on the page still works. Previously the whole page was built from a single request, so one failure took the page down entirely, and a failure that was quietly swallowed showed up as an empty panel — indistinguishable from a genuinely quiet week.

  That distinction is the point: an empty panel now means the answer really was nothing, and a broken one says so out loud. The panels also reserve their space while loading, so a slow one no longer shifts the page around as it arrives.

  The dashboard reads the same information in the same order as before, with one correction: the count above each panel now matches the rows beneath it. "Recent activity" could previously say ten events above a list of five.

## 0.26.4

### Patch Changes

- ff69928: Fixed usenet downloads never reaching SABnzbd. Instead of sending the NZB, Comicarr sent SAB a link pointing back at itself and expected SAB to come and fetch the file — from an address Comicarr had to guess (a network probe, a STUN lookup, or the `host_return` setting when both guessed wrong), at an endpoint that did not exist. Inside Docker the guessed address was the container's own short-lived IP, and the missing endpoint answered with a web page rather than an error, so nothing anywhere reported a problem: the snatch looked successful and the download simply never happened. Comicarr now uploads the .nzb to SABnzbd directly, the same way it already does for NZBGet, so the handoff finishes in one step and SAB's own reply confirms it. Your SAB category, priority, and certificate-verification settings are unchanged.

  Because no download client is ever handed a Comicarr address any more, the `host_return` setting has no purpose and is removed from `config.ini` automatically on first start after upgrading. Comicarr also no longer probes the network at startup to work out its own address.

- 455dafb: Fixed the "in flight" count reporting work that stopped happening long ago. When Comicarr restarted, it restored every unfinished search and refresh — correct for something a restart interrupted, but it also restored obligations that could never make progress, over and over, with nothing ever giving up on them. On a long-running install those accumulated into hundreds of entries the health count reported as active work, so the number told you nothing. Comicarr now gives up on an item that has come back from three restarts without ever finishing, records it as quarantined, and stops counting it. The bound is restarts rather than elapsed time, so an item that is simply queued behind a long backlog is never abandoned. Entries stranded before this shipped are cleared once on the first start after upgrading; nothing is lost, because whether an issue is wanted lives on the issue itself and anything still wanted is picked up by the next search.

  The status endpoint also reports `recovery_pending` alongside `in_flight`, so a surface can say "N in flight (K recovered from a restart)" instead of one number that hides the difference.

## 0.26.3

### Patch Changes

- b672dfc: Fixed a failed torrent download landing in manual review — and permanently blocking that issue from that provider — when the .torrent file simply could not be fetched. If the tracker was unreachable, timed out, or returned something unusable, Comicarr crashed inside the send step instead of reporting a clean failure. Because a crash there means "we do not know whether the download client got this", the attempt was filed for manual review, which is terminal: every later attempt on the same issue and provider was then refused before it even reached the client, so the 6-hourly search retried into the same wall forever while telling you nothing useful. A fetch that never reaches the download client is now reported as an ordinary failure and goes to Failed Download Handling, so the release can be retried normally. This affects all five torrent clients (rTorrent, Deluge, qBittorrent, Transmission, uTorrent).
- 6bfa938: Fixed Retry and Search again doing nothing for an issue that had landed in needs-attention. Once an attempt ended in manual review, that issue was permanently blocked from that provider: the retry re-wanted the issue and started a search, and the search then refused to hand anything to the download client — so the item quietly bounced back into needs-attention on the next cycle, forever, with nothing in the log to say why. Resolving a needs-attention item now genuinely releases it, so the next search can grab it again, however many times you need. An item you have _not_ resolved yet still blocks — it may be something your download client already has, and clearing it automatically would both hide it from you and download it twice — but the log now names the item and its reason instead of reporting an unexplained handoff failure.
- e652bfe: Fixed series refresh failing outright whenever it had issue or location changes to write. Refreshing a series looked up its database table under the wrong name, so the moment a refresh found something to update — a new issue, a changed status, a relocated series folder — the write raised `Unknown table for upsert` and the whole run was recorded as failed. Refreshes that happened to find nothing to change appeared to succeed, which is why this could go unnoticed while every real update was being dropped. The same defect affected annuals, the bulk series-location update after a config change, and the dynamic-name maintenance pass. All of them now write correctly, so a refresh actually persists what it finds.

## 0.26.2

### Patch Changes

- 99d0178: Fixed searches aborting and providers going dark for an hour whenever an indexer returned any error at all. A rate-limit response — Prowlarr's plain HTTP 429, the most common thing an indexer says when you search too often — was treated identically to the indexer being unreachable: Comicarr blocklisted the provider and abandoned the search. The check meant to distinguish the two cases had been written so that it always fired, so in practice every transient hiccup cost you the whole search cycle, and the next one 6 hours later. Comicarr now inspects the actual failure: if the provider answered at all, it is left enabled and only that one search is skipped, and only a genuine connection failure (refused, timed out, host or network unreachable) blocklists it. The same fix applies to the GetComics DDL provider. These failures also no longer dump a 130-entry table of system error codes into your logs on every occurrence.

## 0.26.1

### Patch Changes

- 0376408: Comicarr images are now published to Docker Hub as `comicarr/comicarr`, mirroring the existing GHCR images tag for tag from the same build. `docker pull comicarr/comicarr:latest` works, matching what the website has been advertising. Nothing changes for existing installs — `ghcr.io/frankieramirez/comicarr` remains the canonical reference and is still what the update instructions point at, since GHCR does not rate-limit anonymous pulls.
- 5dc0876: Fixed the `docker pull` command in the update-available popover, which pointed at an image tag that does not exist. Comicarr publishes bare-semver tags (`0.26.0`), but the popover copied a `v`-prefixed reference (`ghcr.io/frankieramirez/comicarr:v0.26.0`) that fails with a manifest-not-found error. The surrounding advice was also incomplete: pulling an image never moves a running container onto it, but the popover implied a plain pull was enough. Both paths are now spelled out — set the pinned tag in your compose file and `up -d`, or stop and remove the container and re-run it. The README says the same.

## 0.26.0

### Minor Changes

- 2999227: Needs attention now has a "select all" checkbox in the filter bar, so every visible issue can be selected at once instead of checking cards one by one. It follows the active filters — narrow to Failed or the last 7 days first and only those issues are grabbed — and it shows a dash when only some are picked.
- a85a8bc: The needs-attention band no longer asks you to babysit failures Comicarr can handle itself. After a restart, downloads that vanished from the client, bad DDL links, and similar dead ends are returned to the acquisition cycle automatically — blocklisted when the release is gone, re-wanted so the next sweep can find a different source — instead of stacking up as hundreds of red cards you can only "retry" by hand.

  What still needs you stays on the band: files that downloaded but never made it into the library, downloads waiting on a decision only you can make, and failures where you turned auto-handling off. Those still group by series and cause, still open the Needs attention page, and still clear only when you act.

  Under the hood every failure reason is classified once, in code. New reasons have to declare whether they belong on the band before they can merge, so the next bulk failure can't recreate the old pile.

## 0.25.0

### Minor Changes

- 9a629c7: The needs-attention band no longer buries the Activity timeline. Instead of one red row per failure — several hundred of them on a busy install, pushing the feed off the bottom of the page — the band now shows at most five cards in a single fixed-height row, and the timeline sits directly beneath it no matter how much has gone wrong.

  Failures are grouped by series and cause, so a restart that stranded 47 issues of one title reads as one card marked `×47` rather than 47 identical lines. Each card names the series, says what went wrong in plain language instead of `downloaded_invalid_artifact_command:PostProcessCommandError`, and is colour-coded by what it wants from you: red when Comicarr couldn't finish, amber when it's waiting on your decision. Newest trouble ranks first.

  A new **Needs attention** page at `/activity/attention` is where you actually work through them. It lists every group, filters by stage and age, searches by series or reason, and lets you select several at once. The `⚠ N need attention` count in the status bar now counts distinct problems rather than rows, and clicking it lands here. Activity keeps its three tabs — Timeline, Direct Downloads, Download History — unchanged.

  Group and bulk actions fan out over every issue behind a card in one click. Failures are per-issue: if one of sixteen can't be retried, the other fifteen still clear and you get told which one didn't, rather than losing the whole batch. Comicarr processes 25 issues per action and says how many it left for the next click.

  **Ignore is now Stop wanting**, everywhere. It always meant "mark this ignored in the library and stop searching for it" — not "dismiss this alert" — and the old name invited the wrong reading. Stopping two or more issues at once now asks you to confirm, naming the series, the count, and what happens.

## 0.24.1

### Patch Changes

- ea4f1b2: Open Activity surfaces now refresh the moment work happens instead of waiting out the 30s poll, and they catch up immediately after a dropped connection. Bursty work — a search run grabbing dozens of issues — costs one refresh, not one per issue.

  Toasts are quieter and more useful: Comicarr interrupts you once when something starts needing attention, then stays silent until the needs-attention count clears. Routine progress no longer toasts at all. The noisy "Search Complete", "Task Complete", and duplicate "Series Added" pop-ups are gone; the Activity timeline carries that history instead. A server restart now says so, and the status bar reports `unreachable` when the connection has been down long enough to matter rather than only after the next health check.

- 3e18796: Pagination controls on Library, Search, Wanted, and Activity now stay on the bottom edge of the window. The rows scroll inside the table while the page header, filters, and the pager stay in place, so moving to the next page no longer means scrolling to the end of the list first.

  Every table now shares one footer: it reads `21–40 of 143` so you can see where you are in the results rather than just how many there are, and single-page tables drop the pager instead of showing prev and next greyed out.

## 0.24.0

### Minor Changes

- 9301ee5: The Activity timeline now records real library work as it happens — grabs, downloads, imports, series adds and refreshes, metatagging, and search run summaries — instead of the old unused global message slots. Failed downloads and completed search runs show up as plain-language rows with distinct reasons.

## 0.23.0

### Minor Changes

- cc88c15: Activity now opens on a Timeline tab (with Direct Downloads and Download History beside it). A pinned needs-attention band shows actionable failures above a ledger-style feed of plain-language stories, and series/issue detail pages deep-link into a scoped Activity view.
- e6e12af: The bottom status bar now shows quiet activity counts (`M in flight`, optional `⚠ K need attention`, or `idle`) instead of the old DDL `queue: N active` line. Click the activity text to open Activity.
- 690acb9: After an upgrade, Comicarr shows a What's New modal once until you acknowledge it, and keeps a permanent What's new history under Settings → About.

## 0.22.0

### Minor Changes

- de44564: Comicarr now runs a daily **Ledger Retention** job that prunes old acquisition, pipeline journal, maintenance, and AI activity ledger rows under fixed age and count rules, so those tables stop growing without bound.
- 8c86384: Failed and manual-review downloads on the needs-attention work queue can be cleared with retry, search again, ignore, or import — without rewriting pipeline stage history.
- 60a8c70: When release announcements are enabled (`announce_releases = True` under `[Git]` in `config.ini`; default off), Comicarr sends **one** outbound message through every enabled notifier after a check finds the install behind — body is `{current} → {latest}` plus the GitHub release URL. The same remote version is not re-announced every check interval. Snatch/grab notifier flags are not reused.
- c58a06a: Settings → About now has an **Updates** group: turn automatic release checks on or off, choose whether to announce releases through enabled notifiers, see why update status looks quiet (including air-gapped or rate-limited installs), and run **Check now** even when automatic checks are off.
- 4bd5691: When an update is available, the sidebar version pill shows a quiet status dot. Opening it compares your install to the latest release, loads What’s new from the shared notes pipeline, and offers install-type **How to update** steps plus a Release link — without applying the update in-app.

## 0.21.0

### Minor Changes

- fca4d33: Update checks now compare the Changesets release version against GitHub `releases/latest` (semver `behind` / `current` / `unknown`) instead of counting commits. `GET /api/system/version` exposes `update_state`, `update_reason`, `release_version`, and a v-stripped `latest_version`; `commits_behind` is gone. Automatic release checks default **on** for new and existing installs (config version 16 rewrites a still-`False` `CHECK_GITHUB` to `True`). Comicarr contacts GitHub every 6 hours when checking is enabled — set `check_github = False` under `[Git]` in `config.ini` to opt out. The dead update toast path and `AUTO_UPDATE` self-apply are retired.
- 9522693: Wanted rows now show a live-sticky search annotation (searching…, no match · N tries, never searched) from the latest acquisition run item, without changing when an issue leaves Wanted.

### Patch Changes

- 0d586ab: Default `GIT_USER` now points at the Comicarr project owner so update checks hit the real repository instead of an unrelated third-party one.
- 32b9084: Failed downloads now terminalize `pipeline_journal` so needs-attention and in-flight counts stay honest when a download fails or auto-retry re-searches.

## 0.20.12

### Patch Changes

- e1601bf: Show one release version across the sidebar, Settings, and About instead of mixing the package badge with a git SHA or stale install metadata.
- b7c8c6d: Render unknown series issue dates as a placeholder instead of the `0000-00-00` storage sentinel.
- 5ec70d4: Wanted filtering now searches the full queue, not only the currently loaded page. Typing a filter term sends it to `/api/wanted` so match count, pagination total, and Next/Previous all describe the same filtered result set — matches that used to sit on page 2 are no longer invisible from page 1.

## 0.20.11

### Patch Changes

- ad7a747: Fix the AI chat thread list returning HTTP 500 on ordinary page loads after upgrading past pre-library-chat installs. Schema validation now requires the complete schema for the _stamped_ Alembic revision rather than the migration head, so `0002` databases missing `ai_chat_*` tables can reach `0003_library_chat` and the recent-chats endpoint can return an empty or populated list.
- 14b0403: Keep Library list series titles readable at phone widths by adapting the list row to a title-first three-column layout below the md breakpoint.
- d9970c1: Fix series issue title links so they open the issue detail page instead of redirecting to the Dashboard
- 88832e9: Fix Story Arcs search so Enter, the Search button, and the empty-state action submit the query and render provider results or clear empty/error states

## 0.20.10

### Patch Changes

- d1b93d0: Opening the Library with an out-of-range page in the URL (e.g. `?page=99`) still shows the last real page, but the URL is no longer rewritten to that page — it stays exactly as entered. The rewrite could not tell "rows have not loaded yet" from "genuinely past the end", which is what used to strip the page from cold deep links.

## 0.20.9

### Patch Changes

- 923ad54: Clearing an AI number field (timeout, requests per minute, daily token limit) no longer fails the whole settings save with "Failed to save configuration" — the field now falls back to its default (30 / 20 / 100000) like the other numeric settings.
- 12916e8: The Metron Password field in Settings → API now actually saves. `METRON_PASSWORD` was never registered as writable, so every save silently dropped it — the "Password saved" indicator could only ever reflect a value set outside the UI. The password is stored encrypted like the other secrets, and an empty field leaves a previously saved password unchanged.
- 2617227: Fix the Library table keeping a filtered-out series selected. Selecting a series and then filtering it out of view left it selected: the bulk bar still read "1 selected" and Delete, Pause, and Resume would still act on a series you could no longer see. The selection now follows the view — a series the filters remove is dropped from the selection, and comes back deselected when the filter is cleared. Selections still survive paging, since a series on another page is only out of sight, not filtered out.

## 0.20.8

### Patch Changes

- 6a4b634: Remove the unreachable `IssuesTable` component and the code that existed only to support it. The component was dropped from the series detail page during the frontend redesign and has had no caller since, along with its bulk-metatag hook, progress-bar cell and two supporting types. No user-visible behaviour changes.

## 0.20.7

### Patch Changes

- 3ca42aa: Re-raise SystemExit after config transaction rollback instead of swallowing it as a failed save
- f12c991: Fix the Library page dropping a deep-linked page number. Opening or reloading `/library?page=2` rendered the first page and stripped `page` from the URL, so bookmarks and shared links always landed on page one. Two independent causes had to be addressed: the page-clamp effect ran while the series list was still empty, and TanStack Table's automatic page reset fired after the first render that had rows, undoing the page the URL asked for. A page number that is genuinely out of range still settles onto the last page, and changing the row set still returns you to the first page.

## 0.20.6

### Patch Changes

- 979d94c: Upgrade `nuqs` to 2.9.2, which fixes an upstream bug where URL-backed state could permanently desync from the URL after React discarded a render (nuqs#1501). The library's React Router adapter on React 19 was affected, and the Library page's sorting, filtering and pagination are the state this repo keeps in the URL.

## 0.20.5

### Patch Changes

- 1876c6f: Fix Mylar3 config migration discarding every setting when the source config used NZBsu or DOGnzb

  `_BAD_DEFINITIONS` carried seven remapping entries for NZBsu and DOGnzb — providers Mylar3 shipped built in and Comicarr no longer defines. `migrate_mylar3_config` reads that table independently of `_CONFIG_DEFINITIONS`, so a `config.ini` with an `[NZBsu]` or `[DOGnzb]` section produced keys nothing could define. `process_kwargs` then raised `KeyError` inside `writeconfig`, and the caller swallowed it as "config migration failed (data migration succeeded)" — so all 400+ settings were dropped and the install came up on defaults, with one log line as the only trace.

  The seven entries are removed, and the migration now skips any undefined key with a warning instead of losing the whole batch to it.

## 0.20.4

### Patch Changes

- ecc6cd8: Honour the file operation setting when finalizing a manual import. Confirming an import always moved files into the series folder regardless of whether File Operations was set to copy, hardlink, or softlink — so operators using a link mode to keep their download folder intact lost the source file on every manual import. Finalization now copies, hardlinks, or symlinks to match the setting, and only consumes the source under `move`.
- 85d1830: Route manga post-processing through the shared file placement stage. Sixty-five lines of replace-what-is-there policy — recognising a chapter an earlier pass already placed, moving an existing chapter aside rather than deleting it, putting it back when placement fails — move out of the post-processor and into the one module that owns placement.
- 3462841: Route the remaining post-processor file placements through the shared placement stage, so every one of them reads the file operation setting at the moment it runs rather than from a value passed in earlier.
- 0ab31e2: Route story-arc directory placement through the shared placement stage and remove the two legacy file-operation helpers it was the last caller of. Every file Comicarr places now goes through one module that reads the file operation setting at the moment it runs, and an architecture test keeps it that way.

## 0.20.3

### Patch Changes

- 5eab8db: Surface the actual reason a search is blocked instead of a generic placeholder.

  When no acquisition route was handoff-ready, the search-missing preview and the
  Wanted force-search both read a `reason` key that `get_search_health()` never
  returns, so every blocked search reported `no_viable_acquisition_route` no matter
  the cause. Route readiness already computes a specific blocker per route
  (`path_not_ready`, `client_not_ready`, `disabled`, `providers_temporarily_blocked`,
  a maintenance hold); the blocked response now reports the one closest to ready,
  and the series search dialog explains it in plain language while keeping the raw
  code visible for support.

- f01a1f7: Add a single file placement stage that reads the file operation setting at call time. Callers pass intent — what the file is for, and what to do if the destination is occupied — instead of a resolved mode, so no caller can bind a stale setting and place a file the wrong way. Nothing routes through it yet.

## 0.20.2

### Patch Changes

- 1ff6148: Record API key regeneration as an audit log event with the user and originating IP. Rotation revokes every outstanding API credential, so integrations start failing immediately — previously nothing in the log explained why.

## 0.20.1

### Patch Changes

- 8c6a834: Route every "is this manga, and which provider owns it?" decision through a single `series_kind` module instead of 23 copied ID-prefix checks.

## 0.20.0

### Minor Changes

- ea4b9e9: Add a dedicated saved Library Chat workspace with image attachments.
- ea4b9e9: Redesign the chat workspace and move its entry point out of the sidebar navigation. Chat now opens from a pinned "Ask Comicarr" launcher above the account menu (or ⌘⇧K), the workspace gains a grouped and searchable thread rail, a thread header with the answering model, and a calmer transcript, and the dashboard gets an ask bar plus a recent-chats list in place of the command hint card.

### Patch Changes

- ea4b9e9: Report a pull-list outage in plain language instead of dumping raw response
  headers into the log. When the pull-list host is unhealthy, Cloudflare answers
  on its behalf; only one of those replies was recognised, so the rest were
  logged as an unreadable header dump. All of them now explain that the source is
  temporarily unreachable and that the data shown may be stale, including how
  long upstream asked us to wait when it says so.

## 0.19.14

### Patch Changes

- 1f58860: Fix torrents snatched through qBittorrent, Transmission or uTorrent never being
  monitored. They were sent to the client successfully and then left in Snatched
  forever: nothing polled them, post-processing never ran, and a restart could not
  pick them back up. All five torrent clients are now polled through one code
  path, and a client being unreachable is kept distinct from a torrent genuinely
  being gone, so an outage no longer looks like a lost download.

  The auto-snatch worker now also starts for uTorrent, Transmission and
  qBittorrent — and for a local-post-processing-only setup — so the releases those
  clients queue are actually consumed instead of piling up unread. Torrents paused
  for the local post-processing copy are resumed even when the copy fails, the
  on-snatch script keeps firing for the three newly monitored clients, and every
  qBittorrent and uTorrent WebUI call now has a timeout so one hung client can no
  longer stall monitoring for every download.

- b5ec0d4: Fix saving settings failing whenever the RSS check interval or database update
  interval was changed. Both fields were sent under names the configuration did
  not recognise, which rolled back the entire save — every other setting changed
  at the same time was discarded without a visible error.

  Interval changes now also reach the running scheduler, which they never did, so
  a new search or RSS cadence takes effect without a restart. The database update
  interval is a real setting now and survives a restart instead of resetting to 24
  hours.

  Setting an interval to zero and then correcting it no longer leaves that
  background job switched off. Jobs paused deliberately — from the jobs page, or
  by turning RSS off — still stay paused. A database update interval below an
  hour is raised to an hour, the way the search and RSS intervals already were,
  so a negative value can no longer schedule the updater to run without pause.

- 332bab6: Fix MyAnimeList cover art being blocked by the browser security policy. The
  list of hosts trusted to serve cover images and the Content-Security-Policy
  that permits the browser to load them are now derived from one source, so they
  cannot drift apart again.
- 95fba47: Fix MyAnimeList manga series being treated as comics in two places: downloads
  were post-processed down the ComicVine path instead of the manga path, and the
  scheduled chapter check skipped them entirely, so they never picked up new
  chapters. MangaDex-added series now also record their MangaDex id, which the
  "already in library" check on search results depends on.
- 159f47e: Fix bulk actions on the Wanted and Upcoming lists doing nothing. Selecting rows
  never registered, so the action bar reported no selection and Search or Skip ran
  against an empty set.

  Clearing the selection, changing page, or a row disappearing now also unchecks
  the rows, so a later bulk action cannot skip issues you already cleared or that
  are no longer on screen. A bulk Skip or Mark Wanted that fails partway through
  now reports how many issues were applied and keeps only the failures selected,
  instead of reporting a total failure and retrying the ones that succeeded.

- 98cb480: Fix manga post-processing deleting the downloaded file when the file operation
  is set to hardlink or softlink. Both modes are meant to leave the download in
  place; the manga path moved it regardless, so the original was destroyed. It now
  uses the same mode-aware file placement as the rest of post-processing.

  Manga chapters that are already in the library also import correctly again. A
  repack, a manual re-run, or a post-crash retry now replaces the existing file
  under every file operation mode, instead of failing on the hardlink and softlink
  modes and leaving the chapter unimported.

- 117321b: Fix the version and update-available information never changing after startup.
  The scheduled version check wrote to a copy of the state that the API does not
  read, so a new release was never reported once the process was running. The
  branch name, which nothing ever set, is now reported too. A version check that
  fails to reach GitHub now keeps the last known result instead of reporting
  "up to date".

## 0.19.13

### Patch Changes

- 544eb20: Fix MAL manga series: rescan no longer crashes on chapters without dates, Refresh routes `mal-` IDs through the MAL importer instead of ComicVine, and MAL cover images now display (CSP allowlist plus local cover caching).

## 0.19.12

### Patch Changes

- d692778: Prevent manual imports from overwriting files created during finalization.

## 0.19.11

### Patch Changes

- 7d1c77a: Fix Library pagination controls resetting to the first page.

## 0.19.10

### Patch Changes

- ecf8b0c: Fix Library filters (empty dropdowns, double chevrons, broken search) and unify view toggle, search, and filter chips into one action bar.

## 0.19.9

### Patch Changes

- ad8a35a: Restore legacy MyAnimeList manga covers by normalizing provider image URLs to the MAL CDN.

## 0.19.8

### Patch Changes

- b56f7dc: Restore manga covers and chapter rows when adding MAL series, and fix library inbox matching so scanned manga files can be processed.

## 0.19.7

### Patch Changes

- fd4af61: Show live library, API, and download queue status in the application top bar.

## 0.19.6

### Patch Changes

- ac143fa: Improve the application error recovery screen with clearer guidance and reload controls.

## 0.19.5

### Patch Changes

- 3d626f0: Revoke all active UI sessions durably on logout while preserving the current session when secure key rotation fails.
- 2f59687: Persist additional Newznab and Torznab credentials transactionally with encrypted API keys and truthful save failures, while scrubbing provider secrets from diagnostics and retained config backups.
- 64aea8c: Keep clients, database connections, and runtime context open for terminal process exit when a scheduler job or worker remains alive after its bounded shutdown drain.
- 61249df: Harden bundled downloader integrations and package vendor clients under Comicarr's supported namespace.
- 5bd9fdf: Fix modern backend correctness hazards and enforce a strict lint ratchet for active application code.
- 0433c04: Reject empty, multiple, partial, unknown, and structurally spoofed Alembic revision states before schema mutation, and verify legacy adoption across every supported database dialect.

## 0.19.4

### Patch Changes

- 2e0b8da: Fix library scan reconciliation so detected files are recorded on their issues, and sort matched scan results before unmatched folders.

## 0.19.3

### Patch Changes

- 743a908: Fix library scans so existing comic series are reconciled instead of reported as unmatched.

## 0.19.2

### Patch Changes

- 59fd790: Make library scan progress and import confirmation visible across the Dashboard and Import pages.
- d5d338f: Keep search route loading visible, harden health diagnostics, and allow a single Wanted issue to be searched without forcing the backlog.
- 0f19c09: Reconcile scanned comic folders with existing series and show the outcome in Import.

## 0.19.1

### Patch Changes

- 5816867: Prioritize operator-requested searches over restart recovery, ensure configured Torznab providers are searched, and expose safe provider-attempt diagnostics.

## 0.19.0

### Minor Changes

- b95001e: Restore reliable comic acquisition and recovery: durable search/refresh workers, reservation-before-submit handoffs, acquisition run ledgers, route health, evidence-driven repair, and server-side Search all missing. Add an operator recovery runbook; the current canary permit authorizes or cancels one exact handoff, while a future persisted-candidate executor is required before it can prove a full production canary.

## 0.18.9

### Patch Changes

- 7157998: Restore current operational dashboard data and add a safe, observable weekly release refresh.

## 0.18.8

### Patch Changes

- 476e5bd: Fix scheduled updates for manga libraries, rebuild Activity with searchable sortable paginated tables, show accurate live queue counts and relative activity times, and add a dashboard library-scan action.

## 0.18.7

### Patch Changes

- 860faea: Show the real app version in the sidebar, login screen, and onboarding welcome step instead of a hardcoded 0.15 / v0.15.1 badge.

## 0.18.6

### Patch Changes

- 0450b4a: Keep server-sent event streams responsive under burst traffic by replacing stale queued updates without emitting event-loop errors.
- 2de9e62: Deduplicate legacy database rows across migration batches and report target constraint conflicts as failed migrations.
- a9df84e: Fix AI library completion filters so percentage queries work on SQLite and preserve inclusive bounds, ordering, and limits.
- 8f8fd4e: Validate and persist reconstructable direct-download jobs, keep malformed jobs from stopping the worker, and hold the GetComics download lock through archive publication.
- cd53fb6: Keep provider downloads inside Comicarr's configured directories, publish completed files atomically, and reject remote ZIP archives that would expand beyond safe resource limits.
- d8a05f1: Validate series directories against configured library roots and preserve database records when directory removal fails.
- e1cbccf: Repair atomic upserts on legacy SQLite databases with an isolated safety snapshot and transactional unique indexes that preserve historical null or empty-key rows.
- ee651ca: Persist config changes through a shared transaction boundary, encrypt secrets before disk writes, preserve private file permissions, and report storage failures without committing runtime config state.
- 7298807: Stop logging 32P runtime credentials and scrub previously written credential lines from support carepackages.

## 0.18.5

### Patch Changes

- 027d784: Harden artwork cache paths and cover image fetches against path traversal and SSRF (allowlisted hosts, no redirects, size and content-type caps).
- 37ff1f7: Fix Discord and sibling webhook notifiers so successful deliveries are reported correctly and network errors return false instead of raising.

## 0.18.4

### Patch Changes

- 2ef88d3: Fix API key regeneration persistence, secret redaction handling, dependency floors, and E2E regression coverage.

## 0.18.3

### Patch Changes

- 2a6b0db: Fix manual import matching so selected files are finalized before pending import rows are marked imported.

## 0.18.2

### Patch Changes

- b29dad4: Fix manual import matching so selected manga imports are finalized and stale pending import records can be ignored or deleted from the review table.

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.18.1](https://github.com/frankieramirez/comicarr/compare/v0.18.0...v0.18.1) (2026-06-09)

### Bug Fixes

- address open GitHub issues [#149](https://github.com/frankieramirez/comicarr/issues/149), [#150](https://github.com/frankieramirez/comicarr/issues/150), [#158](https://github.com/frankieramirez/comicarr/issues/158), [#159](https://github.com/frankieramirez/comicarr/issues/159) ([#161](https://github.com/frankieramirez/comicarr/issues/161)) ([b4bbc97](https://github.com/frankieramirez/comicarr/commit/b4bbc978e5907466ccef17572fb3609baea402ff))

## [0.18.0](https://github.com/frankieramirez/comicarr/compare/v0.17.1...v0.18.0) (2026-05-17)

### Features

- Restart-durable download/post-process pipeline ([#156](https://github.com/frankieramirez/comicarr/issues/156)) ([49b569f](https://github.com/frankieramirez/comicarr/commit/49b569fe37970862c61408836bc43dce2c0456fd))

## [0.17.1](https://github.com/frankieramirez/comicarr/compare/v0.17.0...v0.17.1) (2026-04-20)

### Bug Fixes

- Render issue rows on series detail page ([#141](https://github.com/frankieramirez/comicarr/issues/141)) ([ba24726](https://github.com/frankieramirez/comicarr/commit/ba247265a9a4f7dad0a8767be56201b3646aabd0))

## [0.17.0](https://github.com/frankieramirez/comicarr/compare/v0.16.0...v0.17.0) (2026-04-19)

### Features

- Align library, releases, and wanted tables with redesign ([#139](https://github.com/frankieramirez/comicarr/issues/139)) ([4993293](https://github.com/frankieramirez/comicarr/commit/4993293c9956277704f17bdd2a4160eb6d4d94eb))

## [0.16.0](https://github.com/frankieramirez/comicarr/compare/v0.15.1...v0.16.0) (2026-04-19)

### Features

- Major frontend redesign ([#137](https://github.com/frankieramirez/comicarr/issues/137)) ([255438c](https://github.com/frankieramirez/comicarr/commit/255438c9794787cfbd260c167d4a4c3398b9181c))

## [0.15.1](https://github.com/frankieramirez/comicarr/compare/v0.15.0...v0.15.1) (2026-04-15)

### Bug Fixes

- Resolve library pagination not responding to clicks ([#135](https://github.com/frankieramirez/comicarr/issues/135)) ([db39a8b](https://github.com/frankieramirez/comicarr/commit/db39a8ba8cb30a0486fb9c7080540efd4b3a3fcd))

## [0.15.0](https://github.com/frankieramirez/comicarr/compare/v0.14.0...v0.15.0) (2026-04-14)

### Features

- Add list/grid view toggle to library page ([#133](https://github.com/frankieramirez/comicarr/issues/133)) ([7c76e2b](https://github.com/frankieramirez/comicarr/commit/7c76e2bc3cfbbd2747c336b97a351872657a3e99))

## [0.14.0](https://github.com/frankieramirez/comicarr/compare/v0.13.0...v0.14.0) (2026-04-14)

### Features

- Restructure information architecture for modern UX ([#131](https://github.com/frankieramirez/comicarr/issues/131)) ([896c788](https://github.com/frankieramirez/comicarr/commit/896c788107d4e48742e5253d9eb6398c233db79e))

## [0.13.0](https://github.com/frankieramirez/comicarr/compare/v0.12.2...v0.13.0) (2026-04-14)

### Features

- Persist Series page table state in URL via nuqs ([#129](https://github.com/frankieramirez/comicarr/issues/129)) ([80c1777](https://github.com/frankieramirez/comicarr/commit/80c17773bc8e593076fc0df6863f61b91de6cc07))

## [0.12.2](https://github.com/frankieramirez/comicarr/compare/v0.12.1...v0.12.2) (2026-04-07)

### Code Refactoring

- Redesign Import Management into Library Scan + Import Inbox ([#117](https://github.com/frankieramirez/comicarr/issues/117)) ([a2533ef](https://github.com/frankieramirez/comicarr/commit/a2533efb15e19cf8d744e06cdfbb27cd4cd99696))

## [0.12.1](https://github.com/frankieramirez/comicarr/compare/v0.12.0...v0.12.1) (2026-04-07)

### Bug Fixes

- Manga import chapter population, cover caching, and series bulk actions ([#115](https://github.com/frankieramirez/comicarr/issues/115)) ([39636de](https://github.com/frankieramirez/comicarr/commit/39636de83ded726118b3a65fc8527959624ce895))

## [0.12.0](https://github.com/frankieramirez/comicarr/compare/v0.11.1...v0.12.0) (2026-04-07)

### Features

- Add MyAnimeList as primary manga metadata provider ([#113](https://github.com/frankieramirez/comicarr/issues/113)) ([5a68333](https://github.com/frankieramirez/comicarr/commit/5a68333540a8d13a5339440f38aaba9819705882))

## [0.11.1](https://github.com/frankieramirez/comicarr/compare/v0.11.0...v0.11.1) (2026-04-07)

### Bug Fixes

- Make Import page scan cards symmetrical (Comic + Manga side-by-side) ([#111](https://github.com/frankieramirez/comicarr/issues/111)) ([4fedd0b](https://github.com/frankieramirez/comicarr/commit/4fedd0b2c3c720fe7038aec2cb3d5e3ff0e4b586))

## [0.11.0](https://github.com/frankieramirez/comicarr/compare/v0.10.4...v0.11.0) (2026-04-06)

### Features

- Elevate manga to first-class citizen with full parity ([#110](https://github.com/frankieramirez/comicarr/issues/110)) ([ec68bbb](https://github.com/frankieramirez/comicarr/commit/ec68bbb9e1678e2d87d13d6ba1df4293d65035f1))

### Bug Fixes

- Add error fallback for broken images in Recent Downloads ([#108](https://github.com/frankieramirez/comicarr/issues/108)) ([8c63f74](https://github.com/frankieramirez/comicarr/commit/8c63f747a118bb921c0e7d41dd0243af2716497b))

## [0.10.4](https://github.com/frankieramirez/comicarr/compare/v0.10.3...v0.10.4) (2026-04-06)

### Bug Fixes

- Resolve broken dashboard images and AI banner issues ([#106](https://github.com/frankieramirez/comicarr/issues/106)) ([8010da1](https://github.com/frankieramirez/comicarr/commit/8010da1524f9722fac65466d655cc3f19e128ee4))

## [0.10.3](https://github.com/frankieramirez/comicarr/compare/v0.10.2...v0.10.3) (2026-04-06)

### Bug Fixes

- Clean up 9 frontend ESLint warnings for zero-warning baseline ([#96](https://github.com/frankieramirez/comicarr/issues/96)) ([a547170](https://github.com/frankieramirez/comicarr/commit/a54717026c83e2f6689d790f122d6f157be99386))

## [0.10.2](https://github.com/frankieramirez/comicarr/compare/v0.10.1...v0.10.2) (2026-04-06)

### Bug Fixes

- Resolve startup errors in git detection and job scheduler ([#103](https://github.com/frankieramirez/comicarr/issues/103)) ([c5dcb6b](https://github.com/frankieramirez/comicarr/commit/c5dcb6b3e9d27eff5bd4808c4795ec4ce582fd8e))

## [0.10.1](https://github.com/frankieramirez/comicarr/compare/v0.10.0...v0.10.1) (2026-04-06)

### Bug Fixes

- Replace MySQL-only right/concat with SQLite-compatible substr ([#101](https://github.com/frankieramirez/comicarr/issues/101)) ([4cd03a5](https://github.com/frankieramirez/comicarr/commit/4cd03a5c55541aaa5ce841595c43ab96caacec04))

## [0.10.0](https://github.com/frankieramirez/comicarr/compare/v0.9.8...v0.10.0) (2026-04-06)

### Features

- BYOK AI Suite — LLM-Powered Intelligence Layer ([#99](https://github.com/frankieramirez/comicarr/issues/99)) ([1e8e501](https://github.com/frankieramirez/comicarr/commit/1e8e5018b9e0509ca87c7f73f11a4cf1f3852253))

## [0.9.8](https://github.com/frankieramirez/comicarr/compare/v0.9.7...v0.9.8) (2026-04-05)

### Bug Fixes

- Remove deprecated Vitest 4 poolOptions config ([#95](https://github.com/frankieramirez/comicarr/issues/95)) ([ed5b56d](https://github.com/frankieramirez/comicarr/commit/ed5b56dd73baa0ee36ab524e155663e81d59da65))

## [0.9.7](https://github.com/frankieramirez/comicarr/compare/v0.9.6...v0.9.7) (2026-03-25)

### Bug Fixes

- Resolve settings page showing empty pre-filled values ([#84](https://github.com/frankieramirez/comicarr/issues/84)) ([cabc4bc](https://github.com/frankieramirez/comicarr/commit/cabc4bc75b9a75dbb925b393732c6b20bf614f9b))

## [0.9.6](https://github.com/frankieramirez/comicarr/compare/v0.9.5...v0.9.6) (2026-03-25)

### Bug Fixes

- Constrain search result hover cards to prevent viewport overflow ([#81](https://github.com/frankieramirez/comicarr/issues/81)) ([b8e0362](https://github.com/frankieramirez/comicarr/commit/b8e036211671da2ddf763bf83e17f66fed11e45a))

## [0.9.5](https://github.com/frankieramirez/comicarr/compare/v0.9.4...v0.9.5) (2026-03-25)

### Bug Fixes

- Skip unexpanded git export-subst placeholders in version display ([#79](https://github.com/frankieramirez/comicarr/issues/79)) ([4322e01](https://github.com/frankieramirez/comicarr/commit/4322e0107823d1e8edf578d922a1b0b2d7267ee2))

## [0.9.4](https://github.com/frankieramirez/comicarr/compare/v0.9.3...v0.9.4) (2026-03-25)

### Bug Fixes

- Resolve asyncio.get_event_loop() errors in all system router endpoints ([#77](https://github.com/frankieramirez/comicarr/issues/77)) ([5965606](https://github.com/frankieramirez/comicarr/commit/596560658d09fdb6d97237a2edbe82eeded4f2d2))

## [0.9.3](https://github.com/frankieramirez/comicarr/compare/v0.9.2...v0.9.3) (2026-03-25)

### Bug Fixes

- Resolve UnboundLocalError in job_management and KeyError in DDL health check ([#75](https://github.com/frankieramirez/comicarr/issues/75)) ([a649d50](https://github.com/frankieramirez/comicarr/commit/a649d509452dae57c16f995a051a5bd82e92e97d))

## [0.9.2](https://github.com/frankieramirez/comicarr/compare/v0.9.1...v0.9.2) (2026-03-25)

### Bug Fixes

- Remove leftover CherryPy dependencies blocking Docker startup ([#73](https://github.com/frankieramirez/comicarr/issues/73)) ([c51526e](https://github.com/frankieramirez/comicarr/commit/c51526e30fabeaf9482e22b957e5586f92aff224))

## [0.9.1](https://github.com/frankieramirez/comicarr/compare/v0.9.0...v0.9.1) (2026-03-25)

### Bug Fixes

- Include version in settings page config response ([#69](https://github.com/frankieramirez/comicarr/issues/69)) ([f59c89b](https://github.com/frankieramirez/comicarr/commit/f59c89b3d2bce81df233e989708f9543ad5f79b4))

## [0.9.0](https://github.com/frankieramirez/comicarr/compare/v0.8.0...v0.9.0) (2026-03-25)

### Features

- FastAPI migration with vertical domain decomposition ([07f79ad](https://github.com/frankieramirez/comicarr/commit/07f79ad07158f19a9b9f1bf035dc327381ce04ad))

## [0.8.0](https://github.com/frankieramirez/comicarr/compare/v0.7.0...v0.8.0) (2026-03-24)

### Features

- Enrich search results with additional API metadata ([#65](https://github.com/frankieramirez/comicarr/issues/65)) ([e7fd739](https://github.com/frankieramirez/comicarr/commit/e7fd7395160aebc24a0abd098daf42fe43a574ff))

## [0.7.0](https://github.com/frankieramirez/comicarr/compare/v0.6.0...v0.7.0) (2026-03-24)

### Features

- Add content source toggles for comic-only or manga-only experience ([#63](https://github.com/frankieramirez/comicarr/issues/63)) ([d214139](https://github.com/frankieramirez/comicarr/commit/d2141394ea41689270aa8696a59a399a1f859320))

## [0.6.0](https://github.com/frankieramirez/comicarr/compare/v0.5.0...v0.6.0) (2026-03-24)

### Features

- Migrate all tables to DataTable component with OpenStatus data-table ([#62](https://github.com/frankieramirez/comicarr/issues/62)) ([f92ee50](https://github.com/frankieramirez/comicarr/commit/f92ee50f60e70f4f1591794d960462b5b26d8adb))

### Bug Fixes

- resolve weekly table KeyError and add version display to Settings ([#60](https://github.com/frankieramirez/comicarr/issues/60)) ([5662361](https://github.com/frankieramirez/comicarr/commit/5662361ac0f32aea98ed9c6660e7be1f92d0e9ca))

## [0.5.0](https://github.com/frankieramirez/comicarr/compare/v0.4.4...v0.5.0) (2026-03-24)

### Features

- Build complete Story Arcs frontend and fix backend gaps ([#58](https://github.com/frankieramirez/comicarr/issues/58)) ([6868e74](https://github.com/frankieramirez/comicarr/commit/6868e74b705019697df91c236c0e057850bae90c))

## [0.4.4](https://github.com/frankieramirez/comicarr/compare/v0.4.3...v0.4.4) (2026-03-24)

### Bug Fixes

- replace broken db.rawdb calls with direct raw_select_all/raw_select_one ([#56](https://github.com/frankieramirez/comicarr/issues/56)) ([d1a7429](https://github.com/frankieramirez/comicarr/commit/d1a7429b9c6d17e73091bf94014da37d7003a704))

## [0.4.3](https://github.com/frankieramirez/comicarr/compare/v0.4.2...v0.4.3) (2026-03-23)

### Bug Fixes

- dark mode issues in settings and remove placeholder UI ([#54](https://github.com/frankieramirez/comicarr/issues/54)) ([069f57e](https://github.com/frankieramirez/comicarr/commit/069f57e4955c28899d909a4957a3482f9612781e))

## [0.4.2](https://github.com/frankieramirez/comicarr/compare/v0.4.1...v0.4.2) (2026-03-23)

### Bug Fixes

- run uv lock in Docker build to handle version bumps ([27b610d](https://github.com/frankieramirez/comicarr/commit/27b610d2ca42316577ccc8ba1b2b67bfee44ad1b))

## [0.4.1](https://github.com/frankieramirez/comicarr/compare/v0.4.0...v0.4.1) (2026-03-23)

### Bug Fixes

- sync uv.lock and prevent stale lockfile on release ([#51](https://github.com/frankieramirez/comicarr/issues/51)) ([0efcc3e](https://github.com/frankieramirez/comicarr/commit/0efcc3e3c2d2bbb95c42ab24a47bfa8a6ec8457d))

## [0.4.0](https://github.com/frankieramirez/comicarr/compare/v0.3.0...v0.4.0) (2026-03-23)

### Features

- Automate releases with release-please ([#47](https://github.com/frankieramirez/comicarr/issues/47)) ([12adb79](https://github.com/frankieramirez/comicarr/commit/12adb79b4347b59f7bd583fb7b6fb11ff47ed005))

### Bug Fixes

- Metron search missing cover images + API hardening ([#48](https://github.com/frankieramirez/comicarr/issues/48)) ([639c9d3](https://github.com/frankieramirez/comicarr/commit/639c9d39a394fbbdebf4c7c3f0d1d6bb1195c4cd))

## [0.1.0] - 2026-03-21

### Added

- Modern React 19 frontend with Tailwind CSS 4, replacing the legacy jQuery/Bootstrap UI
- Real-time updates via Server-Sent Events (SSE)
- Dark and light theme support with system preference detection
- Smart search with parallel pagination and result caching
- Server-side search sorting with mode-aware controls
- Weekly pull list tracking up to 4 weeks ahead
- Story arc management with lazy loading
- Direct download support for Mega, MediaFire, and Pixeldrain
- Multi-stage Docker build with non-root user and dynamic PUID/PGID support
- GitHub Actions CI/CD: linting, testing (Python 3.10-3.12 matrix), and automated releases to GHCR
- Multi-architecture Docker images (amd64, arm64)
- Comprehensive test suite with unit, integration, and E2E tests

### Changed

- Rebranded from Mylar3 to Comicarr throughout the codebase
- Switched to `uv` for Python dependency management
- Upgraded to Python 3.12 runtime in Docker
- Upgraded to Node.js 22 for frontend builds
- Improved search performance with parallel provider queries
- Enhanced API key and credential handling — secrets are redacted in logs and CarePackage exports

### Fixed

- API key plaintext logging vulnerability
- SABnzbd integration regression
- ComicVine result display when MangaDex is disabled
- Various startup and configuration issues

### Attribution

Comicarr is built on the foundation of [Mylar3](https://github.com/mylar3/mylar3), created by the Mylar3 team. The original project provided the robust backend for comic management, downloading, and post-processing.
