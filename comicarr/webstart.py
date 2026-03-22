# -*- coding: utf-8 -*-

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

import os
import sys

import cherrypy
import portend as portend

import comicarr
from comicarr import logger
from comicarr.api import REST
from comicarr.helpers import create_https_certificates
from comicarr.webserve import WebInterface

# Setup mode paths allowed before initial credentials are configured
_SETUP_ALLOWED_PATHS = ("/auth/setup", "/auth/check_setup", "/assets", "/favicon.ico")


def _check_setup_gate():
    """CherryPy tool: block all requests except setup-related paths when first-run setup is pending."""
    if comicarr.SETUP_TOKEN is None:
        return
    path = cherrypy.request.path_info
    for allowed in _SETUP_ALLOWED_PATHS:
        if path == allowed or path.startswith(allowed + "/"):
            return
    raise cherrypy.HTTPError(503, "Setup required. Please configure credentials via the setup page.")


cherrypy.tools.setup_gate = cherrypy.Tool("before_handler", _check_setup_gate, priority=10)


def _set_samesite_cookie():
    """CherryPy tool: add SameSite=Strict to session cookies (not natively supported in CherryPy 18.x)."""
    name = cherrypy.request.config.get("tools.sessions.name", "session_id")
    cookie = cherrypy.serving.response.cookie
    if name in cookie:
        cookie[name]["samesite"] = "Strict"


cherrypy.tools.samesite = cherrypy.Tool("before_finalize", _set_samesite_cookie, priority=60)


_CSRF_EXEMPT_PREFIXES = ("/api", "/auth/login", "/auth/login_json", "/auth/setup")


def _csrf_protect():
    """CherryPy tool: require X-Requested-With header on state-changing requests.
    Combined with SameSite=Strict cookies, this provides CSRF protection.
    Cross-origin requests with custom headers trigger CORS preflight, which is rejected.
    Exempt: /api (uses API key), /auth/login* (login form), /auth/setup (uses setup token)."""
    if cherrypy.request.method in ("POST", "PUT", "DELETE", "PATCH"):
        path = cherrypy.request.path_info
        for prefix in _CSRF_EXEMPT_PREFIXES:
            if path == prefix or path.startswith(prefix + "/"):
                return
        if cherrypy.request.headers.get("X-Requested-With") != "ComicarrFrontend":
            raise cherrypy.HTTPError(403, "CSRF validation failed")


cherrypy.tools.csrf = cherrypy.Tool("before_handler", _csrf_protect, priority=20)


def _make_bcrypt_checkpassword(user_pass_dict):
    """Create a checkpassword callable that handles bcrypt hashes for HTTP Basic Auth.
    CherryPy's built-in checkpassword_dict does plaintext comparison which breaks after
    bcrypt migration."""
    from comicarr import encrypted

    def checkpassword(realm, username, password):
        stored = user_pass_dict.get(username)
        if stored is None:
            return False
        if stored.startswith("$2b$") or stored.startswith("$2a$"):
            return encrypted.verify_password(password, stored)
        if stored.startswith("^~$z$"):
            edc = encrypted.Encryptor(stored, logon=True)
            ed_chk = edc.decrypt_it()
            return ed_chk["status"] is True and ed_chk["password"] == password
        return password == stored

    return checkpassword


