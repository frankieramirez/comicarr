---
title: "Broken cover images in Metron/provider search results"
category: ui-bugs
date: 2026-03-23
tags:
  - metron-api
  - cover-images
  - backend
  - frontend
  - csp
  - caching
  - thread-safety
severity: high
components:
  - comicarr/metron.py
  - comicarr/mb.py
  - comicarr/mangadex.py
  - comicarr/api.py
  - comicarr/webstart.py
  - comicarr/importer.py
  - frontend/src/hooks/useSearch.ts
  - frontend/src/pages/SearchPage.tsx
related_issues:
  - 48
---

# Broken cover images in Metron/provider search results

## Problem

When Metron API is enabled, comic search results display `ImageOff` placeholder icons instead of cover art. All 50 results per page show broken images. ComicVine and MangaDex fallback paths had the same underlying sentinel issue but were masked because those APIs return images directly in list results.

## Root Cause

Metron's `series_list()` API (via mokkari) returns `BaseSeries` objects with only: `id`, `year_began`, `issue_count`, `volume`, `modified`, `display_name`. No `image` field. The `api.series(id)` detail endpoint also lacks images. Only `CommonIssue` objects (from `api.issues_list()`) carry an `image` attribute.

The backend set `cover_url = "cache/blankcover.jpg"` — a relative path to a file that **does not exist** anywhere in the repository. CherryPy served a 404, the `<img>` tag errored, and the React `CoverThumbnail` component showed the `ImageOff` fallback.

The same phantom path was used across all three providers: `metron.py`, `mb.py` (ComicVine, including story arc path), `mangadex.py`, and `importer.py`.

Additional contributing factors:
- CSP `img-src` only whitelisted `comicvine.gamespot.com` — Metron and MangaDex image URLs would be blocked when CSP enforcement is enabled
- `get_series_image()` called `list(api.issues_list())` which fetched ALL issues across all pages just to get the first cover
- `_IMAGE_CACHE` was an unbounded `dict` with no thread safety (CherryPy runs 15 worker threads)
- Frontend `checkParams` rejected API calls without an `apikey` param, but the frontend relied on session auth

## Investigation Steps

1. Inspected mokkari library schemas — confirmed `BaseSeries` has no `image` field, `CommonIssue` does
2. Confirmed `api.series(id)` also has no `image` field — ruled out detail-fetch approach
3. Determined `api.issues_list({"series_id": id, "page": 1})` + `next(iter())` is the correct approach
4. Searched repo for `cache/blankcover.jpg` — file does not exist, found hardcoded in 4 backend files
5. Traced CSP header — only ComicVine's CDN was whitelisted
6. Traced API auth flow — `checkParams` had no session fallback

## What Didn't Work

A frontend-only `useMetronImages` React hook was attempted first. It detected Metron results with null images and fired throttled `getSeriesImage` API calls (max 4 concurrent), patching the React Query cache via `queryClient.setQueryData()`.

This was **fundamentally broken by React's effect lifecycle**. Each `setQueryData` call triggered a re-render, which produced a new `results` array reference, which re-ran the effect's dependency check, which cancelled the previous queue via the cleanup function. Only 1-4 images loaded before the cascade killed the queue.

Multiple restructuring attempts (stable `idsKey` dependency, `useMemo` for query keys, `fetchedRef` tracking, removing `cancelled` checks) all failed because the core problem is structural: React effects and `setQueryData` create unavoidable re-render cascades for batch operations.

The hook was removed and replaced with server-side parallel fetching.

## Working Solution

### 1. Replace `"cache/blankcover.jpg"` with `None` across all providers

```python
# metron.py — was: cover_url = "cache/blankcover.jpg"
cover_url = None

# mb.py — 5 locations in search and story arc paths
xmlimage = None
xmlthumb = None

# mangadex.py — _extract_cover_url fallback
return None

# importer.py — MangaDex import
"ComicImage": manga.get("cover_url"),
```

The frontend `CoverThumbnail` component already handles `null` images gracefully via the `ImageOff` fallback icon.

### 2. Server-side parallel image fetching via `_backfill_images()`

