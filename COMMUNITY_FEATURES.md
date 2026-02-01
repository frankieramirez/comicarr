# Community Features Implementation Plan

## Overview

This plan addresses the top feature requests from mylar3 GitHub issues that haven't been implemented yet. These features were identified by analyzing user votes, comment activity, and recurring themes.

**Source:** https://github.com/mylar3/mylar3/issues

---

## Priority Features

### Tier 1: High Impact (Most Requested)

| Feature | GitHub Issue | Votes | Effort | Status |
|---------|--------------|-------|--------|--------|
| Interactive Import Mapping | #1337 | 2 | Large | ✅ Done |
| iCal Calendar Feed | #1526 | - | Medium | |
| Matrix Notifications | #1216 | - | Small | ✅ Done |
| Bulk Metadata Actions UI | #1525 | 3 | Medium | ✅ Done |

### Tier 2: Medium Impact

| Feature | GitHub Issue | Votes | Effort |
|---------|--------------|-------|--------|
| SLSKD Download Source | #1683 | 2 | Large |
| Auto-Watch Keywords | #1501 | 1 | Medium |
| DDL Queue Stuck Notifications | #1219 | 1 | Small |
| Series Statistics Dashboard | #1671 | 1 | Medium |

### Tier 3: UX Improvements

| Feature | GitHub Issue | Votes | Effort |
|---------|--------------|-------|--------|
| Visual Feedback When Adding Series | #1210 | - | Small |
| Return to Scroll Position | #1613 | 1 | Small |
| Advanced Search Filters | #1736 | - | Medium |

### Tier 4: Infrastructure (Long-term)

| Feature | GitHub Issue | Votes | Effort |
|---------|--------------|-------|--------|
| Postgres/MySQL Support | #1438 | - | Very Large |

---

## Detailed Implementation Plans

### 1. Interactive Import Mapping Screen ✅ COMPLETED
**Issue:** #1337 | **Priority:** High | **Effort:** Large (3-5 days) | **Status:** IMPLEMENTED

**Problem:** When importing comics, Mylar often can't match files automatically. Users have to enable debug mode to find the root cause. Sonarr/Radarr have interactive import screens where users can manually map unrecognized files.

**Implementation Complete:**

**Backend Changes:**
- `mylar/__init__.py` - Added 6 new columns to `importresults` table:
  - `MatchConfidence` (INTEGER) - 0-100 confidence score
  - `SuggestedComicID` (TEXT) - Best match comic ID
  - `SuggestedComicName` (TEXT) - Best match display name
  - `SuggestedIssueID` (TEXT) - Best issue match
  - `IgnoreFile` (INTEGER DEFAULT 0) - 1 = ignored
  - `MatchSource` (TEXT) - 'auto', 'manual', or 'metadata'

- `mylar/api.py` - Added 5 new API commands:
  ```
  getImportPending   - List unmatched files with pagination
  matchImport        - Manually match file(s) to series
  ignoreImport       - Mark file(s) as ignored
  refreshImport      - Re-scan import directory
  deleteImport       - Remove import record(s)
  ```

- `mylar/filechecker.py` - Added `calculate_match_confidence()` function with scoring:
  - Series Name Match: 40 pts (fuzzy matching)
  - Year Match: 15 pts
  - Volume Match: 15 pts
  - Issue Number: 15 pts
  - Metadata: 10 pts (CBZ with ComicInfo.xml)
  - Path Hints: 5 pts

**Frontend Changes:**
- New page: `frontend/src/pages/ImportPage.tsx`
- New components in `frontend/src/components/import/`:
  - `ImportTable.tsx` - Expandable table showing import groups and files
  - `MatchModal.tsx` - Search modal to find correct series
  - `ImportBulkActions.tsx` - Floating action bar for selections
  - `ConfidenceBadge.tsx` - Color-coded confidence scores
- New hook: `frontend/src/hooks/useImport.ts` - React Query mutations
- Updated: `App.tsx` with `/import` route
- Updated: `AppSidebar.tsx` with Import nav item

