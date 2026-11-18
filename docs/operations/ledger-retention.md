# Ledger retention

Daily job that bounds the five unbounded operational ledgers. Parameters are
**module constants only** (no Settings knobs). This note is self-contained for
operators and implementers; it does not depend on research-branch inventory
files.

| | |
| --- | --- |
| Job id | `ledger_retention` |
| Display name | **Ledger Retention** |
| Cadence | Daily (scheduler `max_instances=1`, coalesce) |
| Entrypoint | `comicarr.app.acquisition.retention.run_ledger_retention` |
| Soft-fail | Logs errors and returns; does not crash the process |

Narrative Activity event retention is a **separate** job
(`activity_retention` / **Activity Event Retention**). Do not conflate the two.

## Decision sources

- [Decide ledger deletion eligibility and delete order](https://github.com/frankieramirez/comicarr/issues/463)
- [Decide per-table ledger retention parameters](https://github.com/frankieramirez/comicarr/issues/464)
- [Decide UX when pruned ledger rows are missing](https://github.com/frankieramirez/comicarr/issues/465)

## Parameter table and hybrid / age formulas

Hybrid predicate (items, runs, maintenance, AI):

```text
eligible AND age > horizon AND row NOT IN (
  newest N eligible rows ordered by age_column DESC, pk DESC
)
```

In plain language: **keep** a row if it is **younger than the age horizon OR
among the newest N eligible rows**; **delete** only when it is **older than the
horizon AND outside the newest N**.

Age-only (`pipeline_journal`): `eligible AND age > 365 days` (no count floor).

| Table | Eligible set | Policy | Age column | Steady-state intent |
| --- | --- | --- | --- | --- |
| `acquisition_run_items` | Terminal outcomes only (`accepted` / `running` never) | **90 days OR newest 50,000** terminal rows | `completed_at`, fallback `updated_at` | Small libs keep ~90d history; large libs hard-capped ~50k terminals |
| `acquisition_runs` | Completed runs with **zero** remaining items | **90 days OR newest 2,000** such runs | `completed_at`, fallback `updated_at` | Headers track item history; health “latest run” still has recent depth |
| `pipeline_journal` | `post_processed` + **resolved** `failed` / `manual_review` only | **365 days age only** | `updated_date` | Mild growth O(release_keys); avoid burst-evicting older series’ last grab |
| `acquisition_maintenance_events` | All rows | **90 days OR newest 5,000** | `created_at` | Recent fence audit + cap on repair-loop spikes |
| `ai_activity_log` | All rows | **90 days OR newest 10,000** | `timestamp` | Recent AI feed; empty is honest |

Constants live in `comicarr/app/acquisition/retention.py`
(`ITEMS_AGE_DAYS`, `ITEMS_KEEP_NEWEST`, …). They are **not** config registry
keys and are **not** operator-tunable.

## Eligibility floors (what may never be deleted)

| Class | Eligible to delete? |
| --- | --- |
| `acquisition_run_items` with `state IN (accepted, running)` | **Never** — recovery floor |
| Other (terminal) item states | Yes, under parameters |
| Runs that still have any items, or are not complete (`completed_at` null) | **Never** |
| Completed runs with zero remaining items | Yes, under parameters |
| `pipeline_journal` open stages | **Never** — recovery / open work |
| Unresolved `failed` / `manual_review` (needs-attention band predicate) | **Never** |
| `post_processed` and **resolved** terminals (`status` in `retried` / `ignored` / `imported`) | Yes, under parameters |
| `acquisition_maintenance_events` | All rows (parameter-eligible) |
| `ai_activity_log` | All rows (parameter-eligible) |

There is **no** “keep newest row per entity” immortality for Wanted sticky
annotations. Annotation loss after the item horizon is intentional honesty
(see UX below).

## Delete order and batching

One shared daily pass, **in this order**:

1. Eligible terminal `acquisition_run_items`
2. Eligible completed `acquisition_runs` with zero remaining items
3. Eligible `pipeline_journal` terminals
4. `acquisition_maintenance_events`
5. `ai_activity_log`

Each table step uses private batch size **500** rows per `DELETE`, looping until
dry for that step. Batch size is a module constant (`DELETE_BATCH_SIZE`), not
config. One transaction per table step so a late failure does not roll back
earlier tables.

## VACUUM (out-of-band only)

The sweep **never** runs `VACUUM` (or equivalent) in-process. Reclaiming free
pages after large deletes is an **operator** concern for the database
deployment (SQLite: out-of-band `VACUUM` / maintenance window; Postgres:
autovacuum or scheduled maintenance). Do not treat vacuum as a product feature
or Settings control.

## Job wiring

- Registered via `_add_recurring_job` in `comicarr/app/core/lifecycle.py` with id
  `ledger_retention`
- Display name in `SCHEDULER_JOB_NAMES`: **Ledger Retention**
  (`comicarr/app/system/service.py`)
- Independent of `SEARCH_INTERVAL`, DB Updater, and narrative retention

## UX when pruned rows are missing (#465)

Missing ledger rows after retention are **data absence**, not a special
“pruned” product state. No tombstones.

| Surface | After prune |
| --- | --- |
| `GET /api/search/runs/{id}` for a pruned run | Existing **404** / “search run not found” |
| Acquisition health “latest run” | Newest **remaining** run for that kind, or **omit** the kind — never invent healthy history from empty |
| AI activity list | Rows vanish; **empty list is honest** (not an error, no retention banner) |
| Wanted sticky annotation | When latest terminal item is gone → **null acquisition** → never-searched presentation (`— never searched`) |
| Needs-attention band | Unresolved rows never prune; band empty only when no open trouble remains |
| Timeline completed-run progress | Ledger-backed progress sources simply disappear for pruned runs (no ghost counters) |

Live nonterminal work stays correct because eligibility forbids pruning it.

## Operator checklist

1. Confirm the job appears as **Ledger Retention** in scheduler / system job
   listings after upgrade.
2. After the first daily run on a large library, expect deleted-row counts in
   logs (`[LEDGER-RETENTION] Sweep complete: …`). Soft-fail logs
   `[LEDGER-RETENTION] Sweep failed: …` without taking down the process.
3. If free disk does not return after large purges, schedule **out-of-band**
   database maintenance (VACUUM / autovacuum) — not an in-app action.
4. Do not expect Wanted sticky history or AI feed depth beyond the parameter
   table; empty / never-searched is correct after the horizon.
