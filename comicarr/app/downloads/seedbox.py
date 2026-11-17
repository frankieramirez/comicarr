#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
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

"""Seedbox delivery: upload a .torrent file to a remote watch folder over SFTP.

Turned on with ``TORRENT_SEEDBOX`` and the ``SEEDBOX_*`` settings in
``config.ini``; there is no Settings screen for it. ``paramiko`` is not a
declared dependency, so an install that uses this route installs it itself.
"""

from __future__ import annotations

import os
import time

import comicarr
from comicarr.app.core import logger

SEND_ATTEMPTS = 3
SETTLE_SECONDS = 5


def _import_paramiko():
    try:
        import paramiko
    except ImportError:
        return None
    return paramiko


def _connect(paramiko, host, port, username, password):
    transport = paramiko.Transport((host, port))
    transport.connect(username=username, password=password)
    return transport, paramiko.SFTPClient.from_transport(transport)


def put_torrent(localpath: str, filename: str) -> str:
    """Upload ``localpath`` to ``SEEDBOX_WATCHDIR`` as ``filename``. Returns "pass" or "fail"."""
    paramiko = _import_paramiko()
    if paramiko is None:
        logger.error(
            "[SEEDBOX] Sending torrents to a seedbox needs the paramiko package, which is not installed. "
            "Install it with: pip install paramiko"
        )
        return "fail"

    host = comicarr.CONFIG.SEEDBOX_HOST
    port = int(comicarr.CONFIG.SEEDBOX_PORT)
    username = comicarr.CONFIG.SEEDBOX_USER
    password = comicarr.CONFIG.SEEDBOX_PASS

    if not filename.endswith("torrent"):
        filename += ".torrent"
    rempath = os.path.join(comicarr.CONFIG.SEEDBOX_WATCHDIR, filename)
    logger.fdebug("[SEEDBOX] Sending %s to %s:%s as %s" % (localpath, host, port, rempath))

    if not os.path.exists(localpath):
        logger.fdebug("[SEEDBOX] File has not finished writing yet - pausing for %ss." % SETTLE_SECONDS)
        time.sleep(SETTLE_SECONDS)
        if not os.path.exists(localpath):
            logger.fdebug("[SEEDBOX] Skipping file at this time.")
            return "fail"

    transport, sftp = _connect(paramiko, host, port, username, password)
    try:
        for attempt in range(1, SEND_ATTEMPTS + 1):
            try:
                sftp.put(localpath, rempath)
                logger.fdebug("[SEEDBOX] Upload complete.")
                return "pass"
            except Exception as e:
                logger.fdebug("[SEEDBOX] Upload attempt %s failed: %s: %s" % (attempt, e.__class__, e))
                if attempt == SEND_ATTEMPTS:
                    break
                sftp.close()
                transport.close()
                transport, sftp = _connect(paramiko, host, port, username, password)
        logger.error("[SEEDBOX] Could not upload %s after %s attempts." % (filename, SEND_ATTEMPTS))
        return "fail"
    finally:
        sftp.close()
        transport.close()
