# src/pyholman/_endpoints/contacts/response.py
"""
Response model for the Holman contacts endpoint.

Prefix-stripping rule (diverges from the other endpoint packages):
    Wire fields that begin with ``contact`` — ``contactFirstName``,
    ``contactEmail``, ``contactData1``..``contactData7``,
    ``contactAuxData1``..``contactAuxData14``,
    ``contactAuxDate1``..``contactAuxDate4``, and similar — are
    exposed on the Python class *without* the ``contact_`` prefix
    (``first_name``, ``email``, ``data_1``, ``aux_data_1``,
    ``aux_date_1``). "Contact" is already implicit in the class name,
    so ``Contact.first_name`` reads cleaner than
    ``Contact.contact_first_name``. ``ResponseModel`` already sets
    ``populate_by_name=True`` and the literal Holman aliases are
    preserved, so wire parsing is unaffected.

    Wire fields that do *not* start with ``contact`` keep their
    natural snake_case names (``city``, ``state_province``,
    ``last_change_date``, and so on).
"""

from datetime import datetime
from typing import Any, ClassVar

from pydantic import Field, field_validator

from pyholman._core import ResponseModel

__all__: list[str] = ['Contact']


class Contact(ResponseModel):
    """
    One contact record as returned by Holman's contacts endpoint.

    Wire-format note: ``contactCellAcceptsText`` is a Y/N indicator on
    the wire (``"Y"`` / ``"N"``); a ``mode='before'`` validator coerces
    it to ``bool | None`` so downstream consumers see the boolean
    semantics directly.
    """

    # Incremental pulls watermark on ``last_change_date`` (Holman's
    # ``lastChangeDate`` on the wire).
    watermark_column: ClassVar[str | None] = 'last_change_date'

    activation_date: datetime | None = Field(
        alias='contactActivationDate', default=None
    )
    address_1: str | None = Field(alias='contactAddress1', default=None)
    address_2: str | None = Field(alias='contactAddress2', default=None)
    address_3: str | None = Field(alias='contactAddress3', default=None)

    aux_data_1: str | None = Field(alias='contactAuxData1', default=None)
    aux_data_2: str | None = Field(alias='contactAuxData2', default=None)
    aux_data_3: str | None = Field(alias='contactAuxData3', default=None)
    aux_data_4: str | None = Field(alias='contactAuxData4', default=None)
    aux_data_5: str | None = Field(alias='contactAuxData5', default=None)
    aux_data_6: str | None = Field(alias='contactAuxData6', default=None)
    aux_data_7: str | None = Field(alias='contactAuxData7', default=None)
    aux_data_8: str | None = Field(alias='contactAuxData8', default=None)
    aux_data_9: str | None = Field(alias='contactAuxData9', default=None)
    aux_data_10: str | None = Field(alias='contactAuxData10', default=None)
    aux_data_11: str | None = Field(alias='contactAuxData11', default=None)
    aux_data_12: str | None = Field(alias='contactAuxData12', default=None)
    aux_data_13: str | None = Field(alias='contactAuxData13', default=None)
    aux_data_14: str | None = Field(alias='contactAuxData14', default=None)

    aux_date_1: datetime | None = Field(alias='contactAuxDate1', default=None)
    aux_date_2: datetime | None = Field(alias='contactAuxDate2', default=None)
    aux_date_3: datetime | None = Field(alias='contactAuxDate3', default=None)
    aux_date_4: datetime | None = Field(alias='contactAuxDate4', default=None)

    cell_accepts_text: bool | None = Field(alias='contactCellAcceptsText', default=None)
    cell_phone: str | None = Field(alias='contactCellPhone', default=None)
    city: str | None = None
    country: str | None = None
    county: str | None = None

    # ``data_2`` is modeled even though Holman's sample response omits
    # it: the PDF documents ``contactData1``..``contactData7`` as a
    # contiguous block, and ``ResponseModel.extra='ignore'`` would
    # silently drop the value if it ever appeared unmodeled. Better to
    # carry the field as always-None today than lose data tomorrow.
    data_1: str | None = Field(alias='contactData1', default=None)
    data_2: str | None = Field(alias='contactData2', default=None)
    data_3: str | None = Field(alias='contactData3', default=None)
    data_4: str | None = Field(alias='contactData4', default=None)
    data_5: str | None = Field(alias='contactData5', default=None)
    data_6: str | None = Field(alias='contactData6', default=None)
    data_7: str | None = Field(alias='contactData7', default=None)

    deactivation_date: datetime | None = Field(
        alias='contactDeactivationDate', default=None
    )
    email: str | None = Field(alias='contactEmail', default=None)
    employee_id: str | None = Field(alias='contactEmployeeId', default=None)
    first_name: str | None = Field(alias='contactFirstName', default=None)
    hire_date: datetime | None = Field(alias='contactHireDate', default=None)
    home_phone: str | None = Field(alias='contactHomePhone', default=None)
    language_preference: str | None = Field(alias='languagePreference', default=None)
    last_change_date: datetime | None = Field(alias='lastChangeDate', default=None)
    last_change_record_id: int | None = Field(alias='lastChangeRecordId', default=None)
    last_name: str | None = Field(alias='contactLastName', default=None)
    middle_name: str | None = Field(alias='contactMiddleName', default=None)
    state_province: str | None = Field(alias='stateProvince', default=None)
    status: str | None = Field(alias='contactStatus', default=None)
    supervisor_email: str | None = Field(alias='supervisorEmail', default=None)
    termination_date: datetime | None = Field(
        alias='contactTerminationDate', default=None
    )
    work_phone: str | None = Field(alias='contactWorkPhone', default=None)
    work_phone_extension: str | None = Field(
        alias='contactWorkPhoneExtension', default=None
    )
    zip_postal_code: str | None = Field(alias='zipPostalCode', default=None)

    @field_validator('cell_accepts_text', mode='before')
    @classmethod
    def _coerce_cell_accepts_text(cls, value: Any) -> bool | None:
        # ``Any``: ``mode='before'`` validators see the raw wire value
        # before Pydantic narrows it.
        """Coerce Holman's Y/N indicator into ``bool | None``."""
        if value is None or value == '':
            return None
        if isinstance(value, bool):
            return value
        if value == 'Y':
            return True
        if value == 'N':
            return False
        raise ValueError(
            f'cell_accepts_text must be None, "Y"/"N", or bool; got {value!r}'
        )
