# tests/test_license.py
"""
Pin the project license so an accidental rewrite to MIT (or to a
corrupted file) fails loudly at test time rather than silently
landing on PyPI. The check is intentionally minimal — just the
first non-blank line of ``LICENSE`` — because the canonical Apache
2.0 text is byte-for-byte stable from
https://www.apache.org/licenses/LICENSE-2.0.txt and a stricter
content check would only re-encode that fact in two places.
"""

from pathlib import Path

__all__: list[str] = []


# The repository root sits two levels above this test file:
# ``tests/test_license.py`` → ``tests/`` → ``<repo root>``. The
# ``LICENSE`` and ``NOTICE`` files live at the repo root rather than
# inside the package, so the path resolves through the parents.
_REPO_ROOT: Path = Path(__file__).resolve().parent.parent


def test_license_file_is_apache_two_point_zero() -> None:
    license_path: Path = _REPO_ROOT / 'LICENSE'
    license_text: str = license_path.read_text(encoding='utf-8')

    first_non_blank_line: str = next(
        line.strip() for line in license_text.splitlines() if line.strip()
    )
    assert 'Apache License' in first_non_blank_line, (
        f'Expected the first non-blank line of LICENSE to name the '
        f'Apache License; got {first_non_blank_line!r}'
    )


def test_notice_file_exists_and_attributes_pyholman() -> None:
    # Apache 2.0 §4(d) requires distributors to preserve the NOTICE
    # file. Pin its presence and that it identifies the project so an
    # accidental deletion or rename of NOTICE fails loudly.
    notice_path: Path = _REPO_ROOT / 'NOTICE'
    assert notice_path.is_file(), 'NOTICE file is missing from the repo root.'
    notice_text: str = notice_path.read_text(encoding='utf-8')
    assert 'pyholman' in notice_text