**Features:**
- View pending imports grouped by series with confidence scores
- Expand rows to see individual files
- Color-coded confidence badges (green >80%, yellow 50-80%, red <50%)
- Manual matching via series search modal
- Bulk ignore/delete actions
- Show/hide ignored files toggle
- Re-scan import directory button

---

### 2. iCal Calendar Feed
**Issue:** #1526 | **Priority:** High | **Effort:** Medium (1-2 days)

**Problem:** Users want to see upcoming comic releases in their calendar apps (Google Calendar, Apple Calendar) and dashboard tools (Homepage).

**Implementation:**

**Backend Changes:**
- `mylar/api.py` - Add endpoint:
  ```
  GET /api/v2/calendar.ics?apikey=...&weeks=4
  ```
- Create `mylar/icalendar.py`:
  ```python
  from icalendar import Calendar, Event

  def generate_ical_feed(weeks=4):
      cal = Calendar()
      cal.add('prodid', '-//Mylar3//Comic Releases//EN')
      cal.add('version', '2.0')

      upcoming = get_upcoming_issues(weeks)
      for issue in upcoming:
          event = Event()
          event.add('summary', f"{issue['series']} #{issue['number']}")
          event.add('dtstart', issue['release_date'])
          event.add('description', issue['description'])
          cal.add_component(event)

      return cal.to_ical()
  ```

**Dependencies:**
- Add `icalendar` to requirements.txt

**Frontend Changes:**
- Settings page: Add "Calendar Feed" section
  - Display iCal URL with copy button
  - Option to set default weeks to include
  - Instructions for adding to Google Calendar, etc.

**Files to Modify:**
- `mylar/api.py` - Add calendar endpoint
- `mylar/icalendar.py` - New file
- `requirements.txt` - Add icalendar package
- `frontend/src/pages/SettingsPage.jsx` - Add calendar section

---

### 3. Matrix Notifications ✅ COMPLETED
**Issue:** #1216 | **Priority:** High | **Effort:** Small (0.5-1 day) | **Status:** IMPLEMENTED

**Problem:** Matrix is a growing open-source chat platform. Other *arr apps support it, but Mylar doesn't.

**Implementation Complete:**

**Files Modified:**
- `mylar/notifiers.py` - Added MATRIX class with notify() and test_notify() methods
- `mylar/config.py` - Added MATRIX_ENABLED, MATRIX_HOMESERVER, MATRIX_ACCESS_TOKEN, MATRIX_ROOM_ID, MATRIX_ONSNATCH
- `mylar/webserve.py` - Added getsettings entries, checked_configs, and testmatrix() endpoint
- `mylar/search.py` - Added snatch notification call
- `mylar/PostProcessor.py` - Added download notification call
- `mylar/cmtagmylar.py` - Added error notification call

**Config Options:**
```ini
[MATRIX]
matrix_enabled = False
matrix_homeserver =      # e.g., https://matrix.org
matrix_access_token =    # Get from Matrix client or API
matrix_room_id =         # e.g., !roomid:matrix.org
matrix_onsnatch = False
```

**Note:** Frontend/UI settings page uses Mako templates in `data/interfaces/` - template updates needed for full UI integration

---

### 4. Bulk Metadata Actions UI ✅ COMPLETED
**Issue:** #1525 | **Priority:** High | **Effort:** Medium (1-2 days) | **Status:** IMPLEMENTED

**Problem:** Currently you either re-tag an entire series (hitting API limits) or click one issue at a time. Users want to select multiple issues and tag them in bulk.

**Implementation Complete:**

**Backend Changes:**
- `mylar/api.py` - Added `bulkMetatag` command that accepts:
  - `id` (ComicID)
  - `issue_ids` (comma-separated IssueIDs)
  - Calls existing `webserve.WebInterface().bulk_metatag()` function
  - Returns immediately while tagging runs in background thread

**Frontend Changes:**
- `frontend/src/hooks/useMetadata.ts` - New file with `useBulkMetatag()` React Query mutation
- `frontend/src/components/series/IssuesTable.tsx`:
  - Added `comicId` prop to component interface
  - Added `Tags` icon import from lucide-react
  - Added `handleBulkMetatag` handler function
  - Added "Tag Metadata" button to bulk action bar
