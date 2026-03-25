---
date: 2026-03-24
topic: byok-ai-features
focus: BYOK AI features that provide real value for comic book management
---

# Ideation: BYOK AI Features for Comicarr

## Codebase Context

**Project shape:** Python 3.10+/CherryPy backend (migrating to FastAPI) + React 19/TypeScript frontend. SQLite database via SQLAlchemy Core. Deployed self-hosted on Synology NAS. No AI features exist currently.

**Metadata providers:** ComicVine, Metron, MangaDex — each with different data shapes, quality levels, and coverage gaps. Fernet encryption for stored API keys (reusable for LLM keys).

**Key pain points relevant to AI:**
- Filename parsing (filechecker.py ~1700 lines of regex) still fails on edge cases, leaving files unprocessed
- Search query construction is brittle; AlternateSearch field exists but requires manual population
- Metadata conflicts across providers resolved by "pick one and live with gaps"
- No discovery, recommendation, or collection intelligence layer
- Story arc reading order is entirely manual
- Weekly pull list is a flat undifferentiated dump
- Post-processing failures are opaque log messages

**Past learnings:**
- Fernet encryption system for API key storage; must respect SECURE_DIR init ordering
- ThreadPoolExecutor(max_workers=4) is the established concurrent API call pattern
- Silent failures are the recurring theme — errors must surface clearly
- Auth gating required on all endpoints (security audit finding)
- Use None for missing data, not sentinel values

**Design principle:** The LLM is the fallback on the happy path (filename parsing, search expansion) and the enabler on new surfaces (collection intelligence, library search, story arcs). Users pay only when something would have broken OR when they're getting genuinely new capabilities.

## Ranked Ideas

### 1. Collection Intelligence Dashboard
**Description:** A dedicated dashboard surface showing cross-series insights powered by the user's library data: nearly-complete runs with key missing issues identified, cross-series connections ("you have 3 X-Men titles but not the crossover event they feed into"), creator-follow suggestions, and collection pattern analysis. Operates on pre-aggregated stats (genre counts, publisher distribution, completion percentages) to control token costs. This is the centerpiece visible feature when AI is enabled.
**Rationale:** Gap detection today is series-by-series and mechanical. No feature connects knowledge across series boundaries. This is the highest-visibility AI feature — a new dashboard panel that makes a large library feel understood rather than just catalogued. For self-hosted users who invested in setup, this is the payoff.
**Downsides:** Token costs scale with library size — must use aggregated stats, not raw issue lists. LLM comic knowledge has a training cutoff. Recommendations require user trust.
**Confidence:** 75%
**Complexity:** High
**Status:** Unexplored

### 2. Natural Language Library Search
**Description:** A chat-style search input that accepts natural language queries about the user's library: "What Batman series am I missing issues from?", "Show me everything by Tom King", "Which runs are closest to complete?" Implemented as structured query building against predefined query patterns (NOT raw SQL generation) — the LLM maps user intent to parameterized query templates, then formats results conversationally.
**Rationale:** The existing UI requires navigating to specific pages and constructing filters manually. For power users with 500+ series, a single input box that makes the entire library queryable is the most visible signal that "AI is on." The database schema (comics, issues, storyarcs, weekly, snatched) is rich enough to answer complex cross-cutting questions.
**Downsides:** Predefined query patterns limit expressiveness vs raw SQL. Must handle gracefully when no pattern matches. Requires careful prompt engineering to map intent reliably.
**Confidence:** 72%
**Complexity:** Medium
**Status:** Unexplored

### 3. Story Arc Reading Order Generator
**Description:** Given an arc name or vague description ("the time Spider-Man got the black suit"), the LLM generates a cross-series reading order with issue-level granularity. Maps results against the user's library to show what they have vs. what's missing. Auto-populates the storyarcs table with ReadingOrder values. All output validated against known DB entries.
**Rationale:** Story arcs spanning 10+ series are effectively impossible to order manually. ComicVine arc data is often incomplete, especially for thematic crossovers. The storyarcs schema already supports manual (non-API) arcs. One-click arc assembly is a visible, delightful interaction.
**Downsides:** LLM may hallucinate issue numbers for less-known arcs. Must validate every issue against the DB. Reading order is subjective for some events.
**Confidence:** 70%
**Complexity:** Medium
**Status:** Unexplored

### 4. Weekly Pull List Curation ("Suggested For You")
**Description:** Each week when the pull list updates, a "Suggested for You" section appears on the pull list page. The LLM analyzes the user's collection patterns (publishers they follow, creators they collect, genres they favor, series with shared characters) and highlights new releases they aren't tracking but should care about: relaunches, spinoffs, same creative teams, crossover tie-ins.
**Rationale:** The weekly pull list currently only surfaces what the user already monitors. There is no discovery mechanism. Comic readers frequently miss new series that match their taste because weekly volume (50-100+ titles) makes manual scanning impractical. This shifts the app from reactive to proactive.
**Downsides:** LLM comic knowledge has training cutoff — may not know the very latest series. Suggestions need to be good enough to build trust or users will ignore them. Token cost per weekly run.
**Confidence:** 68%
**Complexity:** Medium
**Status:** Unexplored

