#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.


"""POST /api/storyarcs adds an arc from arc search (#1503)."""

from comicarr.app.storyarcs import service


def test_add_arc_starts_the_background_add(monkeypatch):
    started = {}

    def fake_start(target, kwargs, name):
        started.update(kwargs=kwargs, name=name)

    monkeypatch.setattr(service, "start_background_thread", fake_start)

    result = service.add_arc(
        {"arcid": "4045-1", "cvarcid": "4045-1", "storyarcname": "Arc", "storyarcissues": "3", "arclist": "1,1|2,2"}
    )

    assert result["success"] is True
    assert started["name"] == "StoryArcAdd"
    assert started["kwargs"]["cvarcid"] == "4045-1"
    assert started["kwargs"]["storyarcissues"] == 3


def test_add_arc_refuses_an_arc_with_no_issue_list(monkeypatch):
    monkeypatch.setattr(service, "start_background_thread", lambda *a, **k: None)
    result = service.add_arc({"cvarcid": "1", "storyarcname": "Arc", "arclist": ""})
    assert result["success"] is False


def test_route_exists_for_post():
    from comicarr.app.storyarcs.router import router

    assert any(route.path == "/api/storyarcs" and "POST" in route.methods for route in router.routes)
