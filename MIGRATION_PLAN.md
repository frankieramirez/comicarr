# Mylar3 React Frontend Migration Plan
## AI-Accelerated Big Bang Rewrite

**Timeline:** 7 days (AI-assisted development)
**Approach:** New React app from scratch, parallel deployment
**Goal:** Working MVP with core features, defer advanced features to week 2+

---

## 🎯 Progress Tracker

**Overall Status:** 3 of 7 days complete (43%)

| Day | Task | Status | Completion Date |
|-----|------|--------|----------------|
| **Day 1** | Foundation Setup | ✅ **COMPLETE** | 2026-01-29 |
| **Day 2** | Series Management | ✅ **COMPLETE** | 2026-01-29 |
| **Day 3** | Search & Add Comics | ✅ **COMPLETE** | 2026-01-29 |
| **Day 4** | Queue & Wanted Management | 🔄 **NEXT** | - |
| **Day 5** | Basic Settings | ⏳ Pending | - |
| **Day 6** | Real-time Updates & Polish | ⏳ Pending | - |
| **Day 7** | Testing & Deployment | ⏳ Pending | - |

**Latest Commit:** `fc8643c9` - IMP: Add React frontend (Days 1-3)

### ✨ What's Been Built

**Days 1-3 Implementation Summary:**

✅ **Core Infrastructure**
- Vite + React 18 + TailwindCSS 4 with hot module replacement
- React Router v6 for client-side routing
- TanStack Query v5 for server state management and caching
- API client connecting to existing Mylar3 `/api` endpoints
- Authentication system with API key login and protected routes
- Responsive layout with navigation (mobile + desktop)

✅ **Series Management**
- Series table with sorting, pagination, and search (TanStack Table)
- Series detail page with cover art, metadata, and description
- Issues table with status badges and sorting
- Actions: pause/resume series, refresh metadata, delete series
- Issue management: mark wanted, skip issues, queue for download

✅ **Search & Discovery**
- Comic search with real-time results
- Grid layout for search results with cover art
- Add comics to library with one click
- Toast notifications for user feedback
- Automatic navigation to series detail after adding

**Tech Stack Implemented:**
- React 18 + Vite 5 + TailwindCSS 4
- TanStack Query + TanStack Table
- Lucide React icons
- shadcn/ui component library
- 40 files, 6,838 lines of code

---

## Executive Summary

Migrate Mylar3 from Mako templates + jQuery to React + TailwindCSS + Vite using AI-assisted development to achieve rapid delivery. Focus on core user workflows first (series management, search, queue), defer advanced features (complex config, import wizards) to post-MVP.

**Key Constraints:**
- Solo developer using AI coding agents
- 1-week timeline for initial working version
- Big bang approach (separate new app)
- Must maintain existing Python backend initially

**Success Criteria:**
- Users can browse/search/add series
- View series details and manage issues
- Queue management and basic settings
- Clean, modern UI with TailwindCSS
- Authentication working

---

## Current State Analysis

### Frontend Architecture (To Replace)
- **Templates:** 37 Mako HTML templates (~14,500 lines)
- **JavaScript:** jQuery 1.7.2 + DataTables + Materialize CSS
- **Routes:** 199+ web endpoints in webserve.py
- **Real-time:** Server-Sent Events for background updates
- **Tables:** 22+ DataTables instances with server-side pagination

### API Status
- **Existing:** 43 API endpoints in api.py (~1,900 lines)
- **Coverage:** Good for series/issue CRUD, gaps in config/import/notifications
- **Auth:** Query parameter API key, session-based
- **Format:** JSON responses with consistent structure

### Critical Functional Areas
1. **Series Management** - Browse, search, add, edit, delete series (HIGH PRIORITY)
2. **Issue Management** - View issues, change status, queue downloads (HIGH PRIORITY)
3. **Search & Discovery** - Search comics, add by ID (HIGH PRIORITY)
4. **Queue/Wanted** - Manage download queue, upcoming releases (HIGH PRIORITY)
5. **Configuration** - 40+ settings across 6 tabs (DEFER - too complex for week 1)
6. **Library Import** - CBL files, directory scanning (DEFER)
7. **Story Arcs** - Reading lists management (MEDIUM PRIORITY)
8. **History/Logs** - Download history, application logs (LOW PRIORITY)

