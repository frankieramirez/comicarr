---
"comicarr": patch
---

Direct downloads that were abandoned mid-transfer no longer sit in Downloading forever. Once a stuck download passes the stuck threshold and no download is running for it, Comicarr closes it out. A download it can't match to a snatch goes to Manual Review. A dead source link is marked Failed and the issue is searched again. A link that still works but stopped transferring is marked Failed and the issue goes back to Wanted. If the link can't be checked, the download is left alone and checked again later. The download that is running is never interrupted; Comicarr only notifies about it, once. Stuck notifications no longer repeat after a restart.
