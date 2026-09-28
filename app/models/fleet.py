"""Fleet: cost categories, sub-categories + configurable attributes, cost centers,
vehicles, effective-dated classification history, fuel configuration, odometer."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, Index, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, BigId, MasterBase, Money, PKMixin, Qty, TxnBase, fk


class CostCategory(Base, MasterBase):
    """e.g. Truck, Trailer (vehicle) or Administration, Workshop (non-vehicle)."""
    __tablename__ = "cost_categories"
    code: Mapped[str] = mapped_column(String(20), unique=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    applies_to: Mapped[str] = mapped_column(String(20), default="VEHICLE")  # VEHICLE / NON_VEHICLE / BOTH
    description: Mapped[str | None] = mapped_column(String(255))


class VehicleSubCategory(Base, MasterBase):
    """e.g. LPG, Open Body, Container under a cost category."""
    __tablename__ = "vehicle_sub_categories"
    __table_args__ = (UniqueConstraint("cost_category_id", "name"),)
    cost_category_id: Mapped[int] = fk("cost_categories.id", nullable=False)
    code: Mapped[str] = mapped_column(String(20), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    default_tyre_layout_id: Mapped[int | None] = fk("tyre_layouts.id")
    description: Mapped[str | None] = mapped_column(String(255))


class SubCategoryAttribute(Base, MasterBase):
    """Configurable technical attribute definitions per sub-category."""
    __tablename__ = "sub_category_attributes"
    __table_args__ = (UniqueConstraint("sub_category_id", "code"),)
    sub_category_id: Mapped[int] = fk("vehicle_sub_categories.id", nullable=False)
    code: Mapped[str] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(100))
    data_type: Mapped[str] = mapped_column(String(20))  # TEXT/INTEGER/DECIMAL/BOOLEAN/DATE/DROPDOWN
    unit_id: Mapped[int | None] = fk("units.id")
    dropdown_options: Mapped[str | None] = mapped_column(Text)  # one option per line / comma separated
    is_mandatory: Mapped[bool] = mapped_column(Boolean, default=False)
    display_order: Mapped[int] = mapped_column(Integer, default=0)
    min_value: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    max_value: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))


class VehicleAttributeValue(Base, PKMixin):
    __tablename__ = "vehicle_sub_category_attribute_values"
    __table_args__ = (UniqueConstraint("vehicle_id", "attribute_id"),)
    vehicle_id: Mapped[int] = fk("vehicles.id", nullable=False, ondelete="CASCADE")
    attribute_id: Mapped[int] = fk("sub_category_attributes.id", nullable=False)
    value_text: Mapped[str | None] = mapped_column(String(500))
    value_number: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    value_bool: Mapped[bool | None] = mapped_column(Boolean)
    value_date: Mapped[date | None] = mapped_column(Date)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime)


class CostCenter(Base, MasterBase):
    __tablename__ = "cost_centers"
    code: Mapped[str] = mapped_column(String(30), unique=True)
    name: Mapped[str] = mapped_column(String(150))
    cc_type: Mapped[str] = mapped_column(String(20), index=True)  # VEHICLE/NON_VEHICLE/COMMON/CONTRACT/OTHER
    cost_category_id: Mapped[int | None] = fk("cost_categories.id")
    branch_id: Mapped[int | None] = fk("branches.id")
    department_id: Mapped[int | None] = fk("departments.id")
    vehicle_id: Mapped[int | None] = mapped_column(BigId, unique=True, nullable=True)  # set for VEHICLE type
    parent_id: Mapped[int | None] = fk("cost_centers.id")
    description: Mapped[str | None] = mapped_column(String(255))


class Vehicle(Base, MasterBase):
    __tablename__ = "vehicles"
    vehicle_code: Mapped[str] = mapped_column(String(30), unique=True)
    registration_number: Mapped[str] = mapped_column(String(20))
    registration_normalized: Mapped[str] = mapped_column(String(20), unique=True)
    fleet_number: Mapped[str | None] = mapped_column(String(30), index=True)
    vehicle_type: Mapped[str | None] = mapped_column(String(50))
    cost_category_id: Mapped[int] = fk("cost_categories.id", nullable=False)
    sub_category_id: Mapped[int] = fk("vehicle_sub_categories.id", nullable=False)
    cost_center_id: Mapped[int | None] = fk("cost_centers.id")
    chassis_number: Mapped[str | None] = mapped_column(String(30), unique=True)
    engine_number: Mapped[str | None] = mapped_column(String(30))
    manufacturer: Mapped[str | None] = mapped_column(String(100))
    model: Mapped[str | None] = mapped_column(String(100))
    manufacturing_year: Mapped[int | None] = mapped_column(Integer)
    purchase_date: Mapped[date | None] = mapped_column(Date)
    purchase_cost: Mapped[Decimal | None] = mapped_column(Money())
    vehicle_status: Mapped[str] = mapped_column(String(30), default="ACTIVE", index=True)
    branch_id: Mapped[int | None] = fk("branches.id")
    location_id: Mapped[int | None] = fk("locations.id")
    rto_id: Mapped[int | None] = fk("rtos.id")
    ownership_type: Mapped[str | None] = mapped_column(String(30))
    owner_name: Mapped[str | None] = mapped_column(String(150))
    capacity: Mapped[Decimal | None] = mapped_column(Qty())
    capacity_unit_id: Mapped[int | None] = fk("units.id")
    gvw: Mapped[Decimal | None] = mapped_column(Qty())
    axle_count: Mapped[int | None] = mapped_column(Integer)
    tyre_layout_id: Mapped[int | None] = fk("tyre_layouts.id")
    current_odometer: Mapped[Decimal | None] = mapped_column(Numeric(12, 1))
    odometer_updated_at: Mapped[datetime | None] = mapped_column(DateTime)
    remarks: Mapped[str | None] = mapped_column(Text)


class VehicleCostCenterHistory(Base, PKMixin):
    """Effective-dated classification history (spec §4.5 / §55).

    Reports resolve a vehicle's category/sub-category/cost center *as at the
    transaction date* from this table, never from today's vehicle master.
    """
    __tablename__ = "vehicle_cost_center_history"
    __table_args__ = (Index("ix_vcch_vehicle_eff", "vehicle_id", "effective_from"),)
    vehicle_id: Mapped[int] = fk("vehicles.id", nullable=False)
    old_cost_category_id: Mapped[int | None] = fk("cost_categories.id", index=False)
    new_cost_category_id: Mapped[int] = fk("cost_categories.id", nullable=False, index=False)
    old_sub_category_id: Mapped[int | None] = fk("vehicle_sub_categories.id", index=False)
    new_sub_category_id: Mapped[int] = fk("vehicle_sub_categories.id", nullable=False, index=False)
    old_cost_center_id: Mapped[int | None] = fk("cost_centers.id", index=False)
    new_cost_center_id: Mapped[int] = fk("cost_centers.id", nullable=False, index=False)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date)
    reason: Mapped[str | None] = mapped_column(String(500))
    changed_by: Mapped[int | None] = mapped_column(BigId)
    changed_at: Mapped[datetime] = mapped_column(DateTime)


class FuelType(Base, MasterBase):
    __tablename__ = "fuel_types"
    code: Mapped[str] = mapped_column(String(20), unique=True)
    name: Mapped[str] = mapped_column(String(60), unique=True)
    default_unit_id: Mapped[int | None] = fk("units.id")
    efficiency_label: Mapped[str | None] = mapped_column(String(20))  # KM/L, KM/KG, KM/kWh
    min_efficiency: Mapped[Decimal | None] = mapped_column(Numeric(10, 3))
    max_efficiency: Mapped[Decimal | None] = mapped_column(Numeric(10, 3))


class VehicleFuel(Base, PKMixin):
    __tablename__ = "vehicle_fuels"
    vehicle_id: Mapped[int] = fk("vehicles.id", nullable=False, ondelete="CASCADE")
    fuel_type_id: Mapped[int] = fk("fuel_types.id", nullable=False)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    tank_capacity: Mapped[Decimal | None] = mapped_column(Qty())
    effective_from: Mapped[date | None] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class OdometerReading(Base, TxnBase):
    """Authoritative odometer log from every source (fuel, tyre, maintenance, manual)."""
    __tablename__ = "odometer_readings"
    __table_args__ = (Index("ix_odo_vehicle_date", "vehicle_id", "reading_at"),)
    vehicle_id: Mapped[int] = fk("vehicles.id", nullable=False, index=False)
    reading_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    reading: Mapped[Decimal] = mapped_column(Numeric(12, 1), nullable=False)
    source_module: Mapped[str] = mapped_column(String(30))  # FUEL/TYRE/MAINTENANCE/MANUAL/GPS
    source_entity_id: Mapped[int | None] = mapped_column(BigId)
    is_override: Mapped[bool] = mapped_column(Boolean, default=False)
    override_reason: Mapped[str | None] = mapped_column(String(500))
    remarks: Mapped[str | None] = mapped_column(String(255))
