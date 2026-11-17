#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""rTorrent download client, built on the first-party ``rtorrent_rpc`` module."""

import os
import re
import time
from base64 import b16encode, b32decode
from urllib.parse import urlparse

import comicarr
from comicarr import logger
from comicarr.app.common import dates as common_dates
from comicarr.app.common import numbers as common_numbers
from comicarr.app.common import strings as common_strings
from comicarr.app.common.torrent_hash import info_hash_of_file
from comicarr.app.downloads.rtorrent_rpc import RTorrentError, Session


def rpc_url(host, rpc_path=None):
    """Build the rTorrent URL from ``RTORRENT_HOST`` and ``RTORRENT_RPC_URL``."""
    ssl = host.startswith("https:")
    url = common_strings.cleanHost(host, protocol=True, ssl=ssl)
    if ssl and url.startswith("httprpc://"):
        url = url.replace("httprpc://", "httprpc+https://")
    if not ssl and "://" not in url:
        url = "http://" + url
    if urlparse(url).scheme in ("http", "https") and rpc_path is not None:
        url += rpc_path
    return url


class TorrentClient(object):
    def __init__(self):
        self.conn = None

    def getVerifySsl(self, verify, ca_bundle):
        if not verify:
            return False

        if ca_bundle is not None and os.path.exists(ca_bundle):
            return ca_bundle

        return True

    def connect(self, host, username, password, auth, verify, rpc_path, ca_bundle, test=False):
        if self.conn is not None:
            return self.conn

        if not host:
            return {"status": False, "error": "No host specified"}

        url = rpc_url(host, rpc_path)
        logger.fdebug(url)

        try:
            self.conn = Session(url, (auth, username, password), verify=self.getVerifySsl(verify, ca_bundle))
        except Exception as err:
            logger.error(
                "Make sure you have the right protocol specified for the rtorrent host. Failed to connect to rTorrent - error: %s."
                % err
            )
            return {"status": False, "error": err}

        if test is True:
            return {"status": True, "version": self.conn.version_text}
        return self.conn

    def find_torrent(self, hash):
        return self.conn.find(hash)

    def get_torrent(self, torrent):
        torrent_files = []
        torrent_directory = os.path.normpath(torrent.directory)
        for path in torrent.files():
            if not os.path.normpath(path).startswith(torrent_directory):
                file_path = os.path.join(torrent_directory, path.lstrip("/"))
            else:
                file_path = path

            torrent_files.append(file_path)

        return {
            "hash": torrent.info_hash,
            "name": torrent.name,
            "label": torrent.label or "",
            "folder": torrent_directory,
            "completed": torrent.complete,
            "files": torrent_files,
            "upload_total": torrent.up_total,
            "download_total": torrent.down_total,
            "ratio": torrent.ratio,
            "total_filesize": torrent.size_bytes,
            "time_started": torrent.time_started,
        }

    def load_torrent(self, filepath):
        start = bool(comicarr.CONFIG.RTORRENT_STARTONLOAD)

        if filepath.startswith("magnet"):
            logger.fdebug("torrent magnet link set to : " + filepath)
            torrent_hash = magnet_hash(filepath)
            try:
                torrent = self.conn.load_magnet(filepath, torrent_hash)
            except Exception as err:
                logger.error("Failed to send magnet to rTorrent: %s", err)
                return False
            if not torrent:
                logger.error("Unable to find the torrent, did it fail to load?")
                return False
            logger.info("Torrent successfully loaded into rtorrent using magnet link as source.")
        else:
            logger.fdebug("filepath to torrent file set to : " + filepath)
            try:
                with open(filepath, "rb") as handle:
                    data = handle.read()
                torrent = self.conn.load_raw(data, info_hash_of_file(filepath))
            except Exception as err:
                logger.error("Failed to send torrent to rTorrent: %s", err)
                return False
            if not torrent:
                logger.error("Unable to find the torrent, did it fail to load?")
                return False

        if comicarr.CONFIG.RTORRENT_LABEL is not None:
            torrent.set_label(comicarr.CONFIG.RTORRENT_LABEL)
            logger.fdebug("Setting label for torrent to : " + comicarr.CONFIG.RTORRENT_LABEL)

        if comicarr.CONFIG.RTORRENT_DIRECTORY is not None:
            torrent.set_directory(comicarr.CONFIG.RTORRENT_DIRECTORY)
            logger.fdebug("Setting directory for torrent to : " + comicarr.CONFIG.RTORRENT_DIRECTORY)

        logger.info("Successfully loaded torrent.")

        if start:
            logger.info("[" + str(start) + "] Now starting torrent.")
            torrent.start()
        else:
            logger.info("[" + str(start) + "] Not starting torrent due to configuration setting.")
        return True

    def start_torrent(self, torrent):
        return torrent.start()

    def stop_torrent(self, torrent):
        return torrent.stop()


