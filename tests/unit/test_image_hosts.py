#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""The cover-host allowlist and the CSP img-src directive share one source.

Two shipped fixes (#281, #298) were each a host added to one copy and not the
other. Asserting that individual hosts appear in the CSP would not have caught
the third drift, because a hand-written directive containing the right hosts
passes that check. These tests pin the wiring instead.
"""

from comicarr.app.core.image_hosts import ALLOWED_IMAGE_DOMAINS, csp_img_src_origins
from comicarr.app.core.middleware import SecurityHeadersMiddleware


class TestAllowlistContents:
    def test_allowlist_membership_is_pinned(self):
        """Deriving the CSP proves the wiring, not the contents.

        Every other test here iterates ALLOWED_IMAGE_DOMAINS, so the suite stays
        green for any contents of the set -- including one with a provider host
        dropped, which silently re-breaks that provider's covers. Pinning the set
        literally makes a removal a deliberate test edit; an addition stays a
        one-line change here alongside the one in image_hosts.
        """
        assert ALLOWED_IMAGE_DOMAINS == frozenset(
            {
                "comicvine.gamespot.com",
                "static.metron.cloud",
                "uploads.mangadex.org",
                "myanimelist.net",
                "cdn.myanimelist.net",
                "api-cdn.myanimelist.net",
            }
        )


class TestCspImgSrcOrigins:
    def test_every_allowed_host_becomes_an_https_origin(self):
        origins = csp_img_src_origins().split(" ")

        assert len(origins) == len(ALLOWED_IMAGE_DOMAINS)
        for host in ALLOWED_IMAGE_DOMAINS:
            assert "https://%s" % host in origins

    def test_output_is_stable_across_calls(self):
        assert csp_img_src_origins() == csp_img_src_origins()


class TestCspDerivesFromTheAllowlist:
    def test_csp_embeds_the_derived_fragment_verbatim(self):
        """A hand-maintained second copy fails this even when its hosts are correct."""
        assert csp_img_src_origins() in SecurityHeadersMiddleware.CSP

    def test_img_src_directive_allows_self_and_local_scheme_uris(self):
        """``blob:`` covers chat composer image previews built with createObjectURL."""
        directive = next(part for part in SecurityHeadersMiddleware.CSP.split("; ") if part.startswith("img-src "))

        assert directive == "img-src 'self' data: blob: " + csp_img_src_origins()


class TestSsrfGuardSharesTheSource:
    def test_image_fetch_reexports_the_canonical_allowlist(self):
        from comicarr.app.metadata import image_fetch

        assert image_fetch.ALLOWED_IMAGE_DOMAINS is ALLOWED_IMAGE_DOMAINS

    def test_mal_hosts_reachable_by_both_consumers(self):
        """The exact drift shipped today: allowed to fetch, blocked from rendering."""
        from comicarr.app.metadata.image_fetch import is_allowed_image_url

        for host in ("myanimelist.net", "cdn.myanimelist.net", "api-cdn.myanimelist.net"):
            assert is_allowed_image_url("https://%s/images/manga/2/253146l.jpg" % host) is True
            assert "https://%s" % host in SecurityHeadersMiddleware.CSP