---

## Target Architecture

### Technology Stack

**Frontend Build:**
```
- Vite 5.x (fast builds, HMR)
- React 18.x (UI framework)
- React Router v6 (client-side routing)
- TailwindCSS 3.x (utility-first styling)
- TypeScript (optional, can start with JSX)
```

**Component Libraries:**
```
- shadcn/ui (TailwindCSS components, copy/paste)
- Radix UI (accessible primitives)
- TanStack Table v8 (replaces DataTables)
- TanStack Query v5 (server state, caching)
- Lucide Icons (modern React icons)
- react-hook-form + zod (forms + validation)
```

**Rationale for Choices:**
- **Vite over Next.js:** Self-hosted app doesn't need SSR, simpler deployment
- **SPA over SSR:** No SEO needs, faster navigation, easier integration
- **shadcn/ui:** Copy/paste components means AI can generate them rapidly
- **TanStack Query:** Handles caching, loading states, real-time updates elegantly

### Backend Strategy

**Week 1: Use Existing Infrastructure**
- Keep CherryPy backend as-is
- Use existing 43 API endpoints via `/api?apikey=...&cmd=...`
- For missing APIs, call webserve.py routes directly (hybrid approach)
- Authentication via existing session cookies

**Post-Week 1: API Expansion**
- Add proper REST endpoints for configuration
- Add library import APIs
- Add notification management APIs
- Migrate hybrid webserve.py calls to proper APIs