def initialize(options):

    # HTTPS stuff stolen from sickbeard
    enable_https = options["enable_https"]
    https_cert = options["https_cert"]
    https_key = options["https_key"]
    https_chain = options["https_chain"]

    if enable_https:
        # If either the HTTPS certificate or key do not exist, try to make
        # self-signed ones.
        if not (https_cert and os.path.exists(https_cert)) or not (https_key and os.path.exists(https_key)):
            if not create_https_certificates(https_cert, https_key):
                logger.warn("Unable to create certificate and key. Disabling HTTPS")
                enable_https = False

        if not (os.path.exists(https_cert) and os.path.exists(https_key)):
            logger.warn("Disabled HTTPS because of missing certificate and key.")
            enable_https = False

    # Build Content-Security-Policy header
    csp = "; ".join(
        [
            "default-src 'self'",
            "script-src 'self'",
            "style-src 'self' 'unsafe-inline'",
            "img-src 'self' data: https://comicvine.gamespot.com",
            "font-src 'self'",
            "connect-src 'self'",
            "frame-ancestors 'none'",
            "base-uri 'self'",
            "form-action 'self'",
            "object-src 'none'",
        ]
    )

    options_dict = {
        "server.socket_port": options["http_port"],
        "server.socket_host": options["http_host"],
        "server.thread_pool": 15,
        "tools.encode.on": True,
        "tools.encode.encoding": "utf-8",
        "tools.encode.text_only": False,
        "tools.decode.on": True,
        "log.screen": options["cherrypy_logging"],
        "engine.autoreload.on": False,
        "tools.setup_gate.on": True,
        "tools.samesite.on": True,
        "tools.csrf.on": True,
        "tools.response_headers.on": True,
        "tools.response_headers.headers": [
            ("X-Content-Type-Options", "nosniff"),
            ("X-Frame-Options", "DENY"),
            ("Referrer-Policy", "strict-origin-when-cross-origin"),
            ("Permissions-Policy", "camera=(), microphone=(), geolocation=()"),
            ("Cross-Origin-Opener-Policy", "same-origin"),
            ("X-XSS-Protection", "0"),
            ("Content-Security-Policy-Report-Only", csp),
        ],
    }

    if enable_https:
        options_dict["server.ssl_certificate"] = https_cert
        options_dict["server.ssl_private_key"] = https_key
        if https_chain:
            options_dict["server.ssl_certificate_chain"] = https_chain
        protocol = "https"
    else:
        protocol = "http"

    logger.info(
        "Starting Comicarr on %s://%s:%d%s"
        % (protocol, options["http_host"], options["http_port"], options["http_root"])
    )
    cherrypy.config.update(options_dict)

    # Serve the new React frontend from frontend/dist/
    frontend_dist = os.path.join(comicarr.PROG_DIR, "frontend", "dist")

    conf = {
        "/": {
            "tools.staticdir.root": frontend_dist,
            "tools.staticdir.on": True,
            "tools.staticdir.dir": "",
            "tools.staticdir.index": "index.html",
            "tools.proxy.on": True,  # pay attention to X-Forwarded-Proto header
        },
        "/assets": {"tools.staticdir.on": True, "tools.staticdir.dir": "assets"},
        "/favicon.ico": {
            "tools.staticfile.on": True,
            "tools.staticfile.filename": os.path.join(frontend_dist, "favicon.ico"),
        },
        "/cache": {"tools.staticdir.on": True, "tools.staticdir.dir": comicarr.CONFIG.CACHE_DIR},
    }

    if options["http_password"] is not None:
        # userpassdict = dict(zip((options['http_username'].encode('utf-8'),), (options['http_password'].encode('utf-8'),)))
        # get_ha1= cherrypy.lib.auth_digest.get_ha1_dict_plain(userpassdict)
        if options["authentication"] == 2:
            # Set up a sessions based login page instead of using basic auth,
            # using the credentials set for basic auth. Attempting to browse to
            # a restricted page without a session token will result in a
            # redirect to the login page. A sucessful login should then redirect
            # to the originally requested page.
            #
            # Login sessions timeout after 43800 minutes (1 month) unless
            # changed in the config.
            # Note - the following command doesn't actually work, see update statement 2 lines down
            # cherrypy.tools.sessions.timeout = options['login_timeout']
            conf["/"].update(
                {
                    "tools.sessions.on": True,
                    "tools.sessions.httponly": True,
                    "tools.sessions.secure": enable_https,
                    "tools.auth.on": True,
                    "tools.sessions.timeout": options["login_timeout"],
                    "auth.forms_username": options["http_username"],
                    "auth.forms_password": options["http_password"],
                    # Set all pages to require authentication.
                    # You can also set auth requirements on a per-method basis by
                    # using the @require() decorator on the methods in webserve.py
                    "auth.require": [],
                }
            )
            # exempt api, login page, json auth endpoints and static assets from authentication requirements
            for i in (
                "/api",
                "/auth/login",
                "/auth/login_json",
                "/auth/logout_json",
                "/auth/check_session",
                "/auth/check_setup",
                "/auth/setup",
                "/assets",
                "/favicon.ico",
            ):
                if i in conf:
                    conf[i].update({"tools.auth.on": False})
                else:
                    conf[i] = {"tools.auth.on": False}
        elif options["authentication"] == 1:
            conf["/"].update(
                {
                    "tools.auth_basic.on": True,
                    "tools.auth_basic.realm": "Comicarr",
                    "tools.auth_basic.checkpassword": _make_bcrypt_checkpassword(
                        {options["http_username"]: options["http_password"]}
                    ),
                }
            )
            conf["/api"] = {"tools.auth_basic.on": False}

    rest_api = {
        "/": {
            "request.dispatch": cherrypy.dispatch.MethodDispatcher(),
            "tools.auth_basic.on": False,
            "tools.auth.on": False,
            "tools.rest_auth.on": True,
            "tools.response_headers.on": True,
            "tools.response_headers.headers": [("Content-Type", "application/json")],
        }
    }

    # Enable OPDS auth if explicitly configured OR if main auth is enabled
    opds_auth = options["opds_authentication"] or (
        options.get("authentication", 0) > 0 and options["http_password"] is not None
    )
    if opds_auth:
        user_list = {}
        if options.get("opds_username") and len(options["opds_username"]) > 0:
            user_list[options["opds_username"]] = options["opds_password"]
        if options["http_password"] is not None and options.get("http_username") != options.get("opds_username"):
            user_list[options["http_username"]] = options["http_password"]
        conf["/opds"] = {
            "tools.auth.on": False,
            "tools.auth_basic.on": True,
            "tools.auth_basic.realm": "Comicarr OPDS",
            "tools.auth_basic.checkpassword": _make_bcrypt_checkpassword(user_list),
        }
    else:
        conf["/opds"] = {"tools.auth_basic.on": False, "tools.auth.on": False}

    # Prevent time-outs
    # cherrypy.engine.timeout_monitor.unsubscribe()

    cherrypy.tree.mount(WebInterface(), str(options["http_root"]), config=conf)

    restroot = REST()
    restroot.comics = restroot.Comics()
    restroot.comic = restroot.Comic()
    restroot.watchlist = restroot.Watchlist()
    # restroot.issues = restroot.comic.Issues()
    # restroot.issue = restroot.comic.Issue()
    cherrypy.tree.mount(restroot, "/rest", config=rest_api)

    try:
        portend.Checker().assert_free(options["http_host"], options["http_port"])
        cherrypy.server.start()
    except Exception as e:
        logger.error("[ERROR] %s" % e)
        print("Failed to start on port: %i. Is something else running?" % (options["http_port"]))
        sys.exit(1)

    cherrypy.server.wait()
