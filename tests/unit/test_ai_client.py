#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Tests for comicarr.app.ai.client."""

from unittest.mock import MagicMock, patch

import pytest


class _MockConfig:
    """Minimal config object for testing."""

    def __init__(self, **kwargs):
        self.AI_BASE_URL = kwargs.get("AI_BASE_URL", None)
        self.AI_API_KEY = kwargs.get("AI_API_KEY", None)
        self.AI_MODEL = kwargs.get("AI_MODEL", None)


class TestCreateAiClients:
    @patch("comicarr.app.ai.client.OpenAI")
    @patch("comicarr.app.ai.client.AsyncOpenAI")
    def test_valid_config_returns_clients(self, mock_async, mock_sync):
        mock_sync.return_value = MagicMock()
        mock_async.return_value = MagicMock()

        from comicarr.app.ai.client import create_ai_clients

        config = _MockConfig(
            AI_BASE_URL="http://localhost:11434/v1",
            AI_API_KEY="sk-test-key",
            AI_MODEL="llama3",
        )
        sync_client, async_client = create_ai_clients(config)
        assert sync_client is not None
        assert async_client is not None
        mock_sync.assert_called_once()
        mock_async.assert_called_once()

    def test_empty_config_returns_none(self):
        from comicarr.app.ai.client import create_ai_clients

        config = _MockConfig()
        sync_client, async_client = create_ai_clients(config)
        assert sync_client is None
        assert async_client is None

    def test_missing_model_returns_none(self):
        from comicarr.app.ai.client import create_ai_clients

        config = _MockConfig(
            AI_BASE_URL="http://localhost:11434/v1",
            AI_API_KEY="sk-test-key",
        )
        sync_client, async_client = create_ai_clients(config)
        assert sync_client is None
        assert async_client is None

    def test_failed_decryption_returns_none(self):
        from comicarr.app.ai.client import create_ai_clients

        config = _MockConfig(
            AI_BASE_URL="http://localhost:11434/v1",
            AI_API_KEY="gAAAAABf1234encrypted_key_here",
            AI_MODEL="llama3",
        )
        sync_client, async_client = create_ai_clients(config)
        assert sync_client is None
        assert async_client is None

    def test_file_scheme_rejected(self):
        from comicarr.app.ai.client import create_ai_clients

        config = _MockConfig(
            AI_BASE_URL="file:///etc/passwd",
            AI_API_KEY="sk-test-key",
            AI_MODEL="llama3",
        )
        sync_client, async_client = create_ai_clients(config)
        assert sync_client is None
        assert async_client is None

    def test_ftp_scheme_rejected(self):
        from comicarr.app.ai.client import create_ai_clients

        config = _MockConfig(
            AI_BASE_URL="ftp://evil.com/v1",
            AI_API_KEY="sk-test-key",
            AI_MODEL="llama3",
        )
        sync_client, async_client = create_ai_clients(config)
        assert sync_client is None
        assert async_client is None

    def test_http_non_local_rejected(self):
        from comicarr.app.ai.client import create_ai_clients

        config = _MockConfig(
            AI_BASE_URL="http://api.openai.com/v1",
            AI_API_KEY="sk-test-key",
            AI_MODEL="gpt-4",
        )
        sync_client, async_client = create_ai_clients(config)
        assert sync_client is None
        assert async_client is None

    @patch("comicarr.app.ai.client.OpenAI")
    @patch("comicarr.app.ai.client.AsyncOpenAI")
    def test_https_non_local_accepted(self, mock_async, mock_sync):
        mock_sync.return_value = MagicMock()
        mock_async.return_value = MagicMock()

        from comicarr.app.ai.client import create_ai_clients

        config = _MockConfig(
            AI_BASE_URL="https://api.openai.com/v1",
            AI_API_KEY="sk-test-key",
            AI_MODEL="gpt-4",
        )
        sync_client, async_client = create_ai_clients(config)
        assert sync_client is not None
        assert async_client is not None

    @patch("comicarr.app.ai.client.OpenAI")
    @patch("comicarr.app.ai.client.AsyncOpenAI")
    def test_http_localhost_accepted(self, mock_async, mock_sync):
        mock_sync.return_value = MagicMock()
        mock_async.return_value = MagicMock()

        from comicarr.app.ai.client import create_ai_clients

        config = _MockConfig(
            AI_BASE_URL="http://127.0.0.1:11434/v1",
            AI_API_KEY="sk-test-key",
            AI_MODEL="llama3",
        )
        sync_client, async_client = create_ai_clients(config)
        assert sync_client is not None
        assert async_client is not None
