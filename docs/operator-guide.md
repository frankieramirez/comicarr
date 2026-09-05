# Operator guide

[Back to the README](../README.md) · [Documentation](https://comicarr.com/docs)

Use these controls after completing [initial setup](https://comicarr.com/docs/initial-setup).

## Series content kind

Open a series and use **Catalog this as** to choose **Comic** or **Manga**. It
works independently of the metadata provider, so a series added from ComicVine
can still use manga chapter labels and matching rules. The choice applies to
future searches, refreshes, and post-processing. It won't change the provider or
rewrite existing files and issue history.

## Interactive release search

Open **Releases**, stay on the **Mine** tab, and choose **Review releases** for
a Wanted issue. Comicarr searches the configured providers and opens a review
sheet with each release candidate's source, age, size, availability, and match
reasons. Provider failures remain visible even when other providers return
results.

**Review missing** on a series page runs that same review across every eligible
missing issue at once, and shows which of them each release would satisfy, so a
single grab can close out more than one. Per-issue review is still there on the
series and story-arc issue rows.

Selecting **Review grab** opens a final confirmation before Comicarr hands the
release to the configured download route. If a candidate was rejected only by an
operator-overridable match rule, you have to acknowledge that separately.
Comicarr never lets this workflow bypass an expired session, missing provider
result, duplicate or in-flight acquisition, unavailable download route, or
ownership check.

## Pack releases

Turn on **Allow packs** under a series' search options and Comicarr will match
multi-issue and multi-volume releases, which otherwise get discarded for
carrying no single issue number. `Solo Leveling v01-14` and
`Invincible #001-144` both qualify. Comicarr checks the pack against what the
series is still missing, and grabbing it marks every issue it covers as
Snatched, so "Search all missing" and **Review missing** stop hunting for those
issues individually.

Packs require torrent search to be enabled. Comicarr takes pack-shaped results
from any indexer, but sends the extra bare-title query that surfaces them only
to Torznab indexers, where pack releases live. Volume packs only ever match
volume-tracked series, so a `v01-14` release can never claim issues 1 through 14
of an issue-tracked comic. On manga series, Comicarr also recognizes numberless
complete-series releases such as `Solo Leveling (2021-2026) (Digital)` and
treats them as covering every issue you do not already have, leaving out any
issue published after the pack's own year span.

## Logging verbosity

Set verbosity to **0** for warnings and errors, **1** for normal output (the default), or **2** for debug output. The level applies to the console, log file, and web log viewer.

Set it wherever suits the install. An explicit startup argument takes precedence over the environment variable, which takes precedence over the level saved in Settings:

```bash
docker run -e COMICARR_LOG_LEVEL=2 ...   # Docker only
python3 Comicarr.py --log-level 2        # source install
```

For an existing Docker Compose install, add or uncomment this entry in the
`comicarr` service's `environment` section alongside the existing `PUID`,
`PGID`, and `TZ` entries in `docker-compose.yml`:

```yaml
services:
  comicarr:
    environment:
      - COMICARR_LOG_LEVEL=2
```

Keep the rest of the existing `docker-compose.yml` and apply the change with
`docker compose up -d`.

Changing it in **Settings** takes effect immediately, no restart. Leave `COMICARR_LOG_LEVEL` unset unless you are debugging: setting it wins over Settings on every restart. (`--quiet` still works as an alias for `--log-level 0`, but it is deprecated.)

When you are reproducing a problem, **Settings → Logs → New log** starts a fresh
`comicarr.log` so the viewer shows only what happened after you clicked. It asks
for confirmation first, and the old log is kept as a rotated archive under your
existing retention settings.