- `frontend/src/pages/SeriesDetailPage.tsx` - Passes `comicId` prop to IssuesTable

**Features:**
- Select multiple issues via existing checkbox selection
- "Tag Metadata" button appears in bulk action bar alongside "Mark Wanted" and "Skip"
- Toast notification confirms operation started
- Backend handles rate limiting via existing `CV_BATCH_LIMIT_PROTECTION` check
- Issues without physical files are automatically filtered out

---

### 5. SLSKD (Soulseek) Download Source
**Issue:** #1683 | **Priority:** Medium | **Effort:** Large (3-4 days)

**Problem:** Soulseek has many comic collections shared by users. LazyLibrarian added SLSKD support, Mylar could benefit too.

**Implementation:**

**Backend Changes:**
- Create `mylar/downloaders/slskd.py`:
  ```python
  class SLSKDDownloader:
      def __init__(self):
          self.api_url = mylar.CONFIG.SLSKD_URL
          self.api_key = mylar.CONFIG.SLSKD_API_KEY

      def search(self, query):
          # POST /api/v0/searches
          pass

      def download(self, file_info):
          # POST /api/v0/transfers/downloads
          pass

      def check_status(self, transfer_id):
          # GET /api/v0/transfers/downloads/{id}
          pass
  ```

- `mylar/config.py` - Add config:
  ```python
  SLSKD_ENABLED = False
  SLSKD_URL = ''
  SLSKD_API_KEY = ''
  SLSKD_PRIORITY = 3  # Order in search providers
  ```

- `mylar/search.py` - Integrate SLSKD as search provider

**Frontend Changes:**
- Settings → Download Clients: Add SLSKD section
  - URL input
  - API Key input
  - Priority selector
  - Test connection button

**Files to Modify:**
- `mylar/downloaders/slskd.py` - New file
- `mylar/config.py` - Add SLSKD config
- `mylar/search.py` - Add SLSKD provider
- `frontend/src/pages/SettingsPage.jsx` - Add SLSKD settings

---

### 6. Auto-Watch Keywords (Customized Watch List)
**Issue:** #1501 | **Priority:** Medium | **Effort:** Medium (1-2 days)

**Problem:** Users want to auto-watch for character names or keywords (e.g., "Deadpool", "Harley Quinn") in weekly pulls without manually adding each one-shot or mini-series.

**Implementation:**

**Backend Changes:**
- `mylar/db.py` - Add `watch_keywords` table:
  ```sql
  CREATE TABLE watch_keywords (
      id INTEGER PRIMARY KEY,
      keyword TEXT NOT NULL,
      match_type TEXT DEFAULT 'contains',  -- 'contains', 'starts_with', 'exact'
      auto_add BOOLEAN DEFAULT FALSE,
      notify BOOLEAN DEFAULT TRUE,
      created_at TIMESTAMP
  );
  ```

- `mylar/api.py` - Add endpoints:
  ```
  GET    /api/v2/watch-keywords
  POST   /api/v2/watch-keywords
  DELETE /api/v2/watch-keywords/{id}
  ```

- `mylar/weeklypull.py` - Check keywords when processing weekly pull:
  ```python
  def check_keyword_matches(issue_title):
      keywords = get_watch_keywords()
      for kw in keywords:
          if matches(issue_title, kw):
              if kw.auto_add:
                  add_to_library(issue)
              if kw.notify:
                  send_notification(f"Keyword match: {issue_title}")
  ```

**Frontend Changes:**
- New page or settings section: "Watch Keywords"
  - List of current keywords with delete button
  - Add keyword form with match type dropdown
  - Toggle for auto-add vs. notify-only
  - Preview of recent matches

**Files to Modify:**
- `mylar/db.py` - Add watch_keywords table
- `mylar/api.py` - Add keyword endpoints
- `mylar/weeklypull.py` - Add keyword matching
- `frontend/src/pages/WatchKeywordsPage.jsx` - New page

