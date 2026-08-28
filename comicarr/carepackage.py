import codecs
import configparser
import os
import platform
import re
import shutil
import subprocess
import sys
import zipfile
from glob import glob

import comicarr
from comicarr import config as config_module
from comicarr import encrypted, logger, versioncheck
from comicarr.app.common.redaction import redact_sensitive_text

_LEGACY_32P_CREDENTIAL_LINE_PATTERN = re.compile(
    r"\buid\s*:\s*[^/\r\n]+\s*/\s*authkey\s*:\s*[^/\r\n]+\s*/\s*passkey\s*:\s*\S+",
    re.IGNORECASE,
)
_RUNTIME_32P_CREDENTIAL_FIELDS = ("auth", "authkey", "passkey")


class carePackage(object):
    def __init__(self, maintenance=False):
        self.maintenance = maintenance
        self.carepackage_version = 1.06
        self.configpath = os.path.join(comicarr.DATA_DIR, "config.ini")
        self.lastrelpath = os.path.join(comicarr.PROG_DIR, ".LASTRELEASE")
        self.keylist = []
        self.pass_thru_vals = None
        base = set(config_module.ENCRYPTED_CONFIG_ITEMS.values())
        extras = {
            ("Interface", "http_password"),
            ("SABnzbd", "sab_username"),
            ("NZBGet", "nzbget_username"),
            ("NZBsu", "nzbsu_apikey"),
            ("DOGnzb", "dognzb_apikey"),
            ("uTorrent", "utorrent_username"),
            ("Transmission", "transmission_username"),
            ("Deluge", "deluge_username"),
            ("qBittorrent", "qbittorrent_username"),
            ("Rtorrent", "rtorrent_username"),
            ("NMA", "nma_apikey"),
            ("Seedbox", "seedbox_user"),
            ("Seedbox", "seedbox_port"),
            ("AutoSnatch", "pp_sshport"),
            ("Email", "email_user"),
            ("DDL", "external_username"),
        }
        self.cleaned_list = base | extras
        self.hostname_list = {
            ("SABnzbd", "sab_host"),
            ("NZBGet", "nzbget_host"),
            ("Torznab", "torznab_host"),
            ("uTorrent", "utorrent_host"),
            ("Transmission", "transmission_host"),
            ("Deluge", "deluge_host"),
            ("qBittorrent", "qbittorrent_host"),
            ("Interface", "http_host"),
            ("Rtorrent", "rtorrent_host"),
            ("AutoSnatch", "pp_sshhost"),
            ("Tablet", "tab_host"),
            ("Seedbox", "seedbox_host"),
            ("GOTIFY", "gotify_server_url"),
            ("Email", "email_server"),
            ("DDL", "external_server"),
            ("DDL", "flaresolverr_url"),
            ("DDL", "http_proxy"),
            ("DDL", "https_proxy"),
        }

    def _collect_runtime_secrets(self):
        """Add derived 32P tokens that are not persisted in config.ini."""
        runtime_32p_keys = getattr(comicarr, "KEYS_32P", None)
        if not isinstance(runtime_32p_keys, dict):
            return

        for key in _RUNTIME_32P_CREDENTIAL_FIELDS:
            value = runtime_32p_keys.get(key)
            if value is None:
                continue
            secret = str(value)
            if secret and secret != "None" and secret not in self.keylist:
                self.keylist.append(secret)

    def loaders(self):
        self.cleaned_config()
        vers_vals = versioncheck.versionload(cli_values=self.pass_thru_vals, carepackage_call=True)
        self.filename = os.path.join(self.log_dir, "ComicarrRunningEnvironment.txt")
        logger.info("vers_vals: %s" % (vers_vals,))
        if not vers_vals:
            vers_vals = {
                "current_branch": comicarr.CONFIG.GIT_BRANCH,
                "current_version": comicarr.CURRENT_VERSION,
                "current_version_name": comicarr.CURRENT_VERSION_NAME,
                "current_release_name": comicarr.CURRENT_RELEASE_NAME,
            }

        if vers_vals["current_branch"] == "master" and vers_vals["current_version_name"] is not None:
            panic_name = "carepackage_%s.zip" % (vers_vals["current_version_name"])
        else:
            panic_name = "carepackage_%s_(%s).zip" % (vers_vals["current_version"], vers_vals["current_branch"])

        self.panicfile = os.path.join(self.log_dir, panic_name)

        self.environment(vers_vals)
        self.panicbutton()
        logger.info("[CARE-PACKAGE-GENERATION] Successfully generated carepackage @ %s" % self.panicfile)
        return {"status": "success", "carepackage": self.panicfile}

    def environment(self, vers_vals):
        f = open(self.filename, "w+")
        f.write("-- Carepackage version %s --\n" % self.carepackage_version)
        f.write("\n-- Release information --\n")
        f.write("installation method: %s\n" % (vers_vals["install_type"]))
        f.write("branch: %s\n" % (vers_vals["current_branch"]))
        f.write("commmit: %s\n" % (vers_vals["current_version"]))
        if vers_vals["current_version_name"] is not None:
            f.write("version: %s\n" % (vers_vals["current_version_name"]))
        if vers_vals["current_release_name"]:
            f.write("release name: %s\n" % (vers_vals["current_release_name"]))
        f.write("-------------------------\n")
        f.write("\nComicarr host information:\n")
        match = re.search("Windows", platform.system(), re.IGNORECASE)
        if match:
            objline = ["systeminfo"]
        else:
            objline = ["uname", "-a"]

        hi = subprocess.run(objline, capture_output=True, text=True)
        for hiline in hi.stdout.split("\n"):
            if platform.system() == "Windows":
                if all(
                    [
                        "Host Name" not in hiline,
                        "OS Name" not in hiline,
                        "OS Version" not in hiline,
                        "OS Configuration" not in hiline,
                        "OS Build Type" not in hiline,
                        "Locale" not in hiline,
                        "Time Zone" not in hiline,
                    ]
                ):
                    continue
            if all([hiline is not None, hiline != "", hiline != r"\n"]):
                f.write("%s\n" % hiline)

        f.write("\n\nComicarr python information:\n")
        pyloc = sys.executable
        pi = subprocess.run([pyloc, "-V"], capture_output=True, text=True)
        f.write("%s" % pi.stdout)
        f.write("%s\n" % pyloc)

        try:
            pf = subprocess.run([pyloc, "-m", "pip", "freeze"], capture_output=True, text=True)
            f.write("\nPIP (freeze) list:\n")
            for pfout in pf.stdout.split("\n"):
                f.write("%s\n" % pfout)
        except Exception:
            logger.warn(
                "Unable to retrieve current pip listing. Usually this is due to pip being referenced as something other than pip3"
            )

        f.write("\n\nComicarr running environment:\n")
        SECRET_PATTERNS = ["KEY", "SECRET", "PASSWORD", "TOKEN", "API", "CREDENTIAL", "SSH", "LS_COLORS"]
        for param in list(os.environ.keys()):
            if not any(pat in param.upper() for pat in SECRET_PATTERNS):
                f.write("%20s = %s\n" % (param, os.environ[param]))

        f.write("\n\nComicarr git status:\n")
        try:
            cmd = [["git", "--version"], ["git", "status"]]
            for c in cmd:
                gs = subprocess.run(c, capture_output=True, text=True)
                for line in gs.stdout.split("\n"):
                    f.write("%s\n" % line)
        except Exception:
            f.write("\n\nUnable to retrieve Git information")

        f.close()

    def cleaned_config(self):
        tmpconfig = configparser.ConfigParser()
        tmpconfig.read_file(codecs.open(self.configpath, "r", "utf8"))

        if self.maintenance is True:
            self.log_dir = tmpconfig["Logs"]["log_dir"]
            if self.log_dir is None:
                self.log_dir = os.path.join(comicarr.DATA_DIR, "logs")

            git_tmp = tmpconfig["Git"]
            git_user = git_tmp["git_user"]
            git_branch = git_tmp["git_branch"]
            git_token = git_tmp["git_token"]
            self.git_path = git_tmp["git_path"]
            try:
                check_github = git_tmp.getboolean("check_github", fallback=True)
            except Exception:
                check_github = True
            self.pass_thru_vals = {
                "git_user": git_user,
                "git_branch": git_branch,
                "git_token": git_token,
                "git_path": self.git_path,
                "check_github": check_github,
            }
        else:
            self.log_dir = comicarr.CONFIG.LOG_DIR

        self.cleanpath = os.path.join(self.log_dir, "clean_config.ini")

        shutil.copy(self.configpath, self.cleanpath)

        for v in self.cleaned_list:
            try:
                tmpkey = tmpconfig.get(v[0], v[1])
                if all([tmpkey is not None, tmpkey != "None"]):
                    if tmpkey[:5] == "^~$z$":
                        tk = encrypted.Encryptor(tmpkey)
                        tk_stat = tk.decrypt_it()
                        if tk_stat["status"] is True:
                            tmpkey = tk_stat["password"]
                    if tmpkey not in self.keylist:
                        self.keylist.append(tmpkey)
                    tmpconfig.set(v[0], v[1], "xXX[REMOVED]XXx")
            except (configparser.NoSectionError, configparser.NoOptionError):
                pass

        for h in self.hostname_list:
            try:
                hkey = tmpconfig.get(h[0], h[1])
                if all([hkey is not None, hkey != "None"]):
                    if hkey[:5] == "^~$z$":
                        encrypted.Encryptor(hkey)
                        hk_stat = tk.decrypt_it()
                        if tk_stat["status"] is True and "username" not in h[1]:
                            hkey = hk_stat["password"]
                    if hkey not in self.keylist:
                        self.keylist.append(hkey)
                    tmpconfig.set(h[0], h[1], "xXX[REMOVED]XXx")
            except (configparser.NoSectionError, configparser.NoOptionError):
                pass

        config_version = tmpconfig.getint("General", "config_version", fallback=15)
        secure_dir = tmpconfig.get(
            "General",
            "secure_dir",
            fallback=None,
        )
        if secure_dir in (None, "", "None"):
            secure_dir = os.path.join(comicarr.DATA_DIR, ".secure")
        for section, option in (("Newznab", "extra_newznabs"), ("Torznab", "extra_torznabs")):
            try:
                entries = config_module.parse_provider_extras(
                    tmpconfig.get(section, option),
                    config_version=config_version,
                )
            except (configparser.NoSectionError, configparser.NoOptionError, ValueError):
                if not tmpconfig.has_section(section):
                    tmpconfig.add_section(section)
                tmpconfig.set(section, option, "xXX[REMOVED]XXx")
                continue

            cleaned_entries = []
            for entry in entries:
                cleaned = list(entry)
                host = cleaned[1]
                if host not in (None, "", "None") and host not in self.keylist:
                    self.keylist.append(host)
                cleaned[1] = "xXX[REMOVED]XXx"

                stored_key = cleaned[3]
                if stored_key not in (None, "", "None"):
                    if stored_key not in self.keylist:
                        self.keylist.append(stored_key)
                    try:
                        runtime_key, _token, _migration = config_module.decrypt_provider_credential(
                            stored_key,
                            secure_dir,
                        )
                    except ValueError:
                        runtime_key = None
                    if runtime_key not in (None, "", "None") and runtime_key not in self.keylist:
                        self.keylist.append(runtime_key)
                    cleaned[3] = "xXX[REMOVED]XXx"

                if section == "Newznab" and cleaned[4] not in (None, "", "None"):
                    if cleaned[4] not in self.keylist:
                        self.keylist.append(cleaned[4])
                    cleaned[4] = "xXX[REMOVED]XXx"
                cleaned_entries.append(tuple(cleaned))

            tmpconfig.set(section, option, config_module.serialize_provider_extras(cleaned_entries))
        try:
            with codecs.open(self.cleanpath, encoding="utf8", mode="w+") as tmp_configfile:
                tmpconfig.write(tmp_configfile)
            logger.fdebug("Configuration cleaned of keys/passwords and written to temporary location.")
        except IOError as e:
            logger.warn("Error writing configuration file: %s" % e)

    def panicbutton(self):
        self._collect_runtime_secrets()
        redaction_keys = sorted(
            (key for key in self.keylist if len(key) > 4 and not key.isdigit()),
            key=len,
            reverse=True,
        )
        dbpath = os.path.join(comicarr.DATA_DIR, "comicarr.db")
        with zipfile.ZipFile(self.panicfile, "w") as zip:
            zip.write(self.filename, os.path.basename(self.filename))
            zip.write(dbpath, os.path.basename(dbpath))
            zip.write(self.cleanpath, os.path.basename(self.cleanpath))
            if os.path.exists(self.lastrelpath):
                zip.write(self.lastrelpath, os.path.basename(self.lastrelpath))

            files = []
            try:
                caredir = os.path.join(self.log_dir, "carepackage")
                os.mkdir(caredir)
            except Exception:
                pass

            for file in glob(os.path.join(self.log_dir, "comicarr.log*")):
                files.append(os.path.join(self.log_dir, os.path.basename(file)))

            if len(files) > 0:
                for fname in files:
                    logger.fdebug("analyzing %s" % fname)
                    cnt = 0
                    filename = os.path.join(caredir, os.path.basename(fname))
                    with open(filename, "w") as output:
                        with open(fname, "r") as f:
                            line = f.readline()
                            while line:
                                line, structured_redactions = _LEGACY_32P_CREDENTIAL_LINE_PATTERN.subn(
                                    "uid:-REDACTED- / authkey:-REDACTED- / passkey:-REDACTED-", line
                                )
                                cnt += structured_redactions
                                cnt += sum(1 for keyed in redaction_keys if keyed in line)
                                line = redact_sensitive_text(line, redaction_keys)
                                output.write(line)
                                line = f.readline()

                    logger.fdebug("removed %s keys from %s" % (cnt, fname))
                    try:
                        zip.write(filename, os.path.basename(fname), zipfile.ZIP_DEFLATED)
                    except RuntimeError:
                        zip.write(filename, os.path.basename(fname))
                    except Exception as e:
                        logger.warn(e)
                    else:
                        os.unlink(filename)

        try:
            shutil.rmtree(caredir)
        except Exception as e:
            logger.warn("Error logged trying to remove temporary carepackage directory: %s" % e)

        os.unlink(self.filename)
        os.unlink(self.cleanpath)
