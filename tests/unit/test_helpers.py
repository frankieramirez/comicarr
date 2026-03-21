"""
Unit tests for comicarr/helpers.py utility functions.

These tests cover pure utility functions that don't require external dependencies.
"""

import pytest
from hypothesis import given, strategies as st, assume

# Import the module under test
# Note: Some imports may need comicarr to be initialized, so we import inside tests
# when necessary to avoid import-time errors


class TestCheckedFunction:
    """Tests for the checked() function."""

    def test_checked_with_true_value(self):
        from comicarr.helpers import checked

        assert checked(True) == "Checked"

    def test_checked_with_false_value(self):
        from comicarr.helpers import checked

        assert checked(False) == ""

    def test_checked_with_truthy_string(self):
        from comicarr.helpers import checked

        assert checked("yes") == "Checked"

    def test_checked_with_empty_string(self):
        from comicarr.helpers import checked

        assert checked("") == ""

    def test_checked_with_none(self):
        from comicarr.helpers import checked

        assert checked(None) == ""

    def test_checked_with_number(self):
        from comicarr.helpers import checked

        assert checked(1) == "Checked"
        assert checked(0) == ""


class TestRadioFunction:
    """Tests for the radio() function."""

    def test_radio_matching_position(self):
        from comicarr.helpers import radio

        assert radio("option1", "option1") == "Checked"

    def test_radio_non_matching_position(self):
        from comicarr.helpers import radio

        assert radio("option1", "option2") == ""

    def test_radio_with_numbers(self):
        from comicarr.helpers import radio

        assert radio(1, 1) == "Checked"
        assert radio(1, 2) == ""

    def test_radio_with_none(self):
        from comicarr.helpers import radio

        assert radio(None, None) == "Checked"
        assert radio(None, "value") == ""


class TestLatinToAscii:
    """Tests for the latinToAscii() function."""

    def test_plain_ascii_unchanged(self):
        from comicarr.helpers import latinToAscii

        assert latinToAscii("Hello World") == "Hello World"

    def test_accented_a_characters(self):
        from comicarr.helpers import latinToAscii

        assert latinToAscii("\xc0") == "A"  # À
        assert latinToAscii("\xc1") == "A"  # Á
        assert latinToAscii("\xe0") == "a"  # à
        assert latinToAscii("\xe1") == "a"  # á

    def test_accented_e_characters(self):
        from comicarr.helpers import latinToAscii

        assert latinToAscii("\xc8") == "E"  # È
        assert latinToAscii("\xc9") == "E"  # É
        assert latinToAscii("\xe8") == "e"  # è
        assert latinToAscii("\xe9") == "e"  # é
        assert latinToAscii("Café") == "Cafe"

    def test_german_umlaut(self):
        from comicarr.helpers import latinToAscii

        assert latinToAscii("\xdc") == "U"  # Ü
        assert latinToAscii("\xfc") == "u"  # ü

    def test_ae_ligature(self):
        from comicarr.helpers import latinToAscii

        assert latinToAscii("\xc6") == "Ae"  # Æ
        assert latinToAscii("\xe6") == "ae"  # æ

    def test_special_characters(self):
        from comicarr.helpers import latinToAscii

        assert latinToAscii("\xa9") == "{C}"  # ©
        assert latinToAscii("\xae") == "{R}"  # ®
        assert latinToAscii("\xb0") == "{degrees}"  # °

    def test_empty_string(self):
        from comicarr.helpers import latinToAscii

        assert latinToAscii("") == ""

    def test_mixed_content(self):
        from comicarr.helpers import latinToAscii

        result = latinToAscii("naïve résumé")
        assert "naive" in result
        assert "resume" in result


