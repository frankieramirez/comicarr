#!/usr/local/bin/python

import os
import time

import comicarr
from comicarr import logger


def putfile(localpath, file):

    try:
        import paramiko
    except ImportError:
        logger.fdebug("paramiko not found on system. Please install manually in order to use seedbox option")
        logger.fdebug("get it at https://github.com/paramiko/paramiko")
        logger.fdebug("to install: python setup.py install")
        logger.fdebug("aborting send.")
        return "fail"

    host = comicarr.CONFIG.SEEDBOX_HOST
    port = int(comicarr.CONFIG.SEEDBOX_PORT)
    transport = paramiko.Transport((host, port))

    logger.fdebug("Sending file: " + str(file))
    logger.fdebug("destination: " + str(host))
    logger.fdebug("Using SSH port : " + str(port))
    password = comicarr.CONFIG.SEEDBOX_PASS
    username = comicarr.CONFIG.SEEDBOX_USER
    transport.connect(username=username, password=password)

    sftp = paramiko.SFTPClient.from_transport(transport)

    if file[-7:] != "torrent":
        file += ".torrent"
    rempath = os.path.join(comicarr.CONFIG.SEEDBOX_WATCHDIR, file)
    logger.fdebug("remote path set to " + str(rempath))
    logger.fdebug("local path set to " + str(localpath))

    if not os.path.exists(localpath):
        logger.fdebug("file has not finished writing yet - pausing for 5s to allow for completion.")
        time.sleep(5)
        if not localpath.exists():
            logger.fdebug("Skipping file at this time.")
            return "fail"

    sendcheck = False

    while not sendcheck:
        try:
            sftp.put(localpath, rempath)
            sendcheck = True
        except Exception as e:
            logger.fdebug("ERROR Sending torrent to seedbox *** Caught exception: %s: %s" % (e.__class__, e))
            logger.fdebug("Forcibly closing connection and attempting to reconnect")
            sftp.close()
            transport.close()
            transport = paramiko.Transport((host, port))
            transport.connect(username=username, password=password)
            sftp = paramiko.SFTPClient.from_transport(transport)
            logger.fdebug("sucessfully reconnected via sftp - attempting to resend.")

    sftp.close()
    transport.close()
    logger.fdebug("Upload complete to seedbox.")
    return "pass"
