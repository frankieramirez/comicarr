# Backend Patterns

### Logging Pattern
- Import: `from comicarr.app.core import logger`
- Usage: `logger.fdebug('[MODULE-CONTEXT] message')` or `logger.error('[CONTEXT] Error: %s' % e)`
- Always prefix with context in brackets

### Configuration Access
- Import: `from comicarr.app.core import runtime`
- Usage: `runtime.current().config.option_name` (a route handler with a `ctx` uses `ctx.config`)
- The config object is loaded at startup; process state lives on `AppContext`, not on the `comicarr` package (`docs/architecture/runtime-context.md`)

### Database Queries
- Import: `from comicarr.app.core import db` (plus the table from `comicarr.app.core.tables`)
- Read: `db.select_one(stmt)` / `db.select_all(stmt)` with a SQLAlchemy Core `select()`
- Write: `db.upsert(table_name, value_dict, key_dict)` — dialect-aware and atomic
- Raw SQL, only where a Core expression will not do: `db.raw_select_one` / `db.raw_select_all` / `db.raw_execute`, which take `?` placeholders
- Always use parameterized queries; never interpolate values into SQL
- `db.DBConnection()` is a deprecated shim for legacy raw-SQL callers, slated for removal — do not use it in new code

### Adding New Features
- Prefer `comicarr/app/<domain>/router.py` + `service.py` (+ `queries.py` when needed)
- Register/include the router from `comicarr/app/main.py`
- Keep heavy provider/search/post-processing logic in existing business modules when it already lives there
