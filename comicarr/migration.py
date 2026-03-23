#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#  Originally based on Mylar3 (https://github.com/mylar3/mylar3).
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  Comicarr is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with Comicarr.  If not, see <http://www.gnu.org/licenses/>.

import configparser
import contextlib
import os
import re
import sqlite3
import threading

import comicarr
from comicarr import encrypted, logger, maintenance

_migration_lock = threading.Lock()
_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# Tables to migrate, ordered by dependency
# (ephemeral tables like searchresults, notifs, provider_searches are excluded)
MIGRATABLE_TABLES = [
    "comics",
    "issues",
    "annuals",
    "snatched",
    "nzblog",
    "failed",
    "storyarcs",
    "readlist",
    "weekly",
    "rssdb",
    "upcoming",
    "futureupcoming",
    "ddl_info",
    "ref32p",
    "oneoffhistory",
    "jobhistory",
]

# Credential keys that use Fernet encryption (not bcrypt)
CREDENTIAL_KEYS = [
    "SAB_PASSWORD",
    "SAB_APIKEY",
    "NZBGET_PASSWORD",
    "UTORRENT_PASSWORD",
    "TRANSMISSION_PASSWORD",
    "DELUGE_PASSWORD",
    "QBITTORRENT_PASSWORD",
    "RTORRENT_PASSWORD",
    "PROWL_KEYS",
    "PUSHOVER_APIKEY",
    "PUSHOVER_USERKEY",
    "BOXCAR_TOKEN",
    "PUSHBULLET_APIKEY",
    "TELEGRAM_TOKEN",
    "COMICVINE_API",
    "PASSWORD_32P",
    "PASSKEY_32P",
    "USERNAME_32P",
    "SEEDBOX_PASS",
    "TAB_PASS",
]

# Path-type settings that may need review in Docker
PATH_SETTINGS = [
    "DESTINATION_DIR",
    "CACHE_DIR",
    "GRABBAG_DIR",
    "NEWCOM_DIR",
    "BACKUP_LOCATION",
    "LOG_DIR",
    "WEEKFOLDER_LOC",
    "FOLDER_CACHE_LOCATION",
]


def _validate_source_path(source_path):
    if "\x00" in source_path or ".." in source_path:
        return False, "Invalid path characters"

    real_path = os.path.realpath(source_path)
    if not os.path.isdir(real_path):
        return False, "Path is not a directory"

    db_path = os.path.join(real_path, "mylar.db")
    if not os.path.isfile(db_path):
        return False, "No mylar.db found at path"

    config_path = os.path.join(real_path, "config.ini")
    if not os.path.isfile(config_path):
        return False, "No config.ini found at path"

    if os.path.realpath(comicarr.DATA_DIR) == real_path:
        return False, "Cannot migrate from own data directory"

    return True, db_path


@contextlib.contextmanager
def _open_source_db(path):
    conn = sqlite3.connect("file:%s?mode=ro" % path, uri=True)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA query_only = ON")
        yield conn
    finally:
        conn.close()


def _get_common_columns(source_conn, dest_conn, table):
    source_cols = {
        row[1]
        for row in source_conn.execute("PRAGMA table_info(%s)" % table).fetchall()
        if _SAFE_IDENTIFIER.match(row[1])
    }
    dest_cols = {
        row[1]
        for row in dest_conn.execute("PRAGMA table_info(%s)" % table).fetchall()
        if _SAFE_IDENTIFIER.match(row[1])
    }
    # For weekly table, exclude rowid from insert (let SQLite auto-assign)
    if table == "weekly":
        source_cols.discard("rowid")
        dest_cols.discard("rowid")
    common = source_cols & dest_cols
    return sorted(common)


