# tests/test_strings.py
"""Tests for ``format_value_for_repr`` and ``build_url``."""

from datetime import UTC, datetime
from urllib.parse import parse_qs, urlsplit

import pytest

from pyholman._strings import build_url, format_value_for_repr
from pyholman._strings.repr import _MAX_VALUE_LENGTH

__all__: list[str] = []


# =============================================================================
# format_value_for_repr
# =============================================================================


class TestNone:
    def test_none_renders_as_literal_none_unquoted(self) -> None:
        assert format_value_for_repr(None) == 'None'


class TestStrings:
    def test_short_string_quoted(self) -> None:
        assert format_value_for_repr('hello') == "'hello'"

    def test_empty_string_quoted(self) -> None:
        assert format_value_for_repr('') == "''"

    def test_string_exactly_at_boundary_not_truncated(self) -> None:
        at_boundary: str = 'a' * _MAX_VALUE_LENGTH
        assert format_value_for_repr(at_boundary) == f"'{at_boundary}'"

    def test_string_just_over_boundary_is_truncated(self) -> None:
        over_boundary: str = 'b' * (_MAX_VALUE_LENGTH + 1)
        rendered: str = format_value_for_repr(over_boundary)
        expected_prefix: str = 'b' * _MAX_VALUE_LENGTH
        assert rendered == f"'{expected_prefix}...' ({len(over_boundary)} chars)"

    def test_long_string_truncation_reports_original_length(self) -> None:
        long_string: str = 'c' * 10_000
        rendered: str = format_value_for_repr(long_string)
        assert '10000 chars' in rendered
        assert rendered.startswith("'" + 'c' * _MAX_VALUE_LENGTH + '...')


class TestNumbers:
    @pytest.mark.parametrize('value', [0, 1, -42, 10**12])
    def test_integer_uses_repr(self, value: int) -> None:
        assert format_value_for_repr(value) == repr(value)

    @pytest.mark.parametrize('value', [0.0, 1.5, -0.25])
    def test_float_uses_repr(self, value: float) -> None:
        assert format_value_for_repr(value) == repr(value)


class TestDatetime:
    def test_tz_aware_datetime_uses_repr(self) -> None:
        value: datetime = datetime(2026, 2, 8, 12, 30, tzinfo=UTC)
        assert format_value_for_repr(value) == repr(value)


class TestOtherTypes:
    def test_bool_uses_repr(self) -> None:
        assert format_value_for_repr(True) == 'True'
        assert format_value_for_repr(False) == 'False'

    def test_long_non_string_repr_is_truncated(self) -> None:
        # A long list produces a repr longer than _MAX_VALUE_LENGTH; the
        # helper applies the same truncation contract as for strings.
        big_list: list[int] = list(range(1000))
        rendered: str = format_value_for_repr(big_list)
        assert 'chars)' in rendered
        assert rendered.startswith("'")


# =============================================================================
# build_url — slash normalization
# =============================================================================


class TestSlashNormalization:
    def test_trailing_base_slash_and_leading_path_slash_yields_single_slash(
        self,
    ) -> None:
        result: str = build_url('https://example.test/', '/api/thing')
        assert result == 'https://example.test/api/thing'

    def test_no_trailing_no_leading_slash_still_yields_single_slash(self) -> None:
        result: str = build_url('https://example.test', 'api/thing')
        assert result == 'https://example.test/api/thing'

    def test_both_slashes_collapse_to_one(self) -> None:
        result: str = build_url('https://example.test/', '/api/thing')
        # The critical invariant: never two consecutive slashes after the
        # scheme, regardless of which side contributed them.
        assert '//api' not in result
        assert result == 'https://example.test/api/thing'

    def test_neither_has_slash_inserts_exactly_one(self) -> None:
        # Single-segment path so the slash count is unambiguous: two from
        # 'https://' and exactly one joining the host to the path.
        result: str = build_url('https://example.test', 'api')
        assert result.count('/') == 3
        assert result == 'https://example.test/api'

    def test_only_base_has_trailing_slash(self) -> None:
        assert build_url('https://example.test/', 'api') == 'https://example.test/api'

    def test_only_path_has_leading_slash(self) -> None:
        assert build_url('https://example.test', '/api') == 'https://example.test/api'


# =============================================================================
# build_url — query parameters
# =============================================================================


class TestQueryParams:
    def test_none_query_params_omits_question_mark(self) -> None:
        result: str = build_url('https://example.test', '/api', query_params=None)
        assert '?' not in result
        assert result == 'https://example.test/api'

    def test_empty_query_params_omits_question_mark(self) -> None:
        result: str = build_url('https://example.test', '/api', query_params={})
        assert '?' not in result
        assert result == 'https://example.test/api'

    def test_populated_query_params_appear_after_question_mark(self) -> None:
        result: str = build_url(
            'https://example.test',
            '/api',
            query_params={'a': '1', 'b': '2'},
        )
        parsed: dict[str, list[str]] = parse_qs(urlsplit(result).query)
        assert parsed == {'a': ['1'], 'b': ['2']}

    def test_value_containing_space_is_percent_encoded(self) -> None:
        result: str = build_url(
            'https://example.test',
            '/api',
            query_params={'q': 'hello world'},
        )
        # ``urlencode`` encodes a space as ``+`` by default for
        # application/x-www-form-urlencoded compatibility. The assertion
        # pins the expected wire form; if the encoding strategy ever
        # changes this test surfaces the behavior shift.
        assert result.endswith('?q=hello+world')

    def test_value_containing_reserved_chars_is_percent_encoded(self) -> None:
        result: str = build_url(
            'https://example.test',
            '/api',
            query_params={'filter': 'a=b&c'},
        )
        parsed: dict[str, list[str]] = parse_qs(urlsplit(result).query)
        # Round-tripping through ``parse_qs`` confirms the encoding is
        # correct: the ``=`` and ``&`` in the value must not be mistaken
        # for parameter delimiters.
        assert parsed == {'filter': ['a=b&c']}

    def test_query_param_order_matches_dict_insertion_order(self) -> None:
        ordered_params: dict[str, str] = {}
        ordered_params['zeta'] = '1'
        ordered_params['alpha'] = '2'
        ordered_params['mike'] = '3'

        result: str = build_url(
            'https://example.test', '/api', query_params=ordered_params
        )
        query_string: str = urlsplit(result).query
        assert query_string == 'zeta=1&alpha=2&mike=3'
