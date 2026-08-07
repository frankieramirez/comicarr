# Activity Center — UX model and event contract

Decision record for [Design live activity visibility and timeline](https://github.com/frankieramirez/comicarr/issues/424),
charted under [Wayfinder: Activity Center](https://github.com/frankieramirez/comicarr/issues/425).
Every product and seam choice below is closed on that map; this document consolidates
them for implementers. Do not re-litigate settled tickets — zoom the linked issue for
detail, evidence, and rejected alternatives.

**Grounding tree:** decisions were verified against the tree at `ced9e2c7` and later
amended only by later closed tickets on the same map.

---

## 1. Destination (what we are building)

Comicarr gains a plain-language **Activity Center**:

1. A **compact global status line** showing whether the app is busy, how much is in
   flight, and whether anything needs the operator.
2. An **Activity page timeline** — chronological, human-readable, live while open —
   as the landing surface on `/activity`, with existing Direct Downloads and Download
   History as drill-downs.
3. A durable **narrative event table** plus **derived** live projections from existing
   acquisition ledgers, published through one **write facade** onto the existing
   `EventBus` / SSE transport.

**Not** a raw-log viewer, not fabricated search percentages, and not a fold-in of
`ai_activity_log`.

---

## 2. Surface ownership

| Surface | Owns | Source of truth |
|---|---|---|
| **Wanted** | Intent (still leave on snatch). Live-and-sticky **annotation** from the latest `acquisition_run_items` row for that issue | Legacy `t_issues.Status == 'Wanted'` membership; annotation from ledger |
| **Timeline** (`/activity` landing) | Narrative of work + pinned **needs-attention** band | Narrative table (feed); `pipeline_journal` (band) |
| **Direct Downloads** (renamed Queue tab) | DDL-only provider detail (`t_ddl_info`) | Unchanged |
| **Download History** | Cross-provider history (`t_snatched`) | Unchanged |
| **Global status line** (`AppStatusBar`) | Quiet counts: library · api · in flight · optional attention | Derived ledgers only |

Decisions: [Decide what Wanted, Queue and Activity each own in the UI](https://github.com/frankieramirez/comicarr/issues/429),
amended by [Prototype the global one-line status indicator](https://github.com/frankieramirez/comicarr/issues/434)
(`in flight` includes active searches, not journal stages alone).

### Tabs on `/activity`

Order: **Timeline · Direct Downloads · Download History**. Timeline is the default
landing view. No new nav item.

`/activity/attention` is a **route beside these tabs, not a fourth tab** — adding one
would change the order this section fixes, for a work queue that should be episodic.
The status indicator's attention count clicks through to it; the `in flight` / `idle`
segments still click through to `/activity`.

### Needs-attention band

Pinned **above** the chronological feed. Population:

```sql
SELECT * FROM pipeline_journal
 WHERE stage IN ('failed', 'manual_review')
   AND (status IS NULL OR status NOT IN ('retried', 'ignored', 'imported'))
   AND (fail_reason IS NULL OR fail_reason NOT IN (
         -- NON_ACTIONABLE_FLAT from comicarr/app/activity/reasons.py
         'download_gone', 'download_failed_researching',
         'ddl_download_or_artifact_validation_failed', 'ddl-worker-rejected',
         'torrent_hash_not_in_client', 'legacy_downloading_without_correlation',
         'ambiguous_ddl_acceptance_after_restart'
       ))
   AND (fail_reason IS NULL OR fail_reason NOT LIKE 'immutable_payload_conflict:%')
 ORDER BY updated_date DESC
```

Admission is the **two-clause actionability test** ([#523](https://github.com/frankieramirez/comicarr/issues/523),
[ADR-0001](../adr/0001-band-actionability.md)): the band admits trouble only when
the operator holds something the system lacks, and exclusion always reconciles
the issue (re-want / blocklist) so nothing is left at `Snatched` with the band
as its only recovery path ([#541](https://github.com/frankieramirez/comicarr/issues/541)).
The live predicate lives in `unresolved_band_condition()`; the SQL above is the
shape, not a second source of truth.

Those rows are then **grouped server-side** before anything renders them
([Decide the grouping key and group-row contract](https://github.com/frankieramirez/comicarr/issues/524)):

- **Key: `(comicid, base_reason)`** from `payload_json`, or a singleton
  `(release_key, base_reason)` when the payload carries no `comicid`. `base_reason` is
  the substring before the first `:` — the same unit `activity/reasons.py` keys on.
- **Labels are payload-first.** No join to `issues` / `annuals` / `comics`, and never a
  key on `comicname` (a typographic apostrophe split one real series in two).
- **List and count share one builder.** `list_attention_groups` and
  `count_attention_groups` run the same code, so the band and the status line cannot
  disagree. `GET /api/activity/status` reports `attention` as a **group** count, with
  the row count beside it as `attention_members`.
- Scoped views filter members **then** group — never a cross-scope group.

The band itself is a **bounded preview that routes, never a workspace**
([Prototype the bounded band preview and triage surface](https://github.com/frankieramirez/comicarr/issues/526)):
at most 5 group cards in one fixed-height row, ranked newest-first with volume as a
card attribute (`×N`), stage-coloured (failed = error, manual review = paused), folding
into `/activity/attention` via "See all N →" and a trailing "+K more" card. The ceiling
is the contract: the timeline's position on the page must not depend on how much has
gone wrong.

- Work queue, not notice board: rows clear only when an operator action moves the item.
- Red + actions live **only** on the band and its triage route; stream rows for the same
  trouble are muted history with **no** actions
  ([Decide how failure, retry and degraded states read in the timeline](https://github.com/frankieramirez/comicarr/issues/432)).
- Band coverage for download failures that never terminalized the journal is achieved by
  **writing** `journal.mark_failed` at those seams, not by widening the predicate
  ([Decide whether the needs-attention band covers journal-less failures](https://github.com/frankieramirez/comicarr/issues/457)).

### Triage route (`/activity/attention`)

The only surface where band trouble can be resolved. **Against Download History:**
Attention shows unresolved, actionable groups and carries the resolution actions;
History is the full ledger of every outcome and carries none. Audit vs work queue.

- Facets: stage (all / failed / manual review), age (any / 7d / 30d), free-text over
  series label and reason phrase.
- Per-group checkboxes; the selection bar shows group count, issue count, and surfaces
  the 25-row cap before the operator commits.
- Honours the same `scope_type` / `scope_id` params as the band — a scoped entry from a
  series page opens the same route, not a separate surface.

### Operator exits (`failed` / `manual_review`)

Stage lattice is **never** rewritten by operator actions. R9 columns already on
`pipeline_journal` (`status`, `retry_count`, `next_retry_at`) carry resolution:

| Stage | Actions (operator label → action id) |
|---|---|
| `failed` | Retry → `retry`, Stop wanting → `stop_wanting` |
| `manual_review` | Import → `import`, Search again → `search_again`, Stop wanting → `stop_wanting` |

A group's `available_actions` is the **intersection** across its members, and is empty
for mixed-stage groups — offering just the destructive half of two different obligations
as one click is worse than making the operator pick rows.

Every **member** also carries its own `available_actions`, derived from its own stage, so
a mixed group is never a dead end. Triage selects by `release_key`; a group checkbox is
shorthand for "all of its members"; bulk actions are the intersection over the selected
*rows*. Mixed groups open expanded, because picking rows is the only way to act on them.

Today's writers cannot produce a mixed group — reason → stage is a function, pinned by
`test_reason_to_stage_is_a_function`. That is a UX guarantee, not a correctness one:
unresolved band rows are **never pruned** (retention only touches resolved terminals,
after 365 days), so a database written by an older Comicarr can still hold a group whose
rows sit at different stages. Member-level eligibility is what keeps those rows workable.

- `retry` / `search again` re-want and call a scoped `search_issue`; stamp
  `status='retried'`; do not reset the failed journal row's stage.
- `stop wanting` → `AcquisitionIntent.IGNORED` + `status='ignored'`. The action id was
  renamed from `ignore` end-to-end ([Decide bulk-action fan-out semantics and action naming](https://github.com/frankieramirez/comicarr/issues/525))
  because "ignore" read as dismiss-this-alert; the **durable stamp keeps its
  `ignored` spelling**, since renaming a persisted status would re-admit every row
  already stamped. Two or more issues always require a consequence confirmation first;
  there is no timed undo.
- `import` → existing validated `POST /api/downloads/process`; stamp
  `status='imported'` **only on success**.

**Bulk fan-out** — `POST /api/downloads/needs-attention/batch` with
`{action, release_keys}`. Best-effort per row: each member runs the same path as the
single-row resolver, so a member that fails stays on the band while its siblings leave
it. At most **25** keys per request (fixed in code, newest `updated_date` first); the
remainder comes back as `skipped_for_cap`. A mixed outcome is `success: true` with
`partial: true` and a `results[]` entry per key, surfaced as a summary toast
("Search again 13 of 16 — 3 still need attention"), never a blocking modal.
- Same-provider retries can produce a byte-identical `release_key` and lose
  `record_transition`'s `won` guard — that bug must be fixed **before** `[retry]`
  ships ([Decide how an item exits manual_review and failed](https://github.com/frankieramirez/comicarr/issues/437)
  amendment from grouping).

`_try_reset_terminal_attempt` is the genuine-re-snatch path only; it is not the
operator path. It supersedes a terminal `failed` row unconditionally, and a
`manual_review` row **only once that row carries an R9 resolution stamp**
([#562](https://github.com/frankieramirez/comicarr/issues/562)).

The asymmetry is the point. An *unresolved* `manual_review` row is an open
obligation — "the client may already have this, go look" — and it is on the band
so a human does. Letting an automatic re-snatch reset it would hide the row and
re-deliver a release the client may already hold; on a route like `watchdir`,
where every acceptance is manual review by construction, every sweep would
deliver another copy. So it still blocks — but `handoff.reserve` now names the
row and its reason in the refusal instead of raising a bare reservation error.

Once the operator has acted, the obligation is discharged and the next grab must
proceed. Before #562 it could not: the stamp takes the row off the band without
rewriting `stage`, so the operator's own `[retry]` / `[search again]` — which
re-wants the issue and queues a search — then wedged at reservation for that
issue+provider, forever. This widens the *stage gate* only; nothing but a fresh
`RESERVED`/`SNATCHED` write reaches the helper, so it still cannot become an
operator exit.

---

## 3. Authority rule (derived vs narrated)

> **Derived state is authoritative for every count and every current-state badge.
> Narrated events are authoritative for every timestamped row. No surface computes one
> from the other, and no query aggregates the narrative table.**

The line is **tense**: ledgers answer *what is true now*; the narrative table answers
*what happened, when*.

| Kind | Examples | Store |
|---|---|---|
| Derived | `N in flight`, `⚠ K need attention`, in-flight run progress (`17 of 42 resolved`), Wanted sticky annotations, open story headers while a story is open | `acquisition_run_items`, `acquisition_runs`, `pipeline_journal` |
| Narrated | Feed rows, closed story headers, run **completion** brackets | Narrative table only |

**Enforcement (greppable):** `COUNT(*)`, `GROUP BY`, or `WHERE status = <current>` over
the narrative table is always a bug. The table is only ever read as an ordered
time slice.

Implications:

- `download.started` does not exist — downloading is live state.
- Per-issue `search.no_match` does not narrate — Wanted annotation + run bracket.
- `degraded` / `retrying` narrate **nothing** — guard + Wanted annotation only.
- In-flight search progress is **derived**; completion is **narrated** past tense.
- Retention may delete a feed row while a band row remains — accepted; the band is
  self-contained.

Decision: [Draw the line between derived state and narrated events](https://github.com/frankieramirez/comicarr/issues/427).

---

## 4. Event vocabulary

Two axes: **`activity` × `status`**. Severity is a pure function of `status`.

### Activities (7)

| activity | Meaning |
|---|---|
| `search` | Provider sweep / run bracket |
| `grab` | Release accepted and handed to downloader |
| `download` | Transfer completed (or failed) |
| `import` | Post-processing / library placement |
| `refresh` | Metadata pulled from a provider |
| `add` | Series or arc enters the library |
| `tag` | Metatagger writing into archives (not `refresh`) |

No `system` activity (version-check, restart, shutdown stay off the timeline).

### Statuses and severity

| status | Severity |
|---|---|
| `started`, `succeeded`, `no_match`, `cancelled` | `normal` |
| *(no narrative `retrying` rows)* | `degraded` is a **guard** only |
| `failed`, `blocked`, `needs_attention` | `action_required` |

**`retrying` is withdrawn.** `next_attempt_at` is written nowhere; the real backoff is
an in-process sleep capped at 60s. Discriminator for “retry pending” (guard only):
`state = accepted AND attempt_count > 0`.

### Subjects

`issue` · `annual` · `series` · `arc` · `run`

### Legal cells (summary)

Original legality table from
[Pin the Activity event vocabulary](https://github.com/frankieramirez/comicarr/issues/426),
amended by later tickets:

- **`tag`** row: `started` / `succeeded` / `failed` / `needs_attention` @ `issue`|`series`
- Blessed: `refresh × arc`, `grab × cancelled`, `import × cancelled`, `download × cancelled`
- Dropped: per-issue `search.no_match`, all `retrying` cells, `search.blocked` @ `run` as a feed row
- Run brackets narrate **completion** (and “nothing to search” vs “searched, no results” split)
- Operator ignore → `cancelled` with `reason_code = ignored_by_operator` on the activity that was in trouble

Producers write **data, never prose**. Sentences render client-side.

### Reason fields

| Field | Role |
|---|---|
| `reason_code` | Enumerated token; **required** when severity ≠ `normal`; client lexicon → phrase |
| `reason_detail` | Nullable free text; expand-only; never the primary detail line |

Unmapped codes degrade to a generic phrase + expandable raw token — never a snake_case
token as the primary sentence.

### Field contract (narrative row / SSE payload)

| Field | Notes |
|---|---|
| `event_id` | PK |
| `created_at` | Feed order; indexed for retention |
| `activity`, `status` | Discriminators |
| `subject_type`, `subject_id`, `subject_label` | Label denormalized so history survives subject deletion |
| `reason_code`, `reason_detail` | As above |
| `provider` | When relevant |
| `run_id` | **Search only** — removed from grab (grouping + seam unimplementable) |
| `release_key` | Required on `download` / `import` (journal join), not the grouping key |
| `parent_series_id` | Denormalized at write for series-scoped filters |
| `scope_type`, `scope_id` | On `run` subjects when the run is scoped |

---

## 5. Story grouping

The group is the **story of one subject**, not a batch / `run_id`.

| Rule | Value |
|---|---|
| Identity | `(subject_type, subject_id)` |
| Opens on | First **advance** for that subject (table below) |
| Closes on | Normative terminal-pair **allowlist** (table below) — not “anything that isn’t an advance” |
| Retry | Opens a **second** story; never reopens or merges with the first |
| Collapse | **Always** collapsed; group-of-one degenerates to a plain row |
| Position | Opening row’s `created_at`; **nothing re-sorts** |
| Open header | Derived from `pipeline_journal.stage` — **highest `stage_rank` among open rows** for the subject (concurrent attempts) |
| Closed header | Terminal event’s own sentence |
| Trouble | Non-`normal` events are closing events → headers; never trapped interior rows |

### Opening advances and terminal-pair allowlist

Terminality is a function of the **`(activity, status)` pair**, not of `status` alone
(`succeeded` ends `import` but not `grab`). The allowlist mirrors the journal’s
`TERMINAL_STAGES` spirit so UI “done” and pipeline “done” cannot drift
([#428](https://github.com/frankieramirez/comicarr/issues/428); `journal.py`
`TERMINAL_STAGES` / `STAGE_RANK`).

| Role | Legal pairs |
|---|---|
| **Advance** (opens a story if none is open; keeps an open story open) | `grab.succeeded`, `download.succeeded`, `import.started`, `tag.started` |
| **Terminal** (closes the open story for that subject) | `grab.failed`, `grab.blocked`, `grab.cancelled`; `download.failed`, `download.cancelled`; `import.succeeded`, `import.failed`, `import.needs_attention`, `import.cancelled`; `tag.succeeded`, `tag.failed`, `tag.needs_attention` |

Rules that follow from the tables:

1. **Only the four advances** may open or extend a multi-event story. Single-event
   rows (`add.*`, `refresh.*`, run brackets, etc.) are stories of one and render as
   plain rows — they do not use the advance/terminal lattice.
2. **A retry never reopens a closed story.** After a terminal pair, the next advance
   for the same `(subject_type, subject_id)` starts a **new** adjacent story (new
   opening `created_at`). It must not mutate or re-parent the prior closed group.
3. **Concurrent open attempts** (e.g. two DDL journal rows for one issue) reduce the
   open header by **max `stage_rank`** among that subject’s open `pipeline_journal`
   rows (`STAGE_RANK`: reserved 5 → snatched 10 → downloaded 20 → post_processing 30
   → moved 40; terminals are not open). Furthest-along attempt wins the header.
4. **Every non-`normal` severity event is a closer** under the allowlist, so trouble
   is always a group header, never an interior row.

Decision: [Decide grouping and collapse rules for the timeline](https://github.com/frankieramirez/comicarr/issues/428).
Prototype asset (throwaway): branch `prototype/timeline-view` — **Variant A (Ledger)**
won ([Prototype the timeline view](https://github.com/frankieramirez/comicarr/issues/435)).

### Timeline chrome (Variant A)

- Absolute `HH:MM` mono gutter, severity mark (6px dot: green open story, red closed-in-trouble, else none), sentence with inline entity link, `RelativeTime` right.
- **No** per-row `StatusPill`.
- Paginated **25** stories (not infinite scroll, not windowed).
- Sticky day rules (`TODAY` / `YESTERDAY` / weekday+date).
- Empty: `EmptyState` instead of toolbar; “Add a series” action.
- **Filters that ship:** free-text over subject/sentence fields, and **activity** dropdown. The prototype’s needs-attention toggle does **not** ship — the band is the attention surface. Scope arrives via query params (below).

---

## 6. Scoped timeline slices

Scoped views are **filters of Activity only** — no embedded feed on series/issue pages.

```
GET /api/activity/timeline?scope_type=issue|annual|series&scope_id=<id>
```

- Issue/annual: exact subject match.
- Series: rollup via `parent_series_id` + series subject rows + series-scoped run events.
- When scoped, the band is the open-trouble predicate **intersected** with that scope,
  and grouping runs **after** that intersection so a scoped view never shows a group
  containing members from outside the scope. `/activity/attention` takes the same two
  params and honours them identically.
- Deleted subjects: scoped deep-link empty/soft-404; global keeps `subject_label` history.
- Detail pages deep-link only, e.g. `/activity?scope_type=series&scope_id=…`.

Decision: [Decide whether series and issue pages get scoped timeline slices](https://github.com/frankieramirez/comicarr/issues/438).

---

## 7. Producer contract and `GLOBAL_MESSAGES`

### Facade

One **publish facade** owns narrative insert + SSE publish (precedent: `ai/service.py`
`log_activity`, corrected):

1. Narrative row **co-commits** into the caller’s transaction when `conn` is supplied.
2. **SSE publish only after a successful commit** of the transaction that made the row
   durable — never on insert success alone, never before durability, never after
   rollback. Invert the `log_activity` bug (publish even when insert failed).
3. **Shared-`conn` behavior:** when the caller passes `conn`, the facade inserts on
   that connection and **does not** publish inside the open transaction. The caller
   remains the transaction owner (today’s post-processor pattern: local
   `with db.get_engine().begin() as conn:` around journal + related writes). Publish
   runs only after that owner’s commit succeeds. Facade-owned writes (no `conn`)
   commit first, then publish.
4. **Do not** wire publish to SQLAlchemy Core `ConnectionEvents.commit` listeners —
   they fire **pre**-commit (verified on Core; `SessionEvents.after_commit` is
   ORM-only and unavailable here). Post-commit is a call-order contract on the
   local transaction owner, not an event-listen hook.
5. Gate journal-backed publishes on `record_transition`’s **`won`** return (idempotent under concurrency).
6. Publish is **best-effort** (no outbox, no poller) — the list is query-backed; a
   dropped SSE only delays an open page until the next refetch.
7. Enforce legal cells and `reason_code` invariants at this choke point.

### Wire

- Single SSE event type: **`activity`**, payload = typed row (`activity`/`status` discriminators).
- Timeline list is **query-backed**; stream **invalidates**, never accumulates.
- `EventBus` left unchanged (drop-oldest is correct under query-backed lists).

### Ledger hygiene (same effort)

- `record_outcome` / `record_requeue` run reasons through
  `comicarr.app.common.redaction.redact_sensitive_text`.
- `record_requeue(..., replay=False)`; facade publishes only when not replay; replay sites pass `replay=True`.
- `pipeline_journal.fail_reason` is token-only; exception text goes to sanitised detail
  (fix the one concatenating site at `downloads/service.py`).

### `GLOBAL_MESSAGES` retirement

~31 production write sites. Each conversion **deletes** its `GLOBAL_MESSAGES` write in
the **same** issue that adds its event. Final cleanup removes the declaration,
`global` entry, dead client handlers, and lands a **CI guard** (attribute assignment
cannot be made to fail by deleting the declaration). Contributor-only guard → document
in `CLAUDE.md`, **no changeset**.

`versioncheck` write is owned by the update-notification map (already sliced), not here.

Decision: [Settle the event producer contract and the fate of GLOBAL_MESSAGES](https://github.com/frankieramirez/comicarr/issues/430).

### Package seam

New domain package **`comicarr/app/activity/`** (facade, queries, router, retention).
Wire the router from `comicarr/app/main.py`. Do not hang narrative ownership off
`downloads` or `series`.

Table name: **`activity_events`**.

---

## 8. Live updates, reconnect, toasts

### Delivery

| Concern | Rule |
|---|---|
| Gap recovery | Refetch only — no `Last-Event-ID` / stream resume |
| Invalidation | Coalesce/debounce all narrative **and** derived keys on `activity` |
| Brief disconnect | Silent; keep last good query data |
| Prolonged loss | Status chrome `unreachable` (wire existing `isConnected` / `isReconnecting`) |
| Fallback poll | Permanent **30s** under SSE |
| Backoff | Keep 64s cap; visibility/focus → immediate reconnect |
| Multi-tab | Per-tab EventSource accepted |

Decision: [Decide live-update delivery, reconnect and fallback for an open timeline](https://github.com/frankieramirez/comicarr/issues/431).

### Toasts

One envelope, two consumers:

| Severity | SSE interrupt toast |
|---|---|
| `action_required` | Yes, subject to **enter-trouble session latch** |
| `degraded` / `normal` | Never |

Latch clears when open trouble the client can see is gone. Local mutation acks stay a
separate layer. Handler disposition table lives on
[Decide the relationship between toasts and the timeline](https://github.com/frankieramirez/comicarr/issues/439)
(`addbyid` / `storyarc_added` rewire; `search_*`, `scheduler_message`, `config_check`,
generic `message` delete; `shutdown`/`restart`/`ai_activity` keep).

---

## 9. Global status indicator

**Variant A — quiet counts** (prototype `prototype/global-status-indicator`):

```
library: N series · api: online · M in flight
library: N series · api: online · M in flight · ⚠ K need attention
library: N series · api: online · idle
library: unavailable · api: offline · unreachable
```

| Number | Query |
|---|---|
| `M in flight` | `COUNT(acquisition_run_items WHERE state IN ('accepted','running'))` **+** `COUNT(pipeline_journal WHERE stage IN OPEN_STAGES)` |
| `recovery_pending` | The subset of those run items with `recovery_count > 0` — a **qualifier** on `M`, never added to it |
| `K need attention` | Same unresolved band predicate as the Timeline band |
| `idle` | both open-work counts zero and attention zero |

**Why `M` is now trustworthy (#555).** Crash replay is a *re-driver*, not a
reaper: it re-queues every non-terminal run item at startup. That is right for
an obligation a restart interrupted and wrong for one that cannot make progress
— which was then replayed forever and counted here, producing a number
(famously "940 in flight") that mixed live work with residue.

`RunLedger.claim_recovery` bounds the re-drive: an item that has survived
`MAX_RECOVERY_ATTEMPTS` (3) restarts without reaching a terminal outcome is
quarantined with reason `recovery_attempts_exhausted` instead of re-queued. The
bound counts **restarts, not time** — a clock cannot tell a stuck item from one
queued behind a long backlog, while surviving three restarts without
terminalising can only mean stuck, so there is no TTL and no tuning knob.

Residue predating the bound is cancelled once by acquisition schema v7 with
reason `stale_before_recovery_bound`, so the number is honest on the first start
after upgrade rather than after three. That is safe because **the run ledger
records attempts, not intent**: wanting lives on `issues.Status`, so cancelling
a dead attempt row cannot lose a want — anything still Wanted is picked up by
the next sweep.

- Shared app SSE invalidates status React Query; **30s poll** remains; **no** second EventSource.
- Single click on activity/attention text → `/activity`.
- `aria-live` only for offline/recovery, attention appear/change/clear, idle↔busy — not count ticks.

Decision: [Prototype the global one-line status indicator](https://github.com/frankieramirez/comicarr/issues/434).

---

## 10. Retention

| Concern | Decision |
|---|---|
| Predicate | Age only: `DELETE WHERE created_at < now - 90 days` |
| Count ceiling | No |
| Severity tier | No |
| Job | Own daily `_add_recurring_job` + `SCHEDULER_JOB_NAMES` entry |
| Config key | No (constant; promote later if needed) |
| Manual purge | No |
| Index | Required on `created_at` |
| Scope | Narrative table **only** |

Five existing unbounded ledgers are a **separate** map:
[Wayfinder: Ledger retention](https://github.com/frankieramirez/comicarr/issues/458).

Decision: [Decide retention for the narrative event table](https://github.com/frankieramirez/comicarr/issues/433).

---

## 11. Explicitly not being built

Carried from the map’s Out of scope and closed tickets:

- Raw-log viewer / streaming `comicarr.log`
- Progress percentages or ETAs for searches; fabricated download progress
- Folding `ai_activity_log` into this timeline
- Retention for the five existing unbounded ledgers (→ #458)
- Manual “clear timeline”
- System notices in the timeline (version / restart / shutdown)
- Stall classifier / age-based open-stage band membership
- Embedded timeline on series/issue detail pages
- Changing the Wanted membership rule (still leaves on snatch)
- Replacing Direct Downloads content (rename + honesty only)
- Self-apply / update toast path (other map)

---

## 12. Implementation issues (dependency order)

Sliced by [Slice the approved design into implementation issues](https://github.com/frankieramirez/comicarr/issues/436).
Native GitHub `blocked_by` edges are the UI-visible frontier; the graph below is the index.

```
[477] Activity narrative table migration and indexes
  ├─► [479] Activity event write facade
  │     └─► [484] Wire producers + retire GLOBAL_MESSAGES writes
  │           └─► [488] Live updates, toast latch, dead SSE cleanup
  ├─► [485] Timeline, band, and open-work read APIs
  │     ├─► [486] Timeline UI + detail deep-links  (also ← 483)
  │     └─► [487] Global quiet-counts status indicator
  │           └─► [488] (also ← 484, 486)
  └─► [489] 90-day retention job

[482] Complete pipeline_journal terminals for failed-download paths
  └─► [483] Needs-attention band resolution actions  (also ← 477)
        └─► [486]

[490] Wanted live-sticky acquisition annotations   (unblocked)
```

**Frontier (can start now):** [#477](https://github.com/frankieramirez/comicarr/issues/477),
[#482](https://github.com/frankieramirez/comicarr/issues/482),
[#490](https://github.com/frankieramirez/comicarr/issues/490).

| # | Title | Changeset? | Blocked by |
|---|---|---|---|
| [#477](https://github.com/frankieramirez/comicarr/issues/477) | Activity narrative table migration and indexes | **No** (schema only) | — |
| [#479](https://github.com/frankieramirez/comicarr/issues/479) | Activity event write facade | **No** (internal) | 477 |
| [#482](https://github.com/frankieramirez/comicarr/issues/482) | Complete pipeline_journal terminals for failed-download paths | **Yes (patch)** | — |
| [#483](https://github.com/frankieramirez/comicarr/issues/483) | Needs-attention band resolution actions | **Yes (minor)** | 482, 477 |
| [#484](https://github.com/frankieramirez/comicarr/issues/484) | Wire activity producers and retire GLOBAL_MESSAGES writes | **No** if before UI; **yes (minor)** if feed already visible | 479, 482 |
| [#485](https://github.com/frankieramirez/comicarr/issues/485) | Activity timeline, band, and open-work read APIs | **No** (API-only) | 477 |
| [#486](https://github.com/frankieramirez/comicarr/issues/486) | Activity Center timeline UI and detail deep-links | **Yes (minor)** | 485, 483 |
| [#487](https://github.com/frankieramirez/comicarr/issues/487) | Global activity status indicator (quiet counts) | **Yes (minor)** | 485 |
| [#488](https://github.com/frankieramirez/comicarr/issues/488) | Activity live updates, toast latch, and dead SSE cleanup | **Yes (patch)**; CI guard no changeset | 484, 486, 487 |
| [#489](https://github.com/frankieramirez/comicarr/issues/489) | Activity narrative 90-day retention job | **No** | 477 |
| [#490](https://github.com/frankieramirez/comicarr/issues/490) | Wanted page live-sticky acquisition annotations | **Yes (minor)** | — |

*Practical call for producers:* prefer **one** minor changeset on the first
operator-visible PR that makes the feed real (usually timeline UI after producers).

### Shape vs the terminal ticket’s rough list

| Expected rough slice | Issue(s) |
|---|---|
| Migration + table | #477 |
| Write facade and seams | #479 |
| EventBus producer wiring + GLOBAL_MESSAGES retirement (writes) | #484 |
| Read endpoints | #485 |
| Timeline components | #486 |
| Status indicator | #487 |
| Retention job | #489 |
| Dead-client-handler cleanup | #488 (with live/toast) |
| **Added from closed decisions** | #482 journal terminals (#457); #483 band actions (#437); #490 Wanted annotations (#429); deep-links folded into #486 (#438) |

### Prototype assets (rewrite; do not merge branches)

- `prototype/timeline-view` — layout, day rules, collapse chrome, `stories` grouping helper
- `prototype/global-status-indicator` — quiet-count format + scenes

---

## 13. Decision index

| Ticket | Gist |
|---|---|
| [#429](https://github.com/frankieramirez/comicarr/issues/429) | Surface ownership; band; tabs; status line shape |
| [#426](https://github.com/frankieramirez/comicarr/issues/426) | Vocabulary axes; severity; subjects; sentences |
| [#427](https://github.com/frankieramirez/comicarr/issues/427) | Tense line; authority rule; reason_code/detail |
| [#432](https://github.com/frankieramirez/comicarr/issues/432) | Loud once; no retrying rows; honesty boundary |
| [#430](https://github.com/frankieramirez/comicarr/issues/430) | Facade; wire; GLOBAL_MESSAGES; tag; guards |
| [#437](https://github.com/frankieramirez/comicarr/issues/437) | R9 exits; band predicate; same-provider retry note |
| [#433](https://github.com/frankieramirez/comicarr/issues/433) | 90-day age retention; own job; no knob |
| [#428](https://github.com/frankieramirez/comicarr/issues/428) | Subject stories; always collapsed |
| [#457](https://github.com/frankieramirez/comicarr/issues/457) | Journal-complete failed paths for band coverage |
| [#438](https://github.com/frankieramirez/comicarr/issues/438) | Scoped Activity filters; deep-links only |
| [#439](https://github.com/frankieramirez/comicarr/issues/439) | Toast latch; handler disposition |
| [#434](https://github.com/frankieramirez/comicarr/issues/434) | Quiet counts status indicator |
| [#435](https://github.com/frankieramirez/comicarr/issues/435) | Ledger timeline chrome (Variant A) |
| [#431](https://github.com/frankieramirez/comicarr/issues/431) | Invalidate + 30s poll; no stream resume |
| [#436](https://github.com/frankieramirez/comicarr/issues/436) | This slice + ADR |

---

## 14. Acceptance against #424

| Criterion | Where |
|---|---|
| Decision record defines UX model and event contract | This document |
| Names data / source-of-truth path | §§2–3, 7 |
| Implementation slices and dependencies | §12 + linked issues |