### 5. AI Filename Parsing Fallback
**Description:** When the regex-based FileChecker.parseit() fails to extract series/issue/year from a downloaded filename, route it to an LLM for structured extraction. Only activates on already-failing files. If the LLM output doesn't match a known series in the DB, it's rejected. Falls back to current behavior if no API key is configured.
**Rationale:** Filename parsing is the single highest-friction silent failure. The existing parser is ~1700 lines of regex that still fails on edge cases. Call volume is naturally tiny (only failures). Every successful AI parse is a file that would have required manual intervention on a headless NAS.
**Downsides:** Requires user to have configured an API key. Results need DB validation. Won't help if the series isn't in the watchlist yet.
**Confidence:** 92%
**Complexity:** Low
**Status:** Unexplored

### 6. Smart Search Query Expansion
**Description:** When an NZB/torrent search returns zero results, pass the query to an LLM to generate 2-3 alternate formulations (abbreviations, alternate titles, volume disambiguation). Auto-populate the AlternateSearch field so the LLM call pays for itself on future search cycles. Compounding effect: each expansion prevents repeated zero-result cycles.
**Rationale:** Search failure is the second-biggest friction point. The AlternateSearch field already exists but requires manual population. This automates what power users do manually. One cheap text call can permanently improve hit rates for a series.
**Downsides:** Alternate names may not match provider naming conventions. Worst case: expanded terms also return nothing (no harm done).
**Confidence:** 88%
**Complexity:** Low
**Status:** Unexplored

### 7. ComicInfo.xml Metadata Enrichment
**Description:** For issues with sparse or missing ComicInfo.xml fields, generate genre tags, age ratings, and short summaries from existing metadata (title, publisher, credits, year). Written back into CBZ during post-processing. Only fills blanks — never overwrites existing fields. User can enable/disable per field type.
**Rationale:** No genre or tagging infrastructure exists in the DB. Many entries from ComicVine have empty descriptions. Enrichment happens once during post-processing but benefits every reader app (Kavita, Komga, Panels) that consumes the file.
**Downsides:** LLM-generated summaries may be inaccurate for obscure titles. Requires user confirmation or trust-based auto-apply setting.
**Confidence:** 75%
**Complexity:** Medium
**Status:** Unexplored

### 8. Metadata Conflict Reconciliation
**Description:** When ComicVine, Metron, and MangaDex return conflicting data (dates, credits, summaries), feed all three responses to an LLM to produce a merged canonical record. Manual trigger only — user clicks "Reconcile" on the issue detail page and approves the result before applying.
**Rationale:** Each provider has different strengths. Today it's "pick one and live with gaps." The LLM can reason about which source is more authoritative per field and handle genuinely ambiguous cases by surfacing them.
**Downsides:** Must be manual trigger, never automatic. User must review before applying. Limited value if user only uses one provider.
**Confidence:** 72%
**Complexity:** Medium
**Status:** Unexplored

## Rejection Summary

| # | Idea | Reason Rejected |
|---|------|-----------------|
| 1 | Vision-Based Cover/Page Analysis | Vision calls 10-50x more expensive than text; scanning thousands of issues is untenable for self-hosted |
| 2 | Vision-Based Duplicate Resolution | Same cost problem; perceptual hashing (pHash) is deterministic, free, and runs locally |
| 3 | Smart Notification Digest | Template problem, not AI problem; Jinja template does this better and free |
| 4 | Download Candidate Ranking | Solved problem in *arr ecosystem with deterministic regex scoring |
| 5 | Adaptive Naming Template Generator | UI/UX problem with ~10 variables; dropdown + live preview is more reliable |
| 6 | Post-Processing Error Diagnosis | Risk of confabulated explanations; better to improve error messages directly |
| 7 | Conversational Library Assistant (raw SQL variant) | LLM-generated SQL against user DB is a data corruption vector |

## Session Log
- 2026-03-24: Initial ideation — 40 raw ideas generated across 5 agents (user pain, missing capabilities, inversion/automation, assumption-breaking, leverage/compounding), deduped to 15 unique candidates, adversarial filtering from 2 critics (pragmatism + technical feasibility), 7 initial survivors
- 2026-03-24: User feedback — survivors too subtle/behind-the-scenes, wants visible experience boost when AI is enabled. Promoted Natural Language Library Search (safe implementation) and Weekly Pull List Curation back to survivors. Reframed Collection Intelligence as centerpiece. Final set: 8 survivors (4 visible UI features + 4 behind-the-scenes quality boosts)