**Why Hybrid Approach:**
- Gets us working UI faster (don't block on API development)
- Can make calls to `/home`, `/config`, etc. and parse responses
- Gradually replace with proper APIs in subsequent iterations

---

## Week 1: MVP Development Plan

### Day 1: Foundation Setup ✅ COMPLETE

**Morning: Project Initialization**
1. Create `/frontend` directory in Mylar3 repo
2. Initialize Vite + React: `npm create vite@latest frontend -- --template react`
3. Install dependencies:
   ```bash
   npm install react-router-dom @tanstack/react-query @tanstack/react-table
   npm install -D tailwindcss postcss autoprefixer
   npm install lucide-react date-fns
   ```
4. Configure TailwindCSS
5. Setup shadcn/ui CLI: `npx shadcn-ui@latest init`

**Afternoon: Core Infrastructure**
1. Setup React Router with basic routes
2. Create auth context (`AuthProvider`) with API key storage
3. Build login page with API key authentication
4. Setup TanStack Query client with default configs
5. Create API client utility (`/src/lib/api.js`)
6. Setup Vite proxy to CherryPy backend:
   ```js
   // vite.config.js
   export default {
     server: {
       proxy: {
         '/api': 'http://localhost:8090',
       }
     }
   }
   ```

**Components to Build:**
- `LoginPage.jsx` - API key entry form
- `AuthContext.jsx` - Auth state management
- `ProtectedRoute.jsx` - Route guard component
- `Layout.jsx` - Main app layout with nav

**Deliverable:** Can log in and see authenticated shell

---

### Day 2: Series Management ✅ COMPLETE

**Morning: Home/Series List**
1. Fetch series data via `/api?cmd=getIndex&apikey=...`
2. Build series table with TanStack Table
3. Implement server-side pagination
4. Add sorting and search functionality
5. Show series status badges (Active, Paused, etc.)
6. Add "Add Series" button (links to search)

**Afternoon: Series Details Page**
1. Fetch series + issues via `/api?cmd=getComic&id=...`
2. Build series header with cover art
3. Build issues table with TanStack Table
4. Show issue status (Downloaded, Wanted, Skipped)
5. Add action buttons (Pause, Resume, Refresh, Delete)
6. Implement issue status changes via API

**Components to Build:**
- `SeriesTable.jsx` - Main series listing table
- `SeriesDetailPage.jsx` - Series detail view
- `IssuesTable.jsx` - Issues list within series
- `SeriesCover.jsx` - Cover art display component
- `StatusBadge.jsx` - Reusable status indicator
- `ActionMenu.jsx` - Dropdown action menu

**API Endpoints Used:**
- `getIndex` - List all series
- `getComic&id=$id` - Get series details + issues
- `pauseComic&id=$id` - Pause series
- `resumeComic&id=$id` - Resume series
- `refreshComic&id=$id` - Refresh metadata
- `delComic&id=$id` - Delete series

**Deliverable:** Can browse series, view details, manage series/issues

---

### Day 3: Search & Add Comics ✅ COMPLETE

**Morning: Search Functionality**
1. Build search page with input form
2. Call `/api?cmd=findComic&name=...`
3. Display search results in grid or list view
4. Show cover art, publisher, year, issue count
5. Add "Add to Library" button per result

**Afternoon: Add Comic Flow**
1. Call `/api?cmd=addComic&id=$comicid`
2. Show progress/success notification
3. Redirect to series detail page after add
4. Add "Add by ID" quick-add input in header

**Components to Build:**
- `SearchPage.jsx` - Search form and results
- `SearchResults.jsx` - Results grid/list
- `ComicCard.jsx` - Individual search result card
- `AddComicButton.jsx` - Action button with loading state
- `Toast.jsx` - Notification component

**API Endpoints Used:**
- `findComic&name=$query` - Search for comics
- `addComic&id=$id` - Add comic to library

**Deliverable:** Can search and add new series to library

---

### Day 4: Queue & Wanted Management (6-8 hours)

**Morning: Wanted/Upcoming Page**
1. Fetch upcoming via `/api?cmd=getUpcoming`
2. Build table showing this week's releases
3. Add filters (new releases vs. existing series)
4. Show issue status and queue status
5. Add bulk actions (mark wanted, download)

**Afternoon: Queue Operations**
1. Implement queue/unqueue via API
2. Build "Wanted" issues view (`getWanted` endpoint)
3. Add manual search trigger
4. Show download progress/status
5. Implement retry for failed downloads

**Components to Build:**
- `UpcomingPage.jsx` - This week's releases
- `WantedPage.jsx` - Wanted issues list
- `QueueTable.jsx` - Download queue table
- `BulkActions.jsx` - Checkbox selection + actions
- `IssueActions.jsx` - Per-issue action menu

**API Endpoints Used:**
- `getUpcoming` - This week's comics
- `getWanted` - Wanted issues
- `queueIssue&id=$id` - Mark issue as wanted
- `unqueueIssue&id=$id` - Mark as skipped
- `forceSearch` - Trigger manual search

**Deliverable:** Can manage download queue and wanted issues

---

### Day 5: Basic Settings & Configuration (6-8 hours)

**Goal:** Minimal viable settings, NOT full feature parity

**Morning: Read-Only Config Display**
1. Create settings page with tabs (use shadcn/ui Tabs)
2. Fetch config via hybrid approach (may need to add simple API endpoint)
3. Display current settings in organized groups
4. Focus on most critical settings:
   - Comic directory paths
   - Download client settings (display only)
   - Search provider settings (display only)

**Afternoon: Editable Settings (Subset)**
1. Build forms for essential settings:
   - API key regeneration
   - Interface preferences (theme, etc.)
   - Basic search settings
2. Implement save functionality
3. Add validation with react-hook-form + zod
4. Show success/error messages

**Components to Build:**
- `SettingsPage.jsx` - Main settings layout with tabs
- `SettingsTab.jsx` - Individual tab content
- `SettingGroup.jsx` - Group of related settings
- `SettingField.jsx` - Individual setting input
- `SaveButton.jsx` - Save with loading state

**Note:** Defer complex config (download clients, notifications, providers) to week 2+

**Deliverable:** Can view and modify basic settings

---

### Day 6: Polish & Real-time Updates (6-8 hours)

**Morning: Real-time Updates**
1. Implement EventSource hook for SSE
2. Connect to `/api?cmd=checkGlobalMessages&apikey=...`
3. Listen for events (addbyid, scheduler_message, etc.)
4. Auto-invalidate TanStack Query caches on events
5. Show real-time notifications for background tasks

**Afternoon: UI Polish**
1. Add loading skeletons (shadcn/ui Skeleton)
2. Improve error handling and error states
3. Add empty states for tables (no series, no results)
4. Implement responsive design (mobile-friendly)
5. Add keyboard shortcuts (search: `/`, etc.)
6. Polish animations and transitions

**Components to Build:**
- `useServerEvents.js` - Custom EventSource hook
- `LoadingSkeleton.jsx` - Skeleton components
- `EmptyState.jsx` - Empty state displays
- `ErrorBoundary.jsx` - Error boundary wrapper
- `KeyboardShortcuts.jsx` - Keyboard nav handler

**Deliverable:** Polished UI with real-time updates

---

### Day 7: Testing & Deployment (6-8 hours)

**Morning: Testing**
1. Manual testing of all core workflows:
   - Login → Browse → Search → Add → Queue → Settings
2. Test edge cases (no internet, API errors, empty states)
3. Test on different browsers (Chrome, Firefox, Safari)
4. Test responsive design on mobile
5. Fix critical bugs

**Afternoon: Deployment Setup**
1. Build production bundle: `npm run build`
2. Configure CherryPy to serve React build:
   ```python
   # In webserve.py, add route:
   @cherrypy.expose
   def app(self, *args, **kwargs):
       return serve_file('data/react-build/index.html')
   ```
3. Setup static file serving for React assets
4. Test production build locally
5. Document deployment process
6. Create README for frontend development

**Deliverable:** Production-ready build, deployment docs

---

## MVP Feature Scope

### INCLUDED in Week 1 MVP ✅

**Core Functionality:**
- ✅ Authentication (API key login)
- ✅ Series browsing with table (pagination, sorting, search)
- ✅ Series details (cover, metadata, issues list)
- ✅ Series management (pause, resume, refresh, delete)
- ✅ Issue status changes (want, skip, download)
- ✅ Comic search and add to library
- ✅ Upcoming/This week's releases
- ✅ Wanted issues management
- ✅ Queue operations (queue/unqueue)
- ✅ Basic settings (view + edit subset)
- ✅ Real-time updates via EventSource
- ✅ Responsive modern UI with TailwindCSS

**API Coverage:** Uses 15-20 existing API endpoints

### DEFERRED to Week 2+ ⏳

**Advanced Features:**
- ⏳ Full configuration management (all 6 tabs, 100+ settings)
- ⏳ Download client configuration and testing
- ⏳ Notification settings and testing
- ⏳ Library import (CBL files, directory scanning)
- ⏳ Story arcs management (can add later)
- ⏳ Reading list functionality
- ⏳ Manual metadata editing
- ⏳ Post-processing configuration
- ⏳ Provider management (Newznab/Torznab)
- ⏳ Advanced analytics/statistics
- ⏳ History page (download history)
- ⏳ Logs viewer
- ⏳ Comic reader integration

**These features remain in old UI temporarily**, accessible via config toggle

---

## Project Structure

```
mylar3/
├── frontend/                    # New React app
│   ├── src/
│   │   ├── components/          # Reusable components
│   │   │   ├── ui/              # shadcn/ui components
│   │   │   ├── series/          # Series-specific components
│   │   │   ├── queue/           # Queue-specific components
│   │   │   └── layout/          # Layout components
│   │   ├── pages/               # Page components
│   │   │   ├── LoginPage.jsx
│   │   │   ├── HomePage.jsx     # Series list
│   │   │   ├── SeriesDetailPage.jsx
│   │   │   ├── SearchPage.jsx
│   │   │   ├── UpcomingPage.jsx
│   │   │   ├── WantedPage.jsx
│   │   │   └── SettingsPage.jsx
│   │   ├── lib/                 # Utilities
│   │   │   ├── api.js           # API client
│   │   │   ├── auth.js          # Auth utilities
│   │   │   └── utils.js         # General utilities
│   │   ├── hooks/               # Custom hooks
│   │   │   ├── useServerEvents.js
│   │   │   ├── useSeries.js
│   │   │   └── useAuth.js
│   │   ├── contexts/            # React contexts
│   │   │   └── AuthContext.jsx
│   │   ├── App.jsx              # Root component
│   │   └── main.jsx             # Entry point
│   ├── public/                  # Static assets
│   ├── index.html
│   ├── vite.config.js
│   ├── tailwind.config.js
│   └── package.json
├── mylar/                       # Existing Python backend
│   ├── webserve.py              # Add route to serve React build
│   └── api.py                   # Existing API endpoints
└── data/
    ├── react-build/             # Production build output (gitignored)
    └── interfaces/              # Old Mako templates (keep for now)
```

---

## API Strategy

### Week 1: Use Existing Endpoints

**Available API Commands (43 total):**
```
# Series Management
getIndex                 # List all series
getComic&id=$id         # Get series + issues
addComic&id=$id         # Add series to library
delComic&id=$id         # Delete series
pauseComic&id=$id       # Pause series
resumeComic&id=$id      # Resume series
refreshComic&id=$id     # Refresh metadata

# Issue Management
queueIssue&id=$id       # Mark as wanted
unqueueIssue&id=$id     # Mark as skipped
changeStatus&id=$id&status=$status

# Search
findComic&name=$query   # Search comics

# Queue/Wanted
getUpcoming             # This week's releases
getWanted              # Wanted issues list
getHistory             # Download history

# Real-time
checkGlobalMessages     # EventSource stream

# System
getVersion             # App version
shutdown               # Shutdown app
restart                # Restart app
```

**API Client Pattern:**
```javascript
// src/lib/api.js
const API_BASE = '/api';

export async function apiCall(cmd, params = {}) {
  const apiKey = localStorage.getItem('apiKey');
  const url = new URL(API_BASE, window.location.origin);
  url.searchParams.set('apikey', apiKey);
  url.searchParams.set('cmd', cmd);

  Object.entries(params).forEach(([key, value]) => {
    url.searchParams.set(key, value);
  });

  const response = await fetch(url);
  const data = await response.json();

  if (!data.success) {
    throw new Error(data.error?.message || 'API call failed');
  }

  return data.data;
}

// Usage in React Query
export function useSeries() {
  return useQuery({
    queryKey: ['series'],
    queryFn: () => apiCall('getIndex'),
  });
}
```

### Week 2+: Expand API for Missing Features

**New Endpoints Needed:**
```python
# In mylar/api.py, add:

# Configuration (30+ endpoints)
GET  /api/v2/config                # Get all config
GET  /api/v2/config/:section       # Get section
PUT  /api/v2/config/:section/:key  # Update setting
POST /api/v2/config/test-sab       # Test SABnzbd
POST /api/v2/config/test-nzbget    # Test NZBGet

# Library Import
POST /api/v2/library/import        # Import directory
POST /api/v2/library/import-cbl    # Import CBL file
GET  /api/v2/library/scan-status   # Scan progress

# Notifications
GET  /api/v2/notifications         # List notifiers
PUT  /api/v2/notifications/:id     # Update notifier
POST /api/v2/notifications/test    # Test notification
```

**Migration Path:**
- Week 1: Use `cmd`-based API (existing)
- Week 2+: Add RESTful `/api/v2/*` endpoints
- Gradually migrate frontend to v2 endpoints
- Keep v1 for backwards compatibility

---

## State Management Patterns

### Server State: TanStack Query

```javascript
// hooks/useSeries.js
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { apiCall } from '@/lib/api';

export function useSeries() {
  return useQuery({
    queryKey: ['series'],
    queryFn: () => apiCall('getIndex'),
    staleTime: 5 * 60 * 1000, // 5 minutes
  });
}

export function useAddSeries() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (comicId) => apiCall('addComic', { id: comicId }),
    onSuccess: () => {
      // Invalidate series list to refetch
      queryClient.invalidateQueries({ queryKey: ['series'] });
    },
  });
}

export function useSeriesDetail(comicId) {
  return useQuery({
    queryKey: ['series', comicId],
    queryFn: () => apiCall('getComic', { id: comicId }),
    enabled: !!comicId,
  });
}
```

### Client State: React Context + Hooks

```javascript
// contexts/AuthContext.jsx
import { createContext, useContext, useState, useEffect } from 'react';

const AuthContext = createContext();

export function AuthProvider({ children }) {
  const [apiKey, setApiKey] = useState(
    () => localStorage.getItem('apiKey')
  );

  const login = (key) => {
    localStorage.setItem('apiKey', key);
    setApiKey(key);
  };

  const logout = () => {
    localStorage.removeItem('apiKey');
    setApiKey(null);
  };

  return (
    <AuthContext.Provider value={{ apiKey, login, logout, isAuthenticated: !!apiKey }}>
      {children}
    </AuthContext.Provider>
  );
}

export const useAuth = () => useContext(AuthContext);
```

### Real-time Updates: EventSource Hook

```javascript
// hooks/useServerEvents.js
import { useEffect } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useAuth } from '@/contexts/AuthContext';

export function useServerEvents() {
  const queryClient = useQueryClient();
  const { apiKey } = useAuth();

  useEffect(() => {
    if (!apiKey) return;

    const eventSource = new EventSource(
      `/api?cmd=checkGlobalMessages&apikey=${apiKey}`
    );

    eventSource.addEventListener('addbyid', (event) => {
      const data = JSON.parse(event.data);
      // Invalidate series list when new series added
      if (data.tables?.includes('comics')) {
        queryClient.invalidateQueries({ queryKey: ['series'] });
      }
    });

    eventSource.addEventListener('scheduler_message', (event) => {
      // Show toast notification
      console.log('Background task:', event.data);
    });

    return () => eventSource.close();
  }, [apiKey, queryClient]);
}

// Use in App.jsx
function App() {
  useServerEvents(); // Connect to SSE
  return <Routes>...</Routes>;
}
```

---

## Component Examples

### Series Table with TanStack Table

```jsx
// components/series/SeriesTable.jsx
import { useReactTable, getCoreRowModel, flexRender } from '@tanstack/react-table';
import { useSeries } from '@/hooks/useSeries';

const columns = [
  { accessorKey: 'ComicName', header: 'Comic' },
  { accessorKey: 'ComicYear', header: 'Year' },
  { accessorKey: 'ComicPublisher', header: 'Publisher' },
  {
    accessorKey: 'Status',
    header: 'Status',
    cell: ({ getValue }) => <StatusBadge status={getValue()} />
  },
  { accessorKey: 'Total', header: 'Issues' },
  { accessorKey: 'Have', header: 'Have' },
];

export function SeriesTable() {
  const { data: series = [], isLoading } = useSeries();

  const table = useReactTable({
    data: series,
    columns,
    getCoreRowModel: getCoreRowModel(),
  });

  if (isLoading) return <div>Loading...</div>;

  return (
    <table>
      <thead>
        {table.getHeaderGroups().map(headerGroup => (
          <tr key={headerGroup.id}>
            {headerGroup.headers.map(header => (
              <th key={header.id}>
                {flexRender(header.column.columnDef.header, header.getContext())}
              </th>
            ))}
          </tr>
        ))}
      </thead>
      <tbody>
        {table.getRowModel().rows.map(row => (
          <tr key={row.id} onClick={() => navigate(`/series/${row.original.ComicID}`)}>
            {row.getVisibleCells().map(cell => (
              <td key={cell.id}>
                {flexRender(cell.column.columnDef.cell, cell.getContext())}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}
```

---

## Deployment Configuration

### Development

```bash
# Terminal 1: Backend
cd /path/to/mylar3
python3 Mylar.py --port 8090

# Terminal 2: Frontend dev server
cd frontend
npm install
npm run dev
# Vite runs on http://localhost:5173
# Proxies /api calls to http://localhost:8090
```

### Production Build

```bash
# Build React app
cd frontend
npm run build
# Outputs to: frontend/dist/

# Copy to data directory
cp -r dist/* ../data/react-build/
```

### CherryPy Integration

```python
# In mylar/webserve.py, add:

class WebInterface:

    @cherrypy.expose
    def app(self, *args, **kwargs):
        """
        Serve React SPA - catch-all route
        All paths under /app/* serve the React app
        """
        # Serve index.html for all /app routes (client-side routing)
        return serve_file(
            os.path.join(mylar.PROG_DIR, 'data/react-build/index.html'),
            content_type='text/html'
        )

# In webstart.py, configure static file serving:
config = {
    '/app': {
        'tools.staticdir.on': True,
        'tools.staticdir.dir': os.path.join(mylar.PROG_DIR, 'data/react-build'),
        'tools.staticdir.index': 'index.html',
    }
}
```

### Access URLs

```
Old UI:  http://localhost:8090/home
New UI:  http://localhost:8090/app
API:     http://localhost:8090/api?apikey=...&cmd=...
```

---

## AI Development Workflow

### Leveraging AI Agents for Rapid Development

**Day-by-Day AI Usage:**

**Day 1-2: Scaffolding**
- Prompt: "Create Vite + React + TailwindCSS project with auth context and routing"
- Prompt: "Setup shadcn/ui and install Button, Table, Dialog, Tabs components"
- Prompt: "Create API client with TanStack Query hooks for Mylar3 API"
- Prompt: "Build login page with API key authentication"

**Day 3-4: Core Components**
- Prompt: "Create series table using TanStack Table with these columns: [list]"
- Prompt: "Build series detail page fetching from /api?cmd=getComic&id=..."
- Prompt: "Add pause/resume/delete actions with confirmation dialogs"
- Prompt: "Create search page with comic card grid layout"

**Day 5-6: Features**
- Prompt: "Build upcoming releases page with filtering"
- Prompt: "Create settings page with tabbed layout for config sections"
- Prompt: "Implement EventSource hook for real-time updates"
- Prompt: "Add loading skeletons and error states"

**Day 7: Polish**
- Prompt: "Add keyboard shortcuts for navigation"
- Prompt: "Make responsive for mobile devices"
- Prompt: "Fix bugs: [list specific issues]"
- Prompt: "Setup production build and deployment"

**Best Practices with AI:**
1. **Be specific** - Provide exact API response formats
2. **Iterate rapidly** - Generate component, test, refine with follow-up prompts
3. **Reuse patterns** - Once one table works, use same pattern for all tables
4. **Copy/paste from shadcn** - Use shadcn/ui examples as templates
5. **Focus AI on boilerplate** - Let AI handle repetitive code, you handle logic

---

## Risk Mitigation

### Technical Risks

**Risk: API limitations block progress**
- Mitigation: Use hybrid approach - call webserve.py routes directly if needed
- Fallback: Can POST to existing web routes and parse responses

**Risk: Real-time updates don't work**
- Mitigation: Implement polling fallback (refetch every 30s)
- Test EventSource early on Day 1

**Risk: TanStack Table learning curve**
- Mitigation: Use shadcn/ui Table examples as templates
- Start with simple table (no sorting/filtering), add features incrementally

**Risk: Authentication complexity**
- Mitigation: Keep existing session-based auth, just add API key input
- React app uses same cookies as old UI

### Timeline Risks

**Risk: Week 1 timeline is too aggressive**
- Mitigation: Ruthlessly cut scope - defer anything non-essential
- Accept "ugly but functional" for MVP
- Use AI heavily to generate boilerplate

**Risk: Unexpected blockers (bugs, API issues)**
- Mitigation: Build buffer into each day (6-8 hour estimates, not 10-12)
- Keep old UI accessible as fallback
- Can extend to Week 2 if needed

**Risk: Testing takes longer than expected**
- Mitigation: Do continuous testing (test each component as built)
- Manual testing only (no automated tests in week 1)
- Focus on happy path, defer edge cases

---

## Success Metrics

### Week 1 MVP Success Criteria

**Must Have (Critical):**
- ✅ Users can log in with API key
- ✅ Can view series list with pagination
- ✅ Can view individual series details
- ✅ Can search and add new series
- ✅ Can queue/unqueue issues
- ✅ Settings page accessible (even if limited)
- ✅ UI is responsive and modern-looking
- ✅ No major bugs in core workflows

**Nice to Have (Bonus):**
- ✅ Real-time updates working
- ✅ Keyboard shortcuts
- ✅ Mobile responsive
- ✅ Dark mode support

**Defer (Week 2+):**
- ⏳ Full configuration parity
- ⏳ Library import
- ⏳ Story arcs
- ⏳ History/logs
- ⏳ Advanced search filters

### User Acceptance

**Test with these workflows:**
1. Login → Browse series → Click series → View issues → Mark wanted
2. Search for comic → Add to library → Navigate to new series
3. View upcoming → Queue multiple issues → Check queue
4. Change basic settings → Save → Verify changes persist

**If all 4 workflows work smoothly, MVP is successful.**

---

## Post-MVP Roadmap

### Week 2: Configuration & Polish
- Complete configuration page (all 6 tabs)
- Add download client management
- Add notification settings
- API endpoint development for config

### Week 3: Advanced Features
- Library import (CBL files, directory scanning)
- Story arcs management
- Reading lists
- History and logs pages

### Week 4: Optimization
- Performance tuning
- Bundle size optimization
- E2E testing with Playwright
- Documentation

### Month 2+: Feature Parity
- Remaining edge cases
- Advanced metadata editing
- Provider management
- Post-processing configuration
- **Remove old Mako UI entirely**

---

## Critical Files

**Files to modify:**

1. **mylar/webserve.py:6777** - Add `/app` route to serve React build
   - Add catch-all route for React Router client-side routing
   - Configure static file serving for assets

2. **mylar/webstart.py** - Configure CherryPy static file handler
   - Add `/app` route config for React build directory

3. **mylar/api.py** - Reference for existing API endpoints
   - No modifications needed for week 1
   - Week 2+: Add v2 REST endpoints here

**New files to create:**

1. **frontend/** - Entire new Vite + React project
2. **frontend/src/lib/api.js** - API client for Mylar3 endpoints
3. **frontend/src/hooks/** - Custom React hooks for data fetching
4. **frontend/src/components/** - All React components
5. **frontend/src/pages/** - Page components for routes

**Reference files (read-only):**

1. **data/interfaces/default/index.html** - Current series table UI (reference for features)
2. **data/interfaces/default/comicdetails.html** - Series detail UI reference
3. **data/js/common.js** - Current JavaScript patterns (understand AJAX calls)

---

## Verification & Testing

### Manual Testing Checklist

**Authentication:**
- [ ] Can enter API key and log in
- [ ] Invalid API key shows error
- [ ] Logout clears session
- [ ] Protected routes redirect to login

**Series Management:**
- [ ] Series table loads with data
- [ ] Pagination works (next/prev page)
- [ ] Click series navigates to detail page
- [ ] Series detail shows issues list
- [ ] Can pause/resume series
- [ ] Can delete series (with confirmation)
- [ ] Can refresh series metadata

**Search & Add:**
- [ ] Search input returns results
- [ ] Search results show cover art and metadata
- [ ] Can add series from search results
- [ ] Add series redirects to detail page
- [ ] New series appears in series list

**Queue Management:**
- [ ] Upcoming page shows this week's releases
- [ ] Can mark issues as wanted
- [ ] Can unqueue issues (mark skipped)
- [ ] Queue status updates in UI

**Settings:**
- [ ] Settings page loads
- [ ] Can view current settings
- [ ] Can modify settings (subset)
- [ ] Save button persists changes

**UI/UX:**
- [ ] Responsive on mobile (375px width)
- [ ] Loading states show during API calls
- [ ] Error states show helpful messages
- [ ] Empty states show when no data
- [ ] Keyboard shortcuts work (if implemented)

### Browser Compatibility

Test on:
- [ ] Chrome (latest)
- [ ] Firefox (latest)
- [ ] Safari (latest)
- [ ] Mobile Safari (iOS)

### Performance Benchmarks

- [ ] Initial page load < 2 seconds
- [ ] Series table loads < 1 second
- [ ] Search results appear < 1 second
- [ ] Page transitions feel instant

---

## Conclusion

This plan outlines an aggressive 7-day migration using AI-assisted development and a big bang rewrite approach. Success depends on:

1. **Ruthless scope management** - MVP features only
2. **AI leverage** - Let AI generate boilerplate and components
3. **Existing API use** - Don't block on new API development
4. **Continuous testing** - Test as you build, not at the end
5. **Realistic expectations** - 80% feature coverage is success

**Week 1 delivers:** Working React app with core workflows (browse, search, add, queue, basic settings)

**Week 2+ adds:** Advanced features, full config, import, polish

**End state:** Modern, maintainable React frontend that's easier to extend and attracts contributors.

Let's build this! 🚀
