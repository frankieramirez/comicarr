#  Copyright (C) 2025-2026 Comicarr contributors
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

"""Create library folders and apply the configured owner and permissions.

Moved unchanged from the old root ``filechecker.py`` (#1415); ``filechecker``
re-exports these names for its remaining callers.
"""

import getpass
import os
import platform

from comicarr.app.core import logger, runtime

if "windows" not in platform.system().lower():
    from grp import getgrnam
    from pwd import getpwnam


def validateAndCreateDirectory(dir, create=False, module=None, dmode=None):
    if module is None:
        module = ""
    module += "[DIRECTORY-CHECK]"
    if dmode is None:
        dirmode = "comic"
    else:
        dirmode = dmode

    try:
        if os.path.exists(dir):
            logger.info("%s Found %s directory: %s" % (module, dirmode, dir))
            return True
        else:
            if create:
                if dir.strip():
                    logger.info("%s %s directory does not exist yet: %s" % (module, dirmode.capitalize(), dir))
                    logger.info(
                        "%s Creating %s directory (%s) : %s"
                        % (module, dirmode, runtime.current().config.CHMOD_DIR, dir)
                    )
                    try:
                        os.umask(0)
                        if runtime.current().config.ENFORCE_PERMS:
                            permission = int(runtime.current().config.CHMOD_DIR, 8)
                            os.makedirs(dir.rstrip(), permission)
                            s_perms = setperms(dir.rstrip(), True)
                            if not s_perms:
                                raise OSError
                        else:
                            os.makedirs(dir.rstrip())
                    except OSError as e:
                        try:
                            if not s_perms:
                                logger.warn("%s Unable to set permissions for : %s [%s]" % (module, dir, e))
                            else:
                                logger.warn("%s Could not create directory: %s [%s]. Aborting" % (module, dir, e))
                        except UnboundLocalError:
                            logger.warn("%s Could not create directory: %s [%s]. Aborting" % (module, dir, e))
                        return False
                    else:
                        return True
                else:
                    logger.warn("%s Provided directory [%s] is blank. Aborting." % (module, dir))
                    return False
            else:
                logger.warn("%s Could not find %s directory: %s" % (module, dirmode, dir))
    except OSError as e:
        logger.warn("%s Could not create directory: %s [%s]. Aborting." % (module, dir, e))
        return False
    return False


def setperms(path, dir=False):

    if "windows" not in runtime.current().os_detect.lower():
        try:
            os.umask(0)
            if runtime.current().config.CHGROUP:
                if (
                    runtime.current().config.CHOWNER is None
                    or runtime.current().config.CHOWNER == "None"
                    or runtime.current().config.CHOWNER == ""
                ):
                    runtime.current().config.CHOWNER = getpass.getuser()

                if not runtime.current().config.CHOWNER.isdigit():
                    try:
                        chowner = getpwnam(runtime.current().config.CHOWNER)[2]
                    except Exception:
                        logger.warn(
                            "[PERMISSIONS] %s does not exist on this system as a user"
                            % runtime.current().config.CHOWNER
                        )
                        chowner = -1
                else:
                    chowner = int(runtime.current().config.CHOWNER)

                if not runtime.current().config.CHGROUP.isdigit():
                    try:
                        chgroup = getgrnam(runtime.current().config.CHGROUP)[2]
                    except Exception:
                        logger.warn(
                            "[PERMISSIONS] %s does not exist on this system as a group"
                            % runtime.current().config.CHGROUP
                        )
                        chgroup = -1
                else:
                    chgroup = int(runtime.current().config.CHGROUP)

                validity_perm = check_valid_perms(chowner, chgroup)
                logger.fdebug("validity_perm: %s" % validity_perm)
                if validity_perm["status"]:
                    chowner = validity_perm["owner"]
                    chgroup = validity_perm["group"]

                if dir:
                    permission = int(runtime.current().config.CHMOD_DIR, 8)
                    if validity_perm["status"]:
                        os.chown(path, chowner, chgroup)
                    os.chmod(path, permission)
                elif os.path.isfile(path):
                    permission = int(runtime.current().config.CHMOD_FILE, 8)
                    if validity_perm["status"]:
                        os.chown(path, chowner, chgroup)
                    os.chmod(path, permission)
                else:
                    for root, dirs, files in os.walk(path):
                        for momo in dirs:
                            permission = int(runtime.current().config.CHMOD_DIR, 8)
                            if validity_perm["status"]:
                                os.chown(os.path.join(root, momo), chowner, chgroup)
                            os.chmod(os.path.join(root, momo), permission)
                        for momo in files:
                            permission = int(runtime.current().config.CHMOD_FILE, 8)
                            if validity_perm["status"]:
                                os.chown(os.path.join(root, momo), chowner, chgroup)
                            os.chmod(os.path.join(root, momo), permission)

                logger.fdebug(
                    "Successfully changed ownership and permissions [%s:%s] / [%s/%s]"
                    % (chowner, chgroup, runtime.current().config.CHMOD_DIR, runtime.current().config.CHMOD_FILE)
                )

            elif os.path.isfile(path):
                permission = int(runtime.current().config.CHMOD_FILE, 8)
                os.chmod(path, permission)
            else:
                for root, dirs, files in os.walk(path):
                    for momo in dirs:
                        permission = int(runtime.current().config.CHMOD_DIR, 8)
                        os.chmod(os.path.join(root, momo), permission)
                    for momo in files:
                        permission = int(runtime.current().config.CHMOD_FILE, 8)
                        os.chmod(os.path.join(root, momo), permission)

                logger.fdebug(
                    "Successfully changed permissions [%s/%s]"
                    % (runtime.current().config.CHMOD_DIR, runtime.current().config.CHMOD_FILE)
                )

        except OSError as e:
            logger.error("[ERROR @ path: %s] %s. Exiting..." % (path, e))
            return False

    return True


def check_valid_perms(chowner, chgroup):
    if all([chowner == -1, chgroup == -1]):
        logger.warn(
            "[PERMISSONS] Unable to set ownership due to both owner:group [%s:%s] being invalid."
            % (runtime.current().config.CHOWNER, runtime.current().config.CHGROUP)
        )
        return {"status": False, "owner": chowner, "group": chgroup}
    else:
        ch_problem = None
        if chowner == -1:
            ch_problem = "owner"
            chownr = getpass.getuser()
            chowner = getgrnam(chownr)[1]
        elif chgroup == -1:
            ch_problem = "group"
            chgp = getpass.getuser()
            chgroup = getgrnam(chgp)[2]
        if ch_problem:
            logger.warn(
                "[PERMISSIONS] Partial enforcement of permissions being done due to invalid %s specified."
                " Perms set to: %s:%s " % (ch_problem, chowner, chgroup)
            )

        return {"status": True, "owner": chowner, "group": chgroup}
