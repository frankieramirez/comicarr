---
"comicarr": patch
---

Startup recovery no longer treats a missing NZBGet download id as a downloader outage. Rows that never recorded an NZBID were re-probed on every restart and logged as if NZBGet were unreachable, even when the client was healthy. Recovery now recognises those rows as unprobeable: if the library already shows the download finished they close normally, and if it does not they stay unknown without blaming NZBGet. A real NZBGet connection failure still retries as a transient outage.
