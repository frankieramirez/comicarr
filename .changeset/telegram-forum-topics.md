---
"comicarr": minor
---

Telegram notifications can now post into a specific forum topic instead of a supergroup's General thread. In **Settings → Notifications**, append the topic ID to the chat ID in **User/Chat ID**, for example `-1007356238347:15`, and every notification Comicarr sends — text and cover images alike — lands in that topic. A plain chat ID or `@username` keeps working exactly as before, and a value whose suffix is not a topic number is still treated as an ordinary chat ID rather than being split.
