"""
Global pytest fixtures and configuration for Comicarr tests.
"""

import os
import sys
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Add project root to Python path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# =============================================================================
# Mock Missing Optional Dependencies
# =============================================================================
# Comicarr has many optional dependencies that may not be installed during testing.
# We mock these at the module level before any comicarr imports happen.

# Create mock modules for optional dependencies
MOCK_MODULES = [
    "transmissionrpc",
    "deluge_client",
    "qbittorrent",
    "rtorrent",
    "bencode",
    "mega",
    "mega.Mega",
    "mediafire",
    "megaup",
    "openai",
]

for mod_name in MOCK_MODULES:
    if mod_name not in sys.modules:
        mock = MagicMock()
        # For 'mega' module, we need Mega class
        if mod_name == "mega":
            mock.Mega = MagicMock()
        sys.modules[mod_name] = mock


# =============================================================================
# Path Fixtures
# =============================================================================


@pytest.fixture(scope="session")
def project_root() -> Path:
    """Return the project root directory."""
    return PROJECT_ROOT


@pytest.fixture(scope="session")
def test_data_dir() -> Path:
    """Return the path to test fixtures directory."""
    return PROJECT_ROOT / "tests" / "fixtures"


@pytest.fixture(scope="session")
def api_responses_dir(test_data_dir) -> Path:
    """Return the path to API response fixtures."""
    return test_data_dir / "api_responses"


@pytest.fixture(scope="session")
def comic_files_dir(test_data_dir) -> Path:
    """Return the path to comic file fixtures."""
    return test_data_dir / "comic_files"


# =============================================================================
# Database Fixtures
# =============================================================================


@pytest.fixture
def temp_db(tmp_path) -> str:
    """
    Create a temporary SQLite database with Comicarr's schema.

    Returns the path to the database file.
    """
    db_path = tmp_path / "test_comicarr.db"

    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    # Create core tables matching Comicarr's schema
    cursor.executescript(
        """
        CREATE TABLE IF NOT EXISTS comics (
            ComicID TEXT PRIMARY KEY,
            ComicName TEXT,
            ComicSortName TEXT,
            ComicYear TEXT,
            ComicPublisher TEXT,
            ComicPublished TEXT,
            ComicImage TEXT,
            Total INTEGER,
            Status TEXT,
            LatestIssue TEXT,
            LatestDate TEXT,
            Description TEXT,
            ComicVersion TEXT,
            AgeRating TEXT,
            ComicLocation TEXT,
            DetailURL TEXT,
            LastUpdated TEXT,
            AlternateSearch TEXT,
            UseFuzzy TEXT,
            ComicImageURL TEXT,
            ComicImageALTURL TEXT,
            DynamicComicName TEXT,
            Type TEXT,
            Corrected_SeriesYear TEXT,
            Corrected_Type TEXT,
            ForceContinuing INTEGER,
            AlternateFileName TEXT
        );

        CREATE TABLE IF NOT EXISTS issues (
            IssueID TEXT PRIMARY KEY,
            ComicID TEXT,
            ComicName TEXT,
            Issue_Number TEXT,
            IssueName TEXT,
            IssueDate TEXT,
            ReleaseDate TEXT,
            DigitalDate TEXT,
            Int_IssueNumber INTEGER,
            Status TEXT,
            Location TEXT,
            DateAdded TEXT,
            ImageURL TEXT,
            ImageURL_ALT TEXT,
            AltIssueNumber TEXT,
            IssueDate_Edit TEXT
        );

        CREATE TABLE IF NOT EXISTS annuals (
            IssueID TEXT PRIMARY KEY,
            ComicID TEXT,
            ComicName TEXT,
            Issue_Number TEXT,
            IssueName TEXT,
            IssueDate TEXT,
            ReleaseDate TEXT,
            Int_IssueNumber INTEGER,
            Status TEXT,
            Location TEXT,
            DateAdded TEXT,
            ReleaseComicID TEXT,
            ReleaseComicName TEXT
        );

        CREATE TABLE IF NOT EXISTS snatched (
            IssueID TEXT,
            ComicID TEXT,
            ComicName TEXT,
            Issue_Number TEXT,
            Size INTEGER,
            Status TEXT,
            DateAdded TEXT,
            Provider TEXT,
            Hash TEXT
        );

        CREATE TABLE IF NOT EXISTS nzblog (
            IssueID TEXT,
            NZBName TEXT,
            SAESSION TEXT,
            Provider TEXT
        );

        CREATE TABLE IF NOT EXISTS weekly (
            SHIPDATE TEXT,
            PUBLISHER TEXT,
            ISSUE TEXT,
            COMIC TEXT,
            EXTRA TEXT,
            STATUS TEXT,
            ComicID TEXT,
            IssueID TEXT,
            DynamicName TEXT,
            weeknumber TEXT,
            year TEXT,
            volume TEXT,
            seriesyear TEXT,
            annession TEXT,
            format TEXT,
            rowid INTEGER PRIMARY KEY AUTOINCREMENT
        );

        CREATE TABLE IF NOT EXISTS readlist (
            IssueID TEXT,
            ComicID TEXT,
            ComicName TEXT,
            Issue_Number TEXT,
            Status TEXT,
            DateAdded TEXT,
            Location TEXT,
            inCacheDIR TEXT,
            readinglist TEXT,
            storyarcid TEXT
        );

        CREATE TABLE IF NOT EXISTS storyarcs (
            StoryArcID TEXT,
            ComicID TEXT,
            IssueID TEXT,
            StoryArc TEXT,
            IssueArcID TEXT,
            ReadingOrder INTEGER,
            TotalIssues INTEGER,
            Status TEXT,
            IssueDate TEXT,
            cv_arcid TEXT,
            cv_status TEXT,
            Location TEXT,
            DynamicComicName TEXT
        );

        CREATE TABLE IF NOT EXISTS ai_activity_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            feature_type TEXT,
            action_description TEXT,
            model TEXT,
            prompt_tokens INTEGER,
            completion_tokens INTEGER,
            latency_ms INTEGER,
            success TEXT,
            error_message TEXT,
            entity_type TEXT,
            entity_id TEXT
        );

        CREATE TABLE IF NOT EXISTS ai_metadata_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entity_type TEXT,
            entity_id TEXT,
            field_name TEXT,
            original_value TEXT,
            ai_value TEXT,
            source TEXT,
            provider TEXT,
            created_at TEXT
        );

        CREATE TABLE IF NOT EXISTS ai_cache (
            cache_key TEXT UNIQUE,
            cache_type TEXT,
            data TEXT,
            created_at TEXT,
            expires_at TEXT
        );
    """
    )

    conn.commit()
    conn.close()

    yield str(db_path)


