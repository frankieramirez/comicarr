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


import datetime
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

from bs4 import BeautifulSoup

from . import helpers, logger


def GCDScraper(ComicName, ComicYear, Total, ComicID, quickmatch=None):
    NOWyr = datetime.date.today().year
    if datetime.date.today().month == 12:
        NOWyr = NOWyr + 1
        logger.fdebug("We're in December, incremented search Year to increase search results: " + str(NOWyr))
    comicnm = ComicName.encode("utf-8").strip()
    comicyr = ComicYear
    comicnm_1 = re.sub(r"\+", "%2B", comicnm)
    comicnm = re.sub(" ", "+", comicnm_1)
    input = (
        "http://www.comics.org/search/advanced/process/?target=series&method=icontains&logic=False&order2=date&order3=&start_date="
        + str(comicyr)
        + "-01-01&end_date="
        + str(NOWyr)
        + "-12-31&series="
        + str(comicnm)
        + "&is_indexed=None"
    )
    response = urllib.request.urlopen(input)
    soup = BeautifulSoup(response)
    cnt1 = len(soup.findAll("tr", {"class": "listing_even"}))
    cnt2 = len(soup.findAll("tr", {"class": "listing_odd"}))

    cnt = int(cnt1 + cnt2)

    resultName = []
    resultID = []
    resultYear = []
    resultIssues = []
    resultURL = None
    n_odd = -1
    n_even = -1
    n = 0
    while n < cnt:
        if n % 2 == 0:
            n_even += 1
            resultp = soup.findAll("tr", {"class": "listing_even"})[n_even]
        else:
            n_odd += 1
            resultp = soup.findAll("tr", {"class": "listing_odd"})[n_odd]
        rtp = resultp("a")[1]
        resultName.append(helpers.cleanName(rtp.findNext(text=True)))
        fip = resultp("a", href=True)[1]
        resultID.append(fip["href"])

        subtxt3 = resultp("td")[3]
        resultYear.append(subtxt3.findNext(text=True))
        resultYear[n] = resultYear[n].replace(" ", "")
        subtxt4 = resultp("td")[4]
        resultIssues.append(helpers.cleanName(subtxt4.findNext(text=True)))
        resiss = resultIssues[n].find("issue")
        resiss = int(resiss)
        resultIssues[n] = resultIssues[n].replace("", "")[:resiss]
        resultIssues[n] = resultIssues[n].replace(" ", "")
        CleanComicName = re.sub("[\\,\\.\\:\\;'\\[\\]\\(\\)\\!\\@\\#\\$\\%\\^\\&\\*\\-\\_\\+\\=\\?\\/]", "", comicnm)
        CleanComicName = re.sub(" ", "", CleanComicName).lower()
        CleanResultName = re.sub(
            "[\\,\\.\\:\\;'\\[\\]\\(\\)\\!\\@\\#\\$\\%\\^\\&\\*\\-\\_\\+\\=\\?\\/]", "", resultName[n]
        )
        CleanResultName = re.sub(" ", "", CleanResultName).lower()
        if CleanResultName == CleanComicName or CleanResultName[3:] == CleanComicName:
            if resultYear[n] == ComicYear or resultYear[n] == str(int(ComicYear) + 1):
                if (
                    int(resultIssues[n]) == int(Total)
                    or int(resultIssues[n]) == int(Total) + 1
                    or (int(resultIssues[n]) + 1) == int(Total)
                ):
                    if int(resultIssues[n]) == int(Total) + 1:
                        issvariation = "cv"
                    elif int(resultIssues[n]) + 1 == int(Total):
                        issvariation = "gcd"
                    else:
                        issvariation = "no"
                    TotalIssues = resultIssues[n]
                    resultURL = str(resultID[n])
                    rptxt = resultp("td")[6]
                    resultPublished = rptxt.findNext(text=True)
                    break

        n += 1
    basnumbs = {
        "one": 1,
        "two": 2,
        "three": 3,
        "four": 4,
        "five": 5,
        "six": 6,
        "seven": 7,
        "eight": 8,
        "nine": 9,
        "ten": 10,
        "eleven": 11,
        "twelve": 12,
    }
    if resultURL is None:
        for numbs in basnumbs:
            if numbs in ComicName.lower():
                numconv = basnumbs[numbs]
                ComicNm = re.sub(str(numbs), str(numconv), ComicName.lower())
                return GCDScraper(ComicNm, ComicYear, Total, ComicID)
                break
        if ComicName.lower().startswith("the "):
            ComicName = ComicName[4:]
            return GCDScraper(ComicName, ComicYear, Total, ComicID)
        if ":" in ComicName:
            ComicName = re.sub(":", "", ComicName)
            return GCDScraper(ComicName, ComicYear, Total, ComicID)
        if "-" in ComicName:
            ComicName = re.sub("-", " ", ComicName)
            return GCDScraper(ComicName, ComicYear, Total, ComicID)
        if "and" in ComicName.lower():
            ComicName = ComicName.replace("and", "&")
            return GCDScraper(ComicName, ComicYear, Total, ComicID)
        if not quickmatch:
            return "No Match"
    if quickmatch == "yes":
        if resultURL is None:
            return "No Match"
        else:
            return "Match"
    return GCDdetails(
        comseries=None,
        resultURL=resultURL,
        vari_loop=0,
        ComicID=ComicID,
        TotalIssues=TotalIssues,
        issvariation=issvariation,
        resultPublished=resultPublished,
    )


