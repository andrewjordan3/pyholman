# tests/_yaml/test_loader.py
"""Tests for the YAML loading utilities in pyholman._yaml.loader."""

import io
from pathlib import Path

import pytest
import yaml

from pyholman._yaml import load_yaml_from_path, parse_yaml_to_dict
from tests._helpers.env import patch_home_directory

__all__: list[str] = []


class TestParseYamlToDict:
    """parse_yaml_to_dict: structural validation of YAML documents."""

    def test_parses_simple_mapping_from_string(self) -> None:
        result: dict[str, object] = parse_yaml_to_dict(
            yaml_source='alpha: 1\nbeta: two\n',
            source_description='<test string>',
        )
        assert result == {'alpha': 1, 'beta': 'two'}

    def test_parses_from_file_like_object(self) -> None:
        stream: io.StringIO = io.StringIO('x: 1\n')
        assert parse_yaml_to_dict(stream, '<stream>') == {'x': 1}

    def test_parses_from_bytes(self) -> None:
        assert parse_yaml_to_dict(b'x: 1\n', '<bytes>') == {'x': 1}

    def test_empty_yaml_raises_value_error_with_source(self) -> None:
        with pytest.raises(ValueError, match='empty: my-source'):
            parse_yaml_to_dict('', 'my-source')

    def test_yaml_with_only_comments_raises(self) -> None:
        with pytest.raises(ValueError, match='empty'):
            parse_yaml_to_dict('# just a comment\n', 'comments-only')

    def test_empty_mapping_raises(self) -> None:
        with pytest.raises(ValueError, match='empty dictionary'):
            parse_yaml_to_dict('{}', 'empty-dict-source')

    @pytest.mark.parametrize(
        ('yaml_text', 'expected_type_name'),
        [
            ('- 1\n- 2\n', 'list'),
            ('just a scalar\n', 'str'),
            ('42\n', 'int'),
        ],
    )
    def test_non_mapping_root_raises_type_error(
        self,
        yaml_text: str,
        expected_type_name: str,
    ) -> None:
        with pytest.raises(TypeError, match=expected_type_name):
            parse_yaml_to_dict(yaml_text, 'bad-root-source')

    def test_non_string_keys_rejected(self) -> None:
        # YAML allows integer keys at the top level; pyholman does not.
        with pytest.raises(TypeError, match='non-string keys'):
            parse_yaml_to_dict('1: alpha\n2: beta\n', 'numeric-keys')

    def test_invalid_yaml_propagates_yaml_error(self) -> None:
        with pytest.raises(yaml.YAMLError):
            parse_yaml_to_dict('key: [unclosed\n', '<bad-yaml>')


class TestLoadYamlFromPath:
    """load_yaml_from_path: filesystem-sourced YAML loading."""

    def test_reads_and_parses_file(self, tmp_path: Path) -> None:
        config_file: Path = tmp_path / 'config.yaml'
        config_file.write_text('alpha: 1\n')

        assert load_yaml_from_path(config_file) == {'alpha': 1}

    def test_expands_tilde(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        patch_home_directory(monkeypatch, tmp_path)
        config_file: Path = tmp_path / 'config.yaml'
        config_file.write_text('alpha: 1\n')

        assert load_yaml_from_path('~/config.yaml') == {'alpha': 1}

    def test_missing_file_raises_with_resolved_path(
        self,
        tmp_path: Path,
    ) -> None:
        missing_file: Path = tmp_path / 'nope.yaml'
        with pytest.raises(FileNotFoundError) as excinfo:
            load_yaml_from_path(missing_file)
        # ``OSError.__str__`` formats ``filename`` via ``repr()`` (which
        # doubles backslashes on Windows), so substring-matching the
        # rendered message is platform-dependent. The structured
        # ``filename`` attribute holds the raw path on every platform.
        assert excinfo.value.filename == str(missing_file)

    def test_accepts_string_path(self, tmp_path: Path) -> None:
        config_file: Path = tmp_path / 'config.yaml'
        config_file.write_text('alpha: 1\n')

        assert load_yaml_from_path(str(config_file)) == {'alpha': 1}