@pytest.fixture
def mock_db_connection(temp_db):
    """
    Create a mock database connection using the temp database.

    This patches comicarr.db.DBConnection to use the temp database.
    """
    with patch("comicarr.db.DBConnection") as mock_class:
        # Create a real connection to the temp db
        conn = sqlite3.connect(temp_db)
        conn.row_factory = sqlite3.Row

        mock_instance = MagicMock()

        def mock_select(query, args=None):
            cursor = conn.cursor()
            if args:
                cursor.execute(query, args)
            else:
                cursor.execute(query)
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

        def mock_selectone(query, args=None):
            result = mock_select(query, args)
            return result[0] if result else None

        def mock_action(query, args=None):
            cursor = conn.cursor()
            if args:
                cursor.execute(query, args)
            else:
                cursor.execute(query)
            conn.commit()
            return cursor.lastrowid

        mock_instance.select = mock_select
        mock_instance.selectone = mock_selectone
        mock_instance.action = mock_action
        mock_instance.connection = conn

        mock_class.return_value = mock_instance
        mock_class.return_value.__enter__ = MagicMock(return_value=mock_instance)
        mock_class.return_value.__exit__ = MagicMock(return_value=False)

        yield mock_instance

        conn.close()


# =============================================================================
# Comicarr Configuration Fixtures
# =============================================================================


@pytest.fixture
def mock_comicarr_globals(tmp_path, monkeypatch):
    """
    Mock comicarr global configuration and paths.

    Sets up a clean test environment with temporary directories.
    """
    data_dir = tmp_path / "comicarr_data"
    data_dir.mkdir()

    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()

    log_dir = tmp_path / "logs"
    log_dir.mkdir()

    # Import comicarr and patch globals
    import comicarr

    monkeypatch.setattr(comicarr, "DATA_DIR", str(data_dir))
    monkeypatch.setattr(comicarr, "PROG_DIR", str(tmp_path))
    monkeypatch.setattr(comicarr, "CACHE_DIR", str(cache_dir))
    monkeypatch.setattr(comicarr, "LOG_DIR", str(log_dir))

    return {
        "data_dir": data_dir,
        "prog_dir": tmp_path,
        "cache_dir": cache_dir,
        "log_dir": log_dir,
    }


