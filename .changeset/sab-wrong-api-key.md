---
"comicarr": patch
---

The SABnzbd connection check in Settings and Activity → Health now says "SABnzbd rejected the API key" when the key is wrong. Before, SABnzbd 5's answer to a wrong key was read as a success, so the check showed Reachable while every grab sent to SABnzbd was refused.
