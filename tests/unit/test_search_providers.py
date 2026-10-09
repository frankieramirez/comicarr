from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

import comicarr
from comicarr import search
from comicarr.app.search.providers import effective_provider_plan
from comicarr.app.series import queries as series_queries


def _config(**overrides):
    values = {
        "ENABLE_DDL": True,
        "ENABLE_GETCOMICS": True,
        "ENABLE_EXTERNAL_SERVER": False,
        "EXPERIMENTAL": False,
        "NEWZNAB": False,
        "EXTRA_NEWZNABS": [],
        "ENABLE_TORRENT_SEARCH": True,
        "ENABLE_32P": False,
        "ENABLE_PUBLIC": False,
        "ENABLE_TORZNAB": True,
        "EXTRA_TORZNABS": [["Nyaa.si", "https://indexer.test/api", "1", "secret", "5070", "1", 1]],
        "PROVIDER_ORDER": {"0": "DDL(GetComics)"},
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_effective_provider_plan_includes_enabled_torznab_missing_from_saved_order():
    plan = effective_provider_plan(_config())

    assert [(candidate.name, candidate.kind, candidate.execution_name) for candidate in plan] == [
        ("DDL(GetComics)", "ddl", "DDL(GetComics)"),
        ("Nyaa.si", "torznab", "torznab: Nyaa.si"),
    ]
    assert all("secret" not in str(candidate) for candidate in plan)


def test_provider_order_routes_enabled_torznab_even_when_provider_order_is_stale(monkeypatch):
    config = _config()
    monkeypatch.setattr(comicarr, "CONFIG", config)
    monkeypatch.setattr(search.helpers, "block_provider_check", lambda _site: False)

    result = search.provider_order(initial_run=True)

    assert result["prov_order"] == ["DDL(GetComics)", "torznab: Nyaa.si"]
    assert result["torznab_info"] == [{"provider": "torznab: Nyaa.si", "info": tuple(config.EXTRA_TORZNABS[0])}]


def test_unnamed_provider_uses_safe_display_identity_without_exposing_its_endpoint():
    config = _config(
        EXTRA_TORZNABS=[["", "https://user:secret@indexer.test/api?apikey=token", "1", "secret", "5070", "1", 1]]
    )

    plan = effective_provider_plan(config)

    torznab = next(candidate for candidate in plan if candidate.kind == "torznab")
    assert torznab.name == "Torznab 1"
    assert "secret" not in repr(torznab)
    assert "indexer.test" not in repr(torznab)


def test_unnamed_provider_uses_safe_identity_during_legacy_execution(monkeypatch):
    config = _config(
        EXTRA_TORZNABS=[["", "https://user:secret@indexer.test/api?apikey=token", "1", "secret", "5070", "1", 1]]
    )
    monkeypatch.setattr(comicarr, "CONFIG", config)
    monkeypatch.setattr(search.helpers, "block_provider_check", lambda _site: False)

    result = search.provider_order()

    assert result["torznab_info"][0]["info"][0] == "Torznab 1"
    assert result["torznab_info"][0]["info"][1] == config.EXTRA_TORZNABS[0][1]


def test_encrypted_provider_key_is_plaintext_only_in_runtime_plan(tmp_path, monkeypatch):
    from comicarr import config as config_module
    from comicarr import encrypted as encrypted_module

    secure_dir = tmp_path / "secure"
    secure_dir.mkdir()
    monkeypatch.setattr(encrypted_module, "_fernet_instance", None)
    secret = "runtime-provider-secret"
    token = encrypted_module.Encryptor(secret, secure_dir=str(secure_dir)).encrypt_it()["password"]
    runtime_config = config_module.Config(str(tmp_path / "config.ini"))
    runtime_config.CONFIG_VERSION = 15
    runtime_config.SECURE_DIR = str(secure_dir)
    runtime_config.ENCRYPT_PASSWORDS = True
    runtime_config.EXTRA_NEWZNABS = []
    runtime_config.EXTRA_TORZNABS = [("Nyaa", "https://indexer.test", "1", token, "5070", "1", 101)]
    monkeypatch.setattr(comicarr, "CONFIG", runtime_config)

    runtime_config._load_provider_extra_credentials()
    plan = effective_provider_plan(_config(EXTRA_TORZNABS=runtime_config.EXTRA_TORZNABS))

    candidate = next(provider for provider in plan if provider.kind == "torznab")
    assert candidate.entry[3] == secret
    assert token not in repr(candidate)
    assert secret not in repr(candidate)


@pytest.mark.parametrize("provider_count", (1, 2))
def test_provider_search_exception_logs_redact_credentials(provider_count, monkeypatch):
    secret = "provider-exception-secret"
    messages = []
    executor = ThreadPoolExecutor(max_workers=2)

    def fail_search(_scenario):
        raise RuntimeError(f"request failed https://indexer.test/api?apikey={secret}")

    monkeypatch.setattr(search, "search_the_matrix", fail_search)
    monkeypatch.setattr(search, "get_search_executor", lambda: executor)

    def submit_background_future(executor, target, *, args=(), kwargs=None, name=None):
        return executor.submit(target, *args, **(kwargs or {}))

    # Main now routes provider work through the shutdown-owned registry. Keep
    # this unit test focused on redaction by injecting its local executor.
    monkeypatch.setattr(search, "submit_background_future", submit_background_future, raising=False)
    monkeypatch.setattr(
        search.logger, "warn", lambda message, *args: messages.append(message % args if args else message)
    )
    try:
        assert search.parallel_search_providers([{} for _ in range(provider_count)]) == {"status": False}
    finally:
        executor.shutdown(wait=True)

    rendered = "\n".join(messages)
    assert secret not in rendered
    assert "[redacted]" in rendered.lower()


def test_newznab_r_query_secret_is_redacted():
    message = search.redact_sensitive_text("https://indexer.test/api?r=newznab-r-secret")

    assert "newznab-r-secret" not in message
    assert "r=[redacted]" in message


def test_rss_result_log_summary_omits_provider_signed_link():
    secret = "rss-signed-link-secret"
    result = {
        "site": "Indexer",
        "title": "Example Comic",
        "link": f"https://indexer.test/download?token={secret}",
    }

    summary = search._rss_result_log_summary(result)

    assert summary == "rss result: site=Indexer title=Example Comic"
    assert secret not in summary
    assert "indexer.test" not in summary


def _override_config(**overrides):
    values = {
        "ENABLE_EXTERNAL_SERVER": True,
        "NEWZNAB": True,
        "USENET_RETENTION": 1500,
        "EXTRA_NEWZNABS": [["NZBGeek", "https://nzb.test/api", "1", "nzb-secret", "", "1"]],
        "EXTRA_TORZNABS": [
            ["Nyaa.si", "https://indexer.test/api", "1", "secret", "5070", "1", 1],
            ["MagIndex", "https://mag.test/api", "1", "mag-secret", "5070", "1", 1],
        ],
        "PROVIDER_ORDER": {"0": "DDL(GetComics)", "1": "DDL(External)", "2": "NZBGeek", "3": "Nyaa.si", "4": "MagIndex"},
    }
    values.update(overrides)
    return _config(**values)


def _names(plan):
    return [candidate.name for candidate in plan]


GLOBAL_ORDER = ["DDL(GetComics)", "DDL(External)", "NZBGeek", "Nyaa.si", "MagIndex"]


@pytest.mark.parametrize("override", (None, "", "not json", {"order": [], "exclude": []}))
def test_series_without_override_uses_the_global_plan(override):
    assert _names(effective_provider_plan(_override_config(), override=override)) == GLOBAL_ORDER


def test_series_override_puts_its_torznab_first_and_keeps_the_rest_in_global_order():
    plan = effective_provider_plan(_override_config(), override='{"order": ["MagIndex"]}')

    assert _names(plan) == ["MagIndex", "DDL(GetComics)", "DDL(External)", "NZBGeek", "Nyaa.si"]


def test_series_override_orders_several_names_and_matches_case_insensitively():
    plan = effective_provider_plan(_override_config(), override={"order": ["magindex", "nyaa.si"]})

    assert _names(plan) == ["MagIndex", "Nyaa.si", "DDL(GetComics)", "DDL(External)", "NZBGeek"]


def test_excluded_provider_is_absent_for_that_series_only(monkeypatch):
    monkeypatch.setattr(comicarr, "CONFIG", _override_config())
    monkeypatch.setattr(search.helpers, "block_provider_check", lambda _site: False)
    stored = {"wizard": '{"order": ["MagIndex"], "exclude": ["DDL(GetComics)"]}'}
    monkeypatch.setattr(series_queries, "get_comic_provider_override", lambda comic_id: stored.get(comic_id))

    wizard = search.provider_order(comic_id="wizard")
    other = search.provider_order(comic_id="other")

    assert wizard["prov_order"] == ["torznab: MagIndex", "DDL(External)", "newznab: NZBGeek", "torznab: Nyaa.si"]
    assert wizard["totalproviders"] == 4
    assert wizard["series_override"] is True
    assert other["prov_order"] == [
        "DDL(GetComics)",
        "DDL(External)",
        "newznab: NZBGeek",
        "torznab: Nyaa.si",
        "torznab: MagIndex",
    ]
    assert other["series_override"] is False


def test_override_ignores_unknown_names_and_never_enables_a_disabled_provider():
    config = _override_config(ENABLE_EXTERNAL_SERVER=False, ENABLE_32P=False)
    override = {"order": ["Gone Indexer", "DDL(External)", "32p", "Nyaa.si"], "exclude": ["Also Gone"]}

    plan = effective_provider_plan(config, override=override)

    assert _names(plan) == ["Nyaa.si", "DDL(GetComics)", "NZBGeek", "MagIndex"]


def test_override_keeps_blocked_providers_blocked():
    plan = effective_provider_plan(
        _override_config(),
        is_blocked=lambda name: name == "MagIndex",
        override={"order": ["MagIndex"]},
    )

    assert plan[0].name == "MagIndex"
    assert plan[0].blocked is True


def _logged_search_init(monkeypatch, *, override, content_type, config=None):
    messages = []
    monkeypatch.setattr(comicarr, "CONFIG", config or _override_config())
    monkeypatch.setattr(search.helpers, "block_provider_check", lambda _site: False)
    monkeypatch.setattr(search.helpers, "get_issue_title", lambda *a, **k: None)
    monkeypatch.setattr(series_queries, "get_comic_provider_override", lambda comic_id: override)

    def capture(message, *args, **kwargs):
        messages.append(str(message))
        if str(message).startswith("search provider order is"):
            raise RuntimeError("captured-provider-order")

    for level in ("fdebug", "warning", "error"):
        monkeypatch.setattr(search.logger, level, capture)
    try:
        result = search.search_init(
            "Wizard", "1", "1991", "1991", None, "1991-07-01", "1991-07-01", "issue-1",
            ComicID="wizard", content_type=content_type,
        )
    except RuntimeError as e:
        assert str(e) == "captured-provider-order"
        result = None
    return result, messages


def test_manga_series_still_drops_ddl_when_its_override_lists_ddl_first(monkeypatch):
    _result, messages = _logged_search_init(
        monkeypatch,
        override='{"order": ["DDL(GetComics)", "MagIndex"]}',
        content_type="manga",
    )

    logged = next(message for message in messages if message.startswith("search provider order is"))
    assert "DDL(" not in logged
    assert "['torznab: MagIndex', 'newznab: NZBGeek', 'torznab: Nyaa.si']" in logged


def test_override_that_excludes_every_provider_warns_and_aborts(monkeypatch):
    config = _override_config(NEWZNAB=False, ENABLE_TORZNAB=False, ENABLE_EXTERNAL_SERVER=False)
    result, messages = _logged_search_init(
        monkeypatch,
        override='{"exclude": ["DDL(GetComics)"]}',
        content_type="comic",
        config=config,
    )

    assert result == ({"status": False}, None)
    assert any("provider override for Wizard excludes every enabled search provider" in m for m in messages)


def test_interactive_release_search_plan_applies_the_series_override(monkeypatch):
    from comicarr.app.core.context import AppContext
    from comicarr.app.search import interactive

    monkeypatch.setattr(interactive.helpers, "block_provider_check", lambda _site: False)
    stored = {"wizard": '{"order": ["MagIndex"], "exclude": ["DDL(GetComics)"]}'}
    monkeypatch.setattr(series_queries, "get_comic_provider_override", lambda comic_id: stored.get(comic_id))
    ctx = AppContext(config=_override_config())

    assert _names(interactive._provider_plan(ctx, "wizard")) == ["MagIndex", "DDL(External)", "NZBGeek", "Nyaa.si"]
    assert _names(interactive._provider_plan(ctx, "other")) == GLOBAL_ORDER
