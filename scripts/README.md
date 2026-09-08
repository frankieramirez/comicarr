# Repository helpers

Run these helpers with `bash` or `python3`; they do not need executable permissions.

## Search diagnostics

From the repository root:

```sh
bash scripts/monitor_performance.sh
bash scripts/view_search_stats.sh
```

Both helpers use the newest `/tmp/comicarr*.log`, falling back to a
`comicarr.log` beneath the repository root. The statistics helper requires GNU
grep (`grep -P`), so its default invocation is intended for Linux.

## Library inspection

Run these from your comic library directory, using the path to your checkout:

```sh
bash /path/to/comicarr/scripts/look4cbrs.sh
python3 /path/to/comicarr/scripts/look4untaggedcbzs.py
```

The first lists CBR archives recursively. The second checks CBZ archives for
`ComicInfo.xml`, appending reports to `notags.txt` and `badzip.txt` in the current
directory. Neither helper modifies comic archives.

These helpers previously lived at the repository root or under `utilities/`.
Update any local shortcuts to use their new paths.
