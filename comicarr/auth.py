#!/usr/bin/env python
# -*- encoding: UTF-8 -*-
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
#
######
# Form based authentication for CherryPy. Requires the
# Session tool to be loaded.
###### from cherrypy/tools on github

import hmac
import threading
import time
import urllib.error
import urllib.parse

# from datetime import datetime, timedelta
import urllib.request
from collections import defaultdict

import cherrypy

import comicarr
from comicarr import encrypted, logger

SESSION_KEY = "_cp_username"


class LoginRateLimiter(object):
    def __init__(self, max_attempts=5, lockout_seconds=300):
        self._attempts = defaultdict(list)
        self._lock = threading.Lock()
        self.max_attempts = max_attempts
        self.lockout_seconds = lockout_seconds

    def is_locked_out(self, ip):
        with self._lock:
            now = time.monotonic()
            cutoff = now - self.lockout_seconds
            recent = [t for t in self._attempts[ip] if t > cutoff]
            if recent:
                self._attempts[ip] = recent
            else:
                self._attempts.pop(ip, None)
            return len(recent) >= self.max_attempts

    def record_failure(self, ip):
        with self._lock:
            self._attempts[ip].append(time.monotonic())

    def record_success(self, ip):
        with self._lock:
            self._attempts.pop(ip, None)


# Module-level rate limiter instance shared across all login endpoints
_rate_limiter = LoginRateLimiter()


def check_credentials(username, password):
    """Verifies credentials for username and password.
    Returns None on success or a string describing the error on failure"""
    # Check rate limit BEFORE any password verification (prevents CPU waste from bcrypt)
    ip = cherrypy.request.remote.ip
    if _rate_limiter.is_locked_out(ip):
        logger.info("[AUTH] Login attempt blocked (rate limited) from IP: %s" % ip)
        return "Incorrect username or password."

    forms_user = cherrypy.request.config["auth.forms_username"]
    forms_pass = cherrypy.request.config["auth.forms_password"]

    if username != forms_user:
        _rate_limiter.record_failure(ip)
        return "Incorrect username or password."

    # Three-state password verification:
    # 1. $2b$/$2a$ prefix → bcrypt hash, verify with bcrypt.checkpw()
    # 2. ^~$z$ prefix → legacy base64, decode and compare, then re-hash
    # 3. No prefix → plaintext, compare directly, then hash
    if forms_pass and (forms_pass.startswith("$2b$") or forms_pass.startswith("$2a$")):
        if encrypted.verify_password(password, forms_pass):
            _rate_limiter.record_success(ip)
            return None
        else:
            _rate_limiter.record_failure(ip)
            return "Incorrect username or password."
    elif forms_pass and forms_pass.startswith("^~$z$"):
        edc = encrypted.Encryptor(forms_pass, logon=True)
        ed_chk = edc.decrypt_it()
        if ed_chk["status"] is True and ed_chk["password"] == password:
            # Migrate to bcrypt on successful login
            new_hash = encrypted.hash_password(password)
            comicarr.CONFIG.process_kwargs({"http_password": new_hash})
            comicarr.CONFIG.writeconfig()
            logger.info("[AUTH] Password migrated from base64 to bcrypt")
            _rate_limiter.record_success(ip)
            return None
        else:
            _rate_limiter.record_failure(ip)
            return "Incorrect username or password."
    else:
        # Plaintext password
        if password == forms_pass:
            # Migrate to bcrypt on successful login
            new_hash = encrypted.hash_password(password)
            comicarr.CONFIG.process_kwargs({"http_password": new_hash})
            comicarr.CONFIG.writeconfig()
            logger.info("[AUTH] Password migrated from plaintext to bcrypt")
            _rate_limiter.record_success(ip)
            return None
        else:
            _rate_limiter.record_failure(ip)
            return "Incorrect username or password."


