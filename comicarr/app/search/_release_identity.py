#  Copyright (C) 2026 Comicarr contributors
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

"""Provider-specific identity derivation for release candidates."""

import os
import pathlib
import re
import urllib.parse
from urllib.parse import unquote, urlparse

from comicarr import logger


def generate_id(nzbprov, link, comicname):
    """Return the provider identity used to identify a release candidate."""

    missing = object()
    nzbid = missing
    if type(nzbprov) != str:
        nzbprov = nzbprov["type"]
        logger.fdebug("nzbprov setting to : %s" % nzbprov)
    if nzbprov == "experimental":
        url_parts = urlparse(link)
        path_parts = url_parts[2].rpartition("/")
        nzbtempid = path_parts[0].rpartition("/")
        nzblen = len(nzbtempid)
        nzbid = nzbtempid[nzblen - 1]
    elif nzbprov == "32P":
        nzbid = link
    elif any([nzbprov == "WWT", nzbprov == "DEM"]):
        if "http" not in link and any([nzbprov == "WWT", nzbprov == "DEM"]):
            nzbid = link
        else:
            url_parts = urlparse(link)
            path_parts = url_parts[2].rpartition("/")
            nzbtempid = path_parts[2]
            nzbid = re.sub(".torrent", "", nzbtempid).rstrip()
    elif "newznab" in nzbprov:
        tmpid = urlparse(link)[4]
        if "searchresultid" in tmpid:
            nzbid = os.path.splitext(link)[0].rsplit("searchresultid=", 1)[1]
        elif tmpid == "" or tmpid is None:
            nzbid = os.path.splitext(link)[0].rsplit("/", 1)[1]
        else:
            nzbinfo = urllib.parse.parse_qs(link)
            nzbid = nzbinfo.get("id", None)
            if nzbid is not None:
                nzbid = "".join(nzbid)
        if nzbid is None:
            findend = tmpid.find("&")
            if findend == -1:
                findend = len(tmpid)
                nzbid = tmpid[findend + 1 :].strip()
            else:
                findend = tmpid.find("apikey=", findend)
                nzbid = tmpid[findend + 1 :].strip()
            if "&id" not in tmpid or nzbid == "":
                tmpid = urlparse(link)[2]
                nzbid = tmpid.rsplit("/", 1)[1]
    elif nzbprov == "torznab":
        idtmp = urlparse(link)[4]
        if idtmp == "":
            idtmp = pathlib.PurePosixPath(unquote(urlparse(link).path))
            for im in idtmp.parts:
                if all(
                    [
                        comicname.lower() not in im.lower(),
                        im != "/",
                        ".cbz" not in im.lower(),
                        ".cbr" not in im.lower(),
                    ]
                ):
                    nzbid = im
                    break
        else:
            idpos = idtmp.find("&")
            nzbid = re.sub("id=", "", idtmp[:idpos]).strip()
    if nzbid is missing:
        raise UnboundLocalError("cannot access local variable 'nzbid' where it is not associated with a value")
    return nzbid