class TestConvertMilliseconds:
    """Tests for the convert_milliseconds() function."""

    def test_under_one_minute(self):
        from comicarr.helpers import convert_milliseconds

        result = convert_milliseconds(30000)  # 30 seconds
        assert result == "00:30"

    def test_one_minute(self):
        from comicarr.helpers import convert_milliseconds

        result = convert_milliseconds(60000)  # 60 seconds
        assert result == "01:00"

    def test_under_one_hour(self):
        from comicarr.helpers import convert_milliseconds

        result = convert_milliseconds(150000)  # 2.5 minutes
        assert result == "02:30"

    def test_over_one_hour(self):
        from comicarr.helpers import convert_milliseconds

        result = convert_milliseconds(3661000)  # 1 hour, 1 minute, 1 second
        assert result == "01:01:01"


class TestConvertSeconds:
    """Tests for the convert_seconds() function."""

    def test_under_one_minute(self):
        from comicarr.helpers import convert_seconds

        result = convert_seconds(30)
        assert result == "00:30"

    def test_one_minute(self):
        from comicarr.helpers import convert_seconds

        result = convert_seconds(60)
        assert result == "01:00"

    def test_under_one_hour(self):
        from comicarr.helpers import convert_seconds

        result = convert_seconds(150)  # 2.5 minutes
        assert result == "02:30"

    def test_over_one_hour(self):
        from comicarr.helpers import convert_seconds

        result = convert_seconds(3661)  # 1 hour, 1 minute, 1 second
        assert result == "01:01:01"


class TestToday:
    """Tests for the today() function."""

    def test_returns_iso_format(self):
        from comicarr.helpers import today

        result = today()
        # Should be in YYYY-MM-DD format
        assert len(result) == 10
        assert result[4] == "-"
        assert result[7] == "-"

    def test_returns_string(self):
        from comicarr.helpers import today

        result = today()
        assert isinstance(result, str)

    def test_with_frozen_time(self, frozen_time):
        from comicarr.helpers import today

        with frozen_time("2024-06-15"):
            assert today() == "2024-06-15"


class TestNow:
    """Tests for the now() function."""

    def test_default_format(self):
        from comicarr.helpers import now

        result = now()
        # Default format: YYYY-MM-DD HH:MM:SS
        assert len(result) == 19
        assert result[4] == "-"
        assert result[10] == " "
        assert result[13] == ":"

    def test_custom_format(self):
        from comicarr.helpers import now

        result = now("%Y/%m/%d")
        assert "/" in result

    def test_with_frozen_time(self, frozen_time):
        from comicarr.helpers import now

        with frozen_time("2024-06-15 14:30:45"):
            assert now() == "2024-06-15 14:30:45"


class TestBytesToMb:
    """Tests for the bytes_to_mb() function."""

    def test_one_megabyte(self):
        from comicarr.helpers import bytes_to_mb

        result = bytes_to_mb(1048576)
        assert result == "1.0 MB"

    def test_half_megabyte(self):
        from comicarr.helpers import bytes_to_mb

        result = bytes_to_mb(524288)
        assert result == "0.5 MB"

    def test_zero_bytes(self):
        from comicarr.helpers import bytes_to_mb

        result = bytes_to_mb(0)
        assert result == "0.0 MB"

    def test_large_size(self):
        from comicarr.helpers import bytes_to_mb

        result = bytes_to_mb(104857600)  # 100 MB
        assert result == "100.0 MB"


class TestHumanSize:
    """Tests for the human_size() function."""

    def test_single_byte(self):
        from comicarr.helpers import human_size

        assert human_size(1) == "1 byte"

    def test_multiple_bytes(self):
        from comicarr.helpers import human_size

        assert human_size(500) == "500 bytes"

    def test_kilobytes(self):
        from comicarr.helpers import human_size

        result = human_size(1024)
        assert "KB" in result

    def test_megabytes(self):
        from comicarr.helpers import human_size

        result = human_size(1048576)  # 1 MB
        assert "MB" in result

    def test_gigabytes(self):
        from comicarr.helpers import human_size

        result = human_size(1073741824)  # 1 GB
        assert "GB" in result

    def test_none_input(self):
        from comicarr.helpers import human_size

        result = human_size(None)
        assert result == "0 bytes"

    def test_zero_input(self):
        from comicarr.helpers import human_size

        result = human_size(0)
        assert "0" in result

    @given(st.integers(min_value=0, max_value=10**15))
    def test_always_returns_string(self, size):
        """Property: human_size always returns a non-empty string."""
        from comicarr.helpers import human_size

        result = human_size(size)
        assert isinstance(result, str)
        assert len(result) > 0

    @given(st.integers(min_value=2, max_value=10**15))
    def test_no_singular_for_multiple(self, size):
        """Property: sizes > 1 byte should not say 'byte' (singular)."""
        from comicarr.helpers import human_size

        result = human_size(size)
        # Should say "bytes", "KB", "MB", etc., not "byte"
        if "byte" in result.lower():
            assert "bytes" in result


