# The log level contract

Comicarr has exactly one verbosity control: the numeric level `comicarr.LOG_LEVEL`.
It resolves to a single stdlib threshold, and that same threshold is applied to
the logger and to every sink it feeds. There is no second dial.

## The dial

| Level | Threshold | Console | `comicarr.log` | Web UI log list |
| --- | --- | --- | --- | --- |
| `0` — `warning` | `WARNING` | warnings and errors | warnings and errors | warnings and errors |
| `1` — `info` (default) | `INFO` | info and above | info and above | info and above |
| `2` — `debug` | `DEBUG` | everything | everything | everything |

Levels below `0` clamp to `WARNING`; above `2` clamp to `DEBUG`.

### The names are determined, not chosen

Each level *is* a stdlib threshold, so the threshold names it. That rules out
the obvious `quiet` / `normal` / `verbose` triple, which this document used
until #620: level `0` emits warnings and errors, and calling it "quiet" is the
same class of lie as #610 — a control describing behaviour the process does not
have. An operator who reads "quiet" and hears "silence" will turn the dial down
and believe failures stopped.

There is exactly one name per level. `warn` is refused as a second spelling of
one level; `error` and `critical` are refused because no level delivers them —
`--log-level error` could only mean "warnings and errors", which is level `0`
under a name that promises something narrower.

`quiet` and `verbose` survive only as the flag spellings `--quiet` and
`--verbose`, which is a different thing from a level name and is covered below.
Neither is accepted as a *value*: `--log-level` was `type=int` before #620, so
nobody could ever have typed them and there is no back-compatibility to keep.

`logger.threshold_for_level()` is the only place this mapping lives, and
`logger.current_log_level()` is the only supported way to ask what the dial is
currently set to. Nothing else may branch on verbosity.

## Where the level comes from

The dial says what a level *means*; this says where the number is *read from*.
Three sources, highest priority first:

| Priority | Source | Set by |
| --- | --- | --- |
| 1 | a startup argument — `--log-level N`, or the `--verbose` / `--quiet` aliases | the command line, a systemd unit, a container entrypoint |
| 2 | the `COMICARR_LOG_LEVEL` environment variable | a compose file, the shell |
| 3 | `LOG_LEVEL` in `config.ini` | the Settings UI |

If none of them supplies a value, the level is `1`.

**Every source accepts both notations.** `--log-level debug`,
`COMICARR_LOG_LEVEL=debug`, `LOG_LEVEL = debug` in `config.ini`, and a `"debug"`
sent to the Settings endpoint all mean level `2`. Matching is
case-insensitive and tolerates surrounding whitespace. One grammar everywhere is
the point: an operator who reads `Debug` on the Settings dial and types
`--log-level debug` must not meet an error, and a source that quietly accepted
less than its neighbours would only ever be discovered by tripping over it.

**The stored value is always the integer.** A name is normalised by
`parse_level` at the boundary and never reaches `config.ini`, so `LOG_LEVEL`
stays the `int` the registry declares and the generated frontend types expect.

**A source counts only when it explicitly supplies a value.** That qualifier is
the whole rule, and it is what #610 got wrong: the Docker entrypoint passed
`--quiet` on every start, so the top of the chain was permanently occupied and
nothing an operator set below it could ever be heard. An argument that was not
passed must leave the layer beneath it alone. In particular, level `0` is a
value, not an absence — a falsy check here reintroduces the bug.

Resolution happens once, when config is read at startup, in
`comicarr/app/config/log_level.py`. Every source is parsed even when a
higher-priority one has already won, so an operator who typoed
`COMICARR_LOG_LEVEL` is told about it, and the winning source announces what it
overrode.

Values outside `0`–`2` are clamped rather than rejected: a compose file asking
for `3` wants maximum verbosity, and refusing to boot over it helps nobody. A
value that is neither a number nor one of the three names is ignored with a
notice, and the next source down is used.

Operator-facing text names the level in both notations — `Log level 2 (debug)
from startup argument overrides 1 (info) from the config file`. The number is
what an operator's config and compose files contain; the name is what `--help`
and the Settings dial show them. `describe_level()` is the single renderer.

