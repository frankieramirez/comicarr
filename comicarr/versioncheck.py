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

import calendar
import datetime
import os
import platform
import re
import subprocess
import tarfile
import time
import urllib.error
import urllib.parse
import urllib.request

import requests
from sqlalchemy import select

import comicarr
from comicarr import db, logger
from comicarr.tables import jobhistory

_VERSION_FIELDS = {
    "current_version": "CURRENT_VERSION",
    "current_version_name": "CURRENT_VERSION_NAME",
    "current_release_name": "CURRENT_RELEASE_NAME",
    "current_branch": "CURRENT_BRANCH",
    "latest_version": "LATEST_VERSION",
    "update_state": "UPDATE_STATE",
    "update_reason": "UPDATE_REASON",
    "install_type": "INSTALL_TYPE",
    "update_value": "UPDATE_VALUE",
}

_GITHUB_REQUEST_TIMEOUT = (10, 10)

_GITHUB_RELEASES_LATEST = "https://api.github.com/repos/frankieramirez/comicarr/releases/latest"
_GITHUB_RELEASE_TAG_URL = "https://github.com/frankieramirez/comicarr/releases/tag/v%s"

UPDATE_STATE_BEHIND = "behind"
UPDATE_STATE_CURRENT = "current"
UPDATE_STATE_UNKNOWN = "unknown"

REASON_NEVER_CHECKED = "never_checked"
REASON_UNREACHABLE = "unreachable"
REASON_RATE_LIMITED = "rate_limited"

RELEASE_ANNOUNCE_EVENT = "Update available"


def _set_version_state(**fields):
    """Write version state once and project it to legacy callers.

    Falls back to a plain module write before the runtime exists (versionload
    runs ahead of the factory) and after it is disposed.
    """
    from comicarr.app.core.runtime import get_runtime_if_initialized, set_runtime_field

    ctx = get_runtime_if_initialized()
    if ctx is not None and ctx.disposed:
        ctx = None

    for field, value in fields.items():
        legacy_name = _VERSION_FIELDS[field]
        if ctx is None:
            setattr(comicarr, legacy_name, value)
        else:
            set_runtime_field(ctx, field, value)


def _get_version_state(field):
    """Read version state from wherever _set_version_state last wrote it."""
    from comicarr.app.core.runtime import get_runtime_if_initialized

    ctx = get_runtime_if_initialized()
    if ctx is not None and ctx.disposed:
        ctx = None

    if ctx is None:
        return getattr(comicarr, _VERSION_FIELDS[field], None)
    return getattr(ctx, field, None)


def runGit(args, ptv=None, suppress_errors=False):

    git_locations = []
    if ptv is not None:
        if ptv["git_path"] is not None:
            git_locations.append(ptv["git_path"])
    else:
        if comicarr.CONFIG.GIT_PATH is not None:
            git_locations.append(comicarr.CONFIG.GIT_PATH)

    git_locations.append("git")

    if platform.system().lower() == "darwin":
        git_locations.append("/usr/local/git/bin/git")

    output = None

    for cur_git in git_locations:
        gitworked = False

        import shlex

        cmd_list = [cur_git] + shlex.split(args)

        try:
            logger.debug("Trying to execute: %s in %s" % (cmd_list, comicarr.PROG_DIR))
            output = subprocess.run(cmd_list, text=True, capture_output=True, cwd=comicarr.PROG_DIR)
            logger.debug("Git output: %s" % output)
            gitworked = True
        except Exception as e:
            if not suppress_errors:
                logger.error("Command %s didn't work [%s]" % (cmd_list, e))
            gitworked = False
            output = None
            continue
        else:
            if all([output.stderr is not None, output.stderr != "", output.returncode > 0]):
                if not suppress_errors:
                    logger.error("Encountered error: %s" % output.stderr)
                gitworked = False

        if all(
            [
                gitworked is True,
                "not found" in output.stdout,
                "not recognized as an internal or external command" in output.stdout,
            ]
        ):
            if not suppress_errors:
                logger.error("[%s] Unable to find git with command: %s" % (output.stdout, cmd))
            output = None
            gitworked = False
        elif ("fatal:" in output.stdout) or ("fatal:" in output.stderr):
            if not suppress_errors:
                logger.error("Error: %s" % output.stderr)
                logger.error("Git returned bad info. Are you sure this is a git installation? [%s]" % output.stdout)
            output = None
            gitworked = False
        elif gitworked:
            output = output.stdout
            break

    return output


