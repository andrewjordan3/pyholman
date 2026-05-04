# tests/_core/response/test_watermark_column.py
"""Tests for the ``watermark_column`` ClassVar on ResponseModel subclasses."""

from pyholman._core import ResponseModel
from pyholman._endpoints.contacts import Contact
from pyholman._endpoints.engine_hours import EngineHours
from pyholman._endpoints.maintenance_purchase_orders import (
    MaintenancePurchaseOrder,
)
from pyholman._endpoints.odometer import Odometer
from pyholman._endpoints.vehicles import Vehicle

__all__: list[str] = []


class TestResponseModelDefault:
    def test_default_is_none(self) -> None:
        assert ResponseModel.watermark_column is None


class TestIncrementalEndpointWatermarks:
    def test_vehicle_watermark(self) -> None:
        assert Vehicle.watermark_column == 'last_change_date'

    def test_maintenance_purchase_order_watermark(self) -> None:
        assert MaintenancePurchaseOrder.watermark_column == 'last_change_date'

    def test_contact_watermark(self) -> None:
        assert Contact.watermark_column == 'last_change_date'


class TestSnapshotEndpointWatermarks:
    def test_odometer_inherits_none(self) -> None:
        assert Odometer.watermark_column is None

    def test_engine_hours_inherits_none(self) -> None:
        assert EngineHours.watermark_column is None


class TestWatermarkReferencesRealField:
    # Regression guard: if a response model renames the watermark field
    # on the Python side and forgets to update the ClassVar, these tests
    # fail loudly rather than letting the orchestrator point at a dead
    # column name at run time.
    def test_vehicle_watermark_is_declared_field(self) -> None:
        assert Vehicle.watermark_column in Vehicle.model_fields

    def test_maintenance_purchase_order_watermark_is_declared_field(self) -> None:
        assert (
            MaintenancePurchaseOrder.watermark_column
            in MaintenancePurchaseOrder.model_fields
        )

    def test_contact_watermark_is_declared_field(self) -> None:
        assert Contact.watermark_column in Contact.model_fields
