---
"comicarr": patch
---

Deluge works again on the Docker image and any Python 3.12+ install. Before this fix, Test in Settings and every Deluge handoff failed with "module 'ssl' has no attribute 'wrap_socket'". The connection now requires TLS 1.2 or newer.
