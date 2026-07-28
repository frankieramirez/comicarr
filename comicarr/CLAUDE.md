# Backend Patterns

### Logging Pattern
- Import: `from comicarr import logger`
- Usage: `logger.fdebug('[MODULE-CONTEXT] message')` or `logger.error('[CONTEXT] Error: %s' % e)`
- Always prefix with context in brackets

### Configuration Access
- Import: `import comicarr`
- Usage: `comicarr.CONFIG.option_name`
- Global config object is initialized at startup

### Database Queries
- Import: `from comicarr import db`
- Usage: `db.DBConnection().action("SELECT * FROM table WHERE id=?", [id])`
- Always use parameterized queries

### Adding New Features
- Prefer `comicarr/app/<domain>/router.py` + `service.py` (+ `queries.py` when needed)
- Register/include the router from `comicarr/app/main.py`
- Keep heavy provider/search/post-processing logic in existing business modules when it already lives there