`COMICARR_LOG_LEVEL` is a deliberate one-off for this one key. Comicarr does not
read the environment for any other setting, and a general `COMICARR_<KEY>`
mechanism is a separate question — it raises precedence, secrets-in-env, and
UI-honesty problems that have nothing to do with logging.

### Saving the level from Settings applies it now

The Settings page is not part of the startup chain: it writes `LOG_LEVEL` to
`config.ini` *and* reconfigures the running logger, so the change takes effect
without a restart. The whole point of turning verbosity up is to catch a
problem while it is happening, and a dial that waits for a restart destroys the
state the operator was trying to capture.

`update_config` (`comicarr/app/system/service.py`) persists first and calls
`logger.configure_log_level()` after — a level that survives the restart but is
not yet live is a much smaller failure than a live level the next start
forgets. If the reconfigure fails (a log directory that has become unwritable
is the realistic case), the save still reports success and the failure is
logged; the level applies at the next start.

The value is read by `parse_level`, exactly as the three startup sources are,
so a level typed into Settings clamps to range the same way and accepts the same
two notations. It differs on one point: an unrecognised value is *refused* with
an error rather than ignored. A startup source has a layer beneath it to fall
through to, and an HTTP request has somewhere to put the complaint — persisting
`"loud"` would leave the operator's setting silently discarded at the next
start. The rejection names both accepted forms, from the same `ACCEPTED_FORMS`
string the startup notice uses, so the two can never describe different rules.

On the next start the chain runs again, so a startup argument or
`COMICARR_LOG_LEVEL` will override what Settings saved. That is the documented
precedence, and it is why the winning source announces what it overrode.

The dial itself shows number, name, and consequence together — `0 · Warning —
warnings and errors` — rather than a bare one-word label. The number is what the
operator's config file contains, the name is what the CLI accepts, and the
consequence is what stops the next "I set it to 0 and expected silence". This
supersedes the `quiet / normal / verbose` labels locked while designing the
surface; the layout of that design is unaffected.

### The dial must say when it is not the one deciding

Because Settings writes the bottom rung of the chain and the write applies live,
three numbers can disagree at once: the level the process is logging at, the
level saved in `config.ini`, and the level the next start will resolve to. A
page that shows only the saved number is #610 in miniature — the UI stating one
thing while the process does another.

`resolve_effective_log_level` (`comicarr/app/config/log_level.py`) reports all
three, and `GET /system/logs` carries them alongside the log lines. The restart
half is the startup chain *re-run now*, not a replay of the boot resolution:
the environment and the config file are read fresh, and only the startup
argument is remembered, because it is the one input that cannot be re-read
later. `record_startup_argument` captures it in `comicarr/config.py` before
`comicarr.LOG_LEVEL` is overwritten with the resolved level.

`pinned` is true when the winner is a startup argument or `COMICARR_LOG_LEVEL`.
Settings → Logs shows its override callout on exactly that flag, and on nothing
else: when the config file is the top of the chain there is nothing to say, and
an always-visible status card would be noise. Note that `pinned` is a statement
about *source*, not about a mismatch in numbers — `--log-level info` against a
saved `1` shows no disagreement and still means the dial cannot change what a
restart does.

### `--quiet` and `--verbose`

Both are deprecated aliases — `--quiet` for `--log-level warning`, `--verbose`
for `--log-level debug` — and both print a notice saying so. Both keep their
short forms `-q` and `-v`, and neither has a removal date: they are in existing
compose files and systemd units, and deleting them would break those for a
cosmetic gain. `--log-level` is the only flag that sets the dial directly.

When more than one is passed, `--log-level` wins, then `--verbose`, then
`--quiet`. A `--log-level` whose value is unusable supplies *nothing*, so it
loses to an alias that was also passed — same rule as the precedence chain, one
level down.

### The two helpers disagree about `None`, on purpose

`comicarr.LOG_LEVEL` is `None` until configuration is read, and the two helpers
resolve that differently. This is deliberate, not an oversight:

- `threshold_for_level(None)` → `INFO`. It answers *"how should the sinks be
  configured?"*, and an unconfigured process should log normally rather than
  start half-muted. In practice both callers pass a resolved integer, so this
  is a defensive default rather than a live path.
