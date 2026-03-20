#  This file is part of Mylar.
#
#  Mylar is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  Mylar is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with Mylar.  If not, see <http://www.gnu.org/licenses/>.

#####################################
## Stolen from Sick-Beard's db.py  ##
#####################################



import os
import sqlite3
import threading
import time
import queue

import mylar
from . import logger

db_lock = threading.Lock()
mylarQueue = queue.Queue()

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
        self._filename = "mylar.db"
        self._connections = {}  # Track connections for cleanup
        self._conn_lock = threading.Lock()
        logger.fdebug('ConnectionPool initialized.')

    def get_connection(self, filename="mylar.db"):
        """Get a connection for the current thread."""
        thread_id = threading.current_thread().ident

        # Check if this thread already has a connection
        if not hasattr(_thread_local, 'connections'):
            _thread_local.connections = {}

        if filename not in _thread_local.connections:
            # Create new connection for this thread
            conn = sqlite3.connect(
                dbFilename(filename),
                timeout=20,
                check_same_thread=False
            )
            conn.row_factory = sqlite3.Row

            # Set PRAGMAs on every new connection
            conn.execute('PRAGMA busy_timeout = 5000')
            conn.execute('PRAGMA foreign_keys = ON')
            conn.execute('PRAGMA mmap_size = 134217728')  # 128MB memory-mapped I/O
            conn.execute('PRAGMA journal_size_limit = 67108864')  # 64MB WAL journal limit

            _thread_local.connections[filename] = conn

            # Track for cleanup
            with self._conn_lock:
                if thread_id not in self._connections:
                    self._connections[thread_id] = {}
                self._connections[thread_id][filename] = conn

            logger.fdebug(
                f'ConnectionPool: Created new connection for thread {thread_id}'
            )

        return _thread_local.connections[filename]

    def close_all(self):
        """Close all connections in the pool."""
        with self._conn_lock:
            for thread_id, conns in self._connections.items():
                for filename, conn in conns.items():
                    try:
                        conn.close()
                        logger.fdebug(
                            f'ConnectionPool: Closed connection for thread {thread_id}'
                        )
                    except Exception as e:
                        logger.warn(f'Error closing connection: {e}')
            self._connections.clear()


# Global connection pool instance
_connection_pool = None


def get_connection_pool():
    """Get the global connection pool instance."""
    global _connection_pool
    if _connection_pool is None:
        _connection_pool = ConnectionPool()
    return _connection_pool

def dbFilename(filename="mylar.db"):

    return os.path.join(mylar.DATA_DIR, filename)

class WriteOnly:
    # DEPRECATED: Dead code. The queue path in upsert (lines below) is commented out
    # and this worker is never actively used. Kept for reference only.

    def __init__(self):
        t = threading.Thread(target=self.worker, name="DB-WRITER")
        t.daemon = True
        t.start()
        logger.fdebug('Thread WriteOnly initialized.')

    def worker(self):
        myDB = DBConnection()
        #this should be in it's own thread somewhere, constantly polling the queue and sending them to the writer.
        logger.fdebug('worker started.')
        while True:
            thisthread = threading.current_thread().name
            if not mylarQueue.empty():
    # Rename the main thread
                logger.fdebug('[' + str(thisthread) + '] queue is not empty yet...')
                (QtableName, QvalueDict, QkeyDict) = mylarQueue.get(block=True, timeout=None)
                logger.fdebug('[REQUEUE] Table: ' + str(QtableName) + ' values: ' + str(QvalueDict) + ' keys: ' + str(QkeyDict))
                sqlResult = myDB.upsert(QtableName, QvalueDict, QkeyDict)
                if sqlResult:
                    mylarQueue.task_done()
                    return sqlResult
            else:
                time.sleep(1)
                #logger.fdebug('[' + str(thisthread) + '] sleeping until active.')

class DBConnection:

    def __init__(self, filename="mylar.db"):

        self.filename = filename
        # Use connection pool instead of creating new connections
        self.connection = get_connection_pool().get_connection(filename)
        self.queue = mylarQueue

    def fetch(self, query, args=None):
        # No lock needed for reads — WAL mode handles read concurrency
        if True:

            if query == None:
                return

            sqlResult = None
            attempt = 0

            while attempt < 5:
                try:
                    if args == None:
                        #logger.fdebug("[FETCH] : " + query)
                        cursor = self.connection.cursor()
                        sqlResult = cursor.execute(query)
                    else:
                        #logger.fdebug("[FETCH] : " + query + " with args " + str(args))
                        cursor = self.connection.cursor()
                        sqlResult = cursor.execute(query, args)
                    # get out of the connection attempt loop since we were successful
                    break
                except sqlite3.OperationalError as e:
                    if any(['unable to open database file' in e.args[0], 'database is locked' in e.args[0]]):
                        logger.warn('Database Error: %s' % e)
                        attempt += 1
                        time.sleep(1)
                    else:
                        logger.warn('DB error: %s' % e)
                        raise
                except sqlite3.DatabaseError as e:
                    logger.error('Fatal error executing query: %s' % e)
                    raise

            return sqlResult



    def action(self, query, args=None, executemany=False):

        with db_lock:
            if query == None:
                return

            sqlResult = None
            attempt = 0

            while attempt < 5:
                try:
                    if args == None:
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
                    if any(['unable to open database file' in e.args[0], 'database is locked' in e.args[0]]):
                        logger.warn('Database Error: %s' % e)
                        logger.warn('sqlresult: %s' %  query)
                        attempt += 1
                        time.sleep(1)
                    else:
                        logger.error('Database error executing %s :: %s' % (query, e))
                        raise
            return sqlResult

    def select(self, query, args=None):

        sqlResults = self.fetch(query, args).fetchall()

        if sqlResults == None:
            return []

        return sqlResults

    def selectone(self, query, args=None):
        sqlResults = self.fetch(query, args)

        if sqlResults == None:
            return []

        return sqlResults


    def upsert(self, tableName, valueDict, keyDict):
        # Atomic upsert using INSERT ... ON CONFLICT DO UPDATE
        # Replaces the old UPDATE-then-check-total_changes-then-INSERT pattern
        # which had a TOCTOU race condition.

        all_keys = list(keyDict.keys()) + list(valueDict.keys())
        all_values = list(keyDict.values()) + list(valueDict.values())

        # Build the column list and placeholders
        columns = ', '.join(all_keys)
        placeholders = ', '.join(['?'] * len(all_keys))

        # Build the ON CONFLICT UPDATE clause (only update value columns, not key columns)
        update_clause = ', '.join(['%s = excluded.%s' % (k, k) for k in valueDict.keys()])
        conflict_keys = ', '.join(keyDict.keys())

        query = 'INSERT INTO %s (%s) VALUES (%s) ON CONFLICT(%s) DO UPDATE SET %s' % (
            tableName, columns, placeholders, conflict_keys, update_clause
        )

        self.action(query, all_values)


        #else:
        #    logger.info('[' + str(thisthread) + '] db is currently locked for writing. Queuing this action until it is free')
        #    logger.info('Table: ' + str(tableName) + ' Values: ' + str(valueDict) + ' Keys: ' + str(keyDict))
        #    self.queue.put( (tableName, valueDict, keyDict) )
        #    #assuming this is coming in from a seperate thread, so loop it until it's free to write.
        #    #self.queuesend()

