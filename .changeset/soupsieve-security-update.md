---
"comicarr": patch
---

Updates the HTML parsing library Comicarr uses to read provider pages (Soup Sieve 4.1.1), closing four reported denial-of-service flaws where a crafted page could stall parsing. Source installs now need Python 3.11.5 or newer; the Docker image is unaffected.
