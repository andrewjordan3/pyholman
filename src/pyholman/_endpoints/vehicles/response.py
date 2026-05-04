# src/pyholman/_endpoints/vehicles/response.py
"""
Response model for the Holman vehicles endpoint.

``Vehicle`` mirrors one record from the live ``basic-query`` payload. The
model is parameterized into :class:`pyholman._core.PaginatedResponse`
(``PaginatedResponse[Vehicle]``) at the point of use — the envelope
itself is shared across every endpoint and lives in ``_core``.

Wire-format rules the type annotations encode:
    - Code-shaped fields stay strings. ``fuelTypeCode='01'``,
      ``division='05'``, ``orderType='F'`` — leading zeros and short
      alpha codes are meaningful (division dispatch, downstream client
      parsers) and coercing them to numbers would destroy information.
    - Numeric values that Holman quotes on the wire are coerced to
      their numeric type via ``mode='before'`` field validators:
      ``capCost`` → ``float``; ``curbWeight``, ``leaseTerm``,
      ``modelYear``, ``odometer``, ``registeredVehicleWeight`` → ``int``.
      ``"000000"`` becomes ``0`` (matches Holman's int-typed
      ``gvwr=0`` for the same empty-state convention).
    - Native numeric fields are unchanged. ``fuelCapacity``, ``gvwr``,
      ``monthsBilled``, ``monthsInService``, ``saleOdometer``,
      ``soldAmount``, ``remainingBookValue``, ``statusCode`` (the
      record-level one), ``lastChangeRecordId``.
    - Date/datetime fields are ISO 8601 with ``Z`` suffix on the wire;
      Pydantic parses them into timezone-aware ``datetime`` natively.
    - Almost every field is nullable on some record. The type of every
      field is ``T | None`` unless a field is structurally required.
"""

from datetime import datetime
from typing import Any, ClassVar

from pydantic import ConfigDict, Field, ValidationInfo, field_validator

from pyholman._core import ResponseModel

__all__: list[str] = ['Vehicle']


