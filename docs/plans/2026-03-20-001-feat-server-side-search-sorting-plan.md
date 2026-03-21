---
title: "Server-Side Search Sorting with Smart Defaults"
type: feat
status: active
date: 2026-03-20
---

# Server-Side Search Sorting with Smart Defaults

## Overview

Fix search result sorting on the search page so it works properly with smart defaults. Remove the broken unified "All" mode and simplify to two clean tabs (Comics / Manga), each with proper relevance defaults, a sort dropdown, and mode-aware sort options.

## Problem Statement / Motivation

Search results feel broken because:
1. **Wrong default sort** -- Comics default to `start_year:desc` instead of relevance. The first results for "Batman" are sorted by year, not by best match
2. **Unified mode is broken** -- "All" mode zips comics and manga (comic, manga, comic, manga...) which destroys both sources' sort orders. Two incompatible APIs can't share meaningful sort state.
3. **No sort dropdown** -- Sort is only accessible by clicking column headers, which don't expose all options (no relevance, follows, latest for manga)
4. **Sort options are mode-agnostic** -- Same 3 sortable columns regardless of comics/manga mode
5. **Mode switching bug** -- Switching from manga (sorted by `follows`) to comics sends invalid sort param to ComicVine API

## Proposed Solution

### 1. Remove Unified "All" Mode

Remove the "All" tab and `useUnifiedSearch` hook entirely. Two tabs: **Comics** and **Manga**. Each has its own sort options and pagination. Default tab is Comics.

### 2. Smart Default Sorts

| Mode | Default Sort | Implementation |
|------|-------------|----------------|
| Comics | Relevance (API natural order) | Omit `&sort=` from ComicVine URL |
| Manga | Relevance | Already works (`order[relevance]: desc`) |

**Backend change in `mylar/mb.py:56-72`:** When `sort` is `None` or `"relevance"`, omit the `&sort=` parameter from the ComicVine API URL entirely. The API's natural result order is the closest proxy for relevance.

### 3. Sort Dropdown with Mode-Aware Options

Add a `<Select>` dropdown above results with options that adapt per mode:

| Option | Comics | Manga |
|--------|--------|-------|
| Relevance | Yes (default) | Yes (default) |
| Year (Newest) | Yes | Yes |
| Year (Oldest) | Yes | Yes |
| Name (A-Z) | Yes | Yes |
| Name (Z-A) | Yes | Yes |
| Most Issues / Fewest Issues | Yes | No |
| Most Followed | No | Yes |
| Latest Upload | No | Yes |

Column headers remain clickable for quick direction toggle and sync with the dropdown.

### 4. Fix Mode-Switching Sort Bug

When switching modes, validate the current sort against the target mode's available options. If invalid, reset to the mode's default (relevance).

## Technical Considerations

### Backend Changes

- **`mylar/mb.py:56-72`** -- Modify `pullsearch()` to conditionally omit `&sort=` for relevance
- **`mylar/metron.py:32-41`** -- Add `'relevance': None` to SORT_MAPPING so relevance falls back to Metron's default order
- **`mylar/api.py:1356`** -- `_findComic()` already passes sort through; no change needed
- **`mylar/mangadex.py:224`** -- Already handles relevance; no change needed

### Frontend Changes

| File | Change |
|------|--------|
| `frontend/src/pages/SearchPage.tsx` | Remove "All" tab/mode, add sort dropdown, mode-aware sort options, fix mode-switch sort validation, change default to `relevance` |
| `frontend/src/components/search/SearchResultsTable.tsx` | Sync column header sort indicators with dropdown, add `aria-sort` attributes, remove `showTypeColumn`/type badge logic |
| `frontend/src/hooks/useSearch.ts` | Update default sort from `start_year:desc` to `relevance` |
| `frontend/src/hooks/useUnifiedSearch.ts` | **Delete entirely** |

### Sort Mapping Updates

