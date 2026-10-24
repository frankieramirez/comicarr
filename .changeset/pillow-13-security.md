---
"comicarr": patch
---

Comicarr now uses Pillow 13, which fixes a batch of security bugs in how cover images inside downloaded comic archives are read. Installs running from source now need Python 3.11 or newer; the Docker image already uses Python 3.12.