---

### 7. DDL Queue Stuck Notifications
**Issue:** #1219 | **Priority:** Medium | **Effort:** Small (0.5 day)

**Problem:** DDL queue can get stuck and users don't know until they check manually.

**Implementation:**

**Backend Changes:**
- `mylar/config.py` - Add config:
  ```python
  DDL_STUCK_NOTIFY = True
  DDL_STUCK_THRESHOLD = 30  # minutes
  ```

- `mylar/__init__.py` - Add scheduler job:
  ```python
  def check_ddl_queue_health():
      oldest_pending = get_oldest_pending_ddl()
      if oldest_pending and oldest_pending.age_minutes > CONFIG.DDL_STUCK_THRESHOLD:
          notify_all(f"DDL queue appears stuck. Oldest item: {oldest_pending.name}")
  ```

**Files to Modify:**
- `mylar/config.py` - Add stuck notification config
- `mylar/__init__.py` - Add health check scheduler
- `mylar/getcomics.py` - Add queue health check function

---

### 8. Series Statistics Dashboard
**Issue:** #1671 | **Priority:** Medium | **Effort:** Medium (1-2 days)

**Problem:** Users want to see file count, directory size, and duplicate detection per series at a glance.

**Implementation:**

**Backend Changes:**
- `mylar/api.py` - Add endpoint:
  ```
  GET /api/v2/series/{id}/stats
  Response: {
      "file_count": 45,
      "directory_size_mb": 2340,
      "duplicates": [
          {"issue": "5", "files": ["issue5.cbz", "issue5.cbr"]}
      ],
      "missing_files": ["issue10.cbz"],
      "format_breakdown": {"cbz": 40, "cbr": 5}
  }
  ```

**Frontend Changes:**
- `SeriesDetailPage.jsx` - Add stats panel:
  - File count / Total issues
  - Directory size
  - Format breakdown (pie chart or bars)
  - Duplicates warning with list
  - "Scan for issues" button

**Files to Modify:**
- `mylar/api.py` - Add stats endpoint
- `mylar/helpers.py` - Add stats calculation functions
- `frontend/src/pages/SeriesDetailPage.jsx` - Add stats panel
- `frontend/src/components/series/SeriesStats.jsx` - New component

---

### 9. Visual Feedback When Adding Series
**Issue:** #1210 | **Priority:** Low | **Effort:** Small (0.5 day)

**Problem:** In search results, there's no visual indicator for which series you've already clicked "Add".

**Implementation:**

**Frontend Changes:**
- `SearchPage.jsx`:
  - Track added series IDs in local state
  - After successful add, update state and show visual feedback
  - Options:
    - Change row background color to light blue/green
    - Replace "Add" button with checkmark icon
    - Show "Added" badge
  - Persist state during session (cleared on new search)

**Files to Modify:**
- `frontend/src/pages/SearchPage.jsx` - Add selection tracking
- `frontend/src/components/search/ComicCard.jsx` - Add visual states

---

### 10. Return to Scroll Position
**Issue:** #1613 | **Priority:** Low | **Effort:** Small (0.5 day)

**Problem:** When navigating from series list to detail and back, the scroll position resets.

**Implementation:**

**Frontend Changes:**
- Create `useScrollPosition` hook:
  ```javascript
  export function useScrollPosition(key) {
      useEffect(() => {
          const saved = sessionStorage.getItem(`scroll-${key}`);
          if (saved) window.scrollTo(0, parseInt(saved));

          return () => {
              sessionStorage.setItem(`scroll-${key}`, window.scrollY);
          };
      }, [key]);
  }
  ```
- Apply to `HomePage.jsx` (series list)

**Files to Modify:**
- `frontend/src/hooks/useScrollPosition.js` - New hook
- `frontend/src/pages/HomePage.jsx` - Use hook

---

### 11. Advanced Search Filters
**Issue:** #1736 | **Priority:** Low | **Effort:** Medium (1-2 days)

**Problem:** Users want to filter search results by publisher, year, book type (HC/TPB/etc).

