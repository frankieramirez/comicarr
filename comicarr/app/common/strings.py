#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""
String utilities extracted from helpers.py.

Pure functions — no comicarr imports, no side effects.
"""

import logging
import platform
import re
import unicodedata

# Latin character transliteration map (from couch potato)
_LATIN_XLATE = {
    0xC0: "A",
    0xC1: "A",
    0xC2: "A",
    0xC3: "A",
    0xC4: "A",
    0xC5: "A",
    0xC6: "Ae",
    0xC7: "C",
    0xC8: "E",
    0xC9: "E",
    0xCA: "E",
    0xCB: "E",
    0x86: "e",
    0xCC: "I",
    0xCD: "I",
    0xCE: "I",
    0xCF: "I",
    0xD0: "Th",
    0xD1: "N",
    0xD2: "O",
    0xD3: "O",
    0xD4: "O",
    0xD5: "O",
    0xD6: "O",
    0xD8: "O",
    0xD9: "U",
    0xDA: "U",
    0xDB: "U",
    0xDC: "U",
    0xDD: "Y",
    0xDE: "th",
    0xDF: "ss",
    0xE0: "a",
    0xE1: "a",
    0xE2: "a",
    0xE3: "a",
    0xE4: "a",
    0xE5: "a",
    0xE6: "ae",
    0xE7: "c",
    0xE8: "e",
    0xE9: "e",
    0xEA: "e",
    0xEB: "e",
    0x0259: "e",
    0xEC: "i",
    0xED: "i",
    0xEE: "i",
    0xEF: "i",
    0xF0: "th",
    0xF1: "n",
    0xF2: "o",
    0xF3: "o",
    0xF4: "o",
    0xF5: "o",
    0xF6: "o",
    0xF8: "o",
    0xF9: "u",
    0xFA: "u",
    0xFB: "u",
    0xFC: "u",
    0xFD: "y",
    0xFE: "th",
    0xFF: "y",
    0xA1: "!",
    0xA2: "{cent}",
    0xA3: "{pound}",
    0xA4: "{currency}",
    0xA5: "{yen}",
    0xA6: "|",
    0xA7: "{section}",
    0xA8: "{umlaut}",
    0xA9: "{C}",
    0xAA: "{^a}",
    0xAB: "<<",
    0xAC: "{not}",
    0xAD: "-",
    0xAE: "{R}",
    0xAF: "_",
    0xB0: "{degrees}",
    0xB1: "{+/-}",
    0xB2: "{^2}",
    0xB3: "{^3}",
    0xB4: "'",
    0xB5: "{micro}",
    0xB6: "{paragraph}",
    0xB7: "*",
    0xB8: "{cedilla}",
    0xB9: "{^1}",
    0xBA: "{^o}",
    0xBB: ">>",
    0xBC: "{1/4}",
    0xBD: "{1/2}",
    0xBE: "{3/4}",
    0xBF: "?",
    0xD7: "*",
    0xF7: "/",
}


def latinToAscii(unicrap):
    """Transliterate latin characters to ASCII equivalents."""
    r = ""
    for i in unicrap:
        if ord(i) in _LATIN_XLATE:
            r += _LATIN_XLATE[ord(i)]
        elif ord(i) >= 0x80:
            pass
        else:
            r += str(i)
    return r


def cleanName(string):
    """Lowercase and strip special characters for fuzzy matching."""
    pass1 = latinToAscii(string).lower()
    return re.sub('[\\/\\@\\#\\$\\%\\^\\*\\+"\\[\\]\\{\\}\\<\\>\\=\\_]', " ", pass1)


def filesafe(comic):
    """Make a comic name safe for use as a filename."""
    if "\u2014" in comic:
        comic = re.sub("\u2014", " - ", comic)
    try:
        u_comic = unicodedata.normalize("NFKD", comic).encode("ASCII", "ignore").strip()
    except TypeError:
        u_comic = comic.encode("ASCII", "ignore").strip()

    if type(u_comic) != bytes:
        comicname_filesafe = re.sub("[\\:'\"\\,\\?\\!\\\\]", "", u_comic)
        comicname_filesafe = re.sub(r"[\/\*]", "-", comicname_filesafe)
    else:
        comicname_filesafe = re.sub("[\\:'\"\\,\\?\\!\\\\]", "", u_comic.decode("utf-8"))
        comicname_filesafe = re.sub(r"[\/\*]", "-", comicname_filesafe)

    return comicname_filesafe


def replace_all(text, dic):
    """Replace all occurrences of keys in dic with their values."""
    for i, j in dic.items():
        if all([j != "None", j is not None]):
            text = text.replace(i, j)
    return text.rstrip()


def cleanTitle(title):
    """Normalize title replacing dots/dashes/slashes with spaces and title-case."""
    title = re.sub(r"[\.\-\/\_]", " ", title).lower()
    # Strip out extra whitespace
    title = " ".join(title.split())
    title = title.title()
    return title


def cleanhtml(raw_html):
    """Strip HTML tags, keeping only valid paragraph/div content."""
    from bs4 import BeautifulSoup

    VALID_TAGS = ["div", "p"]

    soup = BeautifulSoup(raw_html, "html.parser")

    for tag in soup.findAll("p"):
        if tag.name not in VALID_TAGS:
            tag.replaceWith(tag.renderContents())
    flipflop = soup.renderContents()
    print(flipflop)
    return flipflop


def replacetheslash(data):
    """Replace backslashes with forward slashes on Windows for web display."""
    if platform.system() == "Windows":
        slashreplaced = data.replace("\\", "/")
    else:
        slashreplaced = data
    return slashreplaced


def clean_url(url):
    """Remove leading/trailing whitespace from a URL string."""
    leading = len(url) - len(url.lstrip(" "))
    ending = len(url) - len(url.rstrip(" "))
    if leading >= 1:
        url = url[leading:]
    if ending >= 1:
        url = url[:-ending]
    return url


def cleanHost(host, protocol=True, ssl=False, username=None, password=None):
    """Return a cleaned up host with given url options set.

    Taken verbatim from CouchPotato.
    Changes protocol to https if ssl is set to True and http if ssl is set to false.
    >>> cleanHost("localhost:80", ssl=True)
    'https://localhost:80/'
    >>> cleanHost("localhost:80", ssl=False)
    'http://localhost:80/'

    Username and password is managed with the username and password variables
    >>> cleanHost("localhost:80", username="user", password="passwd")
    'http://user:passwd@localhost:80/'

    Output without scheme (protocol) can be forced with protocol=False
    >>> cleanHost("localhost:80", protocol=False)
    'localhost:80'
    """
    log = logging.getLogger("comicarr")

    if "://" not in host and protocol:
        host = ("https://" if ssl else "http://") + host

    if not protocol:
        host = host.split("://", 1)[-1]

    if protocol and username and password:
        try:
            auth = re.findall("^(?:.+?//)(.+?):(.+?)@(?:.+)$", host)
            if auth:
                log.error("Cleanhost error: auth already defined in url: %s, please remove BasicAuth from url.", host)
            else:
                host = host.replace("://", "://%s:%s@" % (username, password), 1)
        except:
            pass

    host = host.rstrip("/ ")
    if protocol:
        host += "/"

    return host
