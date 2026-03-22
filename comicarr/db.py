#  Copyright (C) 2012–2024 Mylar3 contributors
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

##################################################
## Database connection handler (based on Sick-Beard) ##
##################################################


import os
import queue
import sqlite3
import threading
import time

import comicarr

from . import logger

db_lock = threading.Lock()
db_queue = queue.Queue()

# Thread-local storage for database connections
# SQLite connections can only be used from the thread that created them
_thread_local = threading.local()


class ConnectionPool:
    """
    Thread-safe connection pool for SQLite.

    Uses thread-local storage to provide one connection per thread,
    which is the recommended pattern for SQLite since connections
    are not thread-safe.
    """

    _instance = None
    _init_lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._init_lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._filename = "comicarr.db"
        self._connections = {}  # Track connections for cleanup
        self._conn_lock = threading.Lock()
        logger.fdebug("ConnectionPool initialized.")

    def get_connection(self, filename="comicarr.db"):
        """Get a connection for the current thread."""
        thread_id = threading.current_thread().ident

        # Check if this thread already has a connection
        if not hasattr(_thread_local, "connections"):
            _thread_local.connections = {}

        if filename not in _thread_local.connections:
            # Create new connection for this thread
            conn = sqlite3.connect(dbFilename(filename), timeout=20, check_same_thread=False)
            conn.row_factory = sqlite3.Row

            # Set PRAGMAs on every new connection (per-connection state)
            conn.execute("PRAGMA busy_timeout = 15000")  # 15s wait on locked DB
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("PRAGMA synchronous = NORMAL")  # WAL-safe, faster writes
            conn.execute("PRAGMA mmap_size = 67108864")  # 64MB memory-mapped I/O
            conn.execute("PRAGMA journal_size_limit = 67108864")  # 64MB WAL journal limit

            _thread_local.connections[filename] = conn

            # Track for cleanup
            with self._conn_lock:
                if thread_id not in self._connections:
                    self._connections[thread_id] = {}
                self._connections[thread_id][filename] = conn

            logger.fdebug(f"ConnectionPool: Created new connection for thread {thread_id}")

        return _thread_local.connections[filename]

    def close_all(self):
        """Close all connections in the pool."""
        with self._conn_lock:
            for thread_id, conns in self._connections.items():
                for _filename, conn in conns.items():
                    try:
                        conn.close()
                        logger.fdebug(f"ConnectionPool: Closed connection for thread {thread_id}")
                    except Exception as e:
                        logger.warn(f"Error closing connection: {e}")
            self._connections.clear()


# Global connection pool instance
_connection_pool = None


def get_connection_pool():
    """Get the global connection pool instance."""
    global _connection_pool
    if _connection_pool is None:
        _connection_pool = ConnectionPool()
    return _connection_pool


def dbFilename(filename="comicarr.db"):

    return os.path.join(comicarr.DATA_DIR, filename)


class DBConnection:
    def __init__(self, filename="comicarr.db"):

        self.filename = filename
        # Use connection pool instead of creating new connections
        self.connection = get_connection_pool().get_connection(filename)
        self.queue = db_queue

    def fetch(self, query, args=None):
        # No lock needed for reads — WAL mode handles read concurrency
        if query is None:
            return

        sqlResult = None
        attempt = 0

        while attempt < 5:
            try:
                cursor = self.connection.cursor()
                if args is None:
                    sqlResult = cursor.execute(query)
                else:
                    sqlResult = cursor.execute(query, args)
                break
            except sqlite3.OperationalError as e:
                if any(["unable to open database file" in e.args[0], "database is locked" in e.args[0]]):
                    logger.warn("Database Error: %s" % e)
                    attempt += 1
                    time.sleep(1)
                else:
                    logger.warn("DB error: %s" % e)
                    raise
            except sqlite3.DatabaseError as e:
                logger.error("Fatal error executing query: %s" % e)
                raise

        return sqlResult

    def action(self, query, args=None, executemany=False):

        with db_lock:
            if query is None:
                return

            sqlResult = None
            attempt = 0

            while attempt < 5:
                try:
                    if args is None:
                        if executemany is False:
                            sqlResult = self.connection.execute(query)
                        else:
                            sqlResult = self.connection.executemany(query)
                    else:
                        if executemany is False:
                            sqlResult = self.connection.execute(query, args)
                        else:
                            sqlResult = self.connection.executemany(query, args)
                    self.connection.commit()
                    break
                except sqlite3.OperationalError as e:
                    if any(["unable to open database file" in e.args[0], "database is locked" in e.args[0]]):
                        logger.warn("Database Error: %s" % e)
                        logger.warn("sqlresult: %s" % query)
                        attempt += 1
                        time.sleep(1)
                    else:
                        logger.error("Database error executing %s :: %s" % (query, e))
                        raise
            return sqlResult

    def select(self, query, args=None):

        sqlResults = self.fetch(query, args).fetchall()

        if sqlResults is None:
            return []

        return sqlResults

    def selectone(self, query, args=None):
        sqlResults = self.fetch(query, args)

        if sqlResults is None:
            return []

        return sqlResults

    def upsert(self, tableName, valueDict, keyDict):
        # Atomic UPDATE-then-INSERT holding db_lock across both operations.
        # Uses cursor.rowcount (statement-scoped) instead of total_changes
        # (connection-scoped) to avoid the TOCTOU race condition.

        with db_lock:

            def genParams(myDict):
                return [x + " = ?" for x in list(myDict.keys())]

            update_query = (
                "UPDATE "
                + tableName
                + " SET "
                + ", ".join(genParams(valueDict))
                + " WHERE "
                + " AND ".join(genParams(keyDict))
            )
            update_values = list(valueDict.values()) + list(keyDict.values())

            attempt = 0
            while attempt < 5:
                try:
                    cursor = self.connection.execute(update_query, update_values)

                    if cursor.rowcount == 0:
                        insert_query = (
                            "INSERT INTO "
                            + tableName
                            + " ("
                            + ", ".join(list(valueDict.keys()) + list(keyDict.keys()))
                            + ")"
                            + " VALUES ("
                            + ", ".join(["?"] * len(list(valueDict.keys()) + list(keyDict.keys())))
                            + ")"
                        )
                        self.connection.execute(insert_query, list(valueDict.values()) + list(keyDict.values()))

                    self.connection.commit()
                    break
                except sqlite3.OperationalError as e:
                    if any(["unable to open database file" in e.args[0], "database is locked" in e.args[0]]):
                        logger.warn("Database Error: %s" % e)
                        attempt += 1
                        time.sleep(1)
                    else:
                        logger.error("Database error executing %s :: %s" % (update_query, e))
                        raise