def getVersion(ptv):
    current_version = None
    current_version_name = None
    current_release_name = None

    if ptv["git_branch"] is not None and ptv["git_branch"].startswith("win32build"):
        _set_version_state(install_type="win")

        return {
            "current_version": "Windows Install",
            "current_version_name": "None",
            "branch": "None",
            "current_release_name": current_release_name,
        }

    elif os.path.isdir(os.path.join(comicarr.PROG_DIR, ".git")):
        _set_version_state(install_type="git")
        output = runGit("describe --exact-match --tags", ptv, suppress_errors=True)
        if output:
            branch_output = runGit("rev-parse --abbrev-ref HEAD", ptv)
            if branch_output:
                output = output.strip() + "\n" + branch_output.strip() + "\n"
            else:
                output = None

        if not output:
            output = runGit("rev-parse HEAD --abbrev-ref HEAD", ptv)
            if not output:
                logger.error("Couldn't find latest installed version.")
                cur_commit_hash = None
                cur_branch = ptv["git_branch"]

        if output is not None:
            opp = output.find("\n")
            cur_commit_hash = output[:opp]
            cur_branch = output[opp : output.find("\n", opp + 1)].strip()

            if cur_commit_hash.startswith("v") and ptv.get("check_github") is True:
                url2 = "https://api.github.com/repos/frankieramirez/comicarr/tags"
                try:
                    response = requests.get(url2, verify=True, auth=ptv["git_token"], timeout=_GITHUB_REQUEST_TIMEOUT)
                    git = response.json()
                except Exception as e:
                    logger.warn("[ERROR] %s" % e)
                    pass
                else:
                    if git[0]["name"] is not None:
                        for x in git:
                            if x["name"] == output[:opp]:
                                current_version_name = x["name"]
                                cur_commit_hash = x["commit"]["sha"]
                                break
                        logger.info("version_name: %s" % current_version_name)
                        url3 = "https://api.github.com/repos/frankieramirez/comicarr/releases/tags/%s" % (
                            current_version_name,
                        )
                        try:
                            repochk = requests.get(
                                url3, verify=True, auth=ptv["git_token"], timeout=_GITHUB_REQUEST_TIMEOUT
                            )
                            repo_resp = repochk.json()
                            current_release_name = repo_resp["name"]
                        except Exception:
                            pass

        logger.info("cur_commit_hash: %s" % cur_commit_hash)
        logger.info("cur_branch: %s" % cur_branch)

        if (
            cur_commit_hash is not None
            and not re.match("^[a-z0-9]+$", cur_commit_hash)
            and current_version_name is None
        ):
            logger.error("Output does not look like a hash, not using it")
            cur_commit_hash = None

        if ptv["git_branch"] == cur_branch:
            branch = ptv["git_branch"]

        if cur_commit_hash is None:
            branch = None
        else:
            branch = None
            branch_name = runGit("branch --contains %s" % cur_commit_hash, ptv)
            if not branch_name:
                logger.warn("Could not retrieve branch name [%s] from git. Defaulting to Master." % branch)
                branch = "master"
            else:
                for line in branch_name.split("\n"):
                    if "*" in line:
                        branch = re.sub("[\\*\n]", "", line).strip()
                        break

        if not branch and ptv["git_branch"]:
            logger.warn(
                "Unable to retrieve branch name [%s] from git. Setting branch to configuration value of : %s"
                % (branch, ptv["git_branch"])
            )
            branch = ptv["git_branch"]
        if not branch:
            logger.warn("Could not retrieve branch name [%s] from git. Defaulting to Master." % branch)
            branch = "master"
        else:
            logger.info("Branch detected & set to : %s" % branch)

        return {
            "current_version": cur_commit_hash,
            "current_version_name": current_version_name,
            "branch": branch,
            "current_release_name": current_release_name,
        }

    else:
        d_path = "/proc/self/cgroup"
        if (
            os.path.exists("/.dockerenv")
            or "KUBERNETES_SERVICE_HOST" in os.environ
            or os.path.isfile(d_path)
            and any("docker" in line for line in open(d_path))
        ):
            logger.info("[DOCKER-AWARE] Docker installation detected.")
            _set_version_state(install_type="docker")
            if any([comicarr.CONFIG.DESTINATION_DIR is None, comicarr.CONFIG.DESTINATION_DIR == ""]):
                logger.info("[DOCKER-AWARE] Setting default comic location path to /comics")
                comicarr.CONFIG.DESTINATION_DIR = "/comics"
        else:
            logger.info("Not a Docker installation.")
            _set_version_state(install_type="source")

        branch = None

        version_file = os.path.join(comicarr.PROG_DIR, ".LAST_RELEASE")
        if current_version is None:
            try:
                if not os.path.isfile(version_file):
                    current_version = None
                else:
                    with open(version_file, "r") as f:
                        raw = f.read()
                    if "$Format:" in raw or "%H" in raw:
                        logger.info("[LAST_RELEASE] File contains unexpanded git export-subst placeholders, skipping")
                    else:
                        cnt = 0
                        for i in raw.splitlines():
                            logger.info("i: %s" % (i))
                            i.split()
                            if cnt == 0:
                                if i.find(">") != -1:
                                    i_clean = i[i.find(">") + 1 :]
                                    if "," in i_clean:
                                        find_clean = i_clean.find(",")
                                        mrclean = i_clean[:find_clean].strip()
                                    else:
                                        mrclean = re.sub(r"[\)\(\>]", "", i_clean).strip()
                                    branch = mrclean
                                    logger.info("[LAST_RELEASE] Branch: %s" % branch)
                                if "tag" in i:
                                    i_clean = i.find("tag")
                                    mrclean = re.sub("tag: ", "", re.sub(r"[\(\)]", "", i[i_clean:])).strip()
                                    current_version_name = mrclean
                                    logger.info("[LAST_RELEASE] Version: %s" % current_version_name)
                                elif i[1] == "(":
                                    branch = re.sub(r"[\(\)]", "", i).strip()
                                    logger.info("[LAST_RELEASE] Branch: %s" % branch)
                            elif cnt == 1:
                                current_version = i.strip()
                                logger.info("[LAST_RELEASE] Commit: %s" % "".join(current_version))
                            elif cnt == 2:
                                current_release_name = i.strip()
                                logger.info("[LAST_RELEASE] Release Name: %s" % "".join(current_release_name))
                            cnt += 1

            except Exception as e:
                logger.error("error: %s" % e)

        if current_version_name is not None and current_release_name is None and branch == "master":
            url2 = "https://api.github.com/repos/frankieramirez/comicarr/releases/tags/%s" % (current_version_name,)
            try:
                response = requests.get(
                    url2, verify=True, auth=comicarr.CONFIG.GIT_TOKEN, timeout=_GITHUB_REQUEST_TIMEOUT
                )
                git = response.json()
                current_release_name = git["name"]
            except Exception:
                pass
            else:
                if os.path.isfile(version_file):
                    logger.fdebug("this would have been written to the .LAST_RELEASE file: %s" % (current_release_name))
                    try:
                        with open(version_file, "a") as wf:
                            wf.write("%s" % current_release_name)
                    except Exception:
                        pass

        if current_version:
            if comicarr.CONFIG.GIT_BRANCH:
                logger.info("Branch detected & set to : " + ptv["git_branch"])
                return {
                    "current_version": current_version,
                    "current_version_name": current_version_name,
                    "branch": ptv["git_branch"],
                    "current_release_name": current_release_name,
                }
            else:
                if branch:
                    logger.info("Branch detected & set to : " + branch)
                else:
                    branch = "master"
                    logger.warn(
                        "No branch specified within config - could not poll version from comicarr. Defaulting to %s"
                        % branch
                    )
                return {
                    "current_version": current_version,
                    "current_version_name": current_version_name,
                    "branch": branch,
                    "current_release_name": current_release_name,
                }
        else:
            if comicarr.CONFIG.GIT_BRANCH:
                logger.info("Branch detected & set to : " + ptv["git_branch"])
                return {
                    "current_version": current_version,
                    "current_version_name": current_version_name,
                    "branch": ptv["git_branch"],
                    "current_release_name": current_release_name,
                }
            else:
                logger.warn("No branch specified within config - will attempt to poll version from comicarr")
                try:
                    branch = version.COMICARR_VERSION
                    logger.info("Branch detected & set to : " + branch)
                except:
                    branch = "master"
                    logger.info(
                        "Unable to detect branch properly - set branch in config.ini, currently defaulting to : "
                        + branch
                    )
                return {
                    "current_version": current_version,
                    "current_version_name": current_version_name,
                    "branch": branch,
                    "current_release_name": current_release_name,
                }

            logger.warn("Unable to determine which commit is currently being run. Defaulting to Master branch.")


