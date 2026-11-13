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
#
#  You should have received a copy of the GNU General Public License
#  along with Comicarr.  If not, see <http://www.gnu.org/licenses/>.

"""A minimal NNTP server for recording real download-client responses.

SABnzbd and NZBGet only produce a completed or failed history entry after a
real download. This server lets a recording run finish one without Usenet: it
serves single-part yEnc articles from memory and answers ``430`` for any
other message id, which the clients report as missing articles.

Used by the recorders in ``tests/fakes/``, never by the test suite itself.
"""

from __future__ import annotations

import socketserver
import threading
import time
import zlib
from xml.sax.saxutils import escape

_LINE = 128


def _escape_line(line: bytearray) -> bytearray:
    if line and line[-1] in (9, 32):
        last = line.pop()
        line += b"=" + bytes([(last + 64) % 256])
    return line


def yenc_article(data: bytes, name: str) -> bytes:
    """Encode ``data`` as a dot-stuffed, single-part yEnc article body."""
    out = bytearray()
    line = bytearray()
    for byte in data:
        encoded = (byte + 42) % 256
        critical = encoded in (0, 10, 13, 61) or (not line and encoded in (9, 32, 46))
        if critical:
            line += b"=" + bytes([(encoded + 64) % 256])
        else:
            line.append(encoded)
        if len(line) >= _LINE:
            out += _escape_line(line) + b"\r\n"
            line = bytearray()
    if line:
        out += _escape_line(line) + b"\r\n"
    crc = "%08x" % (zlib.crc32(data) & 0xFFFFFFFF)
    head = "=ybegin part=1 total=1 line=%d size=%d name=%s\r\n=ypart begin=1 end=%d\r\n" % (
        _LINE,
        len(data),
        name,
        len(data),
    )
    tail = "=yend size=%d part=1 pcrc32=%s crc32=%s" % (len(data), crc, crc)
    body = head.encode() + bytes(out) + tail.encode()
    return b"\r\n".join(b"." + ln if ln.startswith(b".") else ln for ln in body.split(b"\r\n"))


class _Handler(socketserver.StreamRequestHandler):
    def _send(self, text: str) -> None:
        self.wfile.write(text.encode() + b"\r\n")

    def handle(self) -> None:
        articles = self.server.articles
        self._send("200 recording server ready")
        for raw in self.rfile:
            command = raw.decode(errors="replace").strip()
            word = command.split(" ")[0].upper() if command else ""
            argument = command[len(word) :].strip()
            if word == "QUIT":
                self._send("205 bye")
                return
            if word == "CAPABILITIES":
                self.wfile.write(b"101 Capability list:\r\nVERSION 2\r\nREADER\r\nAUTHINFO USER\r\n.\r\n")
            elif word == "MODE":
                self._send("200 reader")
            elif word == "AUTHINFO":
                self._send("381 password required" if argument.upper().startswith("USER") else "281 ok")
            elif word == "GROUP":
                self._send("211 1 1 1 %s" % argument)
            elif word == "DATE":
                self._send("111 %s" % time.strftime("%Y%m%d%H%M%S", time.gmtime()))
            elif word in ("BODY", "ARTICLE", "HEAD", "STAT"):
                message_id = argument.strip("<>")
                if message_id not in articles:
                    self._send("430 no such article")
                    continue
                if self.server.delay:
                    time.sleep(self.server.delay)
                if word == "STAT":
                    self._send("223 0 <%s>" % message_id)
                    continue
                self._send("%d 0 <%s>" % ({"BODY": 222, "ARTICLE": 220, "HEAD": 221}[word], message_id))
                if word in ("ARTICLE", "HEAD"):
                    self.wfile.write(
                        b"Message-ID: <%s>\r\nSubject: recording\r\nFrom: rec@example.invalid\r\n"
                        b"Newsgroups: alt.binaries.test\r\n" % message_id.encode()
                    )
                    if word == "ARTICLE":
                        self.wfile.write(b"\r\n")
                if word != "HEAD":
                    self.wfile.write(articles[message_id] + b"\r\n")
                self.wfile.write(b".\r\n")
            else:
                self._send("500 unknown command")


class RecordingNNTPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, port: int, delay: float = 0.0):
        super().__init__(("0.0.0.0", port), _Handler)
        self.articles: dict[str, bytes] = {}
        self.delay = delay
        threading.Thread(target=self.serve_forever, daemon=True).start()

    def add(self, message_id: str, data: bytes, name: str) -> int:
        """Serve ``data`` as article ``message_id``; return its encoded size."""
        self.articles[message_id] = yenc_article(data, name)
        return len(self.articles[message_id])


def nzb_document(files: list[tuple[str, str, int]]) -> bytes:
    """Build an NZB for ``(filename, message id, segment bytes)`` entries."""
    parts = ['<?xml version="1.0" encoding="utf-8"?>', '<nzb xmlns="http://www.newzbin.com/DTD/2003/nzb">']
    for name, message_id, size in files:
        parts.append(
            '<file poster="rec@example.invalid" date="1763000000" subject="&quot;%s&quot; yEnc (1/1)">'
            "<groups><group>alt.binaries.test</group></groups>"
            '<segments><segment bytes="%d" number="1">%s</segment></segments></file>'
            % (escape(name), size, escape(message_id))
        )
    parts.append("</nzb>")
    return ("\n".join(parts) + "\n").encode()