class Mylar3Migration:
    def __init__(self, source_path):
        self.source_path = source_path
        self.real_path = None
        self.dbfile = None

    def validate(self):
        valid, result = _validate_source_path(self.source_path)
        if not valid:
            return {"valid": False, "error": result}

        self.dbfile = result
        self.real_path = os.path.realpath(self.source_path)
        real_path = self.real_path

        try:
            with _open_source_db(self.dbfile) as conn:
                # Get Mylar3 version
                version = "unknown"
                try:
                    row = conn.execute("SELECT DatabaseVersion FROM mylar_info").fetchone()
                    if row:
                        version = str(row["DatabaseVersion"])
                except Exception:
                    pass

                # Count series and issues
                series_count = 0
                issue_count = 0
                try:
                    row = conn.execute("SELECT COUNT(*) as cnt FROM comics").fetchone()
                    if row:
                        series_count = int(row["cnt"])
                except Exception:
                    pass
                try:
                    row = conn.execute("SELECT COUNT(*) as cnt FROM issues").fetchone()
                    if row:
                        issue_count = int(row["cnt"])
                except Exception:
                    pass

                # Get table summaries
                tables = []
                for table in MIGRATABLE_TABLES:
                    try:
                        row = conn.execute("SELECT COUNT(*) as cnt FROM %s" % table).fetchone()
                        tables.append(
                            {
                                "name": table,
                                "row_count": int(row["cnt"]) if row else 0,
                            }
                        )
                    except Exception:
                        # Table doesn't exist in source
                        pass

                # Detect config categories
                config_categories = []
                config_path = os.path.join(real_path, "config.ini")
                try:
                    cp = configparser.RawConfigParser()
                    cp.read(config_path)
                    config_categories = cp.sections()
                except Exception:
                    pass

                # Check path settings that may need review
                path_warnings = []
                for key in PATH_SETTINGS:
                    for section in config_categories:
                        try:
                            val = cp.get(section, key.lower())
                            if val and val.strip():
                                path_warnings.append("%s = %s" % (key, val))
                        except (configparser.NoOptionError, configparser.NoSectionError):
                            pass

                return {
                    "valid": True,
                    "version": version,
                    "series_count": series_count,
                    "issue_count": issue_count,
                    "tables": tables,
                    "config_categories": config_categories,
                    "path_warnings": path_warnings,
                }
        except Exception as e:
            logger.error("[MIGRATION] Validation failed: %s" % e)
            return {"valid": False, "error": str(e)}

    def execute(self):
        if not _migration_lock.acquire(blocking=False):
            logger.error("[MIGRATION] Migration already in progress")
            return False

        try:
            comicarr.MIGRATION_IN_PROGRESS = True
            comicarr.MIGRATION_STATUS = "migrating"
            comicarr.MIGRATION_ERROR = None
            comicarr.MIGRATION_TABLES_COMPLETE = 0

            # Validate first (use resolved path to prevent TOCTOU)
            if self.dbfile is None or self.real_path is None:
                valid, result = _validate_source_path(self.source_path)
                if not valid:
                    comicarr.MIGRATION_STATUS = "error"
                    comicarr.MIGRATION_ERROR = "Migration validation failed"
                    return False
                self.dbfile = result
                self.real_path = os.path.realpath(self.source_path)

            real_path = self.real_path

            # Pre-migration backup
            logger.info("[MIGRATION] Creating pre-migration backup...")
            backup_dir = os.path.join(comicarr.DATA_DIR, "backups")
            maintenance.auto_backup_db(comicarr.DB_FILE, backup_dir)

            # Open source database read-only
            with _open_source_db(self.dbfile) as source_conn:
                # Open destination with direct connection for bulk operations
                dest_conn = sqlite3.connect(comicarr.DB_FILE, timeout=20)

                try:
                    # Performance PRAGMAs for bulk import
                    dest_conn.execute("PRAGMA synchronous = NORMAL")
                    dest_conn.execute("PRAGMA cache_size = -128000")
                    dest_conn.execute("PRAGMA temp_store = MEMORY")
                    dest_conn.execute("PRAGMA foreign_keys = OFF")

                    # Drop indexes for faster inserts (dbcheck() rebuilds them)
                    for idx in dest_conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='index' AND sql IS NOT NULL"
                    ).fetchall():
                        if _SAFE_IDENTIFIER.match(idx[0]):
                            dest_conn.execute('DROP INDEX IF EXISTS "%s"' % idx[0])

                    # Determine which tables exist in both source and destination
                    source_tables = {
                        row[0]
                        for row in source_conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
                    }
                    dest_tables = {
                        row[0]
                        for row in dest_conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
                    }
                    tables_to_migrate = [t for t in MIGRATABLE_TABLES if t in source_tables and t in dest_tables]
                    comicarr.MIGRATION_TABLES_TOTAL = len(tables_to_migrate)

                    # Migrate each table
                    for table in tables_to_migrate:
                        comicarr.MIGRATION_CURRENT_TABLE = table
                        logger.info("[MIGRATION][%s] Starting import..." % table.upper())

                        columns = _get_common_columns(source_conn, dest_conn, table)
                        if not columns:
                            logger.warn("[MIGRATION][%s] No common columns found, skipping" % table.upper())
                            comicarr.MIGRATION_TABLES_COMPLETE += 1
                            continue

                        col_list = ", ".join(columns)
                        placeholders = ", ".join(["?"] * len(columns))
                        insert_sql = "INSERT OR IGNORE INTO %s (%s) VALUES (%s)" % (table, col_list, placeholders)

                        source_cursor = source_conn.execute("SELECT %s FROM %s" % (col_list, table))

                        dest_conn.execute("BEGIN")
                        try:
                            total_rows = 0
                            while True:
                                batch = source_cursor.fetchmany(5000)
                                if not batch:
                                    break
                                dest_conn.executemany(insert_sql, [tuple(row) for row in batch])
                                total_rows += len(batch)
                            dest_conn.commit()
                            logger.info("[MIGRATION][%s] Imported %d rows" % (table.upper(), total_rows))
                        except Exception as e:
                            dest_conn.rollback()
                            logger.error("[MIGRATION][%s] Failed: %s" % (table.upper(), e))
                            comicarr.MIGRATION_STATUS = "error"
                            comicarr.MIGRATION_ERROR = "Failed on table %s" % table
                            return False

                        comicarr.MIGRATION_TABLES_COMPLETE += 1

                finally:
                    try:
                        dest_conn.execute("PRAGMA synchronous = NORMAL")
                        dest_conn.execute("PRAGMA foreign_keys = ON")
                        dest_conn.execute("PRAGMA optimize")
                    except Exception:
                        pass
                    dest_conn.close()

            # Migrate config after database
            logger.info("[MIGRATION] Migrating config settings...")
            try:
                migrate_mylar3_config(real_path)
            except Exception as e:
                logger.error("[MIGRATION] Config migration failed (data migration succeeded): %s" % e)
                # Don't fail the whole migration for config issues

            # Run dbcheck() to rebuild indexes and apply schema updates
            logger.info("[MIGRATION] Running dbcheck() to rebuild indexes...")
            from comicarr import dbcheck

            dbcheck()

            # Post-migration verification
            _verify_migration(self.dbfile)

            # Clear empty DB flag
            comicarr.DB_EMPTY = False
            comicarr.MIGRATION_STATUS = "complete"
            comicarr.MIGRATION_CURRENT_TABLE = ""
            logger.info("[MIGRATION] Migration completed successfully")
            return True

        except Exception as e:
            logger.error("[MIGRATION] Migration failed: %s" % e)
            comicarr.MIGRATION_STATUS = "error"
            comicarr.MIGRATION_ERROR = "Migration failed unexpectedly"
            return False
        finally:
            comicarr.MIGRATION_IN_PROGRESS = False
            _migration_lock.release()


