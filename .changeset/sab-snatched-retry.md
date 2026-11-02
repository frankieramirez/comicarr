---
"comicarr": patch
---

Activity → In Flight can retry post-processing for a SABnzbd download that finished but stayed Snatched. Comicarr also picks those completed jobs up on its own and imports them once. A finished download it cannot import now shows in Needs Attention instead of staying Snatched, and Retry is not offered while post-processing is turned off.