**Implementation:**

**Frontend Changes:**
- `SearchPage.jsx` - Add filter panel:
  - Publisher dropdown (populated from results)
  - Year range inputs (before/after)
  - Book type checkboxes
  - Negative filter (exclude terms)
- Client-side filtering of results
- "Clear filters" button

**Files to Modify:**
- `frontend/src/pages/SearchPage.jsx` - Add filter panel
- `frontend/src/components/search/SearchFilters.jsx` - New component

---

## Implementation Schedule

### Phase 1: Quick Wins (Week 1)
- [x] Matrix Notifications (0.5 day) ✅ COMPLETED
- [ ] Visual Feedback When Adding (0.5 day)
- [ ] Return to Scroll Position (0.5 day)
- [ ] DDL Queue Stuck Notifications (0.5 day)

### Phase 2: Medium Features (Week 2)
- [ ] iCal Calendar Feed (1-2 days)
- [x] Bulk Metadata Actions UI (1-2 days) ✅ COMPLETED
- [ ] Series Statistics Dashboard (1-2 days)

### Phase 3: Larger Features (Week 3-4)
- [ ] Auto-Watch Keywords (1-2 days)
- [ ] Advanced Search Filters (1-2 days)
- [x] Interactive Import Mapping (3-5 days) ✅ COMPLETED

### Phase 4: Major Integration (Future)
- [ ] SLSKD Download Source (3-4 days)
- [ ] Postgres/MySQL Support (weeks - architectural change)

---

## Already Implemented (Reference)

These features from the issues were already found in the codebase:

| Feature | Status | Config/Location |
|---------|--------|-----------------|
| Metron metadata | ✅ Done | `metron.py`, `USE_METRON_SEARCH` |
| MangaDex integration | ✅ Done | `mangadex.py`, `MANGADEX_ENABLED` |
| Interactive Import Mapping | ✅ Done | `/import` page, `getImportPending` API |
| Write metadata on import | ✅ Done | `IMP_METADATA` config |
| Failed download handling | ✅ Done | `Failed.py` |
| Proxy support | ✅ Done | `ENABLE_PROXY`, `HTTP_PROXY` |
| CBR→CBZ conversion | ✅ Done | `CBR2CBZ_ONLY` |
| Flexible renaming | ✅ Done | `FILE_FORMAT`, `REPLACE_CHAR` |
| Duplicate detection | ✅ Done | `DUPECONSTRAINT` |
| 10 notification types | ✅ Done | `notifiers.py` |
| Matrix notifications | ✅ Done | `MATRIX_ENABLED`, `MATRIX_HOMESERVER`, `MATRIX_ACCESS_TOKEN`, `MATRIX_ROOM_ID` |

---

## Verification

### Testing Each Feature

**Matrix Notifications:**
- Configure Matrix credentials in settings
- Click "Test" button
- Verify message appears in Matrix room
- Trigger a download and verify notification

**iCal Feed:**
- Copy iCal URL from settings
- Add to Google Calendar
- Verify upcoming issues appear as events

**Bulk Metadata:** ✅ IMPLEMENTED
- Navigate to a series detail page
- Select multiple issues using checkboxes
- Verify "Tag Metadata" button appears in bulk action bar
- Click "Tag Metadata" and verify toast notification appears
- Check backend logs for tagging activity
- Verify files have updated metadata after completion

**Import Mapping:** ✅ IMPLEMENTED
- Navigate to Import page via sidebar
- Verify pending imports display in grouped table
- Expand a group to see individual files
- Verify confidence badges are color-coded
- Click "Match" on a group to open search modal
- Search and select correct series
- Verify match applied and group updates
- Select multiple groups and use bulk ignore
- Toggle "Show Ignored" to verify they reappear
- Click "Scan Import Directory" to re-scan

---

## Notes

- All new API endpoints should use `/api/v2/` prefix for REST-style routes
- Frontend components should follow existing patterns in `frontend/src/`
- Add appropriate loading states and error handling
- Include toast notifications for user feedback
- Test on both desktop and mobile viewports
