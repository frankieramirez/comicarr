#-# -*- coding: utf-8 -*-
#  This file is part of Mylar.
#
#  Mylar is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  Mylar is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with Mylar.  If not, see <http://www.gnu.org/licenses/>.

import mylar
from mylar import db, mb, importer, search, process, versioncheck, logger, webserve, helpers, encrypted, series_metadata
import threading
import json
import cherrypy
import time
import random
import os
import re
import shutil
import queue
import urllib.request, urllib.error, urllib.parse
from PIL import Image
from . import cache
from operator import itemgetter
from cherrypy.lib.static import serve_file, serve_download
import datetime

cmd_list = ['getIndex', 'getComic', 'getUpcoming', 'getWanted', 'getHistory',
            'getLogs', 'getAPI', 'clearLogs','findComic', 'addComic', 'delComic',
            'pauseComic', 'resumeComic', 'refreshComic', 'addIssue', 'recheckFiles',
            'queueIssue', 'unqueueIssue', 'forceSearch', 'forceProcess', 'changeStatus',
            'getVersion', 'checkGithub','shutdown', 'restart', 'update', 'changeBookType',
            'getComicInfo', 'getIssueInfo', 'getArt', 'downloadIssue', 'regenerateCovers',
            'refreshSeriesjson', 'seriesjsonListing', 'checkGlobalMessages',
            'listProviders', 'changeProvider', 'addProvider', 'delProvider',
            'downloadNZB', 'getReadList', 'getStoryArc', 'addStoryArc', 'listAnnualSeries',
            'getConfig', 'setConfig', 'getSeriesImage',
            'findManga', 'addManga', 'getMangaInfo',
            'getImportPending', 'matchImport', 'ignoreImport', 'refreshImport', 'deleteImport',
            'bulkMetatag', 'getCalendar']

