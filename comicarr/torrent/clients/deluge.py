import base64
import os

import comicarr
from comicarr import logger
from comicarr._vendor.deluge_client import DelugeRPCClient
from comicarr.torrent.contracts import connection_failure


class TorrentClient(object):
    def __init__(self):
        self.conn = None

    def connect(self, host, username, password, test=False):
        if self.conn is not None:
            return self.conn

        if not host:
            return {"status": False, "error": "No host specified"}

        if not username:
            return {"status": False, "error": "No username specified"}

        if not password:
            return {"status": False, "error": "No password specified"}

        try:
            host, portnr = host.rsplit(":", 1)
            if not host or not portnr or not portnr.isdigit():
                raise ValueError
            portnr = int(portnr)
            if not 1 <= portnr <= 65535:
                raise ValueError
        except (AttributeError, ValueError):
            return connection_failure("invalid host; expected host:port")

        try:
            self.client = DelugeRPCClient(host, int(portnr), username, password)
        except Exception as e:
            logger.error("Could not create DelugeRPCClient Object %s" % e)
            return connection_failure(e)
        else:
            try:
                self.client.connect()
            except Exception as e:
                logger.error("Could not connect to Deluge: %s" % host)
                return connection_failure(e)
            else:
                self.conn = self.client
                if test is True:
                    daemon_version = self.client.call("daemon.info")
                    libtorrent_version = self.client.call("core.get_libtorrent_version")
                    return {"status": True, "daemon_version": daemon_version, "libtorrent_version": libtorrent_version}
                else:
                    return self.client

    def find_torrent(self, hash):
        logger.debug("Finding Torrent hash: " + hash)
        torrent_info = self.get_torrent(hash)
        if torrent_info:
            return True
        else:
            return False

    def get_torrent(self, hash):
        logger.debug("Getting Torrent info from hash: " + hash)
        try:
            torrent_info = self.client.call("core.get_torrent_status", hash, "")
        except Exception as e:
            logger.error("Could not get torrent info for %s: %s", hash, e)
            return False
        else:
            if torrent_info is None:
                torrent_info = False
            return torrent_info

    def start_torrent(self, hash):
        try:
            self.find_torrent(hash)
        except Exception:
            return False
        else:
            try:
                self.client.call("core.resume_torrent", hash)
            except Exception as e:
                logger.error("Torrent failed to start: %s", e)
            else:
                logger.info("Torrent " + hash + " was started")
                return True

    def stop_torrent(self, hash):
        try:
            self.find_torrent(hash)
        except Exception:
            logger.error("Torrent Not Found")
            return False
        else:
            try:
                self.client.call("core.pause_torrent", hash)
            except Exception as e:
                logger.error("Torrent failed to be stopped: %s", e)
                return False
            else:
                logger.info("Torrent " + hash + " was stopped")
                return True

    def load_torrent(self, filepath):

        options = {}

        if comicarr.CONFIG.DELUGE_DOWNLOAD_DIRECTORY:
            options["download_location"] = comicarr.CONFIG.DELUGE_DOWNLOAD_DIRECTORY

        if comicarr.CONFIG.DELUGE_DONE_DIRECTORY:
            options["move_completed"] = 1
            options["move_completed_path"] = comicarr.CONFIG.DELUGE_DONE_DIRECTORY

        if comicarr.CONFIG.DELUGE_PAUSE:
            options["add_paused"] = int(comicarr.CONFIG.DELUGE_PAUSE)

        logger.info("filepath to torrent file set to : " + filepath)
        torrent_id = False

        if self.client.connected is True:
            logger.info("Checking if Torrent Exists!")

            if not filepath.startswith("magnet"):
                torrentcontent = open(filepath, "rb").read()
                hash = str.lower(self.get_the_hash(filepath))

                logger.debug('Torrent Hash (load_torrent): "' + hash + '"')
                logger.debug("FileName (load_torrent): " + str(os.path.basename(filepath)))

                if self.find_torrent(str.lower(hash)):
                    logger.info("load_torrent: Torrent already exists!")
                else:
                    logger.info("Torrent not added yet, trying to add it now!")
                    try:
                        torrent_id = self.client.call(
                            "core.add_torrent_file",
                            str(os.path.basename(filepath)),
                            base64.encodebytes(torrentcontent),
                            options,
                        )
                    except Exception as e:
                        logger.debug("[ERROR] Torrent not added. Error returned: %s" % (e,))
                        return False
            else:
                try:
                    torrent_id = self.client.call("core.add_torrent_magnet", str(filepath), options)
                except Exception:
                    logger.debug("Torrent not added")
                    return False

            if torrent_id and comicarr.CONFIG.DELUGE_LABEL:
                logger.info("Setting label to " + comicarr.CONFIG.DELUGE_LABEL)
                try:
                    self.client.call("label.set_torrent", torrent_id, comicarr.CONFIG.DELUGE_LABEL)
                except Exception:
                    try:
                        self.client.call("label.add", comicarr.CONFIG.DELUGE_LABEL)
                        self.client.call("label.set_torrent", torrent_id, comicarr.CONFIG.DELUGE_LABEL)
                    except Exception:
                        logger.warning(
                            "Unable to set label - Either try to create it manually within Deluge, and/or ensure there are no spaces, capitalization or special characters in label"
                        )
                    else:
                        logger.info("Succesfully set label to " + comicarr.CONFIG.DELUGE_LABEL)

        try:
            torrent_info = self.get_torrent(torrent_id)
            logger.info("Double checking that the torrent was added.")
        except Exception:
            logger.warn("Torrent was not added! Please check logs")
            return False
        else:
            logger.info("Torrent successfully added!")
            return {
                "hash": torrent_info["hash"],
                "label": comicarr.CONFIG.DELUGE_LABEL,
                "folder": torrent_info["save_path"],
                "move path": torrent_info["move_completed_path"],
                "total_filesize": torrent_info["total_size"],
                "name": torrent_info["name"],
                "files": torrent_info["files"],
                "time_started": torrent_info["active_time"],
                "pause": torrent_info["paused"],
                "completed": torrent_info["is_finished"],
            }

    def delete_torrent(self, hash, removeData=False):
        try:
            self.find_torrent(hash)
        except Exception:
            logger.error("Torrent " + hash + " does not exist")
            return False
        else:
            try:
                self.client.call("core.remove_torrent", hash, removeData)
            except Exception:
                logger.error("Unable to delete torrent " + hash)
                return False
            else:
                logger.info("Torrent deleted " + hash)
                return True

    def get_the_hash(self, filepath):
        import hashlib

        from comicarr._vendor import bencode

        torrent_file = open(filepath, "rb")
        metainfo = bencode.decode(torrent_file.read())
        info = metainfo["info"]
        thehash = hashlib.sha1(bencode.encode(info)).hexdigest().upper()
        logger.debug("Hash: " + thehash)
        return thehash