def _strip_leading_v(tag_name):
    """Strip a single leading ``v`` from a GitHub release tag at the boundary."""
    if tag_name is None:
        return None
    text = str(tag_name).strip()
    if not text:
        return None
    if text[0] in ("v", "V"):
        return text[1:]
    return text


def _classify_release_state(local_version, remote_version):
    """Compare Changesets semver strings into behind | current | unknown.

    Ahead-of-remote installs collapse to ``current``. Unparseable versions
    never report as up to date.
    """
    from packaging.version import InvalidVersion, Version

    if not local_version or not remote_version:
        return UPDATE_STATE_UNKNOWN
    try:
        local_v = Version(str(local_version))
        remote_v = Version(str(remote_version))
    except InvalidVersion:
        return UPDATE_STATE_UNKNOWN
    if local_v < remote_v:
        return UPDATE_STATE_BEHIND
    return UPDATE_STATE_CURRENT


def release_announce_message(current_version, latest_version):
    """One template for all eleven notifiers: version arrow + release URL only."""
    body = "%s → %s\n%s" % (
        current_version,
        latest_version,
        _GITHUB_RELEASE_TAG_URL % latest_version,
    )
    return RELEASE_ANNOUNCE_EVENT, body


def should_announce_release(announce_on, update_state, latest_version, last_announced_version):
    """Whether this check should fan out a release announcement.

    Contract (#453): global announce toggle × behind × dedup by remote latest.
    Empty ``last_announced_version`` always qualifies when behind and opted in.
    """
    if not announce_on:
        return False
    if update_state != UPDATE_STATE_BEHIND:
        return False
    if not latest_version:
        return False
    last = (last_announced_version or "").strip()
    if last and last == str(latest_version).strip():
        return False
    return True