class Api(object):

    API_ERROR_CODE_DEFAULT = 460

    def __init__(self):
        self.apikey = None
        self.cmd = None
        self.id = None
        self.img = None
        self.file = None
        self.filename = None
        self.kwargs = None
        self.data = None
        self.callback = None
        self.apitype = None
        self.comicrn = False
        self.headers = "application/json"

    def _failureResponse(self, errorMessage, code = API_ERROR_CODE_DEFAULT):
        response = {
            'success': False,
            'error': {
                'code': code,
                'message': errorMessage
            }
        }
        cherrypy.response.headers['Content-Type'] = self.headers
        return json.dumps(response)

    def _eventStreamResponse(self, results):
        if results['status'] is not None:
            event_name = results.get('event', '')
            # Build payload dict from results, excluding the 'event' key
            payload = {k: str(v) for k, v in results.items() if k != 'event' and v is not None}

            if event_name:
                data = '\nevent: %s\ndata: %s\n\n' % (event_name, json.dumps(payload))
            else:
                data = '\ndata: %s\n\n' % json.dumps(payload)
        else:
            data = '\ndata: \n\n'
        cherrypy.response.headers['Content-Type'] = 'text/event-stream'
        cherrypy.response.headers['Cache-Control'] = 'no-cache'
        cherrypy.response.headers['Connection'] = 'keep-alive'
        return data

    def _successResponse(self, results):
        response = {
            'success': True,
            'data': results
        }
        cherrypy.response.headers['Content-Type'] = self.headers
        return json.dumps(response)

    def _resultsFromQuery(self, query):
        myDB = db.DBConnection()
        rows = myDB.select(query)

        results = []

        for row in rows:
            results.append(dict(list(zip(list(row.keys()), row))))

        return results

    def _paginatedResultsFromQuery(self, query, limit=None, offset=None, args=None):
        """
        Execute a query with optional pagination support.

        Returns:
            dict with 'results', 'total', 'limit', 'offset', 'has_more'
        """
        myDB = db.DBConnection()
        if args is None:
            args = []

        # Get total count first (for pagination metadata)
        # Extract the FROM clause to build a count query
        count_query = query
        if ' ORDER BY ' in count_query.upper():
            count_query = count_query[:count_query.upper().find(' ORDER BY ')]
        # Replace SELECT ... FROM with SELECT COUNT(*) FROM
        from_pos = count_query.upper().find(' FROM ')
        if from_pos != -1:
            count_query = 'SELECT COUNT(*)' + count_query[from_pos:]

        total_rows = myDB.select(count_query, args)
        total = total_rows[0][0] if total_rows else 0

        # Apply pagination to original query using parameterized queries
        paginated_query = query
        paginated_args = list(args)
        if limit is not None:
            paginated_query += ' LIMIT ?'
            paginated_args.append(int(limit))
            if offset is not None and int(offset) > 0:
                paginated_query += ' OFFSET ?'
                paginated_args.append(int(offset))

        rows = myDB.select(paginated_query, paginated_args)
        results = []
        for row in rows:
            results.append(dict(list(zip(list(row.keys()), row))))

        # Calculate if there are more results
        current_offset = int(offset) if offset else 0
        current_limit = int(limit) if limit else total
        has_more = (current_offset + len(results)) < total

        return {
            'results': results,
            'total': total,
            'limit': current_limit,
            'offset': current_offset,
            'has_more': has_more
        }

    def checkParams(self, *args, **kwargs):

        if 'cmd' not in kwargs:
            self.data = self._failureResponse('Missing parameter: cmd')
            return

        if 'apikey' not in kwargs and ('apikey' not in kwargs and kwargs['cmd'] != 'getAPI'):
            self.data = self._failureResponse('Missing API key')
            return
        elif kwargs['cmd'] == 'getAPI':
            self.apitype = 'normal'
        else:
            if not mylar.CONFIG.API_ENABLED:
                if kwargs['apikey'] != mylar.DOWNLOAD_APIKEY and kwargs['apikey'] != mylar.SSE_KEY:
                    self.data = self._failureResponse('API not enabled')
                    return

            if kwargs['apikey'] != mylar.CONFIG.API_KEY and all([kwargs['apikey'] != mylar.SSE_KEY, kwargs['apikey'] != mylar.DOWNLOAD_APIKEY, mylar.DOWNLOAD_APIKEY != None]):
                self.data = self._failureResponse('Incorrect API key')
                return
            else:
                if kwargs['apikey'] == mylar.CONFIG.API_KEY:
                    self.apitype = 'normal'
                elif kwargs['apikey'] == mylar.DOWNLOAD_APIKEY:
                    self.apitype = 'download'
                elif kwargs['apikey'] == mylar.SSE_KEY:
                    self.apitype = 'sse'
                self.apikey = kwargs.pop('apikey')

            if not([mylar.CONFIG.API_KEY, mylar.DOWNLOAD_APIKEY, mylar.SSE_KEY]):
                self.data = self._failureResponse('API key not generated')
                return

            if self.apitype:
                if self.apitype == 'normal' and len(mylar.CONFIG.API_KEY) != 32:
                    self.data = self._failureResponse('API key not generated correctly')
                    return
                if self.apitype == 'download' and len(mylar.DOWNLOAD_APIKEY) != 32:
                    self.data = self._failureResponse('Download API key not generated correctly')
                    return
                if self.apitype == 'sse' and len(mylar.SSE_KEY) != 32:
                    self.data = self._failureResponse('SSE-API key not generated correctly')
                    return

            else:
                self.data = self._failureResponse('API key not generated correctly')
                return

        if kwargs['cmd'] not in cmd_list:
            self.data = self._failureResponse('Unknown command: %s' % kwargs['cmd'])
            return

        # Enforce SSE key scope: SSE keys can only access checkGlobalMessages
        if self.apitype == 'sse' and kwargs['cmd'] != 'checkGlobalMessages':
            self.data = self._failureResponse('SSE key can only access checkGlobalMessages')
            return

        # Enforce download key scope: download keys can only access downloadIssue/downloadNZB
        if self.apitype == 'download' and kwargs['cmd'] not in ('downloadIssue', 'downloadNZB'):
            self.data = self._failureResponse('Download key can only access download commands')
            return

        self.cmd = kwargs.pop('cmd')
        self.kwargs = kwargs
        self.data = 'OK'

    def fetchData(self):

        if self.data == 'OK':
            if self.cmd != 'checkGlobalMessages':
                logger.fdebug('Received API command: ' + self.cmd)
            methodToCall = getattr(self, "_" + self.cmd)
            result = methodToCall(**self.kwargs)
            if 'callback' not in self.kwargs:
                if self.img:
                    return serve_file(path=self.img, content_type='image/jpeg')
                if self.file and self.filename:
                    return serve_download(path=self.file, name=self.filename)
                if isinstance(self.data, str):
                    return self.data
                else:
                    if self.comicrn is True:
                        return self.data
                    else:
                        cherrypy.response.headers['Content-Type'] = "application/json"
                        return json.dumps(self.data)
            else:
                self.callback = self.kwargs['callback']
                self.data = json.dumps(self.data)
                self.data = self.callback + '(' + self.data + ');'
                cherrypy.response.headers['Content-Type'] = "application/javascript"
                return self.data
        else:
            return self.data

    def _selectForComics(self):
        return 'SELECT \
            ComicID as ComicID,\
            ComicName as ComicName,\
            ComicImageURL as ComicImage,\
            Status as Status,\
            ComicPublisher as ComicPublisher,\
            ComicYear as ComicYear,\
            LatestIssue as LatestIssue,\
            Total as Total,\
            Have as Have,\
            DetailURL as DetailURL,\
            ContentType as ContentType\
        FROM comics'

    def _selectForIssues(self):
        return 'SELECT \
            IssueID as id,\
            IssueName as name,\
            ImageURL as imageURL,\
            Issue_Number as number,\
            ReleaseDate as releaseDate,\
            IssueDate as issueDate,\
            Status as status,\
            ComicName as comicName,\
            ChapterNumber as chapterNumber,\
            VolumeNumber as volumeNumber\
        FROM issues'

    def _selectForAnnuals(self):
        return 'SELECT \
            IssueID as id,\
            IssueName as name,\
            Issue_Number as number,\
            ReleaseDate as releaseDate,\
            IssueDate as issueDate,\
            Status as status,\
            ComicName as comicName\
        FROM annuals'

    def _selectForReadList(self):
        return 'SELECT \
            IssueID as id,\
            Issue_Number as number,\
            IssueDate as issueDate,\
            Status as status,\
            ComicName as comicName\
        FROM readlist'

    def _getAPI(self, **kwargs):
        if 'username' not in kwargs:
           self.data = self._failureResponse('Missing parameter: username & password MUST be enabled.')
           return
        else:
            username = kwargs['username']

        if 'password' not in kwargs:
           self.data = self._failureResponse('Missing parameter: username & password MUST be enabled.')
           return
        else:
            password = kwargs['password']

        if any([mylar.CONFIG.HTTP_USERNAME is None, mylar.CONFIG.HTTP_PASSWORD is None]):
            self.data = self._failureResponse('Unable to use this command - username & password MUST be enabled.')
            return

        ht_user = mylar.CONFIG.HTTP_USERNAME
        edc = encrypted.Encryptor(mylar.CONFIG.HTTP_PASSWORD)
        ed_chk = edc.decrypt_it()
        if mylar.CONFIG.ENCRYPT_PASSWORDS is True:
            if username == ht_user and all([ed_chk['status'] is True, ed_chk['password'] == password]):
                self.data = self._successResponse(
                    {'apikey': mylar.CONFIG.API_KEY, 'sse_key': mylar.SSE_KEY}
                )
            else:
                self.data = self._failureResponse('Incorrect username or password.')
        else:
            if username == ht_user and password == mylar.CONFIG.HTTP_PASSWORD:
                self.data = self._successResponse(
                    {'apikey': mylar.CONFIG.API_KEY, 'sse_key': mylar.SSE_KEY}
                )
            else:
                self.data = self._failureResponse('Incorrect username or password.')

    def _getIndex(self, **kwargs):
        # Support pagination via limit and offset parameters
        limit = kwargs.get('limit')
        offset = kwargs.get('offset', 0)

        query = '{select} ORDER BY ComicSortName COLLATE NOCASE'.format(
            select = self._selectForComics()
        )

        if limit is not None:
            # Return paginated results with metadata
            paginated = self._paginatedResultsFromQuery(query, limit=limit, offset=offset)
            self.data = self._successResponse({
                'comics': paginated['results'],
                'pagination': {
                    'total': paginated['total'],
                    'limit': paginated['limit'],
                    'offset': paginated['offset'],
                    'has_more': paginated['has_more']
                }
            })
        else:
            # Backwards compatible: return all results without pagination wrapper
            self.data = self._successResponse(
                self._resultsFromQuery(query)
            )

        return

    def _getReadList(self, **kwargs):

        readListQuery = '{select} ORDER BY IssueDate ASC'.format(
            select = self._selectForReadList()
        )

        self.data = self._successResponse(
            self._resultsFromQuery(readListQuery)
        )

        return

    def _getComic(self, **kwargs):

        if 'id' not in kwargs:
            self.data = self._failureResponse('Missing parameter: id')
            return
        else:
            self.id = kwargs['id']

        myDB = db.DBConnection()

        comicQuery = self._selectForComics() + ' WHERE ComicID=? ORDER BY ComicSortName COLLATE NOCASE'
        comic_rows = myDB.select(comicQuery, [self.id])
        comic = [dict(zip(row.keys(), row)) for row in comic_rows]

        issuesQuery = self._selectForIssues() + ' WHERE ComicID=? ORDER BY Int_IssueNumber DESC'
        issues_rows = myDB.select(issuesQuery, [self.id])
        issues = [dict(zip(row.keys(), row)) for row in issues_rows]

        if mylar.CONFIG.ANNUALS_ON:
            annualsQuery = self._selectForAnnuals() + ' WHERE ComicID=?'
            annuals_rows = myDB.select(annualsQuery, [self.id])
            annuals = [dict(zip(row.keys(), row)) for row in annuals_rows]
        else:
            annuals = []

        self.data = self._successResponse({
            'comic': comic,
            'issues': issues,
            'annuals': annuals
        })

        return

    def _getHistory(self, **kwargs):
        # Support pagination via limit and offset parameters
        limit = kwargs.get('limit')
        offset = kwargs.get('offset', 0)

        query = 'SELECT * from snatched order by DateAdded DESC'

        if limit is not None:
            # Return paginated results with metadata
            paginated = self._paginatedResultsFromQuery(query, limit=limit, offset=offset)
            self.data = self._successResponse({
                'history': paginated['results'],
                'pagination': {
                    'total': paginated['total'],
                    'limit': paginated['limit'],
                    'offset': paginated['offset'],
                    'has_more': paginated['has_more']
                }
            })
        else:
            # Backwards compatible: return all results without pagination wrapper
            self.data = self._successResponse(
                self._resultsFromQuery(query)
            )
        return

    def _getUpcoming(self, **kwargs):
        if 'include_downloaded_issues' in kwargs and kwargs['include_downloaded_issues'].upper() == 'Y':
            select_status_clause = "w.STATUS IN ('Wanted', 'Snatched', 'Downloaded')"
        else:
            select_status_clause = "w.STATUS = 'Wanted'"

        # Days in a new year that precede the first Sunday will look to the previous Sunday for week and year.
        today = datetime.date.today()
        if today.strftime('%U') == '00':
            weekday = 0 if today.isoweekday() == 7 else today.isoweekday()
            sunday = today - datetime.timedelta(days=weekday)
            week = sunday.strftime('%U')
            year = sunday.strftime('%Y')
        else:
            week = today.strftime('%U')
            year = today.strftime('%Y')

        myDB = db.DBConnection()
        upcoming_query = "SELECT w.COMIC AS ComicName, w.ISSUE AS IssueNumber, w.ComicID, w.IssueID, w.SHIPDATE AS IssueDate, w.STATUS AS Status, c.ComicName AS DisplayComicName \
            FROM weekly w JOIN comics c ON w.ComicID = c.ComicID WHERE w.COMIC IS NOT NULL AND w.ISSUE IS NOT NULL AND \
            SUBSTR('0' || w.weeknumber, -2) = ? AND w.year = ? AND " + select_status_clause + " ORDER BY c.ComicSortName"
        rows = myDB.select(upcoming_query, [week, year])
        self.data = [dict(zip(row.keys(), row)) for row in rows]
        return

    def _getCalendar(self, **kwargs):
        """
        Generate an iCal calendar feed for upcoming comic releases.

        Parameters:
            days: Number of days to include (default: CALENDAR_DEFAULT_DAYS config, max: 365)
            status: Filter by status - wanted, snatched, downloaded, all (default: wanted)
            include_annuals: Include annual issues - y/n (default: y if ANNUALS_ON)
            include_storyarcs: Include story arc issues - y/n (default: config setting)
        """
        # Parse parameters
        default_days = mylar.CONFIG.CALENDAR_DEFAULT_DAYS if mylar.CONFIG.CALENDAR_DEFAULT_DAYS else 90
        days = min(int(kwargs.get('days', default_days)), 365)
        status_filter = kwargs.get('status', 'wanted').lower()
        include_annuals = kwargs.get('include_annuals', 'y' if mylar.CONFIG.ANNUALS_ON else 'n').upper() == 'Y'
        include_storyarcs = kwargs.get('include_storyarcs', 'y' if mylar.CONFIG.UPCOMING_STORYARCS else 'n').upper() == 'Y'

        myDB = db.DBConnection()

        # Calculate date range
        today = datetime.date.today()
        end_date = today + datetime.timedelta(days=days)
        today_str = today.strftime('%Y-%m-%d')
        end_date_str = end_date.strftime('%Y-%m-%d')

        # Build status clause
        if status_filter == 'all':
            status_clause = "1=1"
        elif status_filter == 'snatched':
            status_clause = "b.Status = 'Snatched'"
        elif status_filter == 'downloaded':
            status_clause = "b.Status = 'Downloaded'"
        else:
            status_clause = "b.Status = 'Wanted'"

        events = []

        # Query main issues
        issues_query = """
            SELECT a.ComicName, a.ComicYear, a.ComicPublisher, b.Issue_Number,
                   b.IssueName, b.ReleaseDate, b.IssueDate, b.IssueID, b.ComicID, b.Status
            FROM comics a
            INNER JOIN issues b ON a.ComicID = b.ComicID
            WHERE %s
            AND b.ReleaseDate IS NOT NULL
            AND b.ReleaseDate != ''
            AND b.ReleaseDate >= ?
            AND b.ReleaseDate <= ?
            ORDER BY b.ReleaseDate
        """ % status_clause

        issues = myDB.select(issues_query, [today_str, end_date_str])
        for issue in issues:
            events.append({
                'comic_name': issue['ComicName'],
                'comic_year': issue['ComicYear'],
                'publisher': issue['ComicPublisher'],
                'issue_number': issue['Issue_Number'],
                'issue_name': issue['IssueName'],
                'release_date': issue['ReleaseDate'],
                'issue_id': issue['IssueID'],
                'comic_id': issue['ComicID'],
                'status': issue['Status'],
                'type': 'issue'
            })

        # Query annuals if enabled
        if include_annuals:
            annuals_query = """
                SELECT a.ComicName, a.ComicYear, a.ComicPublisher, b.Issue_Number,
                       b.IssueName, b.ReleaseDate, b.IssueDate, b.IssueID, b.ComicID,
                       b.ReleaseComicName, b.Status
                FROM comics a
                INNER JOIN annuals b ON a.ComicID = b.ComicID
                WHERE NOT b.Deleted
                AND %s
                AND b.ReleaseDate IS NOT NULL
                AND b.ReleaseDate != ''
                AND b.ReleaseDate >= ?
                AND b.ReleaseDate <= ?
                ORDER BY b.ReleaseDate
            """ % status_clause.replace('b.Status', 'b.Status')

            annuals = myDB.select(annuals_query, [today_str, end_date_str])
            for annual in annuals:
                events.append({
                    'comic_name': annual['ReleaseComicName'] or annual['ComicName'],
                    'comic_year': annual['ComicYear'],
                    'publisher': annual['ComicPublisher'],
                    'issue_number': annual['Issue_Number'],
                    'issue_name': annual['IssueName'],
                    'release_date': annual['ReleaseDate'],
                    'issue_id': annual['IssueID'],
                    'comic_id': annual['ComicID'],
                    'status': annual['Status'],
                    'type': 'annual'
                })

        # Query story arcs if enabled
        if include_storyarcs:
            storyarcs_query = """
                SELECT ComicName, IssueNumber, IssueName, ReleaseDate, IssueID,
                       ComicID, Storyarc, Status
                FROM storyarcs
                WHERE %s
                AND ReleaseDate IS NOT NULL
                AND ReleaseDate != ''
                AND ReleaseDate >= ?
                AND ReleaseDate <= ?
                ORDER BY ReleaseDate
            """ % status_clause.replace('b.Status', 'Status')

            storyarcs = myDB.select(storyarcs_query, [today_str, end_date_str])
            for arc in storyarcs:
                events.append({
                    'comic_name': arc['ComicName'],
                    'comic_year': None,
                    'publisher': None,
                    'issue_number': arc['IssueNumber'],
                    'issue_name': arc['IssueName'],
                    'release_date': arc['ReleaseDate'],
                    'issue_id': arc['IssueID'],
                    'comic_id': arc['ComicID'],
                    'status': arc['Status'],
                    'type': 'storyarc',
                    'storyarc': arc['Storyarc']
                })

        # Generate iCal output
        ical_lines = [
            'BEGIN:VCALENDAR',
            'VERSION:2.0',
            'PRODID:-//Comicarr//Comic Release Calendar//EN',
            'CALSCALE:GREGORIAN',
            'METHOD:PUBLISH',
            'X-WR-CALNAME:Comicarr Releases',
            'X-WR-TIMEZONE:UTC'
        ]

        for event in events:
            release_date = event['release_date']
            if not release_date:
                continue

            # Parse and format date (YYYYMMDD format for all-day events)
            try:
                dt = datetime.datetime.strptime(release_date, '%Y-%m-%d')
                dtstart = dt.strftime('%Y%m%d')
                dtend = (dt + datetime.timedelta(days=1)).strftime('%Y%m%d')
            except ValueError:
                continue

            # Build event summary
            issue_num = event['issue_number'] or '1'
            summary = '%s #%s' % (event['comic_name'], issue_num)
            if event['type'] == 'annual':
                summary = '%s (Annual)' % summary
            elif event['type'] == 'storyarc':
                summary = '%s [%s]' % (summary, event.get('storyarc', 'Story Arc'))

            # Build description
            desc_parts = []
            if event['issue_name']:
                desc_parts.append('Title: %s' % event['issue_name'])
            if event['publisher']:
                desc_parts.append('Publisher: %s' % event['publisher'])
            if event['comic_year']:
                desc_parts.append('Series Year: %s' % event['comic_year'])
            desc_parts.append('Status: %s' % event['status'])
            description = '\\n'.join(desc_parts)

            # Create unique ID
            uid = '%s-%s@comicarr' % (event['issue_id'], event['type'])

            # Escape special characters for iCal
            summary = summary.replace(',', '\\,').replace(';', '\\;')
            description = description.replace(',', '\\,').replace(';', '\\;')

            ical_lines.extend([
                'BEGIN:VEVENT',
                'DTSTART;VALUE=DATE:%s' % dtstart,
                'DTEND;VALUE=DATE:%s' % dtend,
                'SUMMARY:%s' % summary,
                'DESCRIPTION:%s' % description,
                'UID:%s' % uid,
                'STATUS:CONFIRMED',
                'TRANSP:TRANSPARENT',
                'END:VEVENT'
            ])

        ical_lines.append('END:VCALENDAR')

        # Set response headers for iCal
        cherrypy.response.headers['Content-Type'] = 'text/calendar; charset=utf-8'
        cherrypy.response.headers['Content-Disposition'] = 'attachment; filename="comicarr-releases.ics"'

        self.data = '\r\n'.join(ical_lines)
        return

    def _getWanted(self, **kwargs):
        # Support pagination via limit and offset parameters (applies to issues)
        limit = kwargs.get('limit')
        offset = kwargs.get('offset', 0)

        iss_query = "SELECT a.ComicName, a.ComicYear, a.ComicVersion, a.Type as BookType, a.ComicPublisher, a.publisherImprint, b.Issue_Number, b.IssueName, b.ReleaseDate, b.IssueDate, b.DigitalDate, b.Status, b.ComicID, b.IssueID, b.DateAdded from comics as a INNER JOIN issues as b ON a.ComicID = b.ComicID WHERE b.Status='Wanted'"

        if limit is not None:
            # Return paginated issues with metadata
            paginated = self._paginatedResultsFromQuery(iss_query, limit=limit, offset=offset)
            tmp_data = {
                'issues': paginated['results'],
                'pagination': {
                    'total': paginated['total'],
                    'limit': paginated['limit'],
                    'offset': paginated['offset'],
                    'has_more': paginated['has_more']
                }
            }
        else:
            # Backwards compatible: return all results
            issues = self._resultsFromQuery(iss_query)
            tmp_data = {'issues': issues}

        if 'story_arcs' in kwargs and kwargs['story_arcs'] == 'true':
            if mylar.CONFIG.UPCOMING_STORYARCS is True:
                arcs_query = "SELECT Storyarc, StoryArcID, IssueArcID, ComicName, IssueNumber, IssueName, ReleaseDate, IssueDate, DigitalDate, Status, ComicID, IssueID, DateAdded from storyarcs WHERE Status='Wanted'"
                arclist = self._resultsFromQuery(arcs_query)
                tmp_data2 = {**tmp_data, **{'story_arcs': arclist}}
                tmp_data = tmp_data2

        if mylar.CONFIG.ANNUALS_ON:
            annuals_query = "SELECT b.ReleaseComicName as ComicName, a.ComicYear, a.ComicVersion, a.Type as BookType, a.ComicPublisher, a.publisherImprint, a.ComicName as SeriesName, b.Issue_Number as Issue_Number, b.IssueName, b.ReleaseDate, b.IssueDate, b.DigitalDate, b.Status, b.ComicID, b.IssueID, b.ReleaseComicID as SeriesComicID, b.DateAdded FROM comics as a INNER JOIN annuals as b ON a.ComicID = b.ComicID WHERE NOT b.Deleted and b.Status='Wanted'"
            annuals_list = self._resultsFromQuery(annuals_query)
            tmp_data2 = {**tmp_data, **{'annuals': annuals_list}}
            tmp_data = tmp_data2

        self.data = tmp_data
        return

    def _getLogs(self, **kwargs):
        self.data = mylar.LOG_LIST
        return

    def _clearLogs(self, **kwargs):
        mylar.LOG_LIST = []
        self.data = 'Cleared log'
        return

    def _delComic(self, **kwargs):
        if 'id' not in kwargs:
            self.data = self._failureResponse('Missing parameter: id')
            return
        else:
            self.id = kwargs['id']
            if self.id.startswith('4050-'):
                self.id = re.sub('4050-', '', self.id).strip()

        directory_del = False
        if 'directory' in kwargs:
            directory_del = kwargs['directory']
            if all([directory_del != 'true', directory_del != 'false']):
               self.data = self._failureResponse('directory value incorrect (valid: true / false)')
               return

            if any([directory_del == 'False', directory_del == 'false']):
               directory_del = False
            elif any([directory_del == 'True', directory_del == 'true']):
               directory_del = True
            else:
               directory_del = False  #safeguard anything else here.

        try:
            myDB = db.DBConnection()
            delchk = myDB.selectone('SELECT ComicName, ComicYear, ComicLocation FROM comics where ComicID=?', [self.id]).fetchone()
            if not delchk:
                logger.error('ComicID %s not found in watchlist.' %  self.id)
                self.data = self._failureResponse('ComicID %s not found in watchlist.' % self.id)
                return
            logger.fdebug('Deletion request received for %s (%s) [%s]' % (delchk['ComicName'], delchk['ComicYear'], self.id))
            myDB.action('DELETE from comics WHERE ComicID=?', [self.id])
            myDB.action('DELETE from issues WHERE ComicID=?', [self.id])
            myDB.action('DELETE from upcoming WHERE ComicID=?', [self.id])
            if directory_del is True:
                if os.path.exists(delchk['ComicLocation']):
                    shutil.rmtree(delchk['ComicLocation'])
                    logger.fdebug('[API-delComic] Comic Location (%s) successfully deleted' % delchk['ComicLocation'])
                else:
                    logger.fdebug('[API-delComic] Comic Location (%s) does not exist - cannot delete' % delchk['ComicLocation'])

        except Exception as e:
            logger.error('Unable to delete ComicID: %s. Error returned: %s' % (self.id, e))
            self.data = self._failureResponse('Unable to delete ComicID: %s' % self.id)
        else:
            logger.fdebug('[API-delComic] Successfully deleted %s (%s) [%s]' % (delchk['ComicName'], delchk['ComicYear'], self.id))
            self.data = self._successResponse('Successfully deleted %s (%s) [%s]' % (delchk['ComicName'], delchk['ComicYear'], self.id))

    def _pauseComic(self, **kwargs):
        if 'id' not in kwargs:
            self.data = self._failureResponse('Missing parameter: id')
            return
        else:
            self.id = kwargs['id']

        myDB = db.DBConnection()
        controlValueDict = {'ComicID': self.id}
        newValueDict = {'Status': 'Paused'}
        myDB.upsert("comics", newValueDict, controlValueDict)

    def _resumeComic(self, **kwargs):
        if 'id' not in kwargs:
            self.data = self._failureResponse('Missing parameter: id')
            return
        else:
            self.id = kwargs['id']

        myDB = db.DBConnection()
        controlValueDict = {'ComicID': self.id}
        newValueDict = {'Status': 'Active'}
        myDB.upsert("comics", newValueDict, controlValueDict)

    def _regenerateCovers(self, **kwargs):
        # kwargs = id: {comicid, {comicid_list}, 'all', 'missing'}
        #               -- comicid = specific comicid
        #               -- comicid_list = list of comicids
        #               -- all = all series on watchlist
        #               -- missing = just series on watchlist with no cover image in cache
        #        = overwrite_existing: {true, false} (applies only to {comicid, comicid_list, all})

        myDB = db.DBConnection()
        if 'id' not in kwargs:
            self.data = self._failureResponse('Missing parameter: id')
            return
        else:
            self.id = kwargs['id']
            id_list = []
            if any([self.id == 'all', self.id == 'missing']):
                the_list = myDB.select('SELECT * FROM comics')
                for tt in the_list:
                    if self.id == 'missing':
                        if os.path.isfile(os.path.join(mylar.CONFIG.CACHE_DIR, '%s.jpg' % (tt['comicid']))):
                            continue
                    id_list.append({'comicid': tt['ComicID'],
                                    'comicimage': tt['ComicImage'],
                                    'comicimageurl': tt['ComicImageURL'],
                                    'comicimagealturl': tt['ComicImageALTURL'],
                                    'firstimagesize': tt['FirstImageSize']})
            else:
                tmp_list = []
                if ',' in self.id:
                    tmp_list = self.id.split(',')
                else:
                    tmp_list.append(self.id)

                for tm in tmp_list:
                    th = myDB.selectone('SELECT * FROM comics WHERE comicid=?', [tm]).fetchone()
                    id_list.append({'comicid': th['ComicID'],
                                    'comicimage': th['ComicImage'],
                                    'comicimageurl': th['ComicImageURL'],
                                    'comicimagealturl': th['ComicImageALTURL'],
                                    'firstimagesize': th['FirstImageSize']})

            threading.Thread(target=self.get_the_images, name="regenerateCovers", args=(id_list,)).start()
            logger.info('[API-regenerateCovers] Successfully background submitted cover regeneration for  %s series' % (len(id_list)))
            self.data = self._successResponse('RegenerateCovers successfully submitted for %s series.' % (len(id_list)))
            return

    def get_the_images(self, id_list):
        resultresponse = []
        success_count = 0
        failed_count = 0
        already_present = 0
        for idl in id_list:
            comicid = idl['comicid']
            firstimagesize = idl['firstimagesize']
            if firstimagesize is None:
                firstimagesize = 0
            cimage = os.path.join(mylar.CONFIG.CACHE_DIR, '%s.jpg' % (comicid))
            if mylar.CONFIG.ALTERNATE_LATEST_SERIES_COVERS is False or not os.path.isfile(cimage):
                PRComicImage = os.path.join('cache', str(comicid) + ".jpg")
                ComicImage = helpers.replacetheslash(PRComicImage)
                coversize = 0
                if os.path.isfile(cimage):
                    statinfo = os.stat(cimage)
                    coversize = statinfo.st_size
                if firstimagesize != 0 and (os.path.isfile(cimage) is True and firstimagesize == coversize):
                    logger.fdebug('[%s] Cover already exists for series. Not redownloading.' % comicid)
                    already_present +=1
                else:
                    covercheck = helpers.getImage(comicid, idl['comicimageurl'], apicall=True)
                    firstimagesize = covercheck['coversize']
                    if covercheck['status'] == 'retry':
                        logger.info('[%s] Attempting to retrieve alternate comic image for the series.' % comicid)
                        covercheck = helpers.getImage(comicid, idl['comicimagealturl'], apicall=True)
                    if covercheck['status'] == 'success':
                        success_count +=1
                    else:
                        failed_count +=1

            time.sleep(4)

        logger.info('[API-regenerateCovers] Completed: %s covers successfully regenerated, %s covers failed to generate, %s covers already existed.' % (success_count, failed_count, already_present))

    def _refreshComic(self, **kwargs):
        if 'id' not in kwargs:
            self.data = self._failureResponse('Missing parameter: id')
            return
        else:
            self.id = kwargs['id']
            id_list = []
            if ',' in self.id:
                id_list = self.id.split(',')

            else:
                id_list.append(self.id)

        watch = []
        already_added = []
        notfound = []
        myDB = db.DBConnection()
        for comicid in id_list:
            if comicid.startswith('4050-'):
                comicid = re.sub('4050-', '', comicid).strip()

            chkdb = myDB.selectone('SELECT ComicName, ComicYear FROM comics WHERE ComicID=?', [comicid]).fetchone()
            if not chkdb:
                notfound.append({'comicid': comicid})
            else:
                if comicid not in mylar.REFRESH_QUEUE.queue: #if not any(ext['comicid'] == comicid for ext in mylar.REFRESH_LIST):
                    watch.append({"comicid": comicid, "comicname": chkdb['ComicName']})
                else:
                    already_added.append({'comicid': comicid, 'comicname': chkdb['ComicName']})

        if len(notfound) > 0:
            logger.info('Unable to locate the following requested ID\'s for Refreshing: %s' % (notfound,))
            self.data = self._failureResponse('Unable to locate the following ID\'s for Refreshing (%s)' % (notfound,))
        if len(already_added) == 1:
            self.data = self._successResponse('[%s] %s has already been queued for refresh in a queue of %s items.' % (already_added[0]['comicid'], already_added[0]['comicname'], mylar.REFRESH_QUEUE.qsize()))
        elif len(already_added) > 1:
            self.data = self._successResponse('%s items (%s) have already been queued for refresh in a queue of % items.' % (len(already_added), already_added, mylar.REFRESH_QUEUE.qsize()))

        if len(watch) == 1:
            logger.info('[SHIZZLE-WHIZZLE] Now queueing to refresh %s %s' % (chkdb['ComicName'], chkdb['ComicYear']))
        elif len(watch) > 1:
            logger.info('[SHIZZLE-WHIZZLE] Now queueing to refresh %s items (%s)' % (len(watch), watch))
        else:
            return

        try:
            refred = importer.refresh_thread(watch)
        except Exception as e:
            logger.warn('[API-refreshComic] Unable to refresh ComicID %s. Error returned: %s' % (self.id, e))
            return
        else:
            if len(watch) == 1:
                ref_line = 'for ComicID %s' % (self.id)
            else:
                ref_line = 'for %s items (%s)' % (len(watch), watch)

            logger.warn('[API-refreshComic] Successfully background submitted refresh %s' % (ref_line))
            self.data = self._successResponse('Refresh successfully submitted %s.' % (self.id, ref_line))

        return

    def _changeBookType(self, **kwargs):
        #change booktype of series
        #id = comicid
        #booktype = specified booktype to force to (Print, Digital, TPB, GN, HC, One-Shot)
        if 'id' not in kwargs:
            self.data = self._failureResponse('Missing ComicID (field: id)')
            return
        self.id = kwargs['id']

        if 'booktype' not in kwargs:
            self.data = self._failureResponse('Missing BookType (field: booktype)')
            return
        booktype = kwargs['booktype']

        if booktype.lower() not in ['hc','gn','tpb','print','one-shot','digital']:
            self.data = self._failureResponse('Missing BookType format (allowed values: TPB, GN, HC, Print, One-Shot, Digital)')
            return
        else:
            booktype = booktype.lower()

        myDB = db.DBConnection()
        btresp = myDB.selectone('SELECT ComicName, ComicYear, Type, Corrected_Type FROM Comics WHERE ComicID=?', [self.id]).fetchone()
        if not btresp:
            self.data = self._failureResponse('Unable to locate ComicID %s within watchlist' % self.id)
            return
        else:
            if btresp['Corrected_Type'] is not None:
                if btresp['Corrected_Type'].lower() == booktype:
                    self.data = self._successResponse('[%s] Forced Booktype is already set as %s.' % (self.id, booktype))
                    return
                if btresp['Type'].lower() == booktype and btresp['Corrected_Type'] == booktype:
                    self.data = self._successResponse('[%s] Booktype is already set as %s.' % (self.id, booktype))
                    return

            for bt in ['HC', 'GN', 'TPB', 'One-Shot', 'Digital', 'Print']:
                if bt.lower() == booktype:
                    booktype = bt
                    break

            try:
                newValue = {'Corrected_Type': booktype}
                newWrite = {'ComicID': self.id}
                myDB.upsert("comics", newValue, newWrite)
            except Exception as e:
                self.data = self._failureResponse('[%s] Unable to update Booktype for ComicID: %s. Error returned: %s' % (self.id, e))
                return
            else:
                self.data = self._successResponse('[%s] Updated Booktype to %s.' % (self.id, booktype))
                return

    def _changeStatus(self, **kwargs):
        #change status_from of every issue in series to specified status_to
        #if no comicid specified will mark ALL issues in EVERY series from status_from to specific status_to
        #required fields: status_to, status_from. Optional: id  (which is the ComicID if applicable)
        if all(['status_to' not in kwargs, 'status_from' not in kwargs]):
            self.data = self._failureResponse('Missing Status')
            return
        else:
            self.status_to = kwargs['status_to']
            self.status_from = kwargs['status_from']

        if 'id' not in kwargs:
            self.data = self._failureResponse('Missing ComicID (field: id)')
            return
        else:
            self.id = kwargs['id']
            if self.id.lower() == 'all':
                self.id = 'All'
                bulk = True
            else:
                bulk = False
                self.id = kwargs['id']
                if type(self.id) is list:
                    bulk = True

        logger.info('[BULK:%s] [%s --> %s] ComicIDs to Change Status: %s' % (bulk, self.status_from, self.status_to, self.id))

        try:
            le_data = helpers.statusChange(self.status_from, self.status_to, self.id, bulk=bulk, api=True)
        except Exception as e:
            logger.error('[ERROR] %s' % e)
            self.data = e
        else:
            self.data = self._successResponse(le_data)
        return

    def _recheckFiles(self, **kwargs):
        #allow either individual / bulk recheck Files based on ComiciD
        #multiples are allowed as long as in a list: {'id': ['100101', '101010', '20181', '47101']}
        if 'id' not in kwargs:
            self.data = self._failureResponse('Missing ComicID')
            return
        else:
            self.id = kwargs['id']

        if type(self.id) != list:
            bulk = False
        else:
            bulk = True

        logger.info('[BULK:%s] ComicIDs to ReCheck: %s' % (bulk, self.id))

        try:
            fc = webserve.WebInterface()
            self.data = fc.forceRescan(ComicID=self.id, bulk=bulk, api=True)
        except Exception as e:
            self.data = e

        return

    def _addComic(self, **kwargs):
        if 'id' not in kwargs:
            self.data = self._failureResponse('Missing parameter: id')
            return
        else:
            self.id = kwargs['id']

        try:
            ac = webserve.WebInterface()
            ac.addbyid(self.id, calledby=True, nothread=False)
            #importer.addComictoDB(self.id)
        except Exception as e:
            self.data = e
        else:
            self.data = self._successResponse("Successfully queued up addding id: %s" % self.id)
        return

    def _queueIssue(self, **kwargs):
        if 'id' not in kwargs:
            self.data = self._failureResponse('Missing parameter: id')
            return
        else:
            self.id = kwargs['id']

        myDB = db.DBConnection()
        controlValueDict = {'IssueID': self.id}
        newValueDict = {'Status': 'Wanted'}
        myDB.upsert("issues", newValueDict, controlValueDict)
        search.searchforissue(self.id)

    def _unqueueIssue(self, **kwargs):
        if 'id' not in kwargs:
            self.data = self._failureResponse('Missing parameter: id')
            return
        else:
            self.id = kwargs['id']

        myDB = db.DBConnection()
        controlValueDict = {'IssueID': self.id}
        newValueDict = {'Status': 'Skipped'}
        myDB.upsert("issues", newValueDict, controlValueDict)

    def _seriesjsonListing(self, **kwargs):
        if 'missing' in kwargs:
            json_present = "WHERE seriesjsonPresent = 0 OR seriesjsonPresent is NULL"
        else:
            json_present = None
        myDB = db.DBConnection()
        msj_query = 'SELECT comicid, ComicLocation FROM comics {json_present}'.format(
            json_present=json_present
        )
        results = self._resultsFromQuery(msj_query)
        if len(results) > 0:
            self.data = self._successResponse(
                results
            )
        else:
            self.data = self._failureResponse('no data returned from seriesjson query')

    def _refreshSeriesjson(self, **kwargs):
        # comicid = [list, comicid, 'missing', 'all', 'refresh-missing']
        if 'comicid' not in kwargs:
            self.data = self._failureResponse('Missing comicid')
            return
        else:
            missing = False
            refresh_missing = False
            self.id = kwargs['comicid']
            if any([self.id == 'missing', self.id == 'all', self.id == 'refresh-missing']):
                bulk = True
                if any([self.id == 'missing', self.id == 'refresh-missing']):
                    if self.id == 'refresh-missing':
                        refresh_missing = True
                    missing = True
                    self._seriesjsonListing(missing=True)
                else:
                    self._seriesjsonListing()
                toqy = json.loads(self.data)
                if toqy['success'] is True:
                    toquery = []
                    for x in toqy['data']:
                        toquery.append(x['ComicID'])
                else:
                    self.data = self._failureResponse('No seriesjson data returned from query.')
                    return
            else:
                bulk = False
                if type(self.id) is list:
                    bulk = True
                toquery = self.id

        logger.info('[API][Refresh-Series.json][BULK:%s][Only_Missing:%s] ComicIDs to refresh series.json files: %s' % (bulk, missing, len(toquery)))

        try:
            sm = series_metadata.metadata_Series(comicidlist=toquery, bulk=bulk, api=True, refreshSeries=refresh_missing)
            sm.update_metadata_thread()
        except Exception as e:
            logger.error('[ERROR] %s' % e)
            self.data = e

        return


    def _forceSearch(self, **kwargs):
        search.searchforissue()

    def _issueProcess(self, **kwargs):
        if 'comicid' not in kwargs:
            self.data = self._failureResponse('Missing parameter: comicid')
            return
        else:
            self.comicid = kwargs['comicid']

        if 'issueid' not in kwargs:
            self.issueid = None
        else:
            self.issueid = kwargs['issueid']

        if 'folder' not in kwargs:
            self.data = self._failureResponse('Missing parameter: folder')
            return
        else:
            self.folder = kwargs['folder']


        fp = process.Process(self.comicid, self.folder, self.issueid)
        self.data = fp.post_process()
        return

    def _forceProcess(self, **kwargs):

        if 'nzb_name' not in kwargs:
            self.data = self._failureResponse('Missing parameter: nzb_name')
            return
        else:
            self.nzb_name = kwargs['nzb_name']

        if 'nzb_folder' not in kwargs:
            self.data = self._failureResponse('Missing parameter: nzb_folder')
            return
        else:
            self.nzb_folder = kwargs['nzb_folder']

        if 'failed' not in kwargs:
            failed = False
        else:
            failed = kwargs['failed']

        if 'issueid' not in kwargs:
            issueid = None
        else:
            issueid = kwargs['issueid']

        if 'comicid' not in kwargs:
            comicid = None
        else:
            comicid = kwargs['comicid']

        if 'ddl' not in kwargs:
            ddl = False
        else:
            ddl = True

        if 'oneoff' not in kwargs:
            oneoff = False
        else:
            if kwargs['oneoff'] == 'True':
                oneoff = True
            else:
                oneoff = False


        if 'apc_version' not in kwargs:
            logger.info('Received API Request for PostProcessing %s [%s]. Queueing...' % (self.nzb_name, self.nzb_folder))
            mylar.PP_QUEUE.put({'nzb_name':    self.nzb_name,
                                'nzb_folder':  self.nzb_folder,
                                'issueid':     issueid,
                                'failed':      failed,
                                'oneoff':      oneoff,
                                'comicid':     comicid,
                                'apicall':     True,
                                'ddl':         ddl})
            self.data = 'Successfully submitted request for post-processing for %s' % self.nzb_name
            #fp = process.Process(self.nzb_name, self.nzb_folder, issueid=issueid, failed=failed, comicid=comicid, apicall=True)
            #self.data = fp.post_process()
        else:
            logger.info('[API] Api Call from ComicRN detected - initiating script post-processing.')
            fp = webserve.WebInterface()
            self.data = fp.post_process(self.nzb_name, self.nzb_folder, failed=failed, apc_version=kwargs['apc_version'], comicrn_version=kwargs['comicrn_version'])
            self.comicrn = True
        return

    def _getVersion(self, **kwargs):
        self.data = self._successResponse({
            'git_path': mylar.CONFIG.GIT_PATH,
            'install_type': mylar.INSTALL_TYPE,
            'current_version': mylar.CURRENT_VERSION,
            'latest_version': mylar.LATEST_VERSION,
            'commits_behind': mylar.COMMITS_BEHIND,
        })

    def _checkGithub(self, **kwargs):
        versioncheck.checkGithub()
        self._getVersion()

    def _shutdown(self, **kwargs):
        mylar.SIGNAL = 'shutdown'

    def _restart(self, **kwargs):
        mylar.SIGNAL = 'restart'

    def _update(self, **kwargs):
        mylar.SIGNAL = 'update'

    def _getArtistArt(self, **kwargs):
        if 'id' not in kwargs:
            self.data = self._failureResponse('Missing parameter: id')
            return
        else:
            self.id = kwargs['id']

        self.data = cache.getArtwork(ComicID=self.id)

    def _getIssueArt(self, **kwargs):
        if 'id' not in kwargs:
            self.data = self._failureResponse('Missing parameter: id')
            return
        else:
            self.id = kwargs['id']

        self.data = cache.getArtwork(IssueID=self.id)

    def _getComicInfo(self, **kwargs):
        if 'id' not in kwargs:
            self.data = self._failureResponse('Missing parameter: id')
            return
        else:
            self.id = kwargs['id']

        myDB = db.DBConnection()
        query = self._selectForComics() + ' WHERE ComicID=?'
        rows = myDB.select(query, [self.id])
        results = [dict(zip(row.keys(), row)) for row in rows]
        if len(results) == 1:
            self.data = self._successResponse(
                results
            )
        else:
            self.data = self._failureResponse('No comic found with that ID')

    def _getIssueInfo(self, **kwargs):
        if 'id' not in kwargs:
            self.data = self._failureResponse('Missing parameter: id')
            return
        else:
            self.id = kwargs['id']

        myDB = db.DBConnection()
        query = self._selectForIssues() + ' WHERE IssueID=?'
        rows = myDB.select(query, [self.id])
        results = [dict(zip(row.keys(), row)) for row in rows]
        if len(results) == 1:
            self.data = self._successResponse(
                results
            )
        else:
            self.data = self._failureResponse('No issue found with that ID')

    def _getArt(self, **kwargs):
        if 'id' not in kwargs:
            self.data = self._failureResponse('Missing parameter: id')
            return
        else:
            self.id = kwargs['id']

        img = None
        image_path = os.path.join(mylar.CONFIG.CACHE_DIR, str(self.id) + '.jpg')

        # Checks if its a valid path and file
        if os.path.isfile(image_path):
            # check if its a valid img
            imghdr = Image.open(image_path)
            if imghdr.get_format_mimetype():
                self.img = image_path
                return
        else:
            # If we cant find the image, lets check the db for a url.
            myDB = db.DBConnection()
            comic_rows = myDB.select('SELECT * from comics WHERE ComicID=?', [self.id])
            comic = [dict(zip(row.keys(), row)) for row in comic_rows]

            # Try every img url in the db
            try:
                img = urllib.request.urlopen(comic[0]['ComicImageURL']).read()
            except:
                try:
                    img = urllib.request.urlopen(comic[0]['ComicImageALTURL']).read()
                except:
                    pass

            if img:
                # verify the img stream
                imghdr = Image.open(img)
                if imghdr.get_format_mimetype():
                    with open(image_path, 'wb') as f:
                        f.write(img)
                    self.img = image_path
                    return
                else:
                    self.data = self._failureResponse('Failed return a image')
            else:
                self.data = self._failureResponse('Failed to return a image')

    def _findComic(self, name, issue=None, type_=None, mode=None, serinfo=None, limit=None, offset=None, sort=None, content_type=None):
        # set defaults
        if type_ is None:
            type_ = 'comic'
        if mode is None:
            mode = 'series'

        # Dont do shit if name is missing
        if len(name) == 0:
            self.data = self._failureResponse('Missing a Comic name')
            return

        # Parse pagination parameters
        try:
            parsed_limit = int(limit) if limit else None
            parsed_offset = int(offset) if offset else None
        except ValueError:
            self.data = self._failureResponse('Invalid pagination parameters: limit and offset must be integers')
            return

        # Handle manga search via content_type parameter
        if content_type == 'manga':
            if not mylar.CONFIG.MANGADEX_ENABLED:
                self.data = self._failureResponse('MangaDex integration is not enabled')
                return
            from mylar import mangadex
            searchresults = mangadex.search_manga(name, limit=parsed_limit, offset=parsed_offset, sort=sort)
        elif type_ == 'comic' and mode == 'series':
            searchresults = mb.findComic(name, mode, issue=issue, limit=parsed_limit, offset=parsed_offset, sort=sort, content_type=content_type)
        elif type_ == 'comic' and mode == 'pullseries':
            searchresults = mb.findComic(name, mode, issue=issue, limit=parsed_limit, offset=parsed_offset, sort=sort, content_type=content_type)
        elif type_ == 'comic' and mode == 'want':
            searchresults = mb.findComic(name, mode, issue=issue, limit=parsed_limit, offset=parsed_offset, sort=sort, content_type=content_type)
        elif type_ == 'story_arc':
            searchresults = mb.findComic(name, mode, issue=None, search_type='story_arc', limit=parsed_limit, offset=parsed_offset, sort=sort)

        # Transform haveit field to in_library boolean for frontend
        def add_in_library(comic):
            # haveit is either "No" (not in library) or a dict (in library)
            comic['in_library'] = comic.get('haveit') != "No"
            return comic

        # Handle both old format (list) and new format (dict with pagination)
        if isinstance(searchresults, dict) and 'results' in searchresults:
            # New format with pagination - don't sort here, respect server-side sort
            searchresults['results'] = [add_in_library(c) for c in searchresults['results']]
            self.data = searchresults
        else:
            # Legacy format (list) - apply sorting
            searchresults = sorted(searchresults, key=itemgetter('comicyear', 'issues'), reverse=True)
            searchresults = [add_in_library(c) for c in searchresults]
            self.data = searchresults

    def _downloadIssue(self, id):
        if not id:
            self.data = self._failureResponse('You need to provide a issueid')
            return

        self.id = id
        # Fetch a list of dicts from issues table
        myDB = db.DBConnection()
        i_rows = myDB.select('SELECT * from issues WHERE issueID=?', [self.id])
        i = [dict(zip(row.keys(), row)) for row in i_rows]

        if not len(i):
            self.data = self._failureResponse('Couldnt find a issue with issueID %s' % self.id)
            return

        # issueid is unique so it should one dict in the list
        issue = i[0]

        issuelocation = issue.get('Location', None)

        # Check the issue is downloaded
        if issuelocation is not None:
            # Find the comic location
            comic_rows = myDB.select('SELECT * from comics WHERE comicID=?', [issue['ComicID']])
            comic = dict(zip(comic_rows[0].keys(), comic_rows[0]))
            comiclocation = comic.get('ComicLocation')
            f = os.path.join(comiclocation, issuelocation)
            if not os.path.isfile(f):
                try:
                    if all([mylar.CONFIG.MULTIPLE_DEST_DIRS is not None, mylar.CONFIG.MULTIPLE_DEST_DIRS != 'None']):
                        if os.path.exists(os.path.join(mylar.CONFIG.MULTIPLE_DEST_DIRS, os.path.basename(comiclocation))):
                            secondary_folders = os.path.join(mylar.CONFIG.MULTIPLE_DEST_DIRS, os.path.basename(comiclocation))
                        else:
                            ff = mylar.filers.FileHandlers(ComicID=issue['ComicID'])
                            secondary_folders = ff.secondary_folders(comiclocation)

                        f = os.path.join(secondary_folders, issuelocation)
                        self.file = f
                        self.filename = issuelocation

                except Exception:
                    pass
            else:
                self.file = f
                self.filename = issuelocation
        else:
            self.data = self._failureResponse('You need to download that issue first')
            return

    def _downloadNZB(self, nzbname):
        if not nzbname:
            self.data = self._failureResponse('You need to provide a nzbname')
            return

        self.nzbname = nzbname
        f = os.path.join(mylar.CONFIG.CACHE_DIR, nzbname)
        if os.path.isfile(f):
            self.file = f
            self.filename = nzbname
        else:
            self.data = self._failureResponse('NZBname does not exist within the cache directory. Unable to retrieve.')
            return

    def _getStoryArc(self, **kwargs):
        if not 'id' in kwargs:
            if 'customOnly' in kwargs and kwargs['customOnly']:
                self.data = self._resultsFromQuery('SELECT StoryArcID, StoryArc, MAX(ReadingOrder) AS HighestOrder from storyarcs WHERE StoryArcID LIKE "C%" GROUP BY StoryArcID ORDER BY StoryArc')
            else:
                self.data = self._resultsFromQuery('SELECT StoryArcID, StoryArc, MAX(ReadingOrder) AS HighestOrder from storyarcs GROUP BY StoryArcID ORDER BY StoryArc')
        else:
            self.id = kwargs['id']
            myDB = db.DBConnection()
            rows = myDB.select('SELECT StoryArc, ReadingOrder, ComicID, ComicName, IssueNumber, IssueID, \
                                            IssueDate, IssueName, IssuePublisher from storyarcs WHERE StoryArcID=? ORDER BY ReadingOrder', [self.id])
            self.data = [dict(zip(row.keys(), row)) for row in rows]
        return

    def _addStoryArc(self, **kwargs):
        issuecount = 0
        if not 'id' in kwargs:
            self.id = 'C%04d' % random.randint(1, 9999)
            if not 'storyarcname' in kwargs:
                self.data = self._failureResponse('You need to provide either id or storyarcname')
                return
            else:
                storyarcname = kwargs.pop('storyarcname')
        else:
            self.id = kwargs.pop('id')
            myDB = db.DBConnection()
            arc_rows = myDB.select('SELECT * from storyarcs WHERE StoryArcID=? ORDER by ReadingOrder', [self.id])
            arc = [dict(zip(row.keys(), row)) for row in arc_rows]
            storyarcname = arc[0]['StoryArc']
            issuecount = len(arc)
        if not 'issues' in kwargs and not 'arclist' in kwargs:
            self.data = self._failureResponse('No issues specified')
            return
        else:
            arclist = ""
            if 'issues' in kwargs:
                issuelist = kwargs.pop('issues').split(",")
                index = 0
                for issue in issuelist:
                    arclist += "%s,%s" % (issue, issuecount + 1)
                    index += 1
                    issuecount += 1
                    if index < len(issuelist):
                        arclist += "|"
            if 'arclist' in kwargs:
                cvlist = kwargs.pop('arclist')
                issuelist = cvlist.split("|")
                index = 0
                for issue in issuelist:
                    arclist += "%s,%s" % (issue.split(",")[0],issuecount + 1)
                    index += 1
                    issuecount += 1
                    if index < len(issuelist):
                        arclist += "|"
        wi = webserve.WebInterface()
        logger.info("arclist: %s - arcid: %s - storyarcname: %s - storyarcissues: %s" % (arclist, self.id, storyarcname, issuecount))
        wi.addStoryArc_thread(arcid=self.id, storyarcname=storyarcname, storyarcissues=issuecount, arclist=arclist, **kwargs)
        self.data = self._successResponse('Adding %s issue(s) to %s' % (issuecount, storyarcname))
        return

    def _listAnnualSeries(self, **kwargs):
        # list_issues = true/false
        # group_series = true/false
        # show_downloaded_only = true/false
        # - future: recreate as individual series (annual integration off after was enabled) = true/false
        if all(['list_issues' not in kwargs, 'group_series' not in kwargs]): #, 'recreate' not in kwargs]):
            self.data = self._failureResponse('Missing parameter(s): Must specify either `list_issues` or `group_series`')
            return
        else:
            list_issues = True
            group_series = True
            show_downloaded = True
            #recreate_from_annuals = True
            try:
                listissues = kwargs['list_issues']
            except Exception:
                list_issues = False
            try:
                groupseries = kwargs['group_series']
            except Exception:
                group_series = False
            try:
                showdownloaded = kwargs['show_downloaded']
            except Exception:
                show_downloaded = False

            if group_series:
                annual_listing = {}
            else:
                annual_listing = []

            #try:
            #    recreatefromannuals = kwargs['recreate']
            #except Exception:
            #    recreate_from_annuals = False

        try:
            myDB = db.DBConnection()
            las = myDB.select('SELECT * from Annuals WHERE NOT Deleted')
        except Exception as e:
            self.data = self._failureResponse('Unable to query Annuals table - possibly no annuals have been detected as being integrated.')
            return

        if las is None:
            self.data = self._failureResponse('No annuals have been detected as ever being integrated.')
            return

        annuals = {}
        for lss in las:
            if show_downloaded is False or all([show_downloaded is True, lss['Status'] == 'Downloaded']):
                annuals = {'series': lss['ComicName'],
                           'annualname': lss['ReleaseComicName'],
                           'annualcomicid': lss['ReleaseComicID'],
                           'issueid': int(lss['IssueID']),
                           'filename': lss['Location'],
                           'issuenumber': lss['Issue_Number']}

                if group_series is True:
                    if int(lss['ComicID']) not in annual_listing.keys():
                        annual_listing[int(lss['comicid'])] = [annuals]
                    else:
                        annual_listing[int(lss['comicid'])] += [annuals]
                else:
                    annuals['comicid'] = int(lss['ComicID'])
                    annual_listing.append(annuals)

        self.data = self._successResponse(annual_listing)
        return

    def _checkGlobalMessages(self, **kwargs):
        the_message = {'status': None, 'event': None, 'comicname': None, 'seriesyear': None, 'comicid': None, 'tables': None, 'message': None}
        if mylar.GLOBAL_MESSAGES is not None:
            try:
                event = mylar.GLOBAL_MESSAGES['event']
            except Exception:
                event = None

            if event is not None and any([event == 'shutdown', event == 'config_check']):
                the_message = {'status': mylar.GLOBAL_MESSAGES['status'], 'event': event, 'message': mylar.GLOBAL_MESSAGES['message']}
            elif event is not None and event == 'check_update':
                the_message = {'status': mylar.GLOBAL_MESSAGES['status'], 'event': event, 'current_version': mylar.GLOBAL_MESSAGES['current_version'], 'latest_version': mylar.GLOBAL_MESSAGES['latest_version'], 'commits_behind': str(mylar.GLOBAL_MESSAGES['commits_behind']), 'docker': mylar.GLOBAL_MESSAGES['docker'], 'message': mylar.GLOBAL_MESSAGES['message']}
            elif event is not None and event in ['search_progress', 'search_complete']:
                the_message = {
                    'status': mylar.GLOBAL_MESSAGES['status'],
                    'event': event,
                    'search_id': mylar.GLOBAL_MESSAGES.get('search_id'),
                    'message': mylar.GLOBAL_MESSAGES['message']
                }
                if event == 'search_complete':
                    the_message['result_count'] = mylar.GLOBAL_MESSAGES.get('result_count', 0)
            else:
                the_message = {'status': mylar.GLOBAL_MESSAGES['status'], 'event': event, 'comicid': mylar.GLOBAL_MESSAGES['comicid'], 'tables': mylar.GLOBAL_MESSAGES['tables'], 'message': mylar.GLOBAL_MESSAGES['message']}
                try:
                    the_fields = {'comicname': mylar.GLOBAL_MESSAGES['comicname'], 'seriesyear': mylar.GLOBAL_MESSAGES['seriesyear']}
                    the_message = dict(the_message, **the_fields)
                except Exception as e:
                    logger.warn('error: %s' % e)
            #logger.fdebug('the_message added: %s' % (the_message,))
            # Don't save search events to database, just stream them
            if mylar.GLOBAL_MESSAGES['status'] != 'mid-message-event' and event not in ['search_progress', 'search_complete']:
                myDB = db.DBConnection()
                tmp_message = dict(the_message, **{'session_id': mylar.SESSION_ID})
                if event != 'check_update':
                    try:
                        tmp_message.pop('tables')
                    except Exception:
                        pass
                else:
                    tmp_message.pop('current_version')
                    tmp_message.pop('latest_version')
                    tmp_message.pop('commits_behind')
                    tmp_message.pop('docker')
                the_tmp_message = tmp_message.pop('message')
                the_real_message = re.sub(r'\r\n|\n|</br>', '', the_tmp_message)
                tmp_message = dict(tmp_message, **{'message': the_real_message})
                #logger.fdebug('the_message re-added: %s' % (tmp_message,))
                myDB.upsert( "notifs", tmp_message, {'date': helpers.now()} )
            if event in ['search_progress', 'search_complete']:
                logger.info('[SSE] Sending search event via SSE: event=%s, search_id=%s' % (event, the_message.get('search_id')))
            mylar.GLOBAL_MESSAGES = None
        self.data = self._eventStreamResponse(the_message)

    def _listProviders(self, **kwargs):
        try:
            newznabs = []
            for nz in mylar.CONFIG.EXTRA_NEWZNABS:
                uid = nz[4]
                if '#' in nz[4]:
                    cats = re.sub('#', ',', nz[4][nz[4].find('#')+1:].strip()).strip()
                    uid = nz[4][:nz[4].find('#')].strip()
                else:
                    cats = None
                newznabs.append({'name': nz[0],
                                 'host': nz[1],
                                 'apikey': nz[3],
                                 'categories': cats,
                                 'uid': uid,
                                 'enabled': bool(int(nz[5])),
                                 'id': int(nz[6])})
            torznabs= []
            for nz in mylar.CONFIG.EXTRA_TORZNABS:
                cats = nz[4]
                if '#' in nz[4]:
                    cats = re.sub('#', ',', nz[4]).strip()
                torznabs.append({'name': nz[0],
                                 'host': nz[1],
                                 'apikey': nz[3],
                                 'categories': nz[4],
                                 'enabled': bool(int(nz[5])),
                                 'id': int(nz[6])})

            providers = {'newznabs': newznabs, 'torznabs': torznabs}
        except Exception as e:
            self.data = self._failureResponse(e)
        else:
            self.data = self._successResponse(providers)
        return

    def _addProvider(self, **kwargs):
        if 'providertype' not in kwargs:
            self.data = self._failureResponse('No provider type provided')
            logger.fdebug('[API][addProvider] %s' % (self.data,))
            return
        else:
            providertype = kwargs['providertype']
            if all([providertype != 'newznab', providertype != 'torznab']):
                self.data = self._failureResponse('providertype indicated %s is not a valid option. Options are `newznab` or `torznab`.' % providertype)
                logger.fdebug('[API][addProvider] %s' % (self.data,))
                return

        if any(['host' not in kwargs, 'name' not in kwargs, 'prov_apikey' not in kwargs, 'enabled' not in kwargs]):
            if providertype == 'newznab':
                self.data = self._failureResponse('Missing arguement. Required arguements are: `name`, `host`, `prov_apikey`, `enabled`. `categories` & `uid` is optional but `uid` is required for RSS.')
            elif providertype == 'torznab':
                self.data = self._failureResponse('Missing arguement. Required arguements are: `name`, `host`, `prov_apikey`, `categories`, `enabled.`')
                logger.fdebug('[API][addProvider] %s' % (self.data,))
            return

        if providertype == 'newznab':
            if 'name' in kwargs:
                newznab_name = kwargs['name']
                if any([newznab_name is None, newznab_name.strip() == '']):
                    self.data = self._failureResponse('name given for provider cannot be None or blank')
                    logger.fdebug('[API][addProvider] %s' % (self.data,))
                    return
                for x in mylar.CONFIG.EXTRA_NEWZNABS:
                    if x[0].lower() == newznab_name.lower():
                        self.data = self._failureResponse('%s already exists as a provider.' % newznab_name)
                        logger.fdebug('[API][addProvider] %s' % (self.data,))
                        return

            if 'host' in kwargs:
                newznab_host = kwargs['host']
                if not newznab_host.startswith('http'):
                    self.data = self._failureResponse('protocol is required for % host entry' % providertype)
                    logger.fdebug('[API][addProvider] %s' % (self.data,))
                    return
                if newznab_host.startswith('https'):
                    newznab_verify = '1'
                else:
                    newznab_verify = '0'
            if 'prov_apikey' in kwargs:
                newznab_apikey = kwargs['prov_apikey']

            newznab_enabled = '0' # set the default to disabled.
            if 'enabled' in kwargs:
                newznab_enabled = '1'
            if 'uid' in kwargs:
                newznab_uid = kwargs['uid']
            else:
                newznab_uid = None

            if 'categories' in kwargs:
                newznab_categories = kwargs['categories']
                if newznab_uid is not None:
                    newznab_uid += '%s%s'.strip() % ('#', re.sub(',', '#', newznab_categories))
                else:
                    newznab_uid = '%s%s'.strip() % ('#', re.sub(',', '#', newznab_categories))

            #prov_id assignment here
            prov_id = mylar.PROVIDER_START_ID + 1

            prov_line = (newznab_name, newznab_host, newznab_verify, newznab_apikey, newznab_uid, newznab_enabled, prov_id)
            if prov_line not in mylar.CONFIG.EXTRA_NEWZNABS:
                mylar.CONFIG.EXTRA_NEWZNABS.append(prov_line)
            else:
                self.data = self._failureResponse('exact details belong to another provider id already [%]. Maybe you should be using changeProvider' % prov_id)
                logger.fdebug('[API][addProvider] %s' % (self.data,))
                return

            p_name = newznab_name

        elif providertype == 'torznab':
            if 'name' in kwargs:
                torznab_name = kwargs['name']
                if any([torznab_name is None, torznab_name.strip() == '']):
                    self.data = self._failureResponse('name given for provider cannot be None or blank')
                    logger.fdebug('[API][addProvider] %s' % (self.data,))
                    return
                for x in mylar.CONFIG.EXTRA_TORZNABS:
                    if x[0].lower() == torznab_name.lower():
                        self.data = self._failureResponse('%s already exists as a provider.' % torznab_name)
                        logger.fdebug('[API][addProvider] %s' % (self.data,))
                        return

            if 'host' in kwargs:
                torznab_host = kwargs['host']
                if not torznab_host.startswith('http'):
                    self.data = self._failureResponse('protocol is required for % host entry' % providertype)
                    logger.fdebug('[API][addProvider] %s' % (self.data,))
                    return
                if torznab_host.startswith('https'):
                    torznab_verify = '1'
                else:
                    torznab_verify = '0'
            if 'prov_apikey' in kwargs:
                torznab_apikey = kwargs['prov_apikey']
            torznab_enabled = '0'
            if 'enabled' in kwargs:
                torznab_enabled = '1'
            if 'categories' in kwargs:
                torznab_categories = kwargs['categories']
                if ',' in torznab_categories:
                    tc = torznab_categories.split(',')
                    torznab_categories = '#'.join(tc).strip()

            #prov_id assignment here
            prov_id = mylar.PROVIDER_START_ID + 1

            prov_line = (torznab_name, torznab_host, torznab_verify, torznab_apikey, torznab_categories, torznab_enabled, prov_id)
            if prov_line not in mylar.CONFIG.EXTRA_TORZNABS:
                mylar.CONFIG.EXTRA_TORZNABS.append(prov_line)
            else:
                self.data = self._failureResponse('exact details belong to another provider id already [%]. Maybe you should be using changeProvider' % prov_id)
                logger.fdebug('[API][addProvider] %s' % (self.data,))
                return

            p_name = torznab_name

        try:
            mylar.CONFIG.writeconfig()
        except Exception as e:
            logger.error('[API][ADD_PROVIDER][%s] error returned : %s' % (providertype, e))
            self.data = self._failureResponse('Unable to add %s provider %s to the provider list. Check the logs.' % (providertype, p_name))
        else:
            self.data = self._successResponse('Successfully added %s provider %s to the provider list [prov_id: %s]' % (providertype, p_name, prov_id))
        return

    def _delProvider(self, **kwargs):
        providername = None
        prov_id = None
        if 'name' in kwargs:
            providername = kwargs['name'].strip()

        if 'prov_id' in kwargs:
            prov_id = int(kwargs['prov_id'])

        if any([providername is None, providername == '']) and prov_id is None:
            self.data = self._failureResponse('at least one of prov_id or name must be provided (cannot be blank)')
            logger.fdebug('[API][delProvider] %s' % (self.data,))
            return

        providertype = None
        if 'providertype' in kwargs:
            providertype = kwargs['providertype'].strip()
        else:
            self.data = self._failureResponse('No provider type provided')
            logger.fdebug('[API][addProvider] %s' % (self.data,))
            return

        if any([providertype is None, providertype == '']) or all([providertype != 'torznab', providertype != 'newznab']):
            if any([providertype is None, providertype == '']):
                self.data = self._failureResponse('`providertype` cannot be None or blank (either `torznab` or `newznab`)')
            elif all([providertype != 'torznab', providertype != 'newznab']):
                self.data = self._failureResponse('`providertype` provided not recognized. Must be either `torznab` or `newznab`)')
            logger.fdebug('[API][delProvider] %s' % (self.data,))
            return

        del_match = False
        newznabs = []
        if providertype == 'newznab':
            if prov_id is not None:
                prov_match = 'id'
            else:
                prov_match = 'name'
            for nz in mylar.CONFIG.EXTRA_NEWZNABS:
                if prov_match == 'id':
                    if prov_id == nz[6]:
                        del_match = True
                        providername = nz[0]
                        continue
                    else:
                        newznabs.append(nz)
                else:
                    if providername.lower() == nz[0]:
                        del_match = True
                        prov_id = nz[6]
                        continue
                    else:
                        newznabs.append(nz)

            if del_match is True:
                mylar.CONFIG.EXTRA_NEWZNABS = ((newznabs))
        else:
            torznabs= []
            if prov_id is not None:
                prov_match = 'id'
            else:
                prov_match = 'name'
            for nz in mylar.CONFIG.EXTRA_TORZNABS:
                if prov_match == 'id':
                    if prov_id == nz[6]:
                        del_match = True
                        providername = nz[0]
                        continue
                    else:
                        torznabs.append(nz)
                else:
                    if providername.lower() == nz[0]:
                        del_match = True
                        prov_id = nz[6]
                        continue
                    else:
                        torznabs.append(nz)

            if del_match is True:
                mylar.CONFIG.EXTRA_TORZNABS = ((torznabs))

        if del_match is False:
            self.data = self._failureResponse('Cannot remove %s as a provider, as it does not exist as a %s provider' % (providername, providertype))
            logger.fdebug('[API][delProvider] %s' % self.data)
            return
        else:
            try:
                mylar.CONFIG.writeconfig()
            except Exception as e:
                logger.error('[API][ADD_PROVIDER][%s] error returned : %s' % (providertype, e))
                self.data = self._failureResponse('Unable to save config of deleted %s provider %s. Check the logs.' % (providertype, providername))
            else:
                self.data = self._successResponse('Successfully removed %s provider %s [prov_id:%s]' % (providertype, providername, prov_id))
                logger.fdebug('[API][delProvider] %s' % self.data)
        return

    def _changeProvider(self, **kwargs):
        providername = None
        changename = None
        prov_id = None
        if 'altername' in kwargs:
            changename = kwargs.pop('altername').strip()
            if any([changename is None, changename == '']):
                self.data = self._failureResponse('altered name given for provider cannot be None or blank')
                logger.fdebug('[API][changeProvider] %s' % (self.data,))
                return

        if 'prov_id' in kwargs:
            prov_id = int(kwargs['prov_id'])

        if 'name' not in kwargs:
            if prov_id is None:
                self.data = self._failureResponse('provider id (`prov_id`) or provider name (`name`) not given. One must be supplied.')
                logger.fdebug('[API][changeProvider] %s' % (self.data,))
                return
        else:
            providername = kwargs['name'].strip()
            if all([providername is None, providername == '']):
                self.data = self._failureResponse('name given for provider cannot be None or blank')
                logger.fdebug('[API][changeProvider] %s' % (self.data,))
                return

        providertype = None
        if 'providertype' not in kwargs:
            self.data = self._failureResponse('No provider type provided')
            logger.fdebug('[API][changeProvider] %s' % (self.data,))
            return
        else:
            providertype = kwargs['providertype'].strip()
            if all([providertype != 'newznab', providertype != 'torznab']):
                self.data = self._failureResponse('providertype indicated %s is not a valid option. Options are `newznab` or `torznab`.' % providertype)
                logger.fdebug('[API][changerovider] %s' % (self.data,))
                return

        # find the values to change.
        if 'host' in kwargs:
            providerhost = kwargs['host']
            if providerhost.startswith('http'):
                if providerhost.startswith('https'):
                    prov_verify = '1'
                else:
                    prov_verify = '0'
            else:
                self.data = self._failureResponse('protocol is required for % host entry' % providertype)
                logger.fdebug('[API][changeProvider] %s' % (self.data,))
                return
        else:
            providerhost = None
            prov_verify = None

        if 'prov_apikey' in kwargs:
            prov_apikey = kwargs['prov_apikey']
        else:
            prov_apikey = None

        if 'enabled' in kwargs:
            tmp_enable = kwargs['enabled']
            prov_enabled = '1'
            if tmp_enable == 'true':
                prov_enabled = '1'
            elif any([tmp_enable == 'false', tmp_enable is None, tmp_enable == '']):
                prov_enabled = '0'
            else:
                self.data = self._failureResponse('`enabled` value must be `true`, `false` or not declared')
                logger.fdebug('[API][changeProvider] %s' % (self.data,))
                return

        elif 'disabled' in kwargs:
            tmp_enable = kwargs['disabled']
            prov_enabled = '0'
            if tmp_enable == 'true':
                prov_enabled = '0'
            elif any([tmp_enable == 'false', tmp_enable is None, tmp_enable == '']):
                prov_enabled = '1'
            else:
                self.data = self._failureResponse('`disabled` value must be `true`, `false` or not declared')
                logger.fdebug('[API][changeProvider] %s' % (self.data,))
                return
        else:
            prov_enabled = None

        torznab_categories = None
        if 'categories' in kwargs and providertype == 'torznab':
            torznab_categories = kwargs['categories']
            if ',' in torznab_categories:
                tc = torznab_categories.split(',')
                torznab_categories = '#'.join(tc).strip()

        if 'uid' in kwargs and providertype == 'newznab':
            newznab_uid = kwargs['uid']
        else:
            newznab_uid = None

        newznab_categories = None
        if 'categories' in kwargs and providertype == 'newznab':
            newznab_categories = kwargs['categories']
            if newznab_uid is not None:
                newznab_uid += '%s%s'.strip() % ('#', re.sub(',', '#', newznab_categories))
            else:
                newznab_uid = '%s%s'.strip() % ('#', re.sub(',', '#', newznab_categories))

        newznabs = []
        change_match = []
        if providertype == 'newznab':
            if prov_id is not None:
                prov_match = 'id'
            else:
                prov_match = 'name'
            for nz in mylar.CONFIG.EXTRA_NEWZNABS:
                if prov_match == 'id':
                    if nz[6] != prov_id:
                        newznabs.append(nz)
                        continue
                else:
                    if providername.lower() != nz[0].lower():
                        newznabs.append(nz)
                        continue
                if not prov_id:
                    # cannot alter prov_id via changeProvider method
                    prov_id = nz[6]
                if changename is not None:
                    if providername is None:
                        providername = changename
                        change_match.append('name')
                    elif providername.lower() != changename.lower():
                        providername = changename
                        change_match.append('name')
                else:
                    if providername is None:
                        providername = nz[0]
                    else:
                        change_match.append('name')
                p_host = nz[1]
                if providerhost is not None:
                    if p_host.lower() != providerhost.lower():
                        p_host = providerhost
                        change_match.append('host')
                p_verify = nz[2]
                if prov_verify is not None:
                    if p_verify != prov_verify:
                        p_verify = prov_verify
                        change_match.append('verify')
                p_apikey = nz[3]
                if prov_apikey is not None:
                    if p_apikey != prov_apikey:
                        p_apikey = prov_apikey
                        change_match.append('apikey')
                p_uid = nz[4]
                if newznab_uid is not None:
                    if p_uid != newznab_uid:
                        p_uid = newznab_uid
                        change_match.append('uid')
                p_enabled = nz[5]
                if p_enabled != prov_enabled and prov_enabled is not None:
                    p_enabled = prov_enabled
                    change_match.append('enabled')
                newznabs.append((providername, p_host, p_verify, p_apikey, p_uid, p_enabled, prov_id))

            if len(change_match) > 0:
                mylar.CONFIG.EXTRA_NEWZNABS = ((newznabs))
        else:
            torznabs= []
            if prov_id is not None:
                prov_match = 'id'
            else:
                prov_match = 'name'
            for nt in mylar.CONFIG.EXTRA_TORZNABS:
                if prov_match == 'id':
                    if nt[6] != prov_id:
                        torznabs.append(nt)
                        continue
                else:
                    if providername.lower() != nt[0].lower():
                        torznabs.append(nt)
                        continue
                if not prov_id:
                    # cannot alter prov_id via changeProvider method
                    prov_id = nt[6]
                if changename is not None:
                    if providername is None:
                        providername = changename
                        change_match.append('name')
                    elif providername.lower() != changename.lower():
                        providername = changename
                        change_match.append('name')
                else:
                    if providername is None:
                        providername = nt[0]
                    else:
                        change_match.append('name')
                p_host = nt[1]
                if providerhost is not None:
                    if p_host.lower() != providerhost.lower():
                        p_host = providerhost
                        change_match.append('host')
                p_verify = nt[2]
                if p_verify != prov_verify and prov_verify is not None:
                    p_verify = prov_verify
                    change_match.append('verify')
                p_apikey = nt[3]
                if prov_apikey is not None:
                    if p_apikey != prov_apikey:
                        p_apikey = prov_apikey
                        change_match.append('apikey')
                p_categories = nt[4]
                if torznab_categories is not None:
                    if p_categories != torznab_categories:
                        p_categories = torznab_categories
                        change_match.append('categories')
                p_enabled = nt[5]
                if p_enabled != prov_enabled and prov_enabled is not None:
                    p_enabled = prov_enabled
                    change_match.append('enabled')
                torznabs.append((providername, p_host, p_verify, p_apikey, p_categories, p_enabled, prov_id))

            if len(change_match) > 0:
                mylar.CONFIG.EXTRA_TORZNABS = ((torznabs))

        if len(change_match) == 0:
            self.data = self._failureResponse('Nothing to change for %s provider %s. It does not exist as a %s provider or nothing to change' % (providertype, providername, providertype))
            logger.fdebug('[API][changeProvider] %s' % self.data)
            return
        else:
            try:
                mylar.CONFIG.writeconfig()
            except Exception as e:
                logger.error('[API][ADD_PROVIDER][%s] error returned : %s' % (providertype, e))
            else:
                self.data = self._successResponse('Successfully changed %s for %s provider %s [prov_id:%s]' % (change_match, providertype, providername, prov_id))
                logger.fdebug('[API][changeProvider] %s' % self.data)
        return

    def _bulkMetatag(self, **kwargs):
        """
        Bulk tag metadata for multiple issues.
        Required: id (ComicID), issue_ids (comma-separated IssueIDs)
        """
        if 'id' not in kwargs:
            self.data = self._failureResponse('Missing ComicID (field: id)')
            return

        if 'issue_ids' not in kwargs:
            self.data = self._failureResponse('Missing issue IDs (field: issue_ids)')
            return

        comic_id = kwargs['id']
        issue_ids_str = kwargs['issue_ids']

        # Parse comma-separated issue IDs into a list
        issue_ids = [iid.strip() for iid in issue_ids_str.split(',') if iid.strip()]

        if len(issue_ids) == 0:
            self.data = self._failureResponse('No valid issue IDs provided')
            return

        try:
            result = webserve.WebInterface().bulk_metatag(comic_id, issue_ids)
            self.data = self._successResponse('Bulk metatag started for %s issues' % len(issue_ids))
        except Exception as e:
            logger.error('[API][bulkMetatag] Error: %s' % e)
            self.data = self._failureResponse('Failed to start bulk metatag: %s' % str(e))
        return

    def _getConfig(self, **kwargs):
        """
        Get safe configuration values for frontend settings page.
        Returns filtered dict of ~20 config values that are safe to expose.
        """
        # Map download client integers to readable labels
        nzb_downloader_map = {
            0: 'SABnzbd',
            1: 'NZBGet',
            2: 'Blackhole',
            3: 'None'
        }
        torrent_downloader_map = {
            0: 'Watch Folder',
            1: 'uTorrent',
            2: 'rTorrent',
            3: 'Transmission',
            4: 'Deluge',
            5: 'qBittorrent'
        }

        config_data = {
            # General (read-only paths)
            'comic_dir': mylar.CONFIG.COMIC_DIR,
            'destination_dir': mylar.CONFIG.DESTINATION_DIR,
            'cache_dir': mylar.CONFIG.CACHE_DIR,
            'log_dir': mylar.CONFIG.LOG_DIR,

            # Interface
            'http_host': mylar.CONFIG.HTTP_HOST,
            'http_port': mylar.CONFIG.HTTP_PORT,
            'http_username': mylar.CONFIG.HTTP_USERNAME,
            'launch_browser': mylar.CONFIG.LAUNCH_BROWSER,
            'interface': mylar.CONFIG.INTERFACE,

            # API
            'api_key': mylar.CONFIG.API_KEY,

            # Comic Vine
            'comicvine_api': mylar.CONFIG.COMICVINE_API,
            'cv_verify': mylar.CONFIG.CV_VERIFY,
            'cv_only': mylar.CONFIG.CV_ONLY,

            # Metron
            'metron_username': mylar.CONFIG.METRON_USERNAME,
            'metron_password': mylar.CONFIG.METRON_PASSWORD,
            'use_metron_search': mylar.CONFIG.USE_METRON_SEARCH,

            # Search
            'preferred_quality': mylar.CONFIG.PREFERRED_QUALITY,
            'use_minsize': mylar.CONFIG.USE_MINSIZE,
            'minsize': mylar.CONFIG.MINSIZE,
            'use_maxsize': mylar.CONFIG.USE_MAXSIZE,
            'maxsize': mylar.CONFIG.MAXSIZE,

            # Download Clients (read-only labels)
            'nzb_downloader': mylar.CONFIG.NZB_DOWNLOADER,
            'nzb_downloader_label': nzb_downloader_map.get(mylar.CONFIG.NZB_DOWNLOADER, 'Unknown'),
            'torrent_downloader': mylar.CONFIG.TORRENT_DOWNLOADER,
            'torrent_downloader_label': torrent_downloader_map.get(mylar.CONFIG.TORRENT_DOWNLOADER, 'Unknown')
        }

        self.data = self._successResponse(config_data)

    def _setConfig(self, **kwargs):
        """
        Update configuration values from frontend settings page.
        Only allows whitelisted safe config values to be updated.
        """
        logger.info('[API][setConfig] Received kwargs: %s' % list(kwargs.keys()))
        # Whitelist of allowed config keys
        allowed_keys = [
            'api_key',
            'launch_browser',
            'interface',
            'comicvine_api',
            'cv_verify',
            'cv_only',
            'metron_username',
            'metron_password',
            'use_metron_search',
            'preferred_quality',
            'use_minsize',
            'minsize',
            'use_maxsize',
            'maxsize',
            # General paths
            'comic_dir',
            'destination_dir',
            'multiple_dest_dirs',
            'create_folders',
            # SABnzbd
            'sab_host',
            'sab_username',
            'sab_password',
            'sab_apikey',
            'sab_category',
            'sab_priority',
            'sab_directory',
            'sab_to_mylar',
            'sab_client_post_processing',
            'sab_remove_completed',
            'sab_remove_failed',
            # NZBGet
            'nzbget_host',
            'nzbget_port',
            'nzbget_username',
            'nzbget_password',
            'nzbget_priority',
            'nzbget_category',
            'nzbget_directory',
            'nzbget_client_post_processing',
            # qBittorrent
            'qbittorrent_host',
            'qbittorrent_username',
            'qbittorrent_password',
            'qbittorrent_label',
            'qbittorrent_folder',
            'qbittorrent_loadaction',
            # Transmission
            'transmission_host',
            'transmission_username',
            'transmission_password',
            'transmission_directory',
            # Deluge
            'deluge_host',
            'deluge_username',
            'deluge_password',
            'deluge_label',
            # Download client selection
            'nzb_downloader',
            'torrent_downloader',
            # Post-processing
            'post_processing',
            'file_opts',
            'enable_meta',
            'rename_files',
            'folder_format',
            'file_format',
        ]

        # Filter kwargs to only allowed keys
        filtered_kwargs = {}
        for key, value in kwargs.items():
            if key in allowed_keys:
                filtered_kwargs[key] = value

        if not filtered_kwargs:
            self.data = self._failureResponse('No valid configuration keys provided')
            return

        try:
            # Update config using existing process_kwargs method
            mylar.CONFIG.process_kwargs(filtered_kwargs)

            # Persist to config.ini
            mylar.CONFIG.writeconfig()

            # Apply config changes at runtime (without this, changes only persist to disk)
            mylar.CONFIG.configure(update=True, startup=False)

            # Check if Metron settings changed and reinitialize if needed
            metron_keys = {'metron_username', 'metron_password', 'use_metron_search'}
            if metron_keys.intersection(filtered_kwargs.keys()):
                from mylar import metron
                metron.reinitialize_metron_api()
                logger.info('[API][setConfig] Metron API reinitialized due to config change')

            self.data = self._successResponse('Configuration updated successfully')
            logger.info('[API][setConfig] Updated config keys: %s' % list(filtered_kwargs.keys()))
        except Exception as e:
            self.data = self._failureResponse('Failed to update configuration: %s' % str(e))
            logger.error('[API][setConfig] Error: %s' % e)

    def _getSeriesImage(self, **kwargs):
        """
        Get cover image URL for a Metron series.
        Used for lazy loading images in search results.
        """
        if 'id' not in kwargs:
            self.data = self._failureResponse('Missing parameter: id')
            return

        series_id = kwargs['id']

        from mylar import metron
        image_url = metron.get_series_image(series_id)

        self.data = self._successResponse({'image': image_url})

    def _findManga(self, **kwargs):
        """
        Search for manga using MangaDex API.

        Parameters:
            name: Manga name to search for (required)
            limit: Number of results per page (optional)
            offset: Offset for pagination (optional)
            sort: Sort order (optional) - relevance, latest, oldest, title_asc, title_desc, year_desc, year_asc, follows

        Returns:
            Search results with pagination metadata
        """
        if 'name' not in kwargs or not kwargs['name']:
            self.data = self._failureResponse('Missing parameter: name')
            return

        name = kwargs['name']
        limit = kwargs.get('limit')
        offset = kwargs.get('offset')
        sort = kwargs.get('sort')

        # Check if MangaDex is enabled
        if not mylar.CONFIG.MANGADEX_ENABLED:
            self.data = self._failureResponse('MangaDex integration is not enabled')
            return

        # Parse pagination parameters
        try:
            parsed_limit = int(limit) if limit else None
            parsed_offset = int(offset) if offset else None
        except ValueError:
            self.data = self._failureResponse('Invalid pagination parameters: limit and offset must be integers')
            return

        from mylar import mangadex
        searchresults = mangadex.search_manga(name, limit=parsed_limit, offset=parsed_offset, sort=sort)

        # Transform haveit field to in_library boolean for frontend
        def add_in_library(manga):
            manga['in_library'] = manga.get('haveit') != "No"
            return manga

        if isinstance(searchresults, dict) and 'results' in searchresults:
            searchresults['results'] = [add_in_library(m) for m in searchresults['results']]
            self.data = searchresults
        else:
            self.data = self._failureResponse('Search returned no results')

    def _addManga(self, **kwargs):
        """
        Add a manga to the library by MangaDex ID.

        Parameters:
            id: MangaDex manga ID (with or without 'md-' prefix) (required)

        Returns:
            Success/failure response
        """
        if 'id' not in kwargs:
            self.data = self._failureResponse('Missing parameter: id')
            return

        manga_id = kwargs['id']

        # Ensure the ID has the md- prefix
        if not str(manga_id).startswith('md-'):
            manga_id = 'md-' + manga_id

        # Check if MangaDex is enabled
        if not mylar.CONFIG.MANGADEX_ENABLED:
            self.data = self._failureResponse('MangaDex integration is not enabled')
            return

        try:
            from mylar import importer
            result = importer.addMangaToDB(manga_id)

            if result and result.get('status') == 'complete':
                self.data = self._successResponse({
                    'message': 'Successfully added manga: %s' % result.get('comicname', manga_id),
                    'comicid': manga_id,
                    'content_type': 'manga'
                })
            else:
                self.data = self._failureResponse('Failed to add manga: %s' % manga_id)
        except Exception as e:
            logger.error('[API][addManga] Error adding manga %s: %s' % (manga_id, e))
            self.data = self._failureResponse('Error adding manga: %s' % str(e))

    def _getMangaInfo(self, **kwargs):
        """
        Get detailed information about a manga from MangaDex.

        Parameters:
            id: MangaDex manga ID (with or without 'md-' prefix) (required)
            include_chapters: Whether to include chapter list (optional, default False)

        Returns:
            Manga details and optionally chapter list
        """
        if 'id' not in kwargs:
            self.data = self._failureResponse('Missing parameter: id')
            return

        manga_id = kwargs['id']
        include_chapters = kwargs.get('include_chapters', 'false').lower() == 'true'

        # Check if MangaDex is enabled
        if not mylar.CONFIG.MANGADEX_ENABLED:
            self.data = self._failureResponse('MangaDex integration is not enabled')
            return

        from mylar import mangadex

        # Get manga details
        details = mangadex.get_manga_details(manga_id)

        if not details:
            self.data = self._failureResponse('Manga not found: %s' % manga_id)
            return

        response_data = {
            'manga': details
        }

        # Optionally include chapters
        if include_chapters:
            chapters = mangadex.get_all_chapters(manga_id)
            response_data['chapters'] = chapters
            response_data['chapter_count'] = len(chapters)

        # Check if manga is in library
        myDB = db.DBConnection()
        if str(manga_id).startswith('md-'):
            db_manga = myDB.selectone('SELECT * FROM comics WHERE ComicID=?', [manga_id]).fetchone()
        else:
            db_manga = myDB.selectone('SELECT * FROM comics WHERE ComicID=?', ['md-' + manga_id]).fetchone()

        response_data['in_library'] = db_manga is not None
        if db_manga:
            response_data['library_status'] = db_manga['Status']
            response_data['have'] = db_manga['Have']
            response_data['total'] = db_manga['Total']

        self.data = self._successResponse(response_data)

    def _getImportPending(self, **kwargs):
        """
        Get list of pending import files with suggested matches and confidence scores.

        Parameters:
            limit: Maximum number of results (optional, default 50)
            offset: Offset for pagination (optional, default 0)
            include_ignored: Include ignored files (optional, default 'false')

        Returns:
            List of import groups with files and pagination info
        """
        myDB = db.DBConnection()

        limit = int(kwargs.get('limit', 50))
        offset = int(kwargs.get('offset', 0))
        include_ignored = kwargs.get('include_ignored', 'false').lower() == 'true'

        # Build query for pending imports - group by DynamicName and Volume
        if include_ignored:
            base_query = """
                SELECT *, COUNT(*) as FileCount
                FROM importresults
                WHERE (WatchMatch IS NULL OR WatchMatch LIKE 'C%')
                  AND Status != 'Imported'
                GROUP BY DynamicName, Volume
                ORDER BY ComicName COLLATE NOCASE
            """
            count_query = """
                SELECT COUNT(DISTINCT DynamicName || COALESCE(Volume, ''))
                FROM importresults
                WHERE (WatchMatch IS NULL OR WatchMatch LIKE 'C%')
                  AND Status != 'Imported'
            """
        else:
            base_query = """
                SELECT *, COUNT(*) as FileCount
                FROM importresults
                WHERE (WatchMatch IS NULL OR WatchMatch LIKE 'C%')
                  AND Status != 'Imported'
                  AND (IgnoreFile IS NULL OR IgnoreFile = 0)
                GROUP BY DynamicName, Volume
                ORDER BY ComicName COLLATE NOCASE
            """
            count_query = """
                SELECT COUNT(DISTINCT DynamicName || COALESCE(Volume, ''))
                FROM importresults
                WHERE (WatchMatch IS NULL OR WatchMatch LIKE 'C%')
                  AND Status != 'Imported'
                  AND (IgnoreFile IS NULL OR IgnoreFile = 0)
            """

        # Get total count
        total_result = myDB.selectone(count_query).fetchone()
        total = total_result[0] if total_result else 0

        # Get paginated results
        paginated_query = base_query + " LIMIT ? OFFSET ?"
        results = myDB.select(paginated_query, [limit, offset])

        imports = []
        for result in results:
            dynamic_name = result['DynamicName']
            volume = result['Volume']

            # Get all files for this group
            if volume is None or volume == 'None':
                files_query = """
                    SELECT * FROM importresults
                    WHERE DynamicName=? AND (Volume IS NULL OR Volume='None')
                    AND (WatchMatch IS NULL OR WatchMatch LIKE 'C%')
                    AND Status != 'Imported'
                """
                if not include_ignored:
                    files_query += " AND (IgnoreFile IS NULL OR IgnoreFile = 0)"
                files = myDB.select(files_query, [dynamic_name])
            else:
                files_query = """
                    SELECT * FROM importresults
                    WHERE DynamicName=? AND Volume=?
                    AND (WatchMatch IS NULL OR WatchMatch LIKE 'C%')
                    AND Status != 'Imported'
                """
                if not include_ignored:
                    files_query += " AND (IgnoreFile IS NULL OR IgnoreFile = 0)"
                files = myDB.select(files_query, [dynamic_name, volume])

            file_list = []
            for f in files:
                file_list.append({
                    'impID': f['impID'],
                    'ComicFilename': f['ComicFilename'],
                    'ComicLocation': f['ComicLocation'],
                    'IssueNumber': f['IssueNumber'],
                    'ComicYear': f['ComicYear'],
                    'Status': f['Status'],
                    'IgnoreFile': f['IgnoreFile'] or 0,
                    'MatchConfidence': f['MatchConfidence'],
                    'SuggestedComicID': f['SuggestedComicID'],
                    'SuggestedComicName': f['SuggestedComicName'],
                    'SuggestedIssueID': f['SuggestedIssueID'],
                    'MatchSource': f['MatchSource']
                })

            # Calculate average confidence for the group
            confidences = [f['MatchConfidence'] for f in file_list if f['MatchConfidence'] is not None]
            avg_confidence = sum(confidences) // len(confidences) if confidences else None

            imports.append({
                'DynamicName': dynamic_name,
                'ComicName': result['ComicName'],
                'Volume': volume,
                'ComicYear': result['ComicYear'],
                'FileCount': result['FileCount'],
                'Status': result['Status'],
                'SRID': result['SRID'],
                'ComicID': result['ComicID'],
                'MatchConfidence': avg_confidence,
                'SuggestedComicID': result['SuggestedComicID'],
                'SuggestedComicName': result['SuggestedComicName'],
                'files': file_list
            })

        self.data = self._successResponse({
            'imports': imports,
            'pagination': {
                'total': total,
                'limit': limit,
                'offset': offset,
                'has_more': (offset + limit) < total
            }
        })

    def _matchImport(self, **kwargs):
        """
        Manually match import file(s) to a comic series.

        Parameters:
            imp_ids: Comma-separated list of import IDs to match (required)
            comic_id: Comic ID to match to (required)
            issue_id: Specific issue ID to match to (optional)

        Returns:
            Number of matched imports
        """
        if 'imp_ids' not in kwargs:
            self.data = self._failureResponse('Missing parameter: imp_ids')
            return

        if 'comic_id' not in kwargs:
            self.data = self._failureResponse('Missing parameter: comic_id')
            return

        imp_ids = kwargs['imp_ids'].split(',')
        comic_id = kwargs['comic_id']
        issue_id = kwargs.get('issue_id')

        myDB = db.DBConnection()

        # Get comic name for display
        comic = myDB.selectone('SELECT ComicName FROM comics WHERE ComicID=?', [comic_id]).fetchone()
        comic_name = comic['ComicName'] if comic else 'Unknown'

        matched = 0
        for imp_id in imp_ids:
            imp_id = imp_id.strip()
            if not imp_id:
                continue

            update_values = {
                'ComicID': comic_id,
                'SuggestedComicID': comic_id,
                'SuggestedComicName': comic_name,
                'MatchSource': 'manual',
                'MatchConfidence': 100,
                'WatchMatch': 'C' + comic_id
            }

            if issue_id:
                update_values['IssueID'] = issue_id
                update_values['SuggestedIssueID'] = issue_id

            myDB.upsert('importresults', update_values, {'impID': imp_id})
            matched += 1

        self.data = self._successResponse({
            'matched': matched,
            'comic_id': comic_id,
            'comic_name': comic_name
        })

    def _ignoreImport(self, **kwargs):
        """
        Mark import file(s) as ignored or unignored.

        Parameters:
            imp_ids: Comma-separated list of import IDs to update (required)
            ignore: Whether to ignore (true) or unignore (false) (optional, default 'true')

        Returns:
            Number of updated imports
        """
        if 'imp_ids' not in kwargs:
            self.data = self._failureResponse('Missing parameter: imp_ids')
            return

        imp_ids = kwargs['imp_ids'].split(',')
        ignore = kwargs.get('ignore', 'true').lower() == 'true'
        ignore_value = 1 if ignore else 0

        myDB = db.DBConnection()

        updated = 0
        for imp_id in imp_ids:
            imp_id = imp_id.strip()
            if not imp_id:
                continue

            myDB.upsert('importresults', {'IgnoreFile': ignore_value}, {'impID': imp_id})
            updated += 1

        self.data = self._successResponse({
            'updated': updated,
            'ignored': ignore
        })

    def _refreshImport(self, **kwargs):
        """
        Trigger a refresh of the import directory scan.

        Returns:
            Success message
        """
        import mylar
        from mylar import librarysync

        # Get import directory from config
        import_dir = mylar.CONFIG.IMPORT_DIR if hasattr(mylar.CONFIG, 'IMPORT_DIR') else None

        if not import_dir:
            self.data = self._failureResponse('Import directory not configured')
            return

        # Queue import scan
        try:
            logger.info('[API][refreshImport] Starting import directory scan for: %s' % import_dir)
            # Use existing import functionality - scanLibrary expects scan=path and queue=queue object
            import_queue = queue.Queue()
            threading.Thread(
                target=librarysync.scanLibrary,
                name="API-ImportScan",
                args=[import_dir, import_queue]
            ).start()

            self.data = self._successResponse({
                'message': 'Import scan started for: %s' % import_dir
            })
        except Exception as e:
            logger.error('[API][refreshImport] Error: %s' % e)
            self.data = self._failureResponse('Failed to start import scan: %s' % str(e))

    def _deleteImport(self, **kwargs):
        """
        Delete import record(s) from the database.

        Parameters:
            imp_ids: Comma-separated list of import IDs to delete (required)

        Returns:
            Number of deleted imports
        """
        if 'imp_ids' not in kwargs:
            self.data = self._failureResponse('Missing parameter: imp_ids')
            return

        imp_ids = kwargs['imp_ids'].split(',')

        myDB = db.DBConnection()

        deleted = 0
        for imp_id in imp_ids:
            imp_id = imp_id.strip()
            if not imp_id:
                continue

            myDB.action('DELETE FROM importresults WHERE impID=?', [imp_id])
            deleted += 1

        self.data = self._successResponse({
            'deleted': deleted
        })


