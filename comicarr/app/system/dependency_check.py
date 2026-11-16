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

import configparser
import os
import platform
import shutil

import comicarr
from comicarr import logger


class RuntimeCapabilityDiagnostics:
    """Report optional host capabilities without inspecting package-manager state."""

    def loaders(self):
        self.find_the_unrar()
        self.release_messages()

    def _unrar_candidates(self):
        commands = ["unrar"]

        if comicarr.CONFIG.UNRAR_CMD:
            commands.append(comicarr.CONFIG.UNRAR_CMD)
            logger.fdebug("[DEPENDENCY-CHECK] unrar_cmd location added to cmd checker: %s" % comicarr.CONFIG.UNRAR_CMD)

        settings_path = os.path.join(comicarr.CONFIG.CT_SETTINGSPATH, "settings")
        config = configparser.ConfigParser()
        try:
            if os.path.isfile(settings_path):
                config.read(settings_path, encoding="utf-8")
                configured_path = config.get("settings", "rar_exe_path", fallback=None)
                if configured_path:
                    commands.append(configured_path)
                    logger.fdebug(
                        "[DEPENDENCY-CHECK] comictagger .settings file path added to cmd checker: %s" % configured_path
                    )
        except (OSError, configparser.Error) as e:
            logger.fdebug("[DEPENDENCY-CHECK] Unable to read comictagger settings: %s" % e)

        if platform.system() == "Windows":
            commands.append("RaR")

        return commands

    def find_the_unrar(self):
        for command in self._unrar_candidates():
            executable = shutil.which(command)
            if executable:
                logger.fdebug("[DEPENDENCY-CHECK] Found unrar executable: %s" % executable)
                comicarr.REQS["rar"] = {"rar_failure": False, "rar_message": executable}
                return

        comicarr.REQS["rar"] = {"rar_failure": True, "rar_message": "Unable to locate unrar"}

    def release_messages(self):
        release_path = os.path.join(comicarr.PROG_DIR or ".", ".release_messages")
        try:
            with open(release_path, encoding="utf-8") as release_file:
                messages = release_file.readlines() or None
        except OSError:
            messages = None

        logger.info("[DEPENDENCY-CHECK] release_messages: %s" % (messages,))
        comicarr.REQS["release_messages"] = messages