def _record_announced_version(latest_version):
    """Persist dedup key after fan-out attempt so flaky notifiers cannot re-spam."""
    try:
        comicarr.CONFIG.LAST_ANNOUNCED_VERSION = latest_version
        comicarr.CONFIG.writeconfig(values={"last_announced_version": latest_version})
    except Exception as e:
        logger.warn("[RELEASE_ANNOUNCE] Could not persist LAST_ANNOUNCED_VERSION=%s: %s" % (latest_version, e))


def _fan_out_release_announce(event, body, current_version, latest_version):
    """Send the release template through every ENABLED notifier (no snatch flags)."""
    from comicarr import notifiers

    module = "[RELEASE_ANNOUNCE]"
    mattermost_meta = {
        "series": "Comicarr",
        "issue": str(latest_version),
        "year": str(current_version) if current_version is not None else "",
    }

    def _try(label, send):
        try:
            send()
        except Exception as e:
            logger.warn("%s %s notify failed: %s" % (module, label, e))

    if comicarr.CONFIG.PROWL_ENABLED:
        logger.info("%s Sending Prowl notification" % module)
        _try("Prowl", lambda: notifiers.PROWL().notify(body, event, module=module))

    if comicarr.CONFIG.PUSHOVER_ENABLED:
        logger.info("%s Sending Pushover notification" % module)
        _try("Pushover", lambda: notifiers.PUSHOVER().notify(event, message=body, module=module))

    if comicarr.CONFIG.BOXCAR_ENABLED:
        logger.info("%s Sending Boxcar notification" % module)
        _try("Boxcar", lambda: notifiers.BOXCAR().notify(prline=event, prline2=body, module=module))

    if comicarr.CONFIG.PUSHBULLET_ENABLED:
        logger.info("%s Sending Pushbullet notification" % module)
        _try(
            "Pushbullet",
            lambda: notifiers.PUSHBULLET().notify(prline=event, prline2=body, module=module),
        )

    if comicarr.CONFIG.TELEGRAM_ENABLED:
        logger.info("%s Sending Telegram notification" % module)
        _try("Telegram", lambda: notifiers.TELEGRAM().notify("%s - %s" % (event, body)))

    if comicarr.CONFIG.SLACK_ENABLED:
        logger.info("%s Sending Slack notification" % module)
        _try("Slack", lambda: notifiers.SLACK().notify(event, body, module=module))

    if comicarr.CONFIG.MATTERMOST_ENABLED:
        logger.info("%s Sending Mattermost notification" % module)
        _try(
            "Mattermost",
            lambda: notifiers.MATTERMOST().notify(event, body, metadata=mattermost_meta, module=module),
        )

    if comicarr.CONFIG.DISCORD_ENABLED:
        logger.info("%s Sending Discord notification" % module)
        _try("Discord", lambda: notifiers.DISCORD().notify(event, body, module=module))

    if comicarr.CONFIG.EMAIL_ENABLED:
        logger.info("%s Sending email notification" % module)
        _try(
            "Email",
            lambda: notifiers.EMAIL().notify(body, "Comicarr notification - %s" % event, module=module),
        )

    if comicarr.CONFIG.GOTIFY_ENABLED:
        logger.info("%s Sending Gotify notification" % module)
        _try("Gotify", lambda: notifiers.GOTIFY().notify(event, body, module=module))

    if comicarr.CONFIG.MATRIX_ENABLED:
        logger.info("%s Sending Matrix notification" % module)
        _try("Matrix", lambda: notifiers.MATRIX().notify(event, body, module=module))