class TestHuman2Bytes:
    """Tests for the human2bytes() function."""

    def test_megabytes(self):
        from comicarr.helpers import human2bytes

        assert human2bytes("1M") == 1048576

    def test_gigabytes(self):
        from comicarr.helpers import human2bytes

        assert human2bytes("1G") == 1073741824

    def test_kilobytes(self):
        from comicarr.helpers import human2bytes

        assert human2bytes("1K") == 1024

    def test_bytes(self):
        from comicarr.helpers import human2bytes

        assert human2bytes("1B") == 1

    def test_zero(self):
        from comicarr.helpers import human2bytes

        assert human2bytes("0M") == 0

    def test_decimal_values(self):
        from comicarr.helpers import human2bytes

        result = human2bytes("1.5M")
        assert result == int(1.5 * 1048576)


class TestReplaceAll:
    """Tests for the replace_all() function."""

    def test_single_replacement(self):
        from comicarr.helpers import replace_all

        result = replace_all("hello world", {"hello": "hi"})
        assert result == "hi world"

    def test_multiple_replacements(self):
        from comicarr.helpers import replace_all

        result = replace_all("hello world", {"hello": "hi", "world": "there"})
        assert result == "hi there"

    def test_no_replacement_for_none_value(self):
        from comicarr.helpers import replace_all

        result = replace_all("hello world", {"hello": None})
        assert result == "hello world"

    def test_no_replacement_for_string_none(self):
        from comicarr.helpers import replace_all

        result = replace_all("hello world", {"hello": "None"})
        assert result == "hello world"

    def test_strips_trailing_whitespace(self):
        from comicarr.helpers import replace_all

        result = replace_all("hello world   ", {})
        assert result == "hello world"


class TestCleanName:
    """Tests for the cleanName() function."""

    def test_removes_special_characters(self):
        from comicarr.helpers import cleanName

        result = cleanName("Spider-Man #1")
        assert "#" not in result

    def test_lowercase_conversion(self):
        from comicarr.helpers import cleanName

        result = cleanName("SPIDER-MAN")
        assert result == result.lower()

    def test_accented_characters(self):
        from comicarr.helpers import cleanName

        result = cleanName("Café Stories")
        assert "cafe" in result.lower()


class TestCleanTitle:
    """Tests for the cleanTitle() function."""

    def test_replaces_separators_with_space(self):
        from comicarr.helpers import cleanTitle

        result = cleanTitle("spider-man_001.cbz")
        assert "-" not in result
        assert "_" not in result
        assert "." not in result

    def test_title_case(self):
        from comicarr.helpers import cleanTitle

        result = cleanTitle("spider-man")
        assert result == "Spider Man"

    def test_collapses_whitespace(self):
        from comicarr.helpers import cleanTitle

        result = cleanTitle("spider  man")
        assert "  " not in result


class TestIsNumber:
    """Tests for the is_number() function."""

    def test_integer(self):
        from comicarr.helpers import is_number

        assert is_number("42") is True

    def test_float(self):
        from comicarr.helpers import is_number

        assert is_number("3.14") is True

    def test_negative(self):
        from comicarr.helpers import is_number

        assert is_number("-5") is True

    def test_string(self):
        from comicarr.helpers import is_number

        assert is_number("hello") is False

    def test_empty_string(self):
        from comicarr.helpers import is_number

        assert is_number("") is False

    def test_none(self):
        from comicarr.helpers import is_number

        assert is_number(None) is False


