#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Read and write comic archive tags without ComicTagger (#1414).

Two tag styles are supported, the two Comicarr ever wrote:

* ``cr``: a ``ComicInfo.xml`` member, the ComicRack schema every reader uses;
* ``cbl``: ComicBookLover's JSON in the zip comment.

Tags are held in a ``Tags`` value: ComicInfo element names to text, plus a
credit list of ``(role, person)``. Both styles convert to and from it, so one
set of merge rules serves both. A ``.cbr`` is rewritten as a ``.cbz`` first,
because only a zip can carry either style.

Merging follows the rules Comicarr's tags have always had: values are laid
over what the archive already says, a ``None`` leaves a field alone, an empty
string removes it, and credits are added to the ones already there.
"""

from __future__ import annotations

import html
import json
import os
import re
import shutil
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field
from datetime import datetime

import rarfile

COMICINFO_MEMBER = "ComicInfo.xml"
CBL_KEY = "ComicBookInfo/1.0"
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".avif", ".jxl")

# ComicInfo elements in the order they are written. Anything else an archive
# already carries is kept, after these.
FIELD_ORDER = (
    "Title",
    "Series",
    "Number",
    "Count",
    "Volume",
    "AlternateSeries",
    "AlternateNumber",
    "StoryArc",
    "StoryArcNumber",
    "SeriesGroup",
    "AlternateCount",
    "Summary",
    "Notes",
    "Year",
    "Month",
    "Day",
)
CREDIT_ELEMENTS = ("Writer", "Penciller", "Inker", "Colorist", "Letterer", "CoverArtist", "Editor")
TRAILING_ORDER = (
    "Publisher",
    "Imprint",
    "Genre",
    "Web",
    "PageCount",
    "LanguageISO",
    "Format",
    "AgeRating",
    "BlackAndWhite",
    "Manga",
    "Characters",
    "Teams",
    "Locations",
    "ScanInformation",
)

# The ComicVine roles each ComicInfo credit element collects. "artist" fills
# both Penciller and Inker, as it always has.
CREDIT_ROLES = {
    "Writer": {"writer", "plotter", "scripter"},
    "Penciller": {"artist", "penciller", "penciler", "breakdowns"},
    "Inker": {"inker", "artist", "finishes"},
    "Colorist": {"colorist", "colourist", "colorer", "colourer"},
    "Letterer": {"letterer"},
    "CoverArtist": {"cover", "covers", "coverartist", "cover artist"},
    "Editor": {"editor"},
}

# ComicInfo element -> ComicBookLover key, for the fields both carry.
CBL_FIELDS = {
    "Series": "series",
    "Title": "title",
    "Publisher": "publisher",
    "Month": "publicationMonth",
    "Year": "publicationYear",
    "Number": "issue",
    "Count": "numberOfIssues",
    "Volume": "volume",
    "Genre": "genre",
    "LanguageISO": "language",
    "Summary": "comments",
}
CBL_NUMBERS = {"publicationMonth", "publicationYear", "numberOfIssues", "volume"}


class NotAComicArchive(Exception):
    """The file is neither a zip nor a rar holding at least one image."""


class CorruptArchive(Exception):
    """The archive opened but could not be read through."""


@dataclass
class Tags:
    fields: dict = field(default_factory=dict)
    credits: list = field(default_factory=list)
    # ComicInfo elements Comicarr does not manage, kept as they were.
    extra: list = field(default_factory=list)
    pages: ET.Element | None = None

    def overlay(self, values):
        """Lay ``values`` over these tags: None keeps, "" removes, anything else sets."""
        for name, value in values.items():
            if value is None:
                continue
            value = str(value)
            if value == "":
                self.fields.pop(name, None)
            else:
                self.fields[name] = value
        return self

    def add_credits(self, credits):
        """Add ``(role, person)`` credits that are not already present."""
        seen = {(role.lower(), person.lower()) for role, person in self.credits}
        for role, person in credits:
            role, person = role.strip(), person.strip()
            if not role or not person or (role.lower(), person.lower()) in seen:
                continue
            seen.add((role.lower(), person.lower()))
            self.credits.append((role, person))
        return self


# -- ComicInfo.xml ----------------------------------------------------------


def parse_comicinfo(data):
    """Tags from ComicInfo.xml bytes; empty tags when they do not parse."""
    tags = Tags()
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        return tags
    known = set(FIELD_ORDER) | set(TRAILING_ORDER)
    for element in root:
        name = element.tag
        text = (element.text or "").strip()
        if name in CREDIT_ELEMENTS:
            tags.add_credits((name, person) for person in text.split(","))
        elif name == "Pages":
            tags.pages = element
        elif name in known:
            if text:
                tags.fields[name] = text
        else:
            tags.extra.append(element)
    return tags


def _default_pages(page_count):
    pages = ET.Element("Pages")
    for index in range(page_count):
        page = ET.SubElement(pages, "Page", Image=str(index))
        if index == 0:
            page.set("Type", "FrontCover")
    return pages


def comicinfo_xml(tags, page_count=0):
    """ComicInfo.xml bytes for ``tags``; pages default to one entry per image."""
    root = ET.Element("ComicInfo")
    root.set("xmlns:xsd", "http://www.w3.org/2001/XMLSchema")
    root.set("xmlns:xsi", "http://www.w3.org/2001/XMLSchema-instance")

    def put(name):
        value = tags.fields.get(name)
        if value not in (None, ""):
            ET.SubElement(root, name).text = value

    for name in FIELD_ORDER:
        put(name)
    for element, roles in CREDIT_ELEMENTS_ROLES:
        people = []
        for role, person in tags.credits:
            name = person.replace(",", "")
            if role.lower() in roles and name not in people:
                people.append(name)
        if people:
            ET.SubElement(root, element).text = ", ".join(people)
    for name in TRAILING_ORDER:
        put(name)
    for element in tags.extra:
        root.append(element)
    pages = tags.pages if tags.pages is not None and len(tags.pages) else _default_pages(page_count)
    if len(pages):
        root.append(pages)
    ET.indent(root)
    return b'<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(root, encoding="utf-8")


# Each credit element with the lowercase roles it collects, including its own
# name so credits read back from ComicInfo land where they came from.
CREDIT_ELEMENTS_ROLES = tuple((name, CREDIT_ROLES[name] | {name.lower()}) for name in CREDIT_ELEMENTS)


# -- ComicBookLover ---------------------------------------------------------


def parse_cbl(comment):
    """Tags from a ComicBookLover zip comment; None when there is no CBL block."""
    try:
        block = json.loads(comment.decode("utf-8"))[CBL_KEY]
    except (ValueError, KeyError, TypeError, UnicodeDecodeError):
        return None
    tags = Tags()
    for element, key in CBL_FIELDS.items():
        value = block.get(key)
        if value not in (None, ""):
            tags.fields[element] = str(value)
    tags.add_credits((c.get("role", ""), c.get("person", "")) for c in block.get("credits") or [])
    return tags


def cbl_comment(tags, now=None):
    """The ComicBookLover zip comment for ``tags``."""
    block = {}
    for element, key in CBL_FIELDS.items():
        value = tags.fields.get(element)
        if value in (None, ""):
            continue
        if key in CBL_NUMBERS:
            try:
                value = int(value)
            except ValueError:
                continue
        block[key] = value
    block["credits"] = [{"person": person, "role": role} for role, person in tags.credits]
    payload = {
        "appID": "Comicarr",
        "lastModified": str(now or datetime.now()),
        CBL_KEY: block,
    }
    return json.dumps(payload).encode("utf-8")


# -- ComicVine --------------------------------------------------------------


def clean_description(text):
    """ComicVine's HTML description as plain text, without the covers table."""
    if not text:
        return ""
    text = text.replace("\n", "")
    text = re.sub(r"<table[^<]*?>.*?</table>", "", text, flags=re.S | re.I)
    text = text.replace("*List of covers and their creators:*", "")
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"</p>", "\n\n", text, flags=re.I)
    text = re.sub(r"<h4>", "*", text, flags=re.I)
    text = re.sub(r"</h4>", "*\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    text = text.replace("List of covers and their creators:", "")
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _names(entries):
    return ", ".join(e["name"] for e in entries or [] if e.get("name"))


def comicvine_values(issue, publisher=None, notes_format="Issue ID", now=None):
    """ComicInfo values and credits from a ComicVine ``issue`` record.

    Returns ``(values, credits)`` ready for ``Tags.overlay`` and
    ``Tags.add_credits``. The Notes line keeps the ``[Issue ID n]`` or
    ``[CVDBn]`` marker other library tools read the ComicVine id from.
    """
    year = month = day = None
    cover = issue.get("cover_date") or ""
    parts = cover.split("-")
    if len(parts) >= 1 and parts[0].isdigit():
        year = str(int(parts[0]))
    if len(parts) >= 2 and parts[1].isdigit():
        month = str(int(parts[1]))
    if len(parts) >= 3 and parts[2].isdigit():
        day = str(int(parts[2]))

    marker = "CVDB" if notes_format == "CVDB" else "Issue ID "
    stamp = (now or datetime.now()).strftime("%Y-%m-%d %H:%M:%S")
    values = {
        "Series": (issue.get("volume") or {}).get("name"),
        "Number": issue_number(issue.get("issue_number")),
        "Title": issue.get("name"),
        "Publisher": publisher,
        "Year": year,
        "Month": month,
        "Day": day,
        "Summary": clean_description(issue.get("description")),
        "Notes": "Tagged by Comicarr using info from Comic Vine on %s.  [%s%s]" % (stamp, marker, issue.get("id")),
        "Web": issue.get("site_detail_url"),
        "Characters": _names(issue.get("character_credits")),
        "Teams": _names(issue.get("team_credits")),
        "Locations": _names(issue.get("location_credits")),
    }
    arcs = _names(issue.get("story_arc_credits"))
    if arcs:
        values["StoryArc"] = arcs
    credits = []
    for person in issue.get("person_credits") or []:
        for role in (person.get("role") or "").split(","):
            if role.strip():
                credits.append((role.strip().title(), person.get("name") or ""))
    return values, credits


def issue_number(number):
    """ComicVine's issue number as ComicInfo writes it: "001" is "1", "1.0" stays."""
    if number is None:
        return None
    text = str(number).strip()
    if text.isdigit():
        return str(int(text))
    match = re.match(r"^0+(\d.*)$", text)
    return match.group(1) if match else text


# -- Archives ---------------------------------------------------------------


def archive_kind(path):
    """ "zip", "rar" or None, by content rather than extension."""
    if zipfile.is_zipfile(path):
        return "zip"
    try:
        if rarfile.is_rarfile(path):
            return "rar"
    except rarfile.Error:
        pass
    return None


def _is_image(name):
    return name.lower().endswith(IMAGE_EXTENSIONS) and not os.path.basename(name).startswith(".")


def page_count(path):
    with zipfile.ZipFile(path) as archive:
        return sum(1 for name in archive.namelist() if _is_image(name))


def rar_to_cbz(path):
    """Rewrite the rar at ``path`` as a .cbz beside it and return the new path.

    The rar is removed once the zip is complete. A read failure raises
    CorruptArchive and leaves the rar where it was.
    """
    target = os.path.splitext(path)[0] + ".cbz"
    partial = target + ".part"
    try:
        with rarfile.RarFile(path) as source, zipfile.ZipFile(partial, "w", zipfile.ZIP_DEFLATED) as dest:
            members = [m for m in source.infolist() if not m.is_dir()]
            if not any(_is_image(m.filename) for m in members):
                raise NotAComicArchive(path)
            for member in members:
                dest.writestr(member.filename, source.read(member))
    except (rarfile.Error, OSError, zipfile.BadZipFile) as e:
        if os.path.exists(partial):
            os.remove(partial)
        raise CorruptArchive(str(e)) from e
    except NotAComicArchive:
        if os.path.exists(partial):
            os.remove(partial)
        raise
    os.replace(partial, target)
    os.remove(path)
    return target


def read_tags(path):
    """``{"cr": Tags | None, "cbl": Tags | None}`` for the zip at ``path``."""
    with zipfile.ZipFile(path) as archive:
        cr = None
        for name in archive.namelist():
            if name.lower() == COMICINFO_MEMBER.lower():
                cr = parse_comicinfo(archive.read(name))
                break
        cbl = parse_cbl(archive.comment) if archive.comment else None
    return {"cr": cr, "cbl": cbl}


def check_archive(path):
    """Raise NotAComicArchive or CorruptArchive unless ``path`` is a readable comic zip."""
    try:
        with zipfile.ZipFile(path) as archive:
            if not any(_is_image(name) for name in archive.namelist()):
                raise NotAComicArchive(path)
            bad = archive.testzip()
    except zipfile.BadZipFile as e:
        raise NotAComicArchive(str(e)) from e
    if bad is not None:
        raise CorruptArchive("CRC check failed for %s" % bad)


def write_tags(path, comicinfo=None, comment=None):
    """Rewrite the zip at ``path`` with a new ComicInfo.xml and/or zip comment.

    ``None`` leaves that part as it was. The archive is rebuilt beside the
    original and swapped in only once it is complete.
    """
    directory = os.path.dirname(os.path.abspath(path))
    handle, partial = tempfile.mkstemp(prefix=".tagging-", suffix=".cbz", dir=directory)
    os.close(handle)
    try:
        with zipfile.ZipFile(path) as source, zipfile.ZipFile(partial, "w", zipfile.ZIP_DEFLATED) as dest:
            for member in source.infolist():
                if comicinfo is not None and member.filename.lower() == COMICINFO_MEMBER.lower():
                    continue
                with source.open(member) as src, dest.open(member, "w") as out:
                    shutil.copyfileobj(src, out)
            if comicinfo is not None:
                dest.writestr(COMICINFO_MEMBER, comicinfo)
            dest.comment = source.comment if comment is None else comment
        os.replace(partial, path)
    finally:
        if os.path.exists(partial):
            os.remove(partial)