def announce_release(current_version, latest_version):
    """Fan out one release announcement, then record the remote latest as announced.

    Write timing is after the attempt (success or partial failure) so a single
    flaky notifier cannot re-spam every check interval (#453 / #475).
    """
    event, body = release_announce_message(current_version, latest_version)
    logger.info(
        "[RELEASE_ANNOUNCE] Announcing release %s → %s to enabled notifiers" % (current_version, latest_version)
    )
    try:
        _fan_out_release_announce(event, body, current_version, latest_version)
    except Exception as e:
        logger.warn("[RELEASE_ANNOUNCE] Fan-out raised: %s" % e)
    _record_announced_version(latest_version)


def maybe_announce_release(update_state, latest_version, current_version):
    """Hook after a release check: announce when opted in, behind, and not yet told."""
    announce_on = bool(getattr(comicarr.CONFIG, "ANNOUNCE_RELEASES", False))
    last_announced = getattr(comicarr.CONFIG, "LAST_ANNOUNCED_VERSION", None)
    if not should_announce_release(announce_on, update_state, latest_version, last_announced):
        return
    announce_release(current_version=current_version, latest_version=latest_version)


def _apply_update_state(update_state, update_reason=None, latest_version=None, message=None):
    """Persist update state for GET /api/system/version and return the check payload."""
    fields = {"update_state": update_state, "update_reason": update_reason}
    if latest_version is not None:
        fields["latest_version"] = latest_version
    _set_version_state(**fields)
    from comicarr.app.system.service import get_release_version

    release_version = get_release_version()
    return {
        "status": "success" if update_state != UPDATE_STATE_UNKNOWN else "failure",
        "update_state": update_state,
        "update_reason": update_reason,
        "latest_version": latest_version if latest_version is not None else _get_version_state("latest_version"),
        "release_version": release_version,
        "current_version": comicarr.CURRENT_VERSION,
        "install_type": comicarr.INSTALL_TYPE,
        "message": message,
    }