def GCDdetails(comseries, resultURL, vari_loop, ComicID, TotalIssues, issvariation, resultPublished):

    gcdinfo = {}
    gcdchoice = []
    gcount = 0
    i = 0

    if vari_loop > 1:
        resultPublished = "Unknown"

    if vari_loop == 99:
        vari_loop = 1

    while i <= vari_loop:
        if vari_loop > 0:
            try:
                boong = comseries["comseries"][i]
            except IndexError:
                break
            resultURL = boong["comseriesID"]
            ComicID = boong["comicid"]
            TotalIssues += int(boong["comseriesIssues"])
        else:
            resultURL = resultURL
            inputMIS = "http://www.comics.org" + str(resultURL)
            resp = urllib.request.urlopen(inputMIS)
            try:
                soup = BeautifulSoup(urllib.request.urlopen(inputMIS))
            except UnicodeDecodeError:
                logger.info("I've detected your system is using: " + sys.stdout.encoding)
                logger.info("unable to parse properly due to utf-8 problem, ignoring wrong symbols")
                try:
                    soup = BeautifulSoup(urllib.request.urlopen(inputMIS)).decode("utf-8", "ignore")
                except UnicodeDecodeError:
                    logger.info("not working...aborting. Tell Evilhero.")
                    return
            pyearit = soup.find("div", {"class": "item_data"})
            pyeartxt = pyearit.find(text=re.compile(r"Series"))
            pyearst = pyeartxt.index("Series")
            ParseYear = pyeartxt[int(pyearst) - 5 : int(pyearst)]

            parsed = soup.find("div", {"id": "series_data"})
            subtxt3 = parsed.find("dd", {"id": "publication_dates"})
            resultPublished = subtxt3.findNext(text=True).rstrip()
            parsfind = parsed.findAll("dt", {"class": "long"})
            len(parsfind)
            resultFormat = ""
            for pf in parsfind:
                if "Publishing Format:" in pf.findNext(text=True):
                    subtxt9 = pf.find("dd", {"id": "series_format"})
                    resultFormat = subtxt9.findNext(text=True).rstrip()
                    continue
            if resultFormat != "":
                if (
                    "ongoing series" in resultFormat.lower()
                    and "was" not in resultFormat.lower()
                    and "present" not in resultPublished.lower()
                ):
                    resultPublished = resultPublished + " - Present"
                if "limited series" in resultFormat.lower() and "?" in resultPublished:
                    resultPublished = resultPublished + " (Limited Series)"
            coverst = soup.find("div", {"id": "series_cover"})
            if coverst < 0:
                gcdcover = "None"
            else:
                subcoverst = coverst("img", src=True)[0]
                gcdcover = subcoverst["src"]

        input2 = "http://www.comics.org" + str(resultURL) + "details/"
        resp = urllib.request.urlopen(input2)
        soup = BeautifulSoup(resp)

        type = soup.find(text=" Pub. Date ")
        if type:
            pass
        else:
            pass

        cnt1 = len(soup.findAll("tr", {"class": "row_even_False"}))
        cnt2 = len(soup.findAll("tr", {"class": "row_even_True"}))

        cnt = int(cnt1 + cnt2)

        n_odd = -1
        n_even = -1
        n = 0
        PrevYRMO = "0000-00"
        while n < cnt:
            if n % 2 == 0:
                n_odd += 1
                parsed = soup.findAll("tr", {"class": "row_even_False"})[n_odd]
            else:
                n_even += 1
                parsed = soup.findAll("tr", {"class": "row_even_True"})[n_even]
            subtxt3 = parsed.find("a")
            ParseIssue = subtxt3.findNext(text=True)

            fid = parsed("a", href=True)[0]
            resultGID = fid["href"]
            resultID = resultGID[7:-1]

            if "," in ParseIssue:
                ParseIssue = re.sub(r"\,", "", ParseIssue)
            variant = "no"
            if "Vol" in ParseIssue or "[" in ParseIssue or "a" in ParseIssue or "b" in ParseIssue or "c" in ParseIssue:
                m = re.findall(r"[^\[\]]+", ParseIssue)
                if "." in m[0]:
                    dec_chk = m[0]
                    dec_st = dec_chk.find(".")
                    dec_b4 = dec_chk[:dec_st]
                    dec_ad = dec_chk[dec_st + 1 :]
                    dec_ad = re.sub(r"\s", "", dec_ad)
                    if dec_b4.isdigit() and dec_ad.isdigit():
                        ParseIssue = dec_b4 + "." + dec_ad
                    else:
                        ParseIssue = re.sub("[^0-9]", " ", dec_chk)
                else:
                    ParseIssue = re.sub("[^0-9]", " ", m[0])

                logger.fdebug("variant cover detected : " + str(ParseIssue))
                variant = "yes"
            isslen = ParseIssue.find(" ")
            if isslen < 0:
                isslen == 0
                isschk = ParseIssue
            else:
                isschk = ParseIssue[:isslen]
            ParseIssue = re.sub(r"\s", "", ParseIssue)
            if "." in isschk:
                isschk_find = isschk.find(".")
                isschk_b4dec = isschk[:isschk_find]
                isschk_decval = isschk[isschk_find + 1 :]
                if len(isschk_decval) == 1:
                    ParseIssue = isschk_b4dec + "." + str(int(isschk_decval) * 10)

            elif "/" in isschk:
                ParseIssue = "0.50"
                isslen = 0
            else:
                isschk_decval = ".00"
                ParseIssue = ParseIssue + isschk_decval
            if variant == "yes":
                pass

            datematch = "false"

            if not any(d.get("GCDIssue", None) == str(ParseIssue) for d in gcdchoice):
                pass
            else:
                for d in gcdchoice:
                    if str(d["GCDIssue"]) == str(ParseIssue):
                        if str(d["GCDDate"]) == str(gcdinfo["ComicDate"]):
                            datematch = "true"
                        else:
                            datematch = "false"

            if datematch == "false":
                gcdinfo["ComicIssue"] = ParseIssue
                ParseDate = GettheDate(parsed, PrevYRMO)

                ParseDate = ParseDate.replace(" ", "")
                PrevYRMO = ParseDate
                gcdinfo["ComicDate"] = ParseDate
                if ComicID[:1] == "G":
                    gcdchoice.append(
                        {
                            "GCDid": ComicID,
                            "IssueID": resultID,
                            "GCDIssue": gcdinfo["ComicIssue"],
                            "GCDDate": gcdinfo["ComicDate"],
                        }
                    )
                    gcount += 1
                else:
                    gcdchoice.append(
                        {"GCDid": ComicID, "GCDIssue": gcdinfo["ComicIssue"], "GCDDate": gcdinfo["ComicDate"]}
                    )

                gcdinfo["gcdchoice"] = gcdchoice

            n += 1
        i += 1
    gcdinfo["gcdvariation"] = issvariation
    if ComicID[:1] == "G":
        gcdinfo["totalissues"] = gcount
    else:
        gcdinfo["totalissues"] = TotalIssues
    gcdinfo["ComicImage"] = gcdcover
    gcdinfo["resultPublished"] = resultPublished
    gcdinfo["SeriesYear"] = ParseYear
    gcdinfo["GCDComicID"] = resultURL.split("/")[0]
    return gcdinfo


