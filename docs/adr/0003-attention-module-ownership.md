# ADR-0003: Attention module ownership and HTTP migration

**Status:** Accepted
**Date:** 2026-08-12
**Related:** [ADR-0001](./0001-band-actionability.md),
[Activity Center contract](../architecture/activity-center.md)

## Context

Needs attention is one operator work queue, but its implementation was split
across several modules. Activity classified, queried, grouped, and counted the
rows; Downloads decided which actions were legal and orchestrated them; journal
callers recorded terminal trouble and separately remembered whether an excluded
reason needed reconciliation.

That split exposed several competing interfaces. In particular,
`GET /api/activity/band` returned the actionable grouped view while
`GET /api/downloads/needs-attention` returned raw unresolved journal rows without
the actionability rule. Reads, counts, recording, and resolution could therefore
drift even though they describe one domain concept.

## Decision

### One top-level module

`comicarr.app.attention` owns the complete work queue of unresolved, actionable
acquisition obligations that Comicarr cannot finish without operator information,
authority, or judgment. The bounded band on Activity and Dashboard pages is a
preview of this queue, not a separate definition of it.

The module exposes exactly three public operations:

```python
read(scope=None) -> AttentionView

resolve(
    ctx,
    ResolutionRequest(action, release_keys, actor, import_source=None),
) -> ResolutionReport

record(
    entry: Failure | ManualReview,
    *,
    conn=None,
) -> RecordOutcome
```

`read` owns admission, reason classification, scoping, grouping, ordering,
action eligibility, and consistent group/member totals. `resolve` owns validation,
the 25-item cap, one-or-many best-effort fan-out, action orchestration, and durable
resolution stamps. `record` makes the journal transition, reason classification,
and any required excluded-reason reconciliation one operation.

The read interface returns immutable typed `AttentionGroup` and
`AttentionMember` values. HTTP and compatibility adapters alone translate those
values to the established dictionary wire shape.

Reason predicates, grouping helpers, count helpers, action-specific resolvers,
reconciliation functions, and stamp helpers are implementation details rather
than additional public interfaces. Unknown reason tokens remain admitted
(fail-open), as decided in ADR-0001.

### Private seams

The pipeline journal remains the private low-level implementation for release
keys, monotonic transitions, caller-owned transactions, and resolution stamps.
Generic transitions, successful completion, release-key derivation, retention,
and the journal stage lattice do not move into Attention. The journal's internal
immutable-payload-conflict transition invokes a private post-transition hook so
it can satisfy reconciliation without recursively calling `record`.

Without a supplied connection, `record` owns one retrying transaction for the
terminal transition, Activity narrative, and reconciliation writes, publishing
the Activity event only after commit. With `conn`, all writes join the caller's
transaction and the caller retains commit ownership.

Only `resolve` receives `AppContext`. Its search, import, and reconciliation
effects are hidden behind one private adapter with production and deterministic
test implementations. `read` and `record` use the SQLite-substitutable persistence
interface directly. Attention is neither a global module instance nor an
addition to `AppContext`.

### Enforcing the seam

The seam is mechanically enforced. `scripts/check_attention_seam.py`, wired into
`npm run lint:guards`, AST-scans every module under `comicarr/` outside
`comicarr/app/attention/` and fails on any import of a private Attention
submodule, including function-local and relatively spelled ones. A declared
seam that nothing checks drifts back into the split this decision removed.

Crossings that already exist are waived by an explicit allowlist keyed on
`(file, private submodule)`, split into permanent internal hooks — the journal's
post-transition reconciliation hook and the boot-time reconciliation sweep —
and deprecated compatibility shims that leave with the routes above. Each entry
carries its reason and its removal trigger.

The allowlist only shrinks. An entry that no longer matches a real import is
itself a failure, so retiring a shim means deleting its import and its
allowlist entry in the same change; the guard names the stale entry when the
second half is forgotten. Widening `__all__` is not a way to satisfy the guard.

### Canonical HTTP interface

The canonical authenticated interface is:

- `GET /api/attention`, optionally scoped, returning groups and group/member
  totals from one `AttentionView`.
- `POST /api/attention/resolve`, accepting one action and one or more
  `release_keys`, plus an optional import source. The authenticated session is
  the actor; a client cannot supply it.

The bounded five-card preview is presentation metadata added by the HTTP adapter,
not domain state. A semantically invalid command returns `400`; a valid command
returns `200` when at least one item succeeds and `409` when none succeeds.
Per-item outcomes remain in the unified report. Framework request-shape errors
remain `422`.

The unused raw `GET /api/downloads/needs-attention` route and its duplicate
journal reader are deleted when this interface ships. The bundled frontend moves
to the canonical routes immediately.

For the release that introduces the canonical interface, the following used
routes remain as deprecated, serialization-only compatibility adapters:

- `GET /api/activity/band`
- `POST /api/downloads/needs-attention/batch`
- `POST /api/downloads/needs-attention/{release_key}/retry`
- `POST /api/downloads/needs-attention/{release_key}/search-again`
- `POST /api/downloads/needs-attention/{release_key}/stop-wanting`
- `POST /api/downloads/needs-attention/{release_key}/import`

They are removed in the immediately following release. The single-item adapters
preserve their existing response bodies and status distinctions; redirects are
not used because the command bodies and responses differ.

## Consequences

- Every read, count, recording path, and operator exit crosses one deep module
  interface, so the actionability rule and available actions cannot diverge by
  caller.
- Journal transaction and monotonicity behavior is preserved while its policy
  helpers cease to be public seams.
- Interface tests replace tests coupled to Activity and Downloads helpers. The
  journal and the neighboring Series intent, search, post-processing, re-snatch,
  and acquisition-repair modules retain their focused tests.
- The extraction preserves behavior except for enforcing ADR-0001 admission
  everywhere and migrating the HTTP interface. It adds no pagination, claim,
  lease, globally atomic batch, or new durability model.
- Removing the compatibility routes requires a follow-up release record; they
  are not indefinite aliases.

## Rejected alternatives

| Alternative | Why rejected |
|---|---|
| Keep ownership in Activity | Makes the operator exits and failure writers depend on a timeline-oriented module |
| Move ownership to Downloads | Makes Activity and Dashboard projections depend on downloader routing and preserves the misleading raw-reader seam |
| Move the full journal into Attention | Conflates a reusable transition ledger with the policy for one projection over it |
| Publish repositories, predicates, counters, stampers, and action-specific resolvers | A wide, shallow interface lets callers reconstruct inconsistent policy |
| Introduce broad public ports for every collaborator | Adds hypothetical flexibility and scatters the behavior that must remain local |
| Pass `AppContext` to every operation or install a global Attention instance | Weakens local substitution and test isolation when only operator resolution needs runtime effects |
| Add only a delegating facade and defer consolidation | Preserves duplicate implementation and makes the new interface ornamental |
| Keep action-specific canonical HTTP routes | Recreates action seams instead of exposing the module's one-or-many resolution command |
| Remove all old routes immediately | Needlessly breaks integrations already using the grouped read and resolution routes |
