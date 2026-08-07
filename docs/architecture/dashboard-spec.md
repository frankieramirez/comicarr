# Dashboard content spec

**Status:** Locked  
**Date:** 2026-08-07  
**Issues:** [#557](https://github.com/frankieramirez/comicarr/issues/557) (IA), [#558](https://github.com/frankieramirez/comicarr/issues/558) (prototype), [#559](https://github.com/frankieramirez/comicarr/issues/559) (spec)  
**Map:** [Wayfinder: working downloads + a dashboard that tells the truth](https://github.com/frankieramirez/comicarr/issues/550)

Implementation is **out of scope** and hands off from this document.

**Prototype:** <https://claude.ai/code/artifact/7af93b62-0c45-49ab-86ad-5d6ebaed6320>
— a throwaway mock of §4 in the app's own tokens, with a scenario switcher for
the five health states in §3.1/§5. The switcher is the point: the panel that
matters most is the one you never see in a screenshot of a working system, so
"Silently broken" (every component reporting fine, nothing downloaded in eleven
days) is the state the design has to be judged against.

---

## 1. The persona and the failure this exists to prevent

The **general operator** runs Comicarr for themselves on a NAS or a home
server. They are not reading logs. They open the dashboard occasionally, and
the only reason they open it is to find out whether they need to do anything.

The failure that motivated this work: for weeks, Comicarr's downloads were
completely broken — the SAB handoff never delivered a file, searches aborted on
any provider hiccup, and series refresh raised on every write — and **the
dashboard showed nothing wrong**. It could not have: every panel reads legacy
tables (`t_snatched`, `t_ddl_info`, `t_comics`) that only record things that
*happened*. A pipeline that produces no events looks identical to a quiet week.

That is the design constraint, stated as a rule:

> **Days of silent failure must be impossible.** A dashboard that renders
> without incident is a positive claim that the automation is working. If the
> dashboard cannot substantiate that claim, it must say so instead.

Everything below follows from it.

---

## 2. Priority of questions

The dashboard answers four questions, in this order. The order is the layout
order, and it is not negotiable by panel prettiness.

| # | Question | Why here |
|---|---|---|
| 1 | **Is my automation healthy right now?** | The only question whose answer can require action today. Everything else is reading. |
| 2 | **What needs me?** | Actionable trouble, already modelled as the needs-attention band. |
| 3 | **What is happening / just happened?** | Confirms the machine is alive. Interesting, not urgent. |
| 4 | **What is my library, and what is coming?** | Ambient. Never changes what the operator does today. |

**Rejected orderings.** Library stats first (the current design) reads as a
vanity panel and pushes the only actionable content below the fold. "Recent
activity" first is exactly the trap that produced the silent failure: it is
*evidence of success only*, and its empty state is indistinguishable from
catastrophe.

---

## 3. Panels

Every panel names its data source. Panels marked **new source** are the point
of the redesign: the APIs already exist and the dashboard does not use them.

### 3.1 Health band — *new source*

The top of the page. Not a card among cards; a full-width band that is visually
quiet when everything is fine and unmissable when it is not.

| Signal | Source | Reads |
|---|---|---|
| Viable download route | `GET /api/search/health` → `viable_route`, `routes[]` | "SABnzbd + qBittorrent reachable" / "**No usable download route**" |
| Provider reachability | `GET /api/search/health` → `providers[]`, route `blocklist` state | "4 of 4 indexers responding" / "**2 indexers unreachable**" |
| Worker liveness | `GET /api/search/health` → `workers{}` (`alive`/`live`/`healthy`, heartbeats) | "Search, download, and post-processing running" / "**Post-processing worker not running**" |
| Acquisition gate | `GET /api/search/health` → `maintenance`, `blocked_producer_count` | "Paused for maintenance" when the runtime gate is closed |
| Last successful search | `GET /api/search/health` → `providers[].lastrun` | **"Last successful search: 3 days ago"** — see below |

**The "last successful search" line is load-bearing and must ship.** It is the
one signal that fails *loud on absence*. Every other health signal reports the
state of a component; this reports whether the pipeline has actually produced a
result recently. In the failure that motivated this spec, every component would
have reported itself fine while this line said "11 days ago". Degrade it
visually past a threshold (warn at > 2× `SEARCH_INTERVAL`); never hide it.

**States.** `healthy` → one quiet line. `degraded` → amber, naming the specific
component. `blocked` → red, naming it and linking to where it is fixed.
`unknown` (endpoint failed) → **must not render as healthy**; render as
"Cannot determine health" in the degraded treatment.

### 3.2 Needs attention — *new source*

`GET /api/downloads/needs-attention` (band groups, not rows).

Shows the group count and the top N groups with their operator phrase and
available actions. Zero groups renders as a single quiet "Nothing needs you"
line, not an empty card with a heading.

This panel is the *actionable* half of failure visibility; §3.1 is the
*infrastructural* half. Both are required — the band cannot show a downloader
that is simply unreachable (that self-heals and is route-scoped, per #554), and
health cannot show a specific release that needs a human decision.

### 3.3 In flight — *new source*

`GET /api/activity/status` → `in_flight`, `recovery_pending`.

One line: "12 in flight". When `recovery_pending > 0`, qualify it — "12 in
flight (3 recovered from a restart)". Never sum the two.

This number is only usable because #555 bounded crash replay; before that it
mixed live work with residue. **Do not re-derive it from any other table** —
`/api/activity/status` is the single definition.

### 3.4 Recent activity — *source change*

Narrative activity events (the `activity` stream / Activity Center reads), **not
`t_snatched`**.

The current panel is structurally incapable of showing a failure: it lists rows
from the snatched table, so an attempt that never got as far as being snatched
leaves no trace. Reading the narrative source instead means failures, manual
reviews, and blocked routes appear in the same timeline as successes.

Read as an **ordered time slice only**. Per the authority rule in
[activity-center.md](./activity-center.md), never `COUNT`, `GROUP BY`, or
`WHERE status = <current>` over the narrative table.

Empty state must be honest: "No activity in the last 30 days" — which, paired
with §3.1's last-successful-search line, is now legible as a problem rather than
as calm.

### 3.5 Upcoming this week — *unchanged*

`storyarcs_service.get_upcoming`. Ambient, correct, cheap. Keeps its place, but
below the actionable content.

### 3.6 Library — *reduced*

Series count, issues held, and completion — **one row of numbers, not the hero
of the page**.

`completion_pct` keeps its current definition (`total_issues / total_expected`)
but must be labelled as what it is: *issues held vs. issues known*. It is not a
health metric and must never be adjacent to the health band, where it would read
as one.

### 3.7 Queue — *removed as a panel; folded into §3.3*

The current "Queue" stat tile counts **active DDL items only**
(`count_active_ddl_items`). Labelled "Queue" on a dashboard, that is a false
claim: an operator running SABnzbd sees "0 queued" while SAB is downloading.
Either it becomes route-complete or it goes. It goes — `in_flight` (§3.3)
already answers "how much work is moving" across every route, and the DDL
preview list belongs on the downloads page, not here.

### 3.8 Ask / chat — *demoted*

Kept, moved below the fold. It is a feature entry point, not an answer to any of
§2's questions. Its suggestion chips ("Anything stuck in the queue?") were doing
health-reporting work that §3.1 now does properly and truthfully.

---

## 4. Layout

```
┌────────────────────────────────────────────────────────────┐
│ HEALTH BAND                        quiet when fine         │  §3.1
│ ✓ Route: SAB + qBittorrent · 4/4 indexers · workers up     │
│ Last successful search: 12 minutes ago                     │
├────────────────────────────────────────────────────────────┤
│ ⚠ 3 need attention                    12 in flight (3 rec.)│  §3.2 §3.3
│   · Saga #12 — download failed          [retry] [stop]     │
│   · 2 more…                                                │
├──────────────────────────────────┬─────────────────────────┤
│ RECENT ACTIVITY (narrative)      │ THIS WEEK               │  §3.4 §3.5
│                                  │                         │
├──────────────────────────────────┴─────────────────────────┤
│ 412 series · 8,204 issues · 87% of known issues held       │  §3.6
├────────────────────────────────────────────────────────────┤
│ Ask about your library…                                    │  §3.8
└────────────────────────────────────────────────────────────┘
```

The vertical order *is* the priority order from §2. On narrow viewports the two
middle columns stack in the same order.

---

## 5. Degraded and error states

The dashboard fans out to several endpoints. Partial failure must not be
silent, and must never be optimistic.

| Condition | Behaviour |
|---|---|
| A panel's endpoint fails | That panel renders "Unavailable", with its own retry. Neighbours still render. |
| **The health endpoint fails** | The health band renders **degraded**, not absent and not healthy. Absence of evidence is not health. |
| A panel is empty | An honest empty sentence, never a blank card. "Nothing needs you" / "No activity in the last 30 days". |
| Everything is loading | Skeleton in the final layout — the health band must not pop in last and shift the page. |

---

## 6. Guarantees this spec makes

1. **No panel infers health from the absence of bad news.** Health is read from
   `/api/search/health`, which reports component state directly.
2. **At least one signal fails loud on absence** — last successful search
   (§3.1). A pipeline that stops producing is visible without anything having to
   report an error.
3. **Failure and success share a timeline** (§3.4). A failed attempt cannot be
   invisible merely because it never reached the snatched table.
4. **No count is derived twice.** `in_flight` and the attention count come from
   `/api/activity/status` and the band predicate respectively — the same sources
   the global status bar uses, so the two can never disagree.
5. **No panel claims coverage it does not have.** The DDL-only "Queue" tile is
   gone rather than relabelled.

---

## 7. Deliberately out of scope

- **Notifications / alerting** (push, email, badge). #554's route-scoped
  grouping gave a downed downloader a single self-healing band row, so the
  loudest infrastructure failure already has a home. Revisit only if the health
  band proves insufficient in use.
- **Per-panel configurability.** A dashboard the operator can rearrange is a
  dashboard whose failure-visibility guarantees can be turned off.
- **Implementation.** Panel components, queries, and hooks are a fresh effort.