Called at the end of `search_series()` before returning results — images arrive with the search response:

```python
from concurrent.futures import ThreadPoolExecutor, as_completed

def _backfill_images(comiclist):
    needs_image = [(i, c["comicid"]) for i, c in enumerate(comiclist) if not c.get("comicimage")]
    if not needs_image:
        return
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(get_series_image, sid): idx for idx, sid in needs_image}
        for future in as_completed(futures):
            idx = futures[future]
            try:
                image_url = future.result()
                if image_url:
                    comiclist[idx]["comicimage"] = image_url
                    comiclist[idx]["comicthumb"] = image_url
            except Exception:
                pass
```

### 3. Fix `get_series_image()` to fetch only page 1

```python
# Before — fetched ALL issues across all pages:
issues = api.issues_list({"series_id": series_id})
issues_list = list(issues)  # Forces full pagination

# After — single page, single element:
issues = api.issues_list({"series_id": series_id, "page": 1})
first_issue = next(iter(issues), None)
```

### 4. Thread-safe bounded image cache

```python
_IMAGE_CACHE = OrderedDict()
_IMAGE_CACHE_MAXSIZE = 1000
_IMAGE_CACHE_LOCK = threading.Lock()

def _cache_image(series_id, value):
    with _IMAGE_CACHE_LOCK:
        _IMAGE_CACHE[series_id] = value
        _IMAGE_CACHE.move_to_end(series_id)
        while len(_IMAGE_CACHE) > _IMAGE_CACHE_MAXSIZE:
            _IMAGE_CACHE.popitem(last=False)
```

### 5. Session auth fallback in `checkParams`

```python
if "apikey" not in kwargs and kwargs["cmd"] != "getAPI":
    username = cherrypy.session.get("_cp_username")
    if username:
        self.apitype = "normal"
    else:
        self.data = self._failureResponse("Missing API key")
        return
```

### 6. CSP `img-src` whitelist update

At the time, the directive was hand-written:

```python
"img-src 'self' data: https://comicvine.gamespot.com https://static.metron.cloud https://uploads.mangadex.org",
```

> **Superseded — do not copy this shape.** Hand-maintaining the directive
> alongside the SSRF allowlist is what let the two drift apart twice more
> (#281, #298). As of PR #306 the CSP is derived from a single source; see
> Prevention Strategy 4 below.

### 7. Page size 50 → 20

Reduces Metron API pressure from 50 concurrent image fetches to 20 (capped at 4 workers).

## Prevention Strategies

1. **Never hardcode file paths as sentinels** — Use `None` for missing data. The frontend handles null images. Any new provider integration must follow this contract.

2. **Server-side batch enrichment over frontend effect cascades** — React `useEffect` + `setQueryData` creates unavoidable re-render cascades. Batch API enrichment belongs server-side.

3. **Thread-safe bounded caches in CherryPy** — Always use `threading.Lock` + bounded `OrderedDict`. Never bare `dict` — CherryPy's 15-thread pool guarantees concurrent access.

4. **Add image hosts in one place — never hand-edit the CSP** — A new provider's host goes into `ALLOWED_IMAGE_DOMAINS` in `comicarr/app/core/image_hosts.py` and nowhere else. The CSP `img-src` directive is derived from that set by `csp_img_src_origins()` (`comicarr/app/core/middleware.py`), so it updates itself. Hand-writing hosts into the directive re-creates the second copy that drifted in #281 and #298; `tests/unit/test_image_hosts.py` fails if the CSP stops being derived. Note that membership grants two powers — the server may fetch from the host, and the browser may render images from it.

5. **Browser-test the full auth flow** — Unit tests don't catch session/API key issues. The `getAPI` failure was only discoverable through actual browser testing.

6. **Respect external API rate limits** — Page size directly affects API call volume. 20 results × 4 concurrent workers is sustainable; 50 was not.

## Related Documents

- [Plan: Fix Metron Search Images](../../plans/2026-03-22-001-fix-metron-search-images-and-api-review-plan.md) — Original plan (Phase 2 frontend hook approach was abandoned in favor of server-side fetching)
- PR #48: fix: Metron search missing cover images + API hardening
