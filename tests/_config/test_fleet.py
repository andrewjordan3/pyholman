# tests/_config/test_fleet.py
"""Tests for FleetConfig."""

import pytest
from pydantic import ValidationError

from pyholman._config import FleetConfig

__all__: list[str] = []


class TestFleetConfigLesseeCodes:
    def test_normalizes_whitespace_case_and_sorts(self) -> None:
        fleet: FleetConfig = FleetConfig(
            lessee_codes=['  aaaa ', 'BBBB', 'BBBB', 'xxxx'],
        )
        assert fleet.lessee_codes == ('AAAA', 'BBBB', 'XXXX')

    def test_returns_tuple(self) -> None:
        fleet: FleetConfig = FleetConfig(lessee_codes=['ABCD'])
        assert isinstance(fleet.lessee_codes, tuple)

    @pytest.mark.parametrize(
        'bad_codes',
        [
            ['ABC'],  # too short
            ['ABCDE'],  # too long
            [''],  # empty string strips to length 0
            ['   '],  # whitespace-only strips to length 0
            ['ABCD', 'XYZ'],  # one element invalid
        ],
    )
    def test_invalid_code_length_rejected(
        self,
        bad_codes: list[str],
    ) -> None:
        with pytest.raises(ValidationError, match='4 characters'):
            FleetConfig(lessee_codes=bad_codes)

    def test_empty_list_rejected(self) -> None:
        with pytest.raises(ValidationError, match='at least one'):
            FleetConfig(lessee_codes=[])

    def test_non_list_rejected(self) -> None:
        with pytest.raises(ValidationError):
            FleetConfig(lessee_codes='ABCD')  # type: ignore[arg-type]

    def test_non_string_element_rejected(self) -> None:
        with pytest.raises(ValidationError):
            FleetConfig(lessee_codes=[1234])  # type: ignore[list-item]


class TestFleetConfigOrganizationIdMerge:
    def test_string_organization_id_merged_and_sorted(self) -> None:
        fleet: FleetConfig = FleetConfig(
            organization_id='9999',  # type: ignore[call-arg]
            lessee_codes=['AAAA'],
        )
        assert fleet.lessee_codes == ('9999', 'AAAA')

    def test_integer_organization_id_coerced_and_merged(self) -> None:
        fleet: FleetConfig = FleetConfig(
            organization_id=9999,  # type: ignore[call-arg]
            lessee_codes=['AAAA'],
        )
        assert fleet.lessee_codes == ('9999', 'AAAA')

    def test_organization_id_absent_leaves_codes_unchanged(self) -> None:
        fleet: FleetConfig = FleetConfig(lessee_codes=['AAAA'])
        assert fleet.lessee_codes == ('AAAA',)

    def test_organization_id_none_leaves_codes_unchanged(self) -> None:
        fleet: FleetConfig = FleetConfig(
            organization_id=None,  # type: ignore[call-arg]
            lessee_codes=['AAAA'],
        )
        assert fleet.lessee_codes == ('AAAA',)

    def test_organization_id_empty_string_leaves_codes_unchanged(self) -> None:
        fleet: FleetConfig = FleetConfig(
            organization_id='',  # type: ignore[call-arg]
            lessee_codes=['AAAA'],
        )
        assert fleet.lessee_codes == ('AAAA',)

    def test_organization_id_whitespace_only_leaves_codes_unchanged(self) -> None:
        fleet: FleetConfig = FleetConfig(
            organization_id='   ',  # type: ignore[call-arg]
            lessee_codes=['AAAA'],
        )
        assert fleet.lessee_codes == ('AAAA',)

    def test_duplicate_organization_id_is_deduped(self) -> None:
        fleet: FleetConfig = FleetConfig(
            organization_id='AAAA',  # type: ignore[call-arg]
            lessee_codes=['AAAA'],
        )
        assert fleet.lessee_codes == ('AAAA',)

    def test_organization_id_bool_rejected(self) -> None:
        with pytest.raises(ValidationError, match='bool'):
            FleetConfig(
                organization_id=True,  # type: ignore[call-arg]
                lessee_codes=['AAAA'],
            )

    def test_organization_id_unsupported_type_rejected(self) -> None:
        # A list for organization_id is neither string nor integer; the
        # merge step raises a loud ValueError rather than coercing it.
        with pytest.raises(ValidationError, match='organization_id must be'):
            FleetConfig(
                organization_id=[1, 2, 3],  # type: ignore[call-arg]
                lessee_codes=['AAAA'],
            )

    def test_merge_skipped_when_lessee_codes_is_not_a_sequence(self) -> None:
        # If ``lessee_codes`` is malformed, the merge step leaves it alone
        # and lets the field validator emit the canonical error.
        with pytest.raises(ValidationError, match='must be a list of strings'):
            FleetConfig(
                organization_id='9999',  # type: ignore[call-arg]
                lessee_codes='AAAA',  # type: ignore[arg-type]
            )

    def test_non_dict_input_passes_through_to_pydantic(self) -> None:
        source_fleet: FleetConfig = FleetConfig(lessee_codes=['AAAA'])
        revalidated_fleet: FleetConfig = FleetConfig.model_validate(source_fleet)
        assert revalidated_fleet.lessee_codes == ('AAAA',)

    def test_organization_id_not_exposed_as_attribute(self) -> None:
        fleet: FleetConfig = FleetConfig(
            organization_id='9999',  # type: ignore[call-arg]
            lessee_codes=['AAAA'],
        )
        assert not hasattr(fleet, 'organization_id')


class TestFleetConfigImmutability:
    def test_is_frozen(self) -> None:
        fleet: FleetConfig = FleetConfig(lessee_codes=['ABCD'])
        with pytest.raises(ValidationError):
            fleet.lessee_codes = ('XYZ1',)  # type: ignore[misc]

    def test_extra_field_rejected(self) -> None:
        with pytest.raises(ValidationError, match='extra'):
            FleetConfig(
                lessee_codes=['ABCD'],
                oops='typo',  # type: ignore[call-arg]
            )