- `current_log_level()` → `0`. It answers *"how loud is the operator asking us
  to be right now?"*, and before the config says otherwise the conservative
  answer is the quiet one.

Picking one shared value would break a caller either way. Making
`current_log_level()` return `1` would stop the first-run setup token from being
echoed to stdout before config load — and losing that token means the operator
cannot finish setup at all. Making `threshold_for_level(None)` return `WARNING`
would silently downgrade default logging. So they stay distinct, and callers
choose by what they are actually asking.

## Two rules that fall out of it

**Subsystem diagnostics are entries, not dials.** Folder scanning used to put
some of its `DEBUG` entries behind `FOLDER_SCAN_LOG_VERBOSE`, a hidden legacy
`config.ini` key. That made level `2` an incomplete promise: an operator could
ask for everything and still miss the matching details they needed. Folder-scan
diagnostics now follow the log level like every other entry. High-cardinality
matching work is summarized per input file instead of requiring a second switch
to keep candidate-by-candidate chatter manageable.

**Level 0 is "warnings and errors", not silence.** An operator who turns the
dial down is asking for less noise, not for failures to be hidden. This is why
the setup-token announcement in `app/system/service.py` echoes to stdout at
level 0: the token is logged at `INFO`, so at level 0 it would otherwise never
reach an operator who has no other way to finish first-run setup.

**Console attachment is a deployment concern, not a verbosity one.** Whether a
`StreamHandler` exists at all is the explicit `console=` argument to
`initLogger()`, and it is orthogonal to the level. Both current callers pass
`True`; the parameter exists so that a future daemon or embedded mode can
detach stdout without inventing a second verbosity flag.

Together these are what let `--quiet` be a plain alias for level `0` rather
than a flag with its own hidden second effect.

## What this replaced

`comicarr.QUIET` was that hidden second effect. `--quiet` set it, nothing ever
cleared it, and five sites read it independently to decide whether output
should appear. It is retired and guarded by `scripts/check_retired_globals.py`.

Three defects came out of it, all fixed alongside the retirement:

- `configure_log_level()` computed `console=QUIET if level == 0 else not QUIET`.
  Under Docker — which always passed `--quiet` — that inverted expression meant
  raising verbosity **removed** the console sink. This is the defect reported in
  #610: the operator could not get more output by asking for more output.
- `initLogger()` set a level only for `loglevel == 1` and `loglevel >= 2`. At
  level 0 it left the logger untouched, so lowering verbosity at runtime kept
  the previous, more verbose threshold, and a fresh level-0 start inherited
  root's `WARNING` by accident rather than by design.
- Failing to create the log directory dropped `LOG_DIR` only when `QUIET` was
  false, so a quiet process kept an uncreatable path and lost the recovery.

## One logger, every locale

The contract above now covers every install. It did not always: `logger.py` used
to branch at import on `LOG_LANG` and build an entirely separate
`RotatingLogger` when the locale did not start with `en`. That branch was
retired in #619, and the history is worth keeping because the shape of the bug
recurs.

**It was never the non-English path — it was the Docker path.**
`python:3.12-slim` sets `LANG=C.UTF-8`, so `locale.getdefaultlocale()` returned
`('C', 'UTF-8')`, `LOG_LANG` was `"C"`, and `"C".startswith("en")` is false.
Every container took the branch. Reading it as a rare non-English edge case is
what let it survive a decade.

What it actually cost:

- **`logger.warning` and `logger.exception` did not exist on it.** The branch
  defined only `debug`, `fdebug`, `info`, `warn`, and `error`. The 21
  `logger.warning(...)` call sites — including `comicsync.py`'s "No COMIC_DIR
  configured" and `importinbox.py`'s missing-import-directory warning — raised
  `AttributeError` instead of logging. The 7 `logger.exception(...)` call sites
  are all inside `except` blocks, so the handler raised while handling the
  error and the original traceback was lost.
- **`sys.excepthook` was never functional.** `initLogger` assigned the *unbound*
  `RotatingLogger.handle_exception`, whose signature takes four parameters while
  Python calls the hook with three; its body also referenced a module-global
  `logger` that only existed in the other branch. `Comicarr.py` said as much at
  startup — *"errors WILL NOT be captured in the logs"*.