def migrate_mylar3_config(source_path):
    config_path = os.path.join(source_path, "config.ini")
    if not os.path.isfile(config_path):
        logger.warn("[MIGRATION] No config.ini found at %s, skipping config migration" % source_path)
        return

    # Bootstrap SECURE_DIR before any credential operations
    if not comicarr.CONFIG.SECURE_DIR:
        comicarr.CONFIG.SECURE_DIR = os.path.join(comicarr.DATA_DIR, ".secure")
    os.makedirs(comicarr.CONFIG.SECURE_DIR, mode=0o700, exist_ok=True)

    fernet = encrypted._get_fernet()
    if fernet is None:
        raise RuntimeError("Cannot initialize encryption — credential migration aborted")

    # Parse source config
    source_config = configparser.RawConfigParser()
    source_config.read(config_path)

    from comicarr.config import _BAD_DEFINITIONS, _CONFIG_DEFINITIONS

    # Build values dict from source config
    values = {}
    for key, definition in _CONFIG_DEFINITIONS.items():
        key_lower = key.lower()
        section = definition[1]
        try:
            raw_val = source_config.get(section, key_lower)
            if raw_val is not None:
                values[key] = raw_val.strip() if isinstance(raw_val, str) else raw_val
        except (configparser.NoOptionError, configparser.NoSectionError):
            pass

    # Apply _BAD_DEFINITIONS remappings
    for new_key, bad_def in _BAD_DEFINITIONS.items():
        if len(bad_def) >= 2:
            old_section = bad_def[0]
            old_key = bad_def[1]
            if old_key is None:
                continue
            try:
                old_val = source_config.get(old_section, old_key.lower())
                if old_val is not None and new_key not in values:
                    values[new_key] = old_val.strip() if isinstance(old_val, str) else old_val
                    logger.fdebug("[MIGRATION] Remapped %s.%s -> %s" % (old_section, old_key, new_key))
            except (configparser.NoOptionError, configparser.NoSectionError):
                pass

    # Handle HTTP_PASSWORD specially (bcrypt, not Fernet)
    if "HTTP_PASSWORD" in values:
        old_pass = values["HTTP_PASSWORD"]
        migrated = encrypted.migrate_password(old_pass)
        if migrated:
            values["HTTP_PASSWORD"] = migrated
            logger.fdebug("[MIGRATION] HTTP_PASSWORD migrated to bcrypt")
        del old_pass  # Don't keep plaintext reference

    # Re-encrypt credential values
    for key in CREDENTIAL_KEYS:
        if key in values and values[key]:
            old_val = values[key]
            # Decrypt from old format
            dec = encrypted.Encryptor(old_val).decrypt_it()
            if dec["status"]:
                # Re-encrypt with current Fernet key
                enc = encrypted.Encryptor(dec["password"]).encrypt_it()
                if enc["status"]:
                    values[key] = enc["password"]
                    logger.fdebug("[MIGRATION] Re-encrypted %s" % key)
                else:
                    logger.warn("[MIGRATION] Failed to re-encrypt %s, skipping" % key)
                    del values[key]
            else:
                # Value might be plaintext — encrypt it
                enc = encrypted.Encryptor(old_val).encrypt_it()
                if enc["status"]:
                    values[key] = enc["password"]
                else:
                    logger.warn("[MIGRATION] Failed to encrypt %s, skipping" % key)
                    del values[key]

    # Write config atomically
    comicarr.CONFIG.writeconfig(values)
    logger.info("[MIGRATION] Config migration completed — %d settings imported" % len(values))


