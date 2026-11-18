#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Transmission download client, built on the maintained ``transmission-rpc`` package."""

import datetime
import os
from urllib.parse import urlparse

import transmission_rpc

import comicarr
from comicarr.app.core import logger
from comicarr.app.downloads.torrent.contracts import connection_failure

DEFAULT_PORT = 9091
DEFAULT_PATH = "/transmission/rpc"


def rpc_target(address):
    """Split ``TRANSMISSION_HOST`` into the parts ``transmission_rpc.Client`` takes.

    The setting is documented as a URL (``http://localhost:9091``) but older
    configs hold a bare ``host`` or ``host:port``. A URL with no path gets the
    standard RPC path. Credentials in the URL are returned so the caller can
    use them when the settings carry none.
    """
    text = str(address).strip()
    if "://" not in text:
        text = "http://" + text
    url = urlparse(text)
    if not url.hostname:
        raise ValueError("invalid Transmission host %r" % address)
    path = url.path if url.path not in ("", "/") else DEFAULT_PATH
    return {
        "protocol": "https" if url.scheme == "https" else "http",
        "host": url.hostname,
        "port": url.port or DEFAULT_PORT,
        "path": path,
        "username": url.username,
        "password": url.password,
    }


def Client(address, user=None, password=None):
    """Connect to Transmission at ``address``; raises when it does not answer."""
    target = rpc_target(address)
    url_user, url_password = target.pop("username"), target.pop("password")
    if not (user and password) and url_user and url_password:
        user, password = url_user, url_password
    if user and password:
        target.update(username=user, password=password)
    return transmission_rpc.Client(**target)


class TorrentClient(object):
    def __init__(self):
        self.conn = None

    def connect(self, host, username, password):
        if self.conn is not None:
            return self.conn

        if not host:
            return connection_failure("No host specified")
        try:
            if username and password:
                self.conn = Client(host, user=username, password=password)
            else:
                self.conn = Client(host)
        except Exception as e:
            logger.error("Could not connect to %s: %s", host, e)
            return connection_failure(e)

        return self.conn

    def find_torrent(self, hash):
        try:
            return self.conn.get_torrent(hash)
        except (KeyError, AttributeError) as e:
            logger.error("torrent %s does not exist: %s", hash, e)
            return False

    def get_torrent(self, torrent):
        torrent = self.conn.get_torrent(torrent.hashString)
        torrent_files = []
        torrent_directory = os.path.normpath(torrent.download_dir)

        for f in torrent.get_files():
            if not os.path.normpath(f.name).startswith(torrent_directory):
                file_path = os.path.join(torrent_directory, f.name.lstrip("/"))
            else:
                file_path = f.name

            torrent_files.append(file_path)

        torrent_info = {
            "hash": torrent.hashString,
            "name": torrent.name,
            "folder": torrent.download_dir,
            "completed": torrent.progress == 100,
            "label": "None",
            "files": torrent_files,
            "upload_total": torrent.uploaded_ever,
            "download_total": torrent.downloaded_ever,
            "ratio": torrent.ratio,
            "total_filesize": torrent.size_when_done,
            "time_started": datetime.datetime.fromtimestamp(torrent.fields["startDate"]),
        }
        logger.debug(torrent_info)
        return torrent_info if torrent_info else False

    def start_torrent(self, torrent):
        return self.conn.start_torrent(torrent.hashString)

    def stop_torrent(self, torrent):
        return self.conn.stop_torrent(torrent.hashString)

    def load_torrent(self, filepath):
        if any(
            [
                comicarr.CONFIG.TRANSMISSION_DIRECTORY is None,
                comicarr.CONFIG.TRANSMISSION_DIRECTORY == "",
                comicarr.CONFIG.TRANSMISSION_DIRECTORY == "None",
            ]
        ):
            down_dir = comicarr.CONFIG.CHECK_FOLDER
        else:
            down_dir = comicarr.CONFIG.TRANSMISSION_DIRECTORY
        if filepath.startswith("magnet"):
            torrent = self.conn.add_torrent(filepath, download_dir=down_dir)
        else:
            with open(filepath, "rb") as torrent_file:
                torrent = self.conn.add_torrent(torrent_file.read(), download_dir=down_dir)

        self.conn.start_torrent(torrent.hashString)
        return self.get_torrent(torrent)