def magnet_hash(magnet):
    torrent_hash = re.findall(r"urn:btih:([\w]{32,40})", magnet)[0]
    if len(torrent_hash) == 32:
        torrent_hash = b16encode(b32decode(torrent_hash)).decode()
    return torrent_hash.upper()


def connect_from_config():
    """A connected ``TorrentClient`` for the configured rTorrent; raises RTorrentError otherwise."""
    client = TorrentClient()
    result = client.connect(
        comicarr.CONFIG.RTORRENT_HOST,
        comicarr.CONFIG.RTORRENT_USERNAME,
        comicarr.CONFIG.RTORRENT_PASSWORD,
        comicarr.CONFIG.RTORRENT_AUTHENTICATION,
        comicarr.CONFIG.RTORRENT_VERIFY,
        comicarr.CONFIG.RTORRENT_RPC_URL,
        comicarr.CONFIG.RTORRENT_CA_BUNDLE,
    )
    if isinstance(result, dict):
        logger.error("[ERROR] Could not connect to %s" % comicarr.CONFIG.RTORRENT_HOST)
        raise RTorrentError(str(result.get("error") or "rTorrent did not connect"))
    return client


def send_or_check(torrent_hash=None, filepath=None, check=False):
    """Add ``filepath`` to rTorrent, or with ``check`` read ``torrent_hash``.

    Returns the torrent info dict, or None when the torrent is missing,
    already present (when adding) or failed to load. Raises RTorrentError
    when rTorrent cannot be reached.
    """
    client = connect_from_config()
    torrent = client.find_torrent(torrent_hash) if torrent_hash else None
    if torrent:
        if check:
            logger.fdebug(
                "Successfully located torrent %s by hash on client. Detailed statistics to follow" % torrent_hash
            )
        else:
            logger.warn("%s Torrent already exists. Not downloading at this time." % torrent_hash)
            return None
    elif check:
        logger.warn("Unable to locate torrent with a hash value of %s" % torrent_hash)
        return None

    if filepath:
        if not client.load_torrent(filepath):
            return None
        if filepath.startswith("magnet"):
            torrent_hash = magnet_hash(filepath)
        else:
            torrent_hash = info_hash_of_file(filepath)
            logger.fdebug("Hash: %s" % torrent_hash)

    torrent = client.find_torrent(torrent_hash)
    if torrent is None:
        logger.warn("Couldn't find torrent with hash: %s" % torrent_hash)
        return None

    torrent_info = client.get_torrent(torrent)
    if check:
        return torrent_info

    if torrent_info["completed"]:
        logger.fdebug("Directory: %s" % torrent_info["folder"])
        logger.fdebug("Name: %s" % torrent_info["name"])
        logger.fdebug("FileSize: %s" % common_numbers.human_size(torrent_info["total_filesize"]))
        logger.fdebug("Completed: %s" % torrent_info["completed"])
        logger.fdebug("Downloaded: %s" % common_numbers.human_size(torrent_info["download_total"]))
        logger.fdebug("Uploaded: %s" % common_numbers.human_size(torrent_info["upload_total"]))
        logger.fdebug("Ratio: %s" % torrent_info["ratio"])
        logger.fdebug("Seeding Time: %s" % common_dates.humanize_time(int(time.time()) - torrent_info["time_started"]))
        if torrent_info["label"]:
            logger.fdebug("Torrent Label: %s" % torrent_info["label"])
    return torrent_info
