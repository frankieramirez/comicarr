# coding=utf8
import http.cookiejar as cookielib
import json
import re
from urllib.error import HTTPError
from urllib.parse import urlencode, urljoin
from urllib.request import HTTPBasicAuthHandler, HTTPCookieProcessor, Request, build_opener

from .upload import MultiPartForm

# Seconds to wait on any single WebUI call. The monitor polls this client from
# a single-threaded worker, so an unbounded request would stall monitoring for
# every download rather than failing one probe.
DEFAULT_TIMEOUT = 30

class UTorrentClient(object):

    def __init__(self, base_url, username, password):
        self.base_url = base_url
        self.username = username
        self.password = password
        self.opener = self._make_opener('uTorrent', base_url, username, password)
        self.token = self._get_token()
        #TODO refresh token, when necessary

    def _make_opener(self, realm, base_url, username, password):
        '''uTorrent API need HTTP Basic Auth and cookie support for token verify.'''

        auth_handler = HTTPBasicAuthHandler()
        auth_handler.add_password(realm=realm,
                                  uri=base_url,
                                  user=username,
                                  passwd=password)
        opener = build_opener(auth_handler)

        cookie_jar = cookielib.CookieJar()
        cookie_handler = HTTPCookieProcessor(cookie_jar)

        handlers = [auth_handler, cookie_handler]
        opener = build_opener(*handlers)
        return opener

    def _get_token(self):
        url = urljoin(self.base_url, "token.html")
        response = self.opener.open(url, timeout=DEFAULT_TIMEOUT)
        token_re = "<div id='token' style='display:none;'>([^<>]+)</div>"
        match = re.search(token_re, response.read().decode("utf-8"))
        return match.group(1)

       
    def list(self, **kwargs):
        params = [('list', '1')]
        params += list(kwargs.items())
        return self._action(params)

    def start(self, *hashes):
        params = [('action', 'start'),]
        for hash in hashes:
            params.append(('hash', hash))
        return self._action(params)
        
    def stop(self, *hashes):
        params = [('action', 'stop'),]
        for hash in hashes:
            params.append(('hash', hash))
        return self._action(params)
 
    def pause(self, *hashes):
        params = [('action', 'pause'),]
        for hash in hashes:
            params.append(('hash', hash))
        return self._action(params)
 
    def forcestart(self, *hashes):
        params = [('action', 'forcestart'),]
        for hash in hashes:
            params.append(('hash', hash))
        return self._action(params)
        
    def remove(self, *hashes):
        params = [('action', 'remove'),]
        for hash in hashes:
            params.append(('hash', hash))
        return self._action(params)
    
    def removedata(self, *hashes):
        params = [('action', 'removedata'),]
        for hash in hashes:
            params.append(('hash', hash))
        return self._action(params)
        
    def recheck(self, *hashes):
        params = [('action', 'recheck'),]
        for hash in hashes:
            params.append(('hash', hash))
        return self._action(params)
 
    def getfiles(self, hash):
        params = [('action', 'getfiles'), ('hash', hash)]
        return self._action(params)
 
    def getprops(self, hash):
        params = [('action', 'getprops'), ('hash', hash)]
        return self._action(params)
        
    def setprio(self, hash, priority, *files):
        params = [('action', 'setprio'), ('hash', hash), ('p', str(priority))]
        for file_index in files:
            params.append(('f', str(file_index)))

        return self._action(params)
        
    def addfile(self, filename, filepath=None, bytes=None):
        params = [('action', 'add-file')]

        form = MultiPartForm()
        if filepath is not None:
            with open(filepath, "rb") as file_handler:
                form.add_file("torrent_file", filename, file_handler)
        else:
            from io import BytesIO

            file_handler = BytesIO(bytes)
            form.add_file("torrent_file", filename, file_handler)

        return self._action(params, str(form), form.get_content_type())

    def _action(self, params, body=None, content_type=None):
        #about token, see https://github.com/bittorrent/webui/wiki/TokenSystem
        url = self.base_url + "?token=" + self.token + "&" + urlencode(params)
        request = Request(url)

        if body:
            body = body.encode("utf-8")
            request.data = body
            request.add_header("Content-length", len(body))
        if content_type:
            request.add_header("Content-type", content_type)

        try:
            response = self.opener.open(request, timeout=DEFAULT_TIMEOUT)
            return response.code, json.loads(response.read())
        except HTTPError:
            raise
        
