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

import base64
import errno
import os
import tempfile
import threading

import bcrypt
from cryptography.fernet import Fernet

from comicarr import logger

_fernet_instance = None
_fernet_secure_dir = None
_fernet_lock = threading.RLock()
_MASTER_KEY_TEMP_PREFIX = ".comicarr-master-key-"
_MASTER_KEY_LOCK_NAME = ".master-key.lock"


def _fsync_directory(directory):
    """Make a newly published key directory entry crash-durable on POSIX."""
    if os.name == "nt":
        return
    descriptor = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _publish_master_key_with_lock(key_path, temp_path):
    """Publish atomically on filesystems that do not support hard links."""
    lock_path = os.path.join(os.path.dirname(key_path), _MASTER_KEY_LOCK_NAME)
    lock_fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    os.chmod(lock_path, 0o600)
    if os.name == "nt":
        import msvcrt

        if os.fstat(lock_fd).st_size == 0:
            os.write(lock_fd, b"\0")
            os.fsync(lock_fd)
        os.lseek(lock_fd, 0, os.SEEK_SET)
        msvcrt.locking(lock_fd, msvcrt.LK_LOCK, 1)
    else:
        import fcntl

        fcntl.flock(lock_fd, fcntl.LOCK_EX)

    try:
        if os.path.exists(key_path):
            return False
        os.replace(temp_path, key_path)
        os.chmod(key_path, 0o600)
        _fsync_directory(os.path.dirname(key_path))
        return True
    finally:
        if os.name == "nt":
            os.lseek(lock_fd, 0, os.SEEK_SET)
            msvcrt.locking(lock_fd, msvcrt.LK_UNLCK, 1)
        else:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)


def _publish_master_key(key_path, key):
    """Publish a complete owner-only key without replacing a concurrent winner."""
    temp_fd = None
    temp_path = None
    try:
        temp_fd, temp_path = tempfile.mkstemp(
            prefix=_MASTER_KEY_TEMP_PREFIX,
            suffix=".tmp",
            dir=os.path.dirname(key_path),
        )
        fchmod = getattr(os, "fchmod", None)
        if callable(fchmod):
            try:
                fchmod(temp_fd, 0o600)
            except (AttributeError, NotImplementedError):
                os.chmod(temp_path, 0o600)
            except OSError:
                if os.name != "nt":
                    raise
                os.chmod(temp_path, 0o600)
        else:
            os.chmod(temp_path, 0o600)

        with os.fdopen(temp_fd, "wb") as key_file:
            temp_fd = None
            key_file.write(key)
            key_file.flush()
            os.fsync(key_file.fileno())

        try:
            os.link(temp_path, key_path)
        except FileExistsError:
            return False
        except (AttributeError, NotImplementedError):
            return _publish_master_key_with_lock(key_path, temp_path)
        except OSError as e:
            unsupported = {errno.EACCES, errno.EPERM, errno.EXDEV}
            if hasattr(errno, "ENOTSUP"):
                unsupported.add(errno.ENOTSUP)
            if hasattr(errno, "EOPNOTSUPP"):
                unsupported.add(errno.EOPNOTSUPP)
            if e.errno not in unsupported:
                raise
            return _publish_master_key_with_lock(key_path, temp_path)
        os.chmod(key_path, 0o600)
        _fsync_directory(os.path.dirname(key_path))
        return True
    finally:
        if temp_fd is not None:
            os.close(temp_fd)
        if temp_path is not None:
            try:
                os.unlink(temp_path)
            except FileNotFoundError:
                pass
            except OSError as e:
                logger.warn("[ENCRYPTION] Unable to remove temporary master key: %s" % type(e).__name__)


def _load_or_create_master_key(key_path, create):
    """Load the durable key, atomically creating it on first use."""
    try:
        with open(key_path, "rb") as key_file:
            key = key_file.read().strip()
        if os.name != "nt":
            os.chmod(key_path, 0o600)
            if (os.stat(key_path).st_mode & 0o777) != 0o600:
                raise PermissionError("Master key permissions are not owner-only")
        return key
    except FileNotFoundError:
        if not create:
            return None
        key = Fernet.generate_key()
        if _publish_master_key(key_path, key):
            logger.info("[ENCRYPTION] Generated new master key at %s" % key_path)
            return key

        with open(key_path, "rb") as key_file:
            return key_file.read().strip()