def GettheDate(parsed, PrevYRMO):
    subtxt1 = parsed("td")[1]
    ParseDate = subtxt1.findNext(text=True).rstrip()
    pformat = "pub"
    if ParseDate is None or ParseDate == "":
        subtxt1 = parsed("td")[2]
        ParseDate = subtxt1.findNext(text=True)
        pformat = "on-sale"
        if len(ParseDate) < 7:
            ParseDate = "0000-00"
    basmonths = {
        "january": "01",
        "february": "02",
        "march": "03",
        "april": "04",
        "may": "05",
        "june": "06",
        "july": "07",
        "august": "08",
        "september": "09",
        "october": "10",
        "november": "11",
        "december": "12",
    }
    pdlen = len(ParseDate)
    pdfind = ParseDate.find(" ", 2)
    if pformat == "on-sale":
        pass
    else:
        if ParseDate[pdfind + 1 : pdlen - 1].isdigit():
            for numbs in basmonths:
                if numbs in ParseDate.lower():
                    pconv = basmonths[numbs]
                    ParseYear = re.sub("/s", "", ParseDate[-5:])
                    ParseDate = str(ParseYear) + "-" + str(pconv)
                    break
        else:
            baseseasons = {"spring": "03", "summer": "06", "fall": "09", "winter": "12"}
            for seas in baseseasons:
                if seas in ParseDate.lower():
                    sconv = baseseasons[seas]
                    ParseYear = re.sub("/s", "", ParseDate[-5:])
                    ParseDate = str(ParseYear) + "-" + str(sconv)
                    break
            if PrevYRMO == "0000-00":
                ParseDate = "0000-00"
            else:
                PrevYR = str(PrevYRMO)[:4]
                PrevMO = str(PrevYRMO)[5:]
                if int(PrevMO) == 12:
                    PrevYR = int(PrevYR) + 1
                    PrevMO = 1
                else:
                    PrevMO = int(PrevMO) + 1
                if int(PrevMO) < 10:
                    PrevMO = "0" + str(PrevMO)
                ParseDate = str(PrevYR) + "-" + str(PrevMO)
    return ParseDate
