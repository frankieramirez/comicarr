---
"comicarr": patch
---

Fix the Library page dropping a deep-linked page number. Opening or reloading `/library?page=2` rendered the first page and stripped `page` from the URL, so bookmarks and shared links always landed on page one. Two independent causes had to be addressed: the page-clamp effect ran while the series list was still empty, and TanStack Table's automatic page reset fired after the first render that had rows, undoing the page the URL asked for. A page number that is genuinely out of range still settles onto the last page, and changing the row set still returns you to the first page.