class REST(object):

    def __init__(self):
        pass

    class verify_api(object):
        def __init__(self):
            pass

        def validate(self):
            logger.info('attempting to validate...')
            req = cherrypy.request.headers
            logger.info('thekey: %s' % req)
            logger.info('url: %s' % cherrypy.url())
            logger.info('mylar.apikey: %s [%s]' % (mylar.CONFIG.API_KEY, type(mylar.CONFIG.API_KEY)))
            logger.info('submitted.apikey: %s [%s]' % (req['Api-Key'], type(req['Api-Key'])))
            if 'Api-Key' not in req or req['Api-Key'] != str(mylar.CONFIG.API_KEY): #str(mylar.API_KEY) or mylar.API_KEY not in cherrypy.url():
                logger.info('wrong APIKEY')
                return 'api-key provided was either not present in auth header, or was incorrect.'
            else:
                return True

    class Watchlist(object):
        exposed = True
        def __init__(self):
            pass

        def GET(self):
            va = REST.verify_api()
            vchk = va.validate()
            if vchk is not True:
                return('api-key provided was either not present in auth header, or was incorrect.')
            #rows_as_dic = []

            #for row in rows:
            #    row_as_dic = dict(zip(row.keys(), row))
            #    rows_as_dic.append(row_as_dic)

            #return rows_as_dic
            some = helpers.havetotals()
            return json.dumps(some)

    class Comics(object):
        exposed = True
        def __init__(self):
            pass

        def _dic_from_query(self, query):
            myDB = db.DBConnection()
            rows = myDB.select(query)

            rows_as_dic = []

            for row in rows:
                row_as_dic = dict(list(zip(list(row.keys()), row)))
                rows_as_dic.append(row_as_dic)

            return rows_as_dic

        def GET(self):
            va = REST.verify_api()
            vchk = va.validate()
            if vchk is not True:
                return('api-key provided was either not present in auth header, or was incorrect.')
            #req = cherrypy.request.headers
            #logger.info('thekey: %s' % req)
            #if 'api-key' not in req or req['api-key'] != 'hello':
            #    logger.info('wrong APIKEY')
            #    return('api-key provided was either not present in auth header, or was incorrect.')

            self.comics = self._dic_from_query('SELECT * from comics order by ComicSortName COLLATE NOCASE')
            return('Here are all the comics we have: %s' % self.comics)

    @cherrypy.popargs('comic_id','issuemode','issue_id')
    class Comic(object):
        exposed = True

        def __init__(self):
            pass

        def _dic_from_query(self, query):
            myDB = db.DBConnection()
            rows = myDB.select(query)

            rows_as_dic = []

            for row in rows:
                row_as_dic = dict(list(zip(list(row.keys()), row)))
                rows_as_dic.append(row_as_dic)

            return rows_as_dic

        def GET(self, comic_id=None, issuemode=None, issue_id=None):
            va = REST.verify_api()
            vchk = va.validate()
            if vchk is not True:
                return('api-key provided was either not present in auth header, or was incorrect.')

            #req = cherrypy.request.headers
            #logger.info('thekey: %s' % req)
            #if 'api-key' not in req or req['api-key'] != 'hello':
            #    logger.info('wrong APIKEY')
            #    return('api-key provided was either not present in auth header, or was incorrect.')

            self.comics = self._dic_from_query('SELECT * from comics order by ComicSortName COLLATE NOCASE')

            if comic_id is None:
                return('No valid ComicID entered')
            else:
                if issuemode is None:
                    match = [c for c in self.comics if comic_id == c['ComicID']]
                    if match:
                        return json.dumps(match,ensure_ascii=False)
                    else:
                        return('No Comic with the ID %s :-(' % comic_id)
                elif issuemode == 'issues':
                    self.issues = self._dic_from_query('SELECT * from issues where comicid="' + comic_id + '"')
                    return json.dumps(self.issues, ensure_ascii=False)
                elif issuemode == 'issue' and issue_id is not None:
                    self.issues = self._dic_from_query('SELECT * from issues where comicid="' + comic_id + '" and issueid="' + issue_id + '"')
                    return json.dumps(self.issues, ensure_ascii=False)
                else:
                    return('Nothing to do.')