- **Level 0 attached no console sink at all**, because the `StreamHandler` was
  built inside `if loglevel:`. Same shape as the #610 defect: a level that
  removes a sink instead of raising its threshold.
- **It never did the encoding job it existed for.** `LOG_CHARSET` was assigned
  at import and read by nothing, anywhere. No `encoding=` on the file handler,
  no charset handling of any kind. The only real differences were the formatter
  string and enforcing the dial in the module-level wrappers rather than at
  handler level.

The one thing it got right was capping the Web UI buffer at 2500 entries.
`LogListHandler` had no cap, so retiring the branch without carrying that across
would have handed every Docker install an unbounded in-memory list. The cap now
lives on `logger.MAX_LOGLIST_ENTRIES` and applies everywhere.

`LOG_LANG` and `LOG_CHARSET` are in `RETIRED_GLOBALS`
(`scripts/check_retired_globals.py`). Pinning `ENV LANG=en_US.UTF-8` in the
`Dockerfile` was considered and rejected: it would have moved containers onto
the working path while leaving non-English bare-metal installs still dropping
warnings, and made correctness depend on an environment variable any operator
can override.

**One log format now.** Containers previously wrote
`INFO :: MainThread : maintenance.py:backup_files:539 :` and now write the
standard `INFO :: comicarr.backup_files.539 : MainThread`. An existing
`comicarr.log` therefore contains both formats across the upgrade boundary —
a constraint on anything that parses the file, noted on
[Build the Settings log viewer and level control](https://github.com/frankieramirez/comicarr/issues/617).

## Searching log files

Settings → Logs lists the current `comicarr.log` and numbered retained files from
`LOG_DIR` (or the data directory's `logs` folder). `GET /api/system/logs/files`
requires a session and returns each regular file's opaque selector, display name,
size in bytes, and UTC modification time. The client treats selectors as opaque
and never sends a path. The server refuses unknown selectors, symlinks, and
non-regular files.

`GET /api/system/logs?selector=…&query=…&component=…&severity=…&lines=200` searches
the selected file. Omitting all search parameters preserves the existing
`GET /api/system/logs?lines=…` current-file tail response. Text and component
inputs search on submit in the viewer. File, severity, and record-limit selections
apply to the submitted search; Refresh rereads both the file list and results.

- `query` is literal, case-insensitive text. A header or any continuation line can
  match; the response includes the entire record.
- `component` is an exact, case-insensitive logger function name. For example,
  `comicarr.backup_files.539` in the current format and
  `maintenance.py:backup_files:539` in the retired format both match `backup_files`.
  The optional `comicarr.` prefix is accepted.
- `severity` is a minimum: `DEBUG`, `INFO`, `WARNING`, `ERROR`, or `CRITICAL`.
  Headers from both formats supply severity and component. Lines without a header
  continue the preceding record; orphan lines form an unknown record. Unknown
  severity or component remains visible unless an explicit filter excludes it.
- `lines` becomes the whole-record limit for searches, from 1 to 5,000 (default
  200). Results contain the newest matching records in file order, capped at
  8 MiB of source text. The server drops oldest whole records to fit the byte cap.
  A single matching record over 8 MiB, or any line over 1 MiB, returns `too_large`
  instead of a partial record.

Search scans the file line by line to the size observed at open, storing offsets
for at most the requested number of matching records. It then reads only those
records and runs `redact_sensitive_text` with configured provider secrets before
returning their lines. Memory use stays bounded as the selected file grows.
Appends after the initial size belong to the next Refresh.

The response carries `file`, `lines_scanned`, `records_matched`,
`records_returned`, `truncated`, `record_limit`, and `byte_limit`, alongside `logs`
and the existing `level` context. The viewer shows these counts beside the results;
Copy exports exactly the displayed text. These filters do not change capture
levels or retention settings.

Search errors carry an `error` message and a `code`: `invalid_selector` and
`unsafe_file` (HTTP 400), `missing` (404), `changed` during rotation (409),
`too_large` (413), or `unreadable` (503). The UI shows the error with a Refresh
files and results action. An unavailable file never appears as an empty search.

Charted under
[Wayfinder: One log level dial, everywhere](https://github.com/frankieramirez/comicarr/issues/611).