def checkGithub(current_version=None):
    """Compare local release semver against GitHub releases/latest.

    ``current_version`` is accepted for call-site compatibility (install SHA)
    but is not used for behind-ness — that is always Changesets release identity.
    """
    del current_version

    from comicarr.app.system.service import get_release_version

    release_version = get_release_version()
    auth = getattr(comicarr.CONFIG, "GIT_TOKEN", None)

    try:
        response = requests.get(
            _GITHUB_RELEASES_LATEST,
            verify=True,
            auth=auth,
            timeout=_GITHUB_REQUEST_TIMEOUT,
        )
    except Exception as e:
        logger.warn("[CHECK_GITHUB] Could not reach GitHub releases/latest: %s" % e)
        return _apply_update_state(
            UPDATE_STATE_UNKNOWN,
            update_reason=REASON_UNREACHABLE,
            message="Could not reach GitHub releases",
        )

    status_code = getattr(response, "status_code", None)
    if status_code in (403, 429):
        logger.warn("[CHECK_GITHUB] GitHub rate limited (HTTP %s)" % status_code)
        return _apply_update_state(
            UPDATE_STATE_UNKNOWN,
            update_reason=REASON_RATE_LIMITED,
            message="GitHub rate limited the release check",
        )
    if status_code != 200:
        logger.warn("[CHECK_GITHUB] Unexpected GitHub status for releases/latest: %s" % status_code)
        return _apply_update_state(
            UPDATE_STATE_UNKNOWN,
            update_reason=REASON_UNREACHABLE,
            message="Could not get latest release from GitHub",
        )

    try:
        payload = response.json()
        latest_version = _strip_leading_v(payload.get("tag_name"))
        release_body = payload.get("body")
    except Exception as e:
        logger.warn("[CHECK_GITHUB] Could not parse GitHub releases/latest response: %s" % e)
        return _apply_update_state(
            UPDATE_STATE_UNKNOWN,
            update_reason=REASON_UNREACHABLE,
            message="Could not parse GitHub release response",
        )

    if not latest_version:
        logger.warn("[CHECK_GITHUB] releases/latest response had no usable tag_name")
        return _apply_update_state(
            UPDATE_STATE_UNKNOWN,
            update_reason=REASON_UNREACHABLE,
            message="GitHub release had no tag_name",
        )

    update_state = _classify_release_state(release_version, latest_version)
    if update_state == UPDATE_STATE_UNKNOWN:
        logger.warn(
            "[CHECK_GITHUB] Could not compare local release %r to remote %r" % (release_version, latest_version)
        )
        return _apply_update_state(
            UPDATE_STATE_UNKNOWN,
            update_reason=REASON_UNREACHABLE,
            latest_version=latest_version,
            message="Could not compare release versions",
        )

    from comicarr.changelog_notes import set_cached_release_body

    if update_state == UPDATE_STATE_BEHIND and release_body:
        set_cached_release_body(latest_version, release_body)
    else:
        set_cached_release_body(None, None)

    if update_state == UPDATE_STATE_BEHIND:
        chk_message = "New version is available. Latest release is %s (running %s)" % (
            latest_version,
            release_version,
        )
    else:
        chk_message = "Comicarr is up to date (release %s)" % release_version
    logger.info("[CHECK_GITHUB] %s" % chk_message)

    result = _apply_update_state(
        update_state,
        update_reason=None,
        latest_version=latest_version,
        message=chk_message,
    )
    maybe_announce_release(
        update_state=result["update_state"],
        latest_version=result["latest_version"],
        current_version=result["release_version"],
    )
    return result


def update():

    if comicarr.INSTALL_TYPE == "win":
        logger.info("Windows .exe updating not supported yet.")
        pass

    elif comicarr.INSTALL_TYPE == "git":
        output = runGit("pull origin " + comicarr.CONFIG.GIT_BRANCH)

        if output is None:
            logger.error("Couldn't download latest version")
            return

        for line in output.split("\n"):
            if "Already up-to-date." in line:
                logger.info("No update available, not updating")
                logger.info("Output: " + str(output))
            elif line.endswith("Aborting."):
                logger.error("Unable to update from git: " + line)
                logger.info("Output: " + str(output))

    elif comicarr.INSTALL_TYPE == "docker":
        logger.info(
            "Docker updates via it's own mechanics. Updating docker via Comicarr GUI not supported at this time."
        )

    else:
        tar_download_url = "https://github.com/%s/comicarr/tarball/%s" % (
            comicarr.CONFIG.GIT_USER,
            comicarr.CONFIG.GIT_BRANCH,
        )
        update_dir = os.path.join(comicarr.PROG_DIR, "update")

        try:
            logger.info("Downloading update from: " + tar_download_url)
            response = requests.get(tar_download_url, verify=True, stream=True)
        except (IOError, urllib.error.URLError):
            logger.error("Unable to retrieve new version from " + tar_download_url + ", can't update")
            return

        download_name = comicarr.CONFIG.GIT_BRANCH + "-github"
        tar_download_path = os.path.join(comicarr.PROG_DIR, download_name)

        with open(tar_download_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=1024):
                if chunk:
                    f.write(chunk)
                    f.flush()

        logger.info("Extracting file" + tar_download_path)
        tar = tarfile.open(tar_download_path)
        tar.extractall(update_dir)
        tar.close()

        logger.info("Deleting file" + tar_download_path)
        os.remove(tar_download_path)

        update_dir_contents = [x for x in os.listdir(update_dir) if os.path.isdir(os.path.join(update_dir, x))]
        if len(update_dir_contents) != 1:
            logger.error("Invalid update data, update failed: " + str(update_dir_contents))
            return
        content_dir = os.path.join(update_dir, update_dir_contents[0])

        for dirname, _dirnames, filenames in os.walk(content_dir):
            dirname = dirname[len(content_dir) + 1 :]
            for curfile in filenames:
                old_path = os.path.join(content_dir, dirname, curfile)
                new_path = os.path.join(comicarr.PROG_DIR, dirname, curfile)

                if os.path.isfile(new_path):
                    os.remove(new_path)
                os.renames(old_path, new_path)


