#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
ComicVine API Response Cache

This module provides a SQLite-based cache for ComicVine API responses with TTL support.
It significantly reduces API calls by caching search results, comic metadata, and story arc info.
"""

import sqlite3
import time
import hashlib
import os
import threading

from mylar import logger


class CVCache:
    """
    SQLite-based cache for ComicVine API responses with TTL (time-to-live) expiry.

    The cache stores API responses keyed by URL hash, with configurable TTLs for
    different types of data (search results, metadata, story arcs).
    """

    def __init__(self, db_path):
        """
        Initialize the cache database.

        Args:
            db_path (str): Path to the SQLite database file
        """
        self.db_path = db_path
        self.lock = threading.Lock()
        self._init_db()

    def _init_db(self):
        """Create the cache table if it doesn't exist."""
        with self.lock:
            conn = sqlite3.connect(self.db_path)
            try:
                cursor = conn.cursor()
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS cv_metadata_cache (
                        cache_key TEXT PRIMARY KEY,
                        response_data BLOB,
                        cached_at INTEGER,
                        expires_at INTEGER
                    )
                ''')
                # Create index on expires_at for efficient cleanup
                cursor.execute('''
                    CREATE INDEX IF NOT EXISTS idx_expires_at
                    ON cv_metadata_cache(expires_at)
                ''')
                conn.commit()
                logger.info('[CV_CACHE] Cache database initialized at: %s' % self.db_path)
            except Exception as e:
                logger.error('[CV_CACHE] Error initializing cache database: %s' % e)
            finally:
                conn.close()

    def _get_cache_key(self, url):
        """
        Generate a cache key from URL.

        Args:
            url (str): The API URL

        Returns:
            str: SHA256 hash of the URL
        """
        return hashlib.sha256(url.encode('utf-8')).hexdigest()

    def get(self, url):
        """
        Retrieve cached response for a URL if not expired.

        Args:
            url (str): The API URL

        Returns:
            bytes: Cached response data, or None if not found or expired
        """
        cache_key = self._get_cache_key(url)

        with self.lock:
            conn = sqlite3.connect(self.db_path)
            try:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT response_data, expires_at
                    FROM cv_metadata_cache
                    WHERE cache_key = ?
                ''', (cache_key,))

                row = cursor.fetchone()
                if row:
                    response_data, expires_at = row
                    current_time = int(time.time())

                    if current_time < expires_at:
                        # Cache hit, not expired
                        return response_data
                    else:
                        # Expired, delete it
                        cursor.execute('DELETE FROM cv_metadata_cache WHERE cache_key = ?', (cache_key,))
                        conn.commit()
                        return None

                return None
            except Exception as e:
                logger.error('[CV_CACHE] Error retrieving from cache: %s' % e)
                return None
            finally:
                conn.close()

    def set(self, url, response_data, ttl):
        """
        Store a response in the cache with TTL.

        Args:
            url (str): The API URL
            response_data (bytes): The response data to cache
            ttl (int): Time-to-live in seconds
        """
        cache_key = self._get_cache_key(url)
        current_time = int(time.time())
        expires_at = current_time + ttl

        with self.lock:
            conn = sqlite3.connect(self.db_path)
            try:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT OR REPLACE INTO cv_metadata_cache
                    (cache_key, response_data, cached_at, expires_at)
                    VALUES (?, ?, ?, ?)
                ''', (cache_key, response_data, current_time, expires_at))
                conn.commit()
            except Exception as e:
                logger.error('[CV_CACHE] Error storing to cache: %s' % e)
            finally:
                conn.close()

    def clear_expired(self):
        """Remove all expired entries from the cache."""
        current_time = int(time.time())

        with self.lock:
            conn = sqlite3.connect(self.db_path)
            try:
                cursor = conn.cursor()
                cursor.execute('DELETE FROM cv_metadata_cache WHERE expires_at < ?', (current_time,))
                deleted_count = cursor.rowcount
                conn.commit()
                if deleted_count > 0:
                    logger.info('[CV_CACHE] Cleared %d expired cache entries' % deleted_count)
                return deleted_count
            except Exception as e:
                logger.error('[CV_CACHE] Error clearing expired entries: %s' % e)
                return 0
            finally:
                conn.close()

    def clear_all(self):
        """Clear all cache entries."""
        with self.lock:
            conn = sqlite3.connect(self.db_path)
            try:
                cursor = conn.cursor()
                cursor.execute('DELETE FROM cv_metadata_cache')
                deleted_count = cursor.rowcount
                conn.commit()
                logger.info('[CV_CACHE] Cleared all %d cache entries' % deleted_count)
                return deleted_count
            except Exception as e:
                logger.error('[CV_CACHE] Error clearing all entries: %s' % e)
                return 0
            finally:
                conn.close()

    def get_stats(self):
        """
        Get cache statistics.

        Returns:
            dict: Statistics including total entries, expired entries, and cache size
        """
        current_time = int(time.time())

        with self.lock:
            conn = sqlite3.connect(self.db_path)
            try:
                cursor = conn.cursor()

                # Total entries
                cursor.execute('SELECT COUNT(*) FROM cv_metadata_cache')
                total = cursor.fetchone()[0]

                # Expired entries
                cursor.execute('SELECT COUNT(*) FROM cv_metadata_cache WHERE expires_at < ?', (current_time,))
                expired = cursor.fetchone()[0]

                # Database size
                cursor.execute('SELECT page_count * page_size as size FROM pragma_page_count(), pragma_page_size()')
                db_size = cursor.fetchone()[0]

                return {
                    'total_entries': total,
                    'expired_entries': expired,
                    'valid_entries': total - expired,
                    'db_size_bytes': db_size,
                    'db_size_mb': round(db_size / (1024 * 1024), 2)
                }
            except Exception as e:
                logger.error('[CV_CACHE] Error getting cache stats: %s' % e)
                return {}
            finally:
                conn.close()