def check_auth(*args, **kwargs):
    """A tool that looks in config for 'auth.require'. If found and it
    is not None, a login is required and the entry is evaluated as a list of
    conditions that the user must fulfill"""
    conditions = cherrypy.request.config.get("auth.require", None)
    get_params = urllib.parse.quote(cherrypy.request.request_line.split()[1])
    if conditions is not None:
        username = cherrypy.session.get(SESSION_KEY)
        if username:
            cherrypy.request.login = username
            for condition in conditions:
                # A condition is just a callable that returns true or false
                if not condition():
                    raise cherrypy.HTTPRedirect(comicarr.CONFIG.HTTP_ROOT + "auth/login?from_page=%s" % get_params)
        else:
            raise cherrypy.HTTPRedirect(comicarr.CONFIG.HTTP_ROOT + "auth/login?from_page=%s" % get_params)


cherrypy.tools.auth = cherrypy.Tool("before_handler", check_auth)


def require(*conditions):
    """A decorator that appends conditions to the auth.require config
    variable."""

    def decorate(f):
        if not hasattr(f, "_cp_config"):
            f._cp_config = {}
        if "auth.require" not in f._cp_config:
            f._cp_config["auth.require"] = []
        f._cp_config["auth.require"].extend(conditions)
        return f

    return decorate


# Conditions are callables that return True
# if the user fulfills the conditions they define, False otherwise
#
# They can access the current username as cherrypy.request.login
#
# Define those at will however suits the application.


def member_of(groupname):
    def check():
        # replace with actual check if <username> is in <groupname>
        return cherrypy.request.login == "joe" and groupname == "admin"

    return check


def name_is(reqd_username):
    return lambda: reqd_username == cherrypy.request.login


# These might be handy


def any_of(*conditions):
    """Returns True if any of the conditions match"""

    def check():
        for c in conditions:
            if c():
                return True
        return False

    return check


# By default all conditions are required, but this might still be
# needed if you want to use it inside of an any_of(...) condition
def all_of(*conditions):
    """Returns True if all of the conditions match"""

    def check():
        for c in conditions:
            if not c():
                return False
        return True

    return check


# Controller to provide login and logout actions


