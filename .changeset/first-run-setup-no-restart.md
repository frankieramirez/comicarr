---
"comicarr": patch
---

Creating your account on first run now takes you straight to the sign-in page. The setup screen used to wait a minute for a restart that never happened and then say "Server restart timed out". Stopping the container (`docker stop`, or an update in Unraid or Portainer) also no longer stalls until Docker force-kills Comicarr when it happens while the weekly pull-list check is waiting to retry a pull-list source that is down.