def _verify_migration(source_db_path):
    try:
        with _open_source_db(source_db_path) as source_conn:
            dest_conn = sqlite3.connect(comicarr.DB_FILE)
            try:
                dest_conn.row_factory = sqlite3.Row

                for table in ["comics", "issues", "annuals"]:
                    try:
                        src_count = source_conn.execute("SELECT COUNT(*) as cnt FROM %s" % table).fetchone()
                        dst_count = dest_conn.execute("SELECT COUNT(*) as cnt FROM %s" % table).fetchone()
                        src_n = int(src_count["cnt"]) if src_count else 0
                        dst_n = int(dst_count["cnt"]) if dst_count else 0
                        if src_n != dst_n:
                            logger.warn(
                                "[MIGRATION][VERIFY] Row count mismatch for %s: source=%d, destination=%d"
                                % (table, src_n, dst_n)
                            )
                        else:
                            logger.fdebug("[MIGRATION][VERIFY] %s: %d rows OK" % (table, dst_n))
                    except Exception as e:
                        logger.warn("[MIGRATION][VERIFY] Could not verify %s: %s" % (table, e))

                # Check for orphaned issues
                try:
                    orphans = dest_conn.execute(
                        "SELECT COUNT(*) as cnt FROM issues WHERE ComicID NOT IN (SELECT ComicID FROM comics)"
                    ).fetchone()
                    orphan_count = int(orphans["cnt"]) if orphans else 0
                    if orphan_count > 0:
                        logger.warn(
                            "[MIGRATION][VERIFY] %d orphaned issues found (referencing non-existent comics)"
                            % orphan_count
                        )
                except Exception as e:
                    logger.warn("[MIGRATION][VERIFY] Orphan check failed: %s" % e)
            finally:
                dest_conn.close()
    except Exception as e:
        logger.warn("[MIGRATION][VERIFY] Verification failed: %s" % e)