```typescript
const COMIC_SORT_OPTIONS = [
  { value: "relevance", label: "Relevance" },
  { value: "year_desc", label: "Year (Newest)" },
  { value: "year_asc", label: "Year (Oldest)" },
  { value: "name_asc", label: "Name (A-Z)" },
  { value: "name_desc", label: "Name (Z-A)" },
  { value: "issues_desc", label: "Most Issues" },
  { value: "issues_asc", label: "Fewest Issues" },
];

const MANGA_SORT_OPTIONS = [
  { value: "relevance", label: "Relevance" },
  { value: "year_desc", label: "Year (Newest)" },
  { value: "year_asc", label: "Year (Oldest)" },
  { value: "name_asc", label: "Name (A-Z)" },
  { value: "name_desc", label: "Name (Z-A)" },
  { value: "follows", label: "Most Followed" },
  { value: "latest", label: "Latest Upload" },
];

// API mappings (internal, not exposed to user)
const comicSortMapping: Record<string, string | null> = {
  relevance: null,  // omit &sort= for ComicVine natural order
  year_desc: "start_year:desc",
  year_asc: "start_year:asc",
  name_asc: "name:asc",
  name_desc: "name:desc",
  issues_desc: "count_of_issues:desc",
  issues_asc: "count_of_issues:asc",
};

const mangaSortMapping: Record<string, string> = {
  relevance: "relevance",
  year_desc: "year_desc",
  year_asc: "year_asc",
  name_asc: "title_asc",
  name_desc: "title_desc",
  follows: "follows",
  latest: "latest",
};
```

### Relevance Flow Through the Stack

When frontend sort value is `"relevance"`:
- `useSearchComics` sends `sort: "relevance"` to the API
- `_findComic()` passes it through to `mb.findComic()`
- `pullsearch()` sees `sort == "relevance"`, sets `sort_param = None`, omits `&sort=` from ComicVine URL
- `useSearchManga` sends `sort: "relevance"` to the API
- `mangadex.search_manga()` maps it to `order[relevance]: desc` (existing behavior)

### URL Parameter Design

- `sort=relevance` is the new default (no `sort` param in URL = relevance)
- Sort persists across searches within the same session via URL params
- Sidebar search resets to defaults (current behavior, intentional)
- `type` param is now `comic` or `manga` only (no more `all`)

## Acceptance Criteria

- [ ] Default search sort is "Relevance" for both comics and manga
- [ ] "All" mode is removed -- only Comics and Manga tabs remain
- [ ] `useUnifiedSearch.ts` is deleted
- [ ] ComicVine search with relevance omits `&sort=` from API URL
- [ ] MangaDex search with relevance sends `order[relevance]: desc` (existing behavior)
- [ ] Sort dropdown shows mode-appropriate options (no "Most Followed" in comics mode)
- [ ] Switching from manga to comics with a manga-only sort resets to relevance
- [ ] Column header clicks update the sort dropdown and vice versa
- [ ] Sort changes reset pagination to page 1
- [ ] Sortable column headers have `aria-sort` attribute and keyboard support
- [ ] Sort dropdown uses shadcn `<Select>` for accessibility
- [ ] Metron handles `sort="relevance"` gracefully (maps to default order)

## Dependencies & Risks

- **ComicVine natural order quality** -- Omitting `&sort=` may not produce great relevance results. If CV's default order is random/unpredictable, fall back to `date_last_updated:desc` as a relevance proxy. Test with common queries like "Batman", "Spider-Man"
- **Metron search backend** -- If enabled, needs to handle `sort="relevance"` gracefully
- **Rate limiting** -- Sort changes trigger new API calls. ComicVine has 1 req/sec rate limit. Rapid sort switching could stack requests. Consider debouncing sort changes (300ms)

## Implementation Order

1. **Backend**: Modify `mb.py` `pullsearch()` to handle relevance sort (omit `&sort=`)
2. **Backend**: Add `'relevance'` to Metron's `SORT_MAPPING`
3. **Frontend**: Remove "All" mode -- delete `useUnifiedSearch.ts`, remove "All" tab from `SearchPage.tsx`
4. **Frontend**: Change default sort from `year_desc` to `relevance` in `SearchPage.tsx` and `useSearch.ts`
5. **Frontend**: Add sort dropdown with mode-aware options to `SearchPage.tsx`
6. **Frontend**: Fix mode-switching sort validation
7. **Frontend**: Add `aria-sort` attributes to column headers, clean up type badge logic
8. **Testing**: Verify sort works across ComicVine, MangaDex, and Metron backends

## Sources

- `mylar/mb.py:56-72` -- ComicVine sort parameter in `pullsearch()`
- `mylar/mb.py:105` -- `findComic()` entry point
- `mylar/mangadex.py:224-278` -- MangaDex sort mapping
- `mylar/metron.py:32-41` -- Metron SORT_MAPPING
- `mylar/api.py:1356` -- `_findComic()` API endpoint
- `frontend/src/pages/SearchPage.tsx` -- Search page with sort/mode state
- `frontend/src/components/search/SearchResultsTable.tsx:79-83` -- Current sort column map
- `frontend/src/hooks/useSearch.ts` -- Search hooks with sort defaults
- `frontend/src/hooks/useUnifiedSearch.ts` -- To be deleted
