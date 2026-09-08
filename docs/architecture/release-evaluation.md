# Release candidate evaluation

`comicarr.app.search.evaluation` owns the interpretation of a Release candidate:
normalization, identity inputs, match verdicts, duplicate suppression, pack
membership, and the tracked items a candidate satisfies. Automatic search,
GetComics, and Interactive release search all cross this module's interface.

Search provider queries, retries, series-wide ranking, candidate persistence,
and acquisition handoff retain their existing owners. Evaluation does no network
retrieval. Its private pack-membership adapter reads the library through the
existing database helpers; tests substitute SQLite. Configuration is read at the
same points as before, including inside the filename parser.

## Interface and state

Each search passes an `EvaluationSession` explicitly through `searchforissue`,
`search_init`, `search_the_matrix`, and `NZB_SEARCH`. GetComics receives the same
session. The session owns accepted-candidate history; no process-wide candidate
global participates in evaluation.

`evaluate(entries, is_info, prefer_pack=None)` returns an `EvaluationBatch`.
Its `evaluations` contain ordered structured verdicts; `selected` returns the
candidates selected by the existing search policy, or raises the original
collection error. A review session retains completed collections in
`evaluations`. `start_search()` resets duplicate history without discarding
already collected review results.

The searched item and eligible items supplied to a series review let evaluation
compute `satisfies`. Series aggregation merges and ranks those results without
decoding pack dictionaries. Single-target pack membership and series-wide
eligible-item satisfaction remain distinct decisions inside the implementation.

`ReleaseCandidateEvaluation.as_dict()` is the public projection. Identity hints
remain server-side and are allowlisted and hashed by session persistence.
Only `evaluation_handoff.py` translates private accepted data into the legacy
dictionary used by acquisition. Revalidation still queries again, requires a
unique identity match and accepted handoff data, and permits only the explicitly
requested overrideable rejection to be bypassed.

## Preserved behavior

| Collection | Duplicate history | Consumption and selection |
| --- | --- | --- |
| Batch, automatic or review | Reset; append each accepted candidate in order | Evaluate all entries; select accepted candidates |
| GetComics automatic | Retain prior batch history; do not append | Stop at first preferred match; otherwise use last fallback |
| GetComics review | Retain prior batch history; do not append | Materialize first, evaluate all; use first preferred match or first fallback |

A batch or automatic GetComics collection stops on an evaluator exception and
raises it when selection is requested. Failed batches do not publish partial
review results. GetComics review retains structured errors and continues, as
the previous collect-all path did.

Pack membership currently registers queue-suppression claims during evaluation,
before handoff. The private adapter preserves that timing. Moving claims to
handoff, changing duplicate scope, freezing a configuration snapshot, or changing
matching rules would be separate behavior changes.

Provider progress callbacks remain in `progress.py`; they carry only completion
and failure updates. They do not carry evaluations or determine review mode.

## Verification

`test_release_evaluation.py` retains the rejection and matching regression
matrix. `test_release_evaluation_integration.py` exercises the interface with
the real parser and SQLite, including pack claims and satisfaction, independent
session state, GetComics iteration, narrow overrides, and provider collection
without handoff. Existing interactive session, grab, and search-pass tests cover
the surrounding workflows. Source-string matcher wiring tests were retired in
favor of observable manga-volume acceptance tests.
