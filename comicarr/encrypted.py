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
import os

import bcrypt
from cryptography.fernet import Fernet

from comicarr import logger

# Module-level cache for the Fernet instance (loaded once per process)
_fernet_instance = None


def _get_fernet():
    """Get or create the Fernet instance using the master key from SECURE_DIR."""
    global _fernet_instance
    if _fernet_instance is not None:
        return _fernet_instance

    import comicarr

    if not comicarr.CONFIG or not comicarr.CONFIG.SECURE_DIR:
        logger.error("[ENCRYPTION] SECURE_DIR not configured — cannot load master key")
        return None

    key_path = os.path.join(comicarr.CONFIG.SECURE_DIR, "master.key")

    if os.path.exists(key_path):
        with open(key_path, "rb") as f:
            key = f.read().strip()
    else:
        # Generate a new Fernet key (direct random bytes, no PBKDF2 needed)
        key = base64.urlsafe_b64encode(os.urandom(32))
        try:
            with open(key_path, "wb") as f:
                f.write(key)
            os.chmod(key_path, 0o600)
            logger.info("[ENCRYPTION] Generated new master key at %s" % key_path)
        except Exception as e:
            logger.error("[ENCRYPTION] Failed to write master key: %s" % e)
            return None

    try:
        _fernet_instance = Fernet(key)
    except Exception as e:
        logger.error("[ENCRYPTION] Invalid master key: %s" % e)
        return None

    return _fernet_instance


# --- bcrypt helpers for login passwords ---


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
        return stored_password  # Already bcrypt

    if stored_password.startswith("^~$z$"):
        # Old base64 encoding — decode to get plaintext
        try:
            decoded = base64.b64decode(stored_password[5:])
            if len(decoded) <= 8:
                logger.error("[ENCRYPTION] Base64 payload too short to contain password + salt")
                return None
            plaintext = decoded[:-8].decode("utf-8")  # Strip 8-byte salt
        except Exception as e:
            logger.error("[ENCRYPTION] Failed to decode base64 password for migration: %s" % e)
            return None
        return hash_password(plaintext)

    # Plaintext password — hash directly
    return hash_password(stored_password)


class Encryptor(object):
    """Encrypt/decrypt service credentials using Fernet.

    Preserves the dict-returning interface:
        {"status": True/False, "password": "..."}

    Handles migration from old base64 encoding (^~$z$ prefix) to Fernet (gAAAAA prefix).
    """

    def __init__(self, password, logon=False):
        self.password = password
        self.logon = logon

    def encrypt_it(self):
        """Encrypt a plaintext credential with Fernet."""
        fernet = _get_fernet()
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

        # Already a Fernet token (starts with gAAAAA)
        if self.password.startswith("gAAAAA"):
            fernet = _get_fernet()
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

        # Legacy base64 encoding (^~$z$ prefix)
        if self.password.startswith("^~$z$"):
            try:
                passd = base64.b64decode(self.password[5:])
                return {"status": True, "password": passd[:-8].decode("utf-8")}
            except Exception as e:
                logger.warn("Error when decrypting legacy password: %s" % e)
                return {"status": False}

        # Not encrypted — return failure
        if not self.logon:
            logger.warn("Error not an encryption that I recognize.")
        return {"status": False}