class TestDecimalIssue:
    """Tests for the decimal_issue() function."""

    def test_whole_number(self):
        from comicarr.helpers import decimal_issue

        deciss, dec_except = decimal_issue("5")
        assert deciss == 5000
        assert dec_except is None

    def test_decimal_number(self):
        from comicarr.helpers import decimal_issue

        deciss, dec_except = decimal_issue("5.1")
        assert deciss == 5010
        assert dec_except is None

    def test_decimal_with_trailing_zeros(self):
        from comicarr.helpers import decimal_issue

        deciss, dec_except = decimal_issue("5.10")
        assert deciss == 5010

    def test_au_suffix(self):
        from comicarr.helpers import decimal_issue

        deciss, dec_except = decimal_issue("5AU")
        assert dec_except == "AU"
        assert deciss == 5000

    def test_zero_decimal(self):
        from comicarr.helpers import decimal_issue

        deciss, dec_except = decimal_issue("5.0")
        assert deciss == 5000


class TestExtractLogline:
    """Tests for the extract_logline() function."""

    def test_valid_log_line(self):
        from comicarr.helpers import extract_logline

        log_line = "2024-01-15 12:00:00 - INFO :: MainThread : Test message"
        result = extract_logline(log_line)

        assert result is not None
        timestamp, level, thread, message = result
        assert "2024-01-15" in timestamp
        assert level == "INFO"
        assert thread == "MainThread"
        assert message == "Test message"

    def test_invalid_log_line(self):
        from comicarr.helpers import extract_logline

        result = extract_logline("This is not a valid log line")
        assert result is None

    def test_debug_level(self):
        from comicarr.helpers import extract_logline

        log_line = "2024-01-15 12:00:00 - DEBUG :: Worker-1 : Debug info"
        result = extract_logline(log_line)

        assert result is not None
        _, level, _, _ = result
        assert level == "DEBUG"


class TestUtcTimestamp:
    """Tests for the utctimestamp() function."""

    def test_returns_float(self):
        from comicarr.helpers import utctimestamp

        result = utctimestamp()
        assert isinstance(result, float)

    def test_returns_reasonable_value(self):
        from comicarr.helpers import utctimestamp

        result = utctimestamp()
        # Should be after year 2020 (timestamp > 1577836800)
        assert result > 1577836800


# =============================================================================
# Property-Based Tests
# =============================================================================


class TestPropertyBased:
    """Property-based tests using Hypothesis."""

    @given(st.text(min_size=0, max_size=100))
    def test_latin_to_ascii_returns_string(self, text):
        """latinToAscii always returns a string."""
        from comicarr.helpers import latinToAscii

        result = latinToAscii(text)
        assert isinstance(result, str)

    @given(st.integers(min_value=0, max_value=1000000000))
    def test_convert_milliseconds_returns_string(self, ms):
        """convert_milliseconds always returns a formatted time string."""
        from comicarr.helpers import convert_milliseconds

        result = convert_milliseconds(ms)
        assert isinstance(result, str)
        # Should contain colons for time format
        assert ":" in result

    @given(st.integers(min_value=0, max_value=1000000))
    def test_convert_seconds_returns_string(self, seconds):
        """convert_seconds always returns a formatted time string."""
        from comicarr.helpers import convert_seconds

        result = convert_seconds(seconds)
        assert isinstance(result, str)
        assert ":" in result

    @given(st.text(alphabet="0123456789.", min_size=1, max_size=10))
    def test_is_number_handles_numeric_strings(self, s):
        """is_number should handle numeric-looking strings."""
        from comicarr.helpers import is_number

        assume(s != "." and not s.startswith(".") or s.count(".") <= 1)
        result = is_number(s)
        assert isinstance(result, bool)
