---
"comicarr": patch
---

Fix the Library table keeping a filtered-out series selected. Selecting a series and then filtering it out of view left it selected: the bulk bar still read "1 selected" and Delete, Pause, and Resume would still act on a series you could no longer see. The selection now follows the view — a series the filters remove is dropped from the selection, and comes back deselected when the filter is cleared. Selections still survive paging, since a series on another page is only out of sight, not filtered out.