class Vehicle(ResponseModel):
    """
    One vehicle record as returned by Holman's vehicles endpoint.

    Field names follow pyholman's convention: Python attributes are
    snake_case, Pydantic aliases mirror Holman's camelCase wire names.
    See the module docstring for the wire-format rules driving the
    annotations.
    """

    # Pydantic reserves the ``model_`` prefix for its own class-level
    # helpers (``model_fields``, ``model_validate``, etc.) and warns when
    # a field uses it. Holman's wire format puts ``modelYear``,
    # ``modelClient``, and ``modelVin`` on real vehicle records, so the
    # snake_case mirror names unavoidably collide with the reserved
    # prefix. Disabling the namespace silences the false-positive warning
    # without affecting the parent class.
    model_config = ConfigDict(protected_namespaces=())

    # Incremental pulls watermark on ``last_change_date`` (Holman's
    # ``lastChangeDate`` on the wire). The value is the snake_case Python
    # attribute name because ``replace_window`` operates on DataFrames
    # built from the Python-side names.
    watermark_column: ClassVar[str | None] = 'last_change_date'

    address_line_1: str | None = Field(alias='addressLine1', default=None)
    address_line_2: str | None = Field(alias='addressLine2', default=None)
    address_line_3: str | None = Field(alias='addressLine3', default=None)
    asset_subtype: str | None = Field(alias='assetSubtype', default=None)
    asset_type: str | None = Field(alias='assetType', default=None)
    assigned_status: str | None = Field(alias='assignedStatus', default=None)

    aux_data_1: str | None = Field(alias='auxData1', default=None)
    aux_data_2: str | None = Field(alias='auxData2', default=None)
    aux_data_3: str | None = Field(alias='auxData3', default=None)
    aux_data_4: str | None = Field(alias='auxData4', default=None)
    aux_data_5: str | None = Field(alias='auxData5', default=None)
    aux_data_6: str | None = Field(alias='auxData6', default=None)
    aux_data_7: str | None = Field(alias='auxData7', default=None)
    aux_data_8: str | None = Field(alias='auxData8', default=None)
    aux_data_9: str | None = Field(alias='auxData9', default=None)
    aux_data_10: str | None = Field(alias='auxData10', default=None)
    aux_data_11: str | None = Field(alias='auxData11', default=None)
    aux_data_12: str | None = Field(alias='auxData12', default=None)
    aux_data_13: str | None = Field(alias='auxData13', default=None)
    aux_data_14: str | None = Field(alias='auxData14', default=None)

    aux_date_1: datetime | None = Field(alias='auxDate1', default=None)
    aux_date_2: datetime | None = Field(alias='auxDate2', default=None)
    aux_date_3: datetime | None = Field(alias='auxDate3', default=None)
    aux_date_4: datetime | None = Field(alias='auxDate4', default=None)

    cap_cost: float | None = Field(alias='capCost', default=None)
    cell_phone: str | None = Field(alias='cellPhone', default=None)
    city: str | None = None

    client_data_1: str | None = Field(alias='clientData1', default=None)
    client_data_2: str | None = Field(alias='clientData2', default=None)
    client_data_3: str | None = Field(alias='clientData3', default=None)
    client_data_4: str | None = Field(alias='clientData4', default=None)
    client_data_5: str | None = Field(alias='clientData5', default=None)
    client_data_6: str | None = Field(alias='clientData6', default=None)
    client_data_7: str | None = Field(alias='clientData7', default=None)

    client_vehicle_number: str | None = Field(alias='clientVehicleNumber', default=None)
    curb_weight: int | None = Field(alias='curbWeight', default=None)
    delivery_date: datetime | None = Field(alias='deliveryDate', default=None)
    division: str | None = None
    driveline: str | None = None
    driver_class: str | None = Field(alias='driverClass', default=None)
    email: str | None = None
    engine_type: str | None = Field(alias='engineType', default=None)
    exec_: str | None = Field(alias='exec', default=None)
    first_name: str | None = Field(alias='firstName', default=None)
    fuel_capacity: float | None = Field(alias='fuelCapacity', default=None)
    fuel_measure_type: str | None = Field(alias='fuelMeasureType', default=None)
    fuel_type: str | None = Field(alias='fuelType', default=None)
    fuel_type_code: str | None = Field(alias='fuelTypeCode', default=None)
    fuel_type_description: str | None = Field(alias='fuelTypeDescription', default=None)
    gvwr: int | None = None
    holman_vehicle_number: str | None = Field(alias='holmanVehicleNumber', default=None)
    home_phone: str | None = Field(alias='homePhone', default=None)
    hour_meter: int | None = Field(alias='hourMeter', default=None)
    hour_meter_date: datetime | None = Field(alias='hourMeterDate', default=None)
    last_change_date: datetime | None = Field(alias='lastChangeDate', default=None)
    last_change_record_id: int | None = Field(alias='lastChangeRecordId', default=None)
    last_name: str | None = Field(alias='lastName', default=None)
    lease_end_date: datetime | None = Field(alias='leaseEndDate', default=None)
    lease_start_date: datetime | None = Field(alias='leaseStartDate', default=None)
    lease_term: int | None = Field(alias='leaseTerm', default=None)
    lessee_code: str | None = Field(alias='lesseeCode', default=None)
    license_plate: str | None = Field(alias='licensePlate', default=None)
    make_client: str | None = Field(alias='makeClient', default=None)
    make_vin: str | None = Field(alias='makeVin', default=None)
    model_client: str | None = Field(alias='modelClient', default=None)
    model_vin: str | None = Field(alias='modelVin', default=None)
    model_year: int | None = Field(alias='modelYear', default=None)
    months_billed: int | None = Field(alias='monthsBilled', default=None)
    months_in_service: int | None = Field(alias='monthsInService', default=None)
    odometer: int | None = None
    odometer_date: datetime | None = Field(alias='odometerDate', default=None)
    on_road_date: datetime | None = Field(alias='onRoadDate', default=None)
    order_type: str | None = Field(alias='orderType', default=None)
    out_of_service_date: datetime | None = Field(alias='outOfServiceDate', default=None)
    plate_type: str | None = Field(alias='plateType', default=None)
    prefix: str | None = None
    registered_vehicle_weight: int | None = Field(
        alias='registeredVehicleWeight', default=None
    )
    remaining_book_value: float | None = Field(alias='remainingBookValue', default=None)
    renewal_date: datetime | None = Field(alias='renewalDate', default=None)
    sale_odometer: int | None = Field(alias='saleOdometer', default=None)
    series: str | None = None
    sold_amount: float | None = Field(alias='soldAmount', default=None)
    sold_date: datetime | None = Field(alias='soldDate', default=None)
    state_province: str | None = Field(alias='stateProvince', default=None)
    status: str | None = None
    status_code: int | None = Field(alias='statusCode', default=None)
    tag_state_province: str | None = Field(alias='tagStateProvince', default=None)
    telematics_device_id: str | None = Field(alias='telematicsDeviceId', default=None)
    telematics_device_model: str | None = Field(
        alias='telematicsDeviceModel', default=None
    )
    telematics_device_vendor: str | None = Field(
        alias='telematicsDeviceVendor', default=None
    )
    title_location_description: str | None = Field(
        alias='titleLocationDescription', default=None
    )
    title_owner_lessor: str | None = Field(alias='titleOwnerLessor', default=None)
    vendor: str | None = None
    vin: str | None = None
    work_phone: str | None = Field(alias='workPhone', default=None)
    work_phone_extension: str | None = Field(alias='workPhoneExtension', default=None)
    zip_postal_code: str | None = Field(alias='zipPostalCode', default=None)

    @field_validator(
        'curb_weight',
        'lease_term',
        'model_year',
        'odometer',
        'registered_vehicle_weight',
        mode='before',
    )
    @classmethod
    def _coerce_to_int(cls, value: Any, info: ValidationInfo) -> int | None:
        # ``Any``: ``mode='before'`` validators receive the raw wire
        # value before Pydantic narrows it.
        """Coerce a wire value to ``int | None`` for the listed fields."""
        if value is None or value == '':
            return None
        if isinstance(value, bool):
            # Python's ``isinstance(True, int)`` is True; intercept
            # bools before they slip into the int branch silently.
            raise ValueError(
                f'{info.field_name} must be None, str, or int; got bool: {value!r}'
            )
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            return int(value)
        raise ValueError(
            f'{info.field_name} must be None, str, or int; got '
            f'{type(value).__name__}: {value!r}'
        )

    @field_validator('cap_cost', mode='before')
    @classmethod
    def _coerce_to_float(cls, value: Any, info: ValidationInfo) -> float | None:
        # ``Any``: same rationale as ``_coerce_to_int``.
        """Coerce a wire value to ``float | None`` for the listed fields."""
        if value is None or value == '':
            return None
        if isinstance(value, bool):
            raise ValueError(
                f'{info.field_name} must be None, str, int, or float; '
                f'got bool: {value!r}'
            )
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            return float(value)
        raise ValueError(
            f'{info.field_name} must be None, str, int, or float; got '
            f'{type(value).__name__}: {value!r}'
        )
