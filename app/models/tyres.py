"""Tyre lifecycle (spec §30-§36). Every tyre is an individually traceable asset.

`tyre_movements` is the authoritative history. `tyre_fitments` holds fitment
periods and enforces, at database level, that a position holds at most one
tyre and a tyre is in at most one position at a time (`current_slot` is 1 for
the open fitment and NULL once closed; MySQL unique indexes ignore NULLs).
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, Index, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, BigId, MasterBase, Money, PKMixin, TxnBase, fk


class TyrePosition(Base, MasterBase):
    __tablename__ = "tyre_positions"
    code: Mapped[str] = mapped_column(String(20), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    axle_number: Mapped[int | None] = mapped_column(Integer)
    side: Mapped[str | None] = mapped_column(String(10))  # LEFT / RIGHT / CENTER
    placement: Mapped[str | None] = mapped_column(String(10))  # OUTER / INNER / SINGLE
    position_type: Mapped[str | None] = mapped_column(String(20))  # STEER / DRIVE / TAG / TRAILER / SPARE
    display_order: Mapped[int] = mapped_column(Integer, default=0)


class TyreLayout(Base, MasterBase):
    __tablename__ = "tyre_layouts"
    code: Mapped[str] = mapped_column(String(20), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    axle_count: Mapped[int | None] = mapped_column(Integer)
    description: Mapped[str | None] = mapped_column(String(255))


class VehicleTyrePositionConfiguration(Base, PKMixin):
    """Positions available in a layout and where they are drawn on the dashboard."""
    __tablename__ = "vehicle_tyre_position_configurations"
    __table_args__ = (UniqueConstraint("layout_id", "position_id"),)
    layout_id: Mapped[int] = fk("tyre_layouts.id", nullable=False, ondelete="CASCADE")
    position_id: Mapped[int] = fk("tyre_positions.id", nullable=False)
    display_row: Mapped[int] = mapped_column(Integer, default=1)
    display_col: Mapped[int] = mapped_column(Integer, default=1)
    is_spare: Mapped[bool] = mapped_column(Boolean, default=False)


class TyreLocation(Base, MasterBase):
    __tablename__ = "tyre_locations"
    code: Mapped[str] = mapped_column(String(20), unique=True)
    name: Mapped[str] = mapped_column(String(150))
    location_type: Mapped[str] = mapped_column(String(30))  # GODOWN/WORKSHOP/RETREADER/SCRAP_YARD/VENDOR/WARRANTY/OTHER
    location_id: Mapped[int | None] = fk("locations.id")
    vendor_id: Mapped[int | None] = fk("vendors.id")
    branch_id: Mapped[int | None] = fk("branches.id")


class Tyre(Base, MasterBase):
    __tablename__ = "tyres"
    __table_args__ = (Index("ix_tyre_status", "current_status"),)
    serial_number: Mapped[str] = mapped_column(String(50), unique=True)
    tyre_code: Mapped[str | None] = mapped_column(String(30), unique=True)
    brand: Mapped[str] = mapped_column(String(60), index=True)
    model: Mapped[str | None] = mapped_column(String(60))
    size: Mapped[str] = mapped_column(String(40), index=True)
    tyre_type: Mapped[str | None] = mapped_column(String(30))  # RADIAL / NYLON / TUBELESS ...
    pattern: Mapped[str | None] = mapped_column(String(60))
    ply_rating: Mapped[str | None] = mapped_column(String(10))
    load_index: Mapped[str | None] = mapped_column(String(10))
    speed_rating: Mapped[str | None] = mapped_column(String(5))
    original_tread_depth: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    current_tread_depth: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    purchase_date: Mapped[date | None] = mapped_column(Date)
    supplier_id: Mapped[int | None] = fk("vendors.id")
    invoice_number: Mapped[str | None] = mapped_column(String(50))
    cost: Mapped[Decimal | None] = mapped_column(Money())
    gst_amount: Mapped[Decimal | None] = mapped_column(Money())
    discount_amount: Mapped[Decimal | None] = mapped_column(Money())
    total_cost: Mapped[Decimal | None] = mapped_column(Money())
    warranty_km: Mapped[int | None] = mapped_column(Integer)
    warranty_months: Mapped[int | None] = mapped_column(Integer)
    warranty_expiry_date: Mapped[date | None] = mapped_column(Date)
    manufacture_date: Mapped[date | None] = mapped_column(Date)
    # lifecycle state — changed only via services/tyres.py operations
    current_status: Mapped[str] = mapped_column(String(30), default="NEW")
    current_vehicle_id: Mapped[int | None] = fk("vehicles.id")
    current_position_id: Mapped[int | None] = fk("tyre_positions.id")
    current_location_id: Mapped[int | None] = fk("tyre_locations.id")
    current_install_odometer: Mapped[Decimal | None] = mapped_column(Numeric(12, 1))
    current_odometer: Mapped[Decimal | None] = mapped_column(Numeric(12, 1))
    total_km: Mapped[Decimal] = mapped_column(Numeric(12, 1), default=0)
    retread_count: Mapped[int] = mapped_column(Integer, default=0)
    scrap_date: Mapped[date | None] = mapped_column(Date)
    scrap_reason: Mapped[str | None] = mapped_column(String(255))
    scrap_value: Mapped[Decimal | None] = mapped_column(Money())
    remarks: Mapped[str | None] = mapped_column(Text)


class TyreFitment(Base, PKMixin):
    __tablename__ = "tyre_fitments"
    __table_args__ = (
        UniqueConstraint("vehicle_id", "position_id", "current_slot", name="uq_tyre_position_occupancy"),
        UniqueConstraint("tyre_id", "current_slot", name="uq_tyre_single_fitment"),
    )
    tyre_id: Mapped[int] = fk("tyres.id", nullable=False)
    vehicle_id: Mapped[int] = fk("vehicles.id", nullable=False)
    position_id: Mapped[int] = fk("tyre_positions.id", nullable=False)
    installed_at: Mapped[datetime] = mapped_column(DateTime)
    install_odometer: Mapped[Decimal] = mapped_column(Numeric(12, 1))
    install_tread_depth: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    removed_at: Mapped[datetime | None] = mapped_column(DateTime)
    removal_odometer: Mapped[Decimal | None] = mapped_column(Numeric(12, 1))
    removal_tread_depth: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    running_km: Mapped[Decimal | None] = mapped_column(Numeric(12, 1))
    current_slot: Mapped[int | None] = mapped_column(Integer, default=1)
    install_movement_id: Mapped[int | None] = mapped_column(BigId)
    removal_movement_id: Mapped[int | None] = mapped_column(BigId)


class TyreMovement(Base, TxnBase):
    __tablename__ = "tyre_movements"
    __table_args__ = (Index("ix_tm_tyre_date", "tyre_id", "movement_date"),)
    tyre_id: Mapped[int] = fk("tyres.id", nullable=False, index=False)
    # PURCHASE / INSTALL / SHIFT / TRANSFER / REMOVE / MOVE_LOCATION / SEND_RETREAD / RECEIVE_RETREAD /
    # INSPECTION_HOLD / SEND_WARRANTY / WARRANTY_RESOLVED / DAMAGED / SCRAP / SELL / LOST / CORRECTION
    movement_type: Mapped[str] = mapped_column(String(30), index=True)
    movement_date: Mapped[datetime] = mapped_column(DateTime)
    from_vehicle_id: Mapped[int | None] = fk("vehicles.id")
    to_vehicle_id: Mapped[int | None] = fk("vehicles.id")
    from_location_id: Mapped[int | None] = fk("tyre_locations.id")
    to_location_id: Mapped[int | None] = fk("tyre_locations.id")
    from_position_id: Mapped[int | None] = fk("tyre_positions.id")
    to_position_id: Mapped[int | None] = fk("tyre_positions.id")
    odometer: Mapped[Decimal | None] = mapped_column(Numeric(12, 1))
    to_odometer: Mapped[Decimal | None] = mapped_column(Numeric(12, 1))
    tread_depth: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    running_km: Mapped[Decimal | None] = mapped_column(Numeric(12, 1))
    status_before: Mapped[str | None] = mapped_column(String(30))
    status_after: Mapped[str | None] = mapped_column(String(30))
    reason: Mapped[str | None] = mapped_column(String(255))
    reference: Mapped[str | None] = mapped_column(String(80))
    performed_by: Mapped[str | None] = mapped_column(String(100))
    is_override: Mapped[bool] = mapped_column(Boolean, default=False)
    override_reason: Mapped[str | None] = mapped_column(String(500))
    remarks: Mapped[str | None] = mapped_column(Text)


class TyreRetreading(Base, TxnBase):
    __tablename__ = "tyre_retreading"
    tyre_id: Mapped[int] = fk("tyres.id", nullable=False)
    vendor_id: Mapped[int | None] = fk("vendors.id")
    sent_date: Mapped[date] = mapped_column(Date)
    return_date: Mapped[date | None] = mapped_column(Date)
    odometer: Mapped[Decimal | None] = mapped_column(Numeric(12, 1))
    tread_condition: Mapped[str | None] = mapped_column(String(100))
    tread_depth: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    retread_type: Mapped[str | None] = mapped_column(String(30))  # PRECURED / MOULD / ...
    cost: Mapped[Decimal | None] = mapped_column(Money())
    gst_amount: Mapped[Decimal | None] = mapped_column(Money())
    invoice_number: Mapped[str | None] = mapped_column(String(50))
    new_tread_depth: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    new_pattern: Mapped[str | None] = mapped_column(String(60))
    retread_serial: Mapped[str | None] = mapped_column(String(50))
    warranty_km: Mapped[int | None] = mapped_column(Integer)
    warranty_months: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="SENT")  # SENT / RETURNED / REJECTED
    remarks: Mapped[str | None] = mapped_column(Text)


class TyreInspection(Base, TxnBase):
    __tablename__ = "tyre_inspections"
    tyre_id: Mapped[int] = fk("tyres.id", nullable=False)
    inspection_date: Mapped[date] = mapped_column(Date)
    vehicle_id: Mapped[int | None] = fk("vehicles.id")
    position_id: Mapped[int | None] = fk("tyre_positions.id")
    odometer: Mapped[Decimal | None] = mapped_column(Numeric(12, 1))
    tread_depth: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    pressure_psi: Mapped[Decimal | None] = mapped_column(Numeric(6, 1))
    condition: Mapped[str | None] = mapped_column(String(30))
    damage: Mapped[str | None] = mapped_column(String(255))
    recommended_action: Mapped[str | None] = mapped_column(String(100))
    inspector: Mapped[str | None] = mapped_column(String(100))
    remarks: Mapped[str | None] = mapped_column(Text)


class TyreMaintenance(Base, TxnBase):
    __tablename__ = "tyre_maintenance"
    tyre_id: Mapped[int] = fk("tyres.id", nullable=False)
    maintenance_type: Mapped[str] = mapped_column(String(30))  # TYRE_MAINTENANCE_TYPE lookup
    maintenance_date: Mapped[date] = mapped_column(Date)
    vehicle_id: Mapped[int | None] = fk("vehicles.id")
    position_id: Mapped[int | None] = fk("tyre_positions.id")
    odometer: Mapped[Decimal | None] = mapped_column(Numeric(12, 1))
    vendor_id: Mapped[int | None] = fk("vendors.id")
    cost: Mapped[Decimal] = mapped_column(Money(), default=0)
    gst_amount: Mapped[Decimal] = mapped_column(Money(), default=0)
    invoice_number: Mapped[str | None] = mapped_column(String(50))
    remarks: Mapped[str | None] = mapped_column(Text)


class TyreWarrantyClaim(Base, TxnBase):
    __tablename__ = "tyre_warranty_claims"
    tyre_id: Mapped[int] = fk("tyres.id", nullable=False)
    warranty_provider_id: Mapped[int | None] = fk("vendors.id")
    vendor_id: Mapped[int | None] = fk("vendors.id")
    claim_number: Mapped[str] = mapped_column(String(50), unique=True)
    claim_date: Mapped[date] = mapped_column(Date)
    failure_date: Mapped[date | None] = mapped_column(Date)
    failure_reason: Mapped[str | None] = mapped_column(String(255))
    evidence: Mapped[str | None] = mapped_column(Text)
    km_at_failure: Mapped[Decimal | None] = mapped_column(Numeric(12, 1))
    tread_depth_at_failure: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    claim_amount: Mapped[Decimal | None] = mapped_column(Money())
    approved_amount: Mapped[Decimal | None] = mapped_column(Money())
    resolution_type: Mapped[str | None] = mapped_column(String(20))  # REPLACEMENT / CREDIT / REJECTED
    replacement_tyre_id: Mapped[int | None] = fk("tyres.id")
    status: Mapped[str] = mapped_column(String(20), default="SUBMITTED")  # SUBMITTED/UNDER_REVIEW/APPROVED/REJECTED/SETTLED
    resolution_date: Mapped[date | None] = mapped_column(Date)
    remarks: Mapped[str | None] = mapped_column(Text)