def _get_fernet(secure_dir=None, create=True):
    """Get or create the Fernet instance using the master key from SECURE_DIR."""
    global _fernet_instance, _fernet_secure_dir

    if secure_dir is None:
        import comicarr

        if not comicarr.CONFIG or not comicarr.CONFIG.SECURE_DIR:
            logger.error("[ENCRYPTION] SECURE_DIR not configured — cannot load master key")
            return None
        secure_dir = comicarr.CONFIG.SECURE_DIR

    secure_dir = os.path.abspath(secure_dir)
    with _fernet_lock:
        key_path = os.path.join(secure_dir, "master.key")
        if _fernet_instance is not None and _fernet_secure_dir == secure_dir:
            if os.path.isfile(key_path):
                return _fernet_instance
            logger.error("[ENCRYPTION] Cached authority lost its durable master key")
            return None

        try:
            key = _load_or_create_master_key(key_path, create)
        except Exception as e:
            logger.error("[ENCRYPTION] Failed to load or create master key: %s" % type(e).__name__)
            return None
        if key is None:
            return None

        try:
            instance = Fernet(key)
        except Exception as e:
            logger.error("[ENCRYPTION] Invalid master key: %s" % e)
            return None

        _fernet_instance = instance
        _fernet_secure_dir = secure_dir
        return instance


def hash_password(password):
    """Hash a login password with bcrypt (cost factor 12)."""
    if isinstance(password, str):
        password = password.encode("utf-8")
    return bcrypt.hashpw(password, bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password(password, hashed):
    """Verify a password against a bcrypt hash. Returns True if match."""
    if isinstance(password, str):
        password = password.encode("utf-8")
    if isinstance(hashed, str):
        hashed = hashed.encode("utf-8")
    try:
        return bcrypt.checkpw(password, hashed)
    except Exception as e:
        logger.error("[ENCRYPTION] bcrypt verify error: %s" % e)
        return False


def migrate_password(stored_password):
    """Migrate a stored password to bcrypt hash. Handles three states:
    - $2b$ prefix: already bcrypt, return as-is
    - ^~$z$ prefix: old base64, decode then hash
    - No prefix: plaintext, hash directly
    Returns the bcrypt hash string, or None on failure.
    """
    if stored_password is None:
        return None

    if stored_password.startswith("$2b$") or stored_password.startswith("$2a$"):
        return stored_password

    if stored_password.startswith("^~$z$"):
        try:
            decoded = base64.b64decode(stored_password[5:], validate=True)
            if len(decoded) <= 8:
                logger.error("[ENCRYPTION] Base64 payload too short to contain password + salt")
                return None
            plaintext = decoded[:-8].decode("utf-8")
        except Exception as e:
            logger.error("[ENCRYPTION] Failed to decode base64 password for migration: %s" % e)
            return None
        return hash_password(plaintext)

    return hash_password(stored_password)


class Encryptor(object):
    """Encrypt/decrypt service credentials using Fernet.

    Preserves the dict-returning interface:
        {"status": True/False, "password": "..."}

    Handles migration from old base64 encoding (^~$z$ prefix) to Fernet (gAAAAA prefix).
    """

    def __init__(self, password, logon=False, secure_dir=None):
        self.password = password
        self.logon = logon
        self.secure_dir = secure_dir

    def encrypt_it(self):
        """Encrypt a plaintext credential with Fernet."""
        fernet = _get_fernet(self.secure_dir)
        if fernet is None:
            logger.error("[ENCRYPTION] Fernet not available — cannot encrypt. Check SECURE_DIR and master.key.")
            return {"status": False}
        try:
            token = fernet.encrypt(self.password.encode("utf-8"))
            return {"status": True, "password": token.decode("utf-8")}
        except Exception as e:
            logger.warn("Error when encrypting: %s" % e)
            return {"status": False}

    def decrypt_it(self):
        """Decrypt a credential. Handles Fernet tokens, legacy base64, and plaintext."""
        if self.password is None:
            return {"status": False}

        if self.password.startswith("gAAAAA"):
            fernet = _get_fernet(self.secure_dir, create=False)
            if fernet is None:
                if self.logon is False:
                    logger.warn("[ENCRYPTION] Fernet not available — cannot decrypt")
                return {"status": False}
            try:
                plaintext = fernet.decrypt(self.password.encode("utf-8"), ttl=None)
                return {"status": True, "password": plaintext.decode("utf-8")}
            except Exception as e:
                logger.warn("Error when decrypting Fernet token: %s" % e)
                return {"status": False}

        if self.password.startswith("^~$z$"):
            try:
                passd = base64.b64decode(self.password[5:], validate=True)
                if len(passd) <= 8:
                    raise ValueError("Base64 payload too short to contain password and salt")
                return {"status": True, "password": passd[:-8].decode("utf-8")}
            except Exception as e:
                logger.warn("Error when decrypting legacy password: %s" % e)
                return {"status": False}

        if not self.logon:
            logger.warn("Error not an encryption that I recognize.")
        return {"status": False}