def versionload(cli_values=None, carepackage_call=False):
    if cli_values:
        pass_thru_vals = cli_values
    else:
        pass_thru_vals = {
            "git_branch": comicarr.CONFIG.GIT_BRANCH,
            "git_user": comicarr.CONFIG.GIT_USER,
            "git_token": comicarr.CONFIG.GIT_TOKEN,
            "check_github": comicarr.CONFIG.CHECK_GITHUB,
            "git_path": comicarr.CONFIG.GIT_PATH,
        }

    version_info = getVersion(pass_thru_vals)
    logger.fdebug("version_info: %s" % (version_info,))
    _set_version_state(
        current_version=version_info["current_version"],
        current_version_name=version_info["current_version_name"],
        current_release_name=version_info["current_release_name"],
        update_state=UPDATE_STATE_UNKNOWN,
        update_reason=REASON_NEVER_CHECKED,
    )

    if cli_values or carepackage_call is True:
        return {
            "current_branch": version_info["branch"],
            "current_version": version_info["current_version"],
            "current_version_name": version_info["current_version_name"],
            "current_release_name": version_info["current_release_name"],
            "install_type": comicarr.INSTALL_TYPE,
        }

    comicarr.CONFIG.GIT_BRANCH = version_info["branch"]
    _set_version_state(current_branch=version_info["branch"])

    if comicarr.CURRENT_VERSION is not None:
        hash = comicarr.CURRENT_VERSION[:7]
    else:
        hash = "unknown"

    if comicarr.CONFIG.GIT_BRANCH == "master":
        vers = "M"
    elif comicarr.CONFIG.GIT_BRANCH == "python3-dev":
        vers = "D"
    else:
        vers = "NONE"

    comicarr.USER_AGENT = "Comicarr/" + str(hash) + "(" + vers + ") +https://github.com/frankieramirez/comicarr/"

    logger.info("Version information: %s [%s]" % (comicarr.CONFIG.GIT_BRANCH, comicarr.CURRENT_VERSION))

    if comicarr.CONFIG.CHECK_GITHUB:
        stmt = select(jobhistory.c.prev_run_timestamp).where(jobhistory.c.JobName == "Check Version")
        with db.get_engine().connect() as conn:
            chk_last = conn.execute(stmt).mappings().fetchone()
        prev_run = False
        if chk_last:
            if chk_last["prev_run_timestamp"] is not None:
                rd = datetime.datetime.utcfromtimestamp(chk_last["prev_run_timestamp"])
                rd_mins = rd + datetime.timedelta(seconds=900)
                rd_now = datetime.datetime.utcfromtimestamp(time.time())
                if calendar.timegm(rd_mins.utctimetuple()) > calendar.timegm(rd_now.utctimetuple()):
                    prev_run = True
                    logger.info("[CHECK_GITHUB] Version check ran  < 15 minutes ago. Not running.")

        if prev_run is False:
            try:
                ac = comicarr.versioncheckit.CheckVersion()
                ac.run(scheduled_job=False)
            except Exception as e:
                logger.warn("[CHECK_GITHUB] Startup release check failed: %s" % e)
