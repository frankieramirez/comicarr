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

from urllib3.util import ssl_ as urllib3_ssl

from comicarr.cfscrape_compat import URLLIB3_1X_DEFAULT_CIPHERS, ensure_default_ciphers_for_cfscrape


def test_ensure_default_ciphers_for_cfscrape_restores_removed_urllib3_symbol(monkeypatch):
    monkeypatch.delattr(urllib3_ssl, "DEFAULT_CIPHERS", raising=False)

    ensure_default_ciphers_for_cfscrape()

    assert urllib3_ssl.DEFAULT_CIPHERS == URLLIB3_1X_DEFAULT_CIPHERS
