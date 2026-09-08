#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Context-local callbacks for reporting search provider progress."""

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Callable, Iterator

ProviderComplete = Callable[[str], None]
ProviderFailure = Callable[[str, str, str], None]

_progress: ContextVar[tuple[ProviderComplete | None, ProviderFailure | None] | None] = ContextVar(
    "search_progress", default=None
)


@contextmanager
def report_progress(
    on_provider_complete: ProviderComplete | None = None,
    on_provider_failure: ProviderFailure | None = None,
) -> Iterator[None]:
    """Route provider progress callbacks for the duration of a context."""
    token = _progress.set((on_provider_complete, on_provider_failure))
    try:
        yield
    finally:
        _progress.reset(token)


def report_provider_complete(provider: str) -> None:
    """Report a provider completion to the active collector, if any."""
    callbacks = _progress.get()
    if callbacks is not None and callbacks[0] is not None:
        callbacks[0](str(provider))


def report_provider_failure(provider: str, code: str, detail: str) -> None:
    """Report a provider failure to the active collector, if any."""
    callbacks = _progress.get()
    if callbacks is not None and callbacks[1] is not None:
        callbacks[1](str(provider), str(code), str(detail))