class AuthController(object):
    def on_login(self, username):
        """Called on successful login"""
        logger.info("%s successfully logged on." % username)
        # not needed or used for Comicarr currently

    def on_logout(self, username):
        """Called on logout"""
        # not needed or used for Comicarr currently

    def get_loginform(self, username, msg="Enter login information", from_page="/"):
        """Serve the React SPA which handles login UI"""
        from comicarr.webserve import _serve_spa_index

        return _serve_spa_index()

    @cherrypy.expose
    def login(self, current_username=None, current_password=None, remember_me="0", from_page="/"):
        if current_username is None or current_password is None:
            return self.get_loginform("", from_page=from_page)

        error_msg = check_credentials(current_username, current_password)
        if error_msg:
            return self.get_loginform(current_username, error_msg, from_page)
        else:
            # if all([from_page != "/", from_page != "//"]):
            #    from_page = from_page
            # if comicarr.OS_DETECT == 'Windows':
            #    if comicarr.CONFIG.HTTP_ROOT != "//":
            #        from_page = re.sub(comicarr.CONFIG.HTTP_ROOT, '', from_page,1).strip()
            # else:
            #    #if comicarr.CONFIG.HTTP_ROOT != "/":
            #    from_page = re.sub(comicarr.CONFIG.HTTP_ROOT, '', from_page,1).strip()
            cherrypy.session.regenerate()
            cherrypy.session[SESSION_KEY] = cherrypy.request.login = current_username
            # expiry = datetime.now() + (timedelta(days=30) if remember_me == '1' else timedelta(minutes=60))
            # cherrypy.session[SESSION_KEY] = {'user':    cherrypy.request.login,
            #                                 'expiry':  expiry}
            self.on_login(current_username)
            # Validate from_page is a safe relative path to prevent open redirect
            redirect_to = comicarr.CONFIG.HTTP_ROOT
            if from_page:
                safe_page = from_page.strip()
                if (
                    safe_page.startswith("/")
                    and not safe_page.startswith("//")
                    and "://" not in safe_page
                    and "\\" not in safe_page
                ):
                    redirect_to = safe_page
            raise cherrypy.HTTPRedirect(redirect_to)

    @cherrypy.expose
    def logout(self, from_page="/"):
        sess = cherrypy.session
        username = sess.get(SESSION_KEY, None)
        sess[SESSION_KEY] = None
        if username:
            cherrypy.request.login = None
            self.on_logout(username)
        return self.get_loginform("", from_page=from_page)

    @cherrypy.expose
    @cherrypy.tools.json_out()
    def login_json(self, username=None, password=None):
        """JSON-based login endpoint for React frontend"""
        if username is None or password is None:
            return {"success": False, "error": "Missing username or password"}

        error_msg = check_credentials(username, password)
        if error_msg:
            return {"success": False, "error": error_msg}

        # Successful login - create session
        cherrypy.session.regenerate()
        cherrypy.session[SESSION_KEY] = cherrypy.request.login = username
        self.on_login(username)
        return {"success": True, "username": username}

    @cherrypy.expose
    @cherrypy.tools.json_out()
    def logout_json(self):
        """JSON-based logout endpoint for React frontend"""
        sess = cherrypy.session
        username = sess.get(SESSION_KEY, None)
        sess[SESSION_KEY] = None
        if username:
            cherrypy.request.login = None
            self.on_logout(username)
        return {"success": True}

    @cherrypy.expose
    @cherrypy.tools.json_out()
    def check_session(self):
        """Check if user has a valid session"""
        username = cherrypy.session.get(SESSION_KEY, None)
        if username:
            return {"success": True, "authenticated": True, "username": username}
        return {"success": True, "authenticated": False}

    @cherrypy.expose
    @cherrypy.tools.json_out()
    def check_setup(self):
        """Check if initial setup is needed (no credentials configured)."""
        needs_setup = not comicarr.CONFIG.HTTP_USERNAME or not comicarr.CONFIG.HTTP_PASSWORD
        return {"success": True, "needs_setup": needs_setup}

    _setup_lock = threading.Lock()

    @cherrypy.expose
    @cherrypy.tools.json_out()
    def setup(self, username=None, password=None, setup_token=None):
        """First-run credential setup. Only works if no auth is configured."""
        # Restrict to POST only to prevent CSRF via GET
        if cherrypy.request.method != "POST":
            cherrypy.response.status = 405
            return {"success": False, "error": "Method not allowed"}

        # Serialize setup attempts to prevent race condition
        with self._setup_lock:
            # Only allow setup if no credentials are configured
            if comicarr.CONFIG.HTTP_USERNAME and comicarr.CONFIG.HTTP_PASSWORD:
                return {"success": False, "error": "Credentials already configured"}

            # Require setup token when one is active (prevents LAN attacker from completing setup)
            if comicarr.SETUP_TOKEN is not None:
                if not setup_token or not hmac.compare_digest(setup_token, comicarr.SETUP_TOKEN):
                    return {"success": False, "error": "Invalid setup token. Check the server console log."}

            if not username or not password:
                return {"success": False, "error": "Username and password required"}

            if len(password) < 8:
                return {"success": False, "error": "Password must be at least 8 characters"}

            # Save credentials via process_kwargs (handles ConfigParser sync)
            comicarr.CONFIG.process_kwargs(
                {
                    "http_username": username,
                    "http_password": password,
                    "authentication": 2,  # Form-based auth
                }
            )
            comicarr.CONFIG.writeconfig()
            comicarr.CONFIG.configure(update=True, startup=False)

            logger.info("[AUTH-SETUP] Initial credentials configured for user: %s" % username)

            # Clear the setup token — setup is complete
            comicarr.SETUP_TOKEN = None

            # CherryPy sessions are configured at mount time based on whether auth
            # is set. A server restart is needed for login/sessions to work.
            comicarr.SIGNAL = "restart"

            return {"success": True, "username": username, "needs_restart": True}
