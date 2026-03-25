#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""
Filesystem utilities extracted from helpers.py.

is_path_within_allowed_dirs requires config access — takes allowed_dirs
as a parameter to stay free of global state.
"""

import errno
import logging
import os
import shutil


def is_path_within_allowed_dirs(path, allowed_dirs):
    """Check if a path is within any of the allowed directories.

    Uses os.path.realpath + os.path.commonpath to prevent path traversal.
    Unlike the original helpers.py version, this takes allowed_dirs as a
    parameter instead of reading from global config.
    """
    real_path = os.path.realpath(path)
    for root in allowed_dirs:
        if not root:
            continue
        real_root = os.path.realpath(root)
        try:
            if os.path.commonpath([real_root, real_path]) == real_root:
                return True
        except ValueError:
            continue
    return False


def urlretrieve(urlfile, fpath):
    """Download a file from an open URL handle to a local path."""
    chunk = 4096
    f = open(fpath, "w")
    while 1:
        data = urlfile.read(chunk)
        if not data:
            print("done.")
            break
        f.write(data)
        print("Read %s bytes" % len(data))


def checkFolder(folderpath=None, check_folder=None, postprocessor=None, queue_cls=None):
    """Validate/create directory and run post-processing on snatched files.

    Takes dependencies as parameters to stay free of global state.
    The wrapper in helpers.py passes in the comicarr globals.
    """
    import queue as queue_module

    log = logging.getLogger("comicarr")
    q = queue_module.Queue()
    # monitor a selected folder for 'snatched' files that haven't been processed
    if folderpath is None:
        log.info("Checking folder " + check_folder + " for newly snatched downloads")
        path = check_folder
    else:
        log.info("Submitted folder " + folderpath + " for direct folder post-processing")
        path = folderpath

    PostProcess = postprocessor.PostProcessor("Manual Run", path, queue=q)
    PostProcess.Process()
    return


def file_ops(path, dst, arc=False, one_off=False, multiple=False,
             file_opts=None, arc_fileops=None, arc_fileops_softlink_relative=False,
             os_detect=None):
    """Perform file copy/move/link operations.

    Takes config values as parameters to stay free of global state.
    The wrapper in helpers.py passes in the comicarr globals.
    """
    log = logging.getLogger("comicarr")

    softlink_type = "absolute"

    if any([one_off, arc]):
        if multiple is True:
            action_op = "copy"
        else:
            action_op = arc_fileops
        if arc_fileops_softlink_relative is True:
            softlink_type = "relative"
    else:
        action_op = file_opts

    if action_op == "copy" or (arc is True and any([action_op == "copy", action_op == "move"])):
        try:
            shutil.copy(path, dst)
        except Exception as e:
            log.error("[%s] error : %s" % (action_op, e))
            return False
        return True

    elif action_op == "move":
        try:
            shutil.move(path, dst)
        except Exception as e:
            log.error("[MOVE] error : %s" % e)
            return False
        return True

    elif any([action_op == "hardlink", action_op == "softlink"]):
        if os_detect is None or "windows" not in os_detect.lower():
            # if it's an arc, then in needs to go reverse since we want to keep the src files (in the series directory)
            if action_op == "hardlink":
                # Open a file
                try:
                    fd = os.open(path, os.O_RDWR | os.O_CREAT)
                    os.close(fd)

                    # Now create another copy of the above file.
                    os.link(path, dst)
                    log.info("Created hard link successfully!!")
                except OSError as e:
                    if e.errno == errno.EXDEV:
                        log.warning(
                            "["
                            + str(e)
                            + "] Hardlinking failure. Could not create hardlink - dropping down to copy mode so that this operation can complete. Intervention is required if you wish to continue using hardlinks."
                        )
                        try:
                            shutil.copy(path, dst)
                            log.debug("Successfully copied file to : " + dst)
                            return True
                        except Exception as e:
                            log.error("[COPY] error : %s" % e)
                            return False
                    else:
                        log.warning(
                            "["
                            + str(e)
                            + "] Hardlinking failure. Could not create hardlink - Intervention is required if you wish to continue using hardlinks."
                        )
                        return False

                hardlinks = os.lstat(dst).st_nlink
                if hardlinks > 1:
                    log.info("Created hard link [" + str(hardlinks) + "] successfully!! (" + dst + ")")
                else:
                    log.warning("Hardlink cannot be verified. You should probably verify that it is created properly.")

                return True

            elif action_op == "softlink":
                try:
                    # first we need to copy the file to the new location, then create the symlink pointing from new -> original
                    if not arc:
                        shutil.move(path, dst)
                        if os.path.lexists(path):
                            os.remove(path)
                        if softlink_type == "absolute":
                            os.symlink(dst, path)
                            log.debug("Successfully created softlink [" + dst + " --> " + path + "]")
                        else:
                            os.symlink(os.path.relpath(dst, os.path.dirname(path)), path)
                            log.debug(
                                "Successfully created (relative) softlink ["
                                + os.path.relpath(dst, os.path.dirname(path))
                                + " --> "
                                + path
                                + "]"
                            )

                    else:
                        if softlink_type == "absolute":
                            os.symlink(path, dst)
                            log.debug("Successfully created softlink [" + path + " --> " + dst + "]")
                        else:
                            os.symlink(os.path.relpath(path, os.path.dirname(dst)), dst)
                            log.debug(
                                "Successfully created (relative) softlink ["
                                + os.path.relpath(path, os.path.dirname(dst))
                                + " --> "
                                + dst
                                + "]"
                            )
                except OSError as e:
                    log.warning(
                        "["
                        + str(e)
                        + "] Unable to create symlink. Dropping down to copy mode so that this operation can continue."
                    )
                    try:
                        shutil.copy(dst, path)
                        log.debug("Successfully copied file [" + dst + " --> " + path + "]")
                    except Exception as e:
                        log.error("[COPY] error : %s" % e)
                        return False

                return True

        else:
            # Not ready just yet.
            pass

            # softlinks = shortcut (normally junctions are called softlinks, but for this it's being called a softlink)
            # hardlinks = MUST reside on the same drive as the original
            # junctions = not used (for directories across same machine only but different drives)

            # option 1
            # this one needs to get tested
            # import ctypes
            # kdll = ctypes.windll.LoadLibrary("kernel32.dll")
            # kdll.CreateSymbolicLinkW(path, dst, 0)

            # option 2
            if file_opts == "hardlink":
                try:
                    os.system(r"mklink /H dst path")
                    log.debug("Successfully hardlinked file [" + dst + " --> " + path + "]")
                except OSError as e:
                    log.warning(
                        "["
                        + e
                        + "] Unable to create symlink. Dropping down to copy mode so that this operation can continue."
                    )
                    try:
                        shutil.copy(dst, path)
                        log.debug("Successfully copied file [" + dst + " --> " + path + "]")
                    except:
                        return False

            elif file_opts == "softlink":  # ie. shortcut.
                try:
                    shutil.move(path, dst)
                    if os.path.lexists(path):
                        os.remove(path)
                    os.system(r"mklink dst path")
                    log.debug("Successfully created symlink [" + dst + " --> " + path + "]")
                except OSError as e:
                    raise e
                    log.warning(
                        "["
                        + e
                        + "] Unable to create softlink. Dropping down to copy mode so that this operation can continue."
                    )
                    try:
                        shutil.copy(dst, path)
                        log.debug("Successfully copied file [" + dst + " --> " + path + "]")
                    except:
                        return False

    else:
        return False
