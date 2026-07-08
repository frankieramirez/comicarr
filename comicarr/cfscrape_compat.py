#  Copyright (C) 2025–2026 Comicarr contributors
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

"""Compatibility helpers for importing legacy cfscrape on urllib3 2.x."""

URLLIB3_1X_DEFAULT_CIPHERS = ":".join(
    [
        "ECDHE+AESGCM",
        "ECDHE+CHACHA20",
        "DHE+AESGCM",
        "DHE+CHACHA20",
        "ECDH+AESGCM",
        "DH+AESGCM",
        "ECDH+AES",
        "DH+AES",
        "RSA+AESGCM",
        "RSA+AES",
        "!aNULL",
        "!eNULL",
        "!MD5",
        "!DSS",
    ]
)


def ensure_default_ciphers_for_cfscrape():
    """Restore the urllib3 symbol cfscrape imports on urllib3 1.x."""
    from urllib3.util import ssl_ as urllib3_ssl

    if not hasattr(urllib3_ssl, "DEFAULT_CIPHERS"):
        urllib3_ssl.DEFAULT_CIPHERS = URLLIB3_1X_DEFAULT_CIPHERS


def import_cfscrape():
    """Import cfscrape after applying urllib3 2.x compatibility."""
    ensure_default_ciphers_for_cfscrape()

    import cfscrape

    return cfscrape
