#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Build a post-processing request or run the way the facade does.

``postprocessing._run_processor`` makes a ``PostProcessRequest`` and hands it
to ``process_download`` with the real folder matcher and legacy
collaborators. Tests that drive one phase build the ``PostProcessRun`` that
phase would get.
"""

from __future__ import annotations

from comicarr.app.downloads.postprocess_pipeline import (
    PostProcessContext,
    PostProcessRequest,
    PostProcessRun,
    process_download,
)


def folder_run(
    nzb_name,
    nzb_folder,
    issueid=None,
    *,
    comicid=None,
    issuearcid=None,
    apicall=False,
    ddl=False,
    journal_release_key=None,
    module="[POST-PROCESSING]",
):
    """The run state a request with these inputs carries."""
    return PostProcessRun(
        context=PostProcessContext(
            issue_id=issueid,
            issue_arc_id=issuearcid,
            comic_id=comicid,
            nzb_name=nzb_name,
            nzb_folder=str(nzb_folder),
            api_call=apicall is True,
            ddl=ddl is True,
            canonical_release_key=journal_release_key,
            log_module=module,
        ),
        nzb_name=nzb_name,
        nzb_folder=str(nzb_folder),
        module=module,
    )


def process(nzb_name, nzb_folder, issueid=None, *, comicid=None, apicall=False, ddl=False, journal_release_key=None):
    """Run one request through the real pipeline; return its messages or None."""
    from comicarr import postprocessor

    request = PostProcessRequest(
        nzb_name,
        str(nzb_folder),
        issue_id=issueid,
        comic_id=comicid,
        api_call=apicall,
        ddl=ddl,
        journal_release_key=journal_release_key,
    )
    return process_download(request, match=postprocessor.match_folder, deps=postprocessor.pipeline_deps())