@pytest.fixture
def mock_config():
    """
    Create a mock configuration object with sensible defaults.
    """
    config = MagicMock()

    # Common config values
    config.API_ENABLED = True
    config.API_KEY = "test_api_key_32_characters_here"
    config.HTTP_HOST = "0.0.0.0"
    config.HTTP_PORT = 8090
    config.HTTP_ROOT = "/"
    config.COMICVINE_API = "test_cv_api_key"
    config.LOG_LEVEL = 1
    config.DOWNLOAD_SCAN_INTERVAL = 5
    config.COMIC_DIR = "/comics"
    config.DESTINATION_DIR = "/downloads"

    return config


# =============================================================================
# HTTP Mocking Fixtures
# =============================================================================


@pytest.fixture
def mock_requests():
    """
    Fixture for mocking HTTP requests using the responses library.

    Usage:
        def test_api_call(mock_requests):
            mock_requests.add(
                responses.GET,
                "https://api.example.com/data",
                json={"key": "value"},
                status=200
            )
            # ... test code that makes HTTP request
    """
    import responses

    with responses.RequestsMock() as rsps:
        yield rsps


# =============================================================================
# Time Mocking Fixtures
# =============================================================================


@pytest.fixture
def frozen_time():
    """
    Fixture for freezing time in tests.

    Usage:
        def test_time_based(frozen_time):
            with frozen_time("2024-01-15 12:00:00"):
                # ... test code
    """
    from freezegun import freeze_time

    return freeze_time


# =============================================================================
# File System Fixtures
# =============================================================================


@pytest.fixture
def temp_comic_dir(tmp_path):
    """
    Create a temporary directory structure for comics.
    """
    comic_dir = tmp_path / "comics"
    comic_dir.mkdir()

    # Create some sample subdirectories
    (comic_dir / "Spider-Man (2020)").mkdir()
    (comic_dir / "Batman (2019)").mkdir()

    return comic_dir


@pytest.fixture
def sample_cbz_file(tmp_path):
    """
    Create a minimal valid CBZ file for testing.

    CBZ files are just ZIP archives with comic images.
    """
    import zipfile
    from io import BytesIO

    # Create a minimal 1x1 pixel image
    from PIL import Image

    img_buffer = BytesIO()
    img = Image.new("RGB", (1, 1), color="white")
    img.save(img_buffer, format="PNG")
    img_data = img_buffer.getvalue()

    cbz_path = tmp_path / "test_comic.cbz"

    with zipfile.ZipFile(cbz_path, "w") as zf:
        zf.writestr("page_001.png", img_data)
        zf.writestr("page_002.png", img_data)

    return cbz_path


# =============================================================================
# Utility Fixtures
# =============================================================================


@pytest.fixture
def capture_logs(caplog):
    """
    Capture log output for assertions.

    Usage:
        def test_logging(capture_logs):
            # ... code that logs
            assert "Expected message" in capture_logs.text
    """
    import logging

    caplog.set_level(logging.DEBUG)
    return caplog


# =============================================================================
# FastAPI AppContext Fixtures
# =============================================================================


@pytest.fixture
def test_context():
    """
    Create an AppContext instance with sensible test defaults.

    Uses in-memory SQLite, no-op scheduler, and mock provider sessions.
    Override fields by modifying the returned object.
    """
    from comicarr.app.core.context import AppContext

    config = MagicMock()
    config.API_KEY = "test_api_key_32chars_here_pad00"
    config.ENABLE_HTTPS = False
    config.HTTP_USERNAME = "testuser"
    config.HTTP_PASSWORD = "testhash"
    config.SECURE_DIR = str(Path(tempfile.gettempdir()) / "comicarr_test_secure")
    config.DESTINATION_DIR = "/tmp/comics"
    config.COMIC_DIR = "/tmp/comics"
    config.OPDS_USERNAME = None
    config.OPDS_PASSWORD = None
    config.AI_BASE_URL = None
    config.AI_API_KEY = None
    config.AI_MODEL = None
    config.AI_TIMEOUT = 30
    config.AI_RPM_LIMIT = 20
    config.AI_DAILY_TOKEN_LIMIT = 100000
    config.AI_CIRCUIT_THRESHOLD = 5
    config.AI_CIRCUIT_COOLDOWN = 300

    return AppContext(
        prog_dir="/tmp/comicarr_test",
        data_dir="/tmp/comicarr_test/data",
        db_file=":memory:",
        config=config,
        scheduler=MagicMock(),
        jwt_secret_key=b"test_secret_key_32_bytes_padding!",
        jwt_generation=0,
        sse_key="test_sse_key",
        download_apikey="test_dl_key",
    )
