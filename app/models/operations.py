"""Fuel, toll and maintenance operational transactions (spec §26-§29).

Manual, Excel and API rows all land in the same tables (`source_type` differs).
"""
from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal

from sqlalchemy import (JSON, Boolean, CheckConstraint, Date, DateTime, Index, Integer, Numeric, String, Text,
                        Time, UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, BigId, MasterBase, Money, PKMixin, Qty, Rate, SourceMixin, TxnBase, fk


# ───────────────────────────── fuel ─────────────────────────────
class FuelStation(Base, MasterBase):
    __tablename__ = "fuel_stations"
    __table_args__ = (UniqueConstraint("provider_id", "station_code"),)
    provider_id: Mapped[int | None] = fk("providers.id")
    station_code: Mapped[str] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(200), index=True)
    address: Mapped[str | None] = mapped_column(Text)
    city: Mapped[str | None] = mapped_column(String(100))
    district_id: Mapped[int | None] = fk("districts.id")
    state_id: Mapped[int | None] = fk("states.id")
    pincode: Mapped[str | None] = mapped_column(String(6))
    latitude: Mapped[Decimal | None] = mapped_column(Numeric(10, 7))
    longitude: Mapped[Decimal | None] = mapped_column(Numeric(10, 7))
    contact: Mapped[str | None] = mapped_column(String(100))


class FuelCard(Base, MasterBase):
    __tablename__ = "fuel_cards"
    __table_args__ = (UniqueConstraint("provider_id", "card_number"),)
    provider_id: Mapped[int] = fk("providers.id", nullable=False)
    card_number: Mapped[str] = mapped_column(String(40))
    vehicle_id: Mapped[int | None] = fk("vehicles.id")
    effective_from: Mapped[date | None] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date)
    remarks: Mapped[str | None] = mapped_column(String(255))


class FuelTransaction(Base, TxnBase, SourceMixin):
    __tablename__ = "fuel_transactions"
    __table_args__ = (
        UniqueConstraint("provider_id", "provider_transaction_id", name="uq_fuel_provider_txn"),
        Index("ix_fuel_vehicle_dt", "vehicle_id", "txn_datetime"),
        Index("ix_fuel_status", "status"),
        CheckConstraint("quantity >= 0", name="qty_non_negative"),
    )
    provider_id: Mapped[int | None] = fk("providers.id", index=False)
    provider_transaction_id: Mapped[str | None] = mapped_column(String(80))
    txn_datetime: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    txn_date: Mapped[date] = mapped_column(Date, index=True)
    vehicle_id: Mapped[int | None] = fk("vehicles.id", index=False)
    vehicle_number_raw: Mapped[str | None] = mapped_column(String(30))
    cost_center_id: Mapped[int | None] = fk("cost_centers.id")
    fuel_station_id: Mapped[int | None] = fk("fuel_stations.id")
    station_raw: Mapped[str | None] = mapped_column(String(200))
    fuel_type_id: Mapped[int | None] = fk("fuel_types.id")
    fuel_type_raw: Mapped[str | None] = mapped_column(String(50))
    quantity: Mapped[Decimal] = mapped_column(Qty())
    unit_id: Mapped[int | None] = fk("units.id")
    rate: Mapped[Decimal | None] = mapped_column(Rate())
    amount: Mapped[Decimal] = mapped_column(Money())
    tax_amount: Mapped[Decimal] = mapped_column(Money(), default=0)
    discount_amount: Mapped[Decimal] = mapped_column(Money(), default=0)
    total_amount: Mapped[Decimal] = mapped_column(Money())
    invoice_number: Mapped[str | None] = mapped_column(String(50))
    card_number: Mapped[str | None] = mapped_column(String(40))
    odometer: Mapped[Decimal | None] = mapped_column(Numeric(12, 1))
    km_since_last: Mapped[Decimal | None] = mapped_column(Numeric(12, 1))
    efficiency: Mapped[Decimal | None] = mapped_column(Numeric(10, 3))
    efficiency_flag: Mapped[str | None] = mapped_column(String(20))  # LOW / HIGH / NORMAL / NA
    # IMPORTED / VALIDATED / VEHICLE_UNMATCHED / FLAGGED / OVERRIDDEN / ERROR / CANCELLED
    status: Mapped[str] = mapped_column(String(20), default="IMPORTED")
    validation_flags: Mapped[list | None] = mapped_column(JSON)
    override_reason: Mapped[str | None] = mapped_column(String(500))
    override_by: Mapped[int | None] = mapped_column(BigId)
    remarks: Mapped[str | None] = mapped_column(Text)


# ───────────────────────────── toll ─────────────────────────────
class TollPlaza(Base, MasterBase):
    """Toll plaza master. Rows can be keyed in by hand or fetched from internet sources
    (services/toll_sync.py); fetched rows always carry toll ID, name, place and state."""
    __tablename__ = "toll_plazas"
    __table_args__ = (UniqueConstraint("api_source", "external_plaza_id", name="uq_toll_plaza_source_ext"),)
    external_plaza_id: Mapped[str | None] = mapped_column(String(40), index=True)
    plaza_code: Mapped[str] = mapped_column(String(40), unique=True)
    name: Mapped[str] = mapped_column(String(200), index=True)
    place: Mapped[str | None] = mapped_column(String(150))
    highway: Mapped[str | None] = mapped_column(String(50))
    road: Mapped[str | None] = mapped_column(String(150))
    state_id: Mapped[int | None] = fk("states.id")
    state_name: Mapped[str | None] = mapped_column(String(100))  # state as given by the source
    district_id: Mapped[int | None] = fk("districts.id")
    latitude: Mapped[Decimal | None] = mapped_column(Numeric(10, 7))
    longitude: Mapped[Decimal | None] = mapped_column(Numeric(10, 7))
    operator: Mapped[str | None] = mapped_column(String(150))
    provider_id: Mapped[int | None] = fk("providers.id")
    api_source: Mapped[str | None] = mapped_column(String(60))
    api_last_synced_at: Mapped[datetime | None] = mapped_column(DateTime)


class TollPlazaSyncRun(Base, PKMixin):
    """One run of the toll plaza fetch from an internet source (history + counts + skipped reasons)."""
    __tablename__ = "toll_plaza_sync_runs"
    integration_id: Mapped[int | None] = fk("toll_api_configurations.id")
    source: Mapped[str] = mapped_column(String(30))
    states: Mapped[str | None] = mapped_column(String(255))  # state codes requested (blank = all)
    dry_run: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(20), index=True)  # QUEUED RUNNING SUCCESS PARTIAL FAILED
    started_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    states_done: Mapped[int] = mapped_column(Integer, default=0)
    states_total: Mapped[int] = mapped_column(Integer, default=0)
    fetched: Mapped[int] = mapped_column(Integer, default=0)
    created: Mapped[int] = mapped_column(Integer, default=0)
    updated: Mapped[int] = mapped_column(Integer, default=0)
    unchanged: Mapped[int] = mapped_column(Integer, default=0)
    skipped: Mapped[int] = mapped_column(Integer, default=0)
    skipped_samples: Mapped[list | None] = mapped_column(JSON)  # first reasons, for review
    error_message: Mapped[str | None] = mapped_column(Text)
    triggered_by: Mapped[int | None] = fk("users.id")


class TollVehicleMapping(Base, MasterBase):
    __tablename__ = "toll_vehicle_mappings"
    __table_args__ = (Index("ix_tvm_lookup", "provider_id", "external_vehicle_number"),)
    provider_id: Mapped[int] = fk("providers.id", nullable=False, index=False)
    external_vehicle_number: Mapped[str | None] = mapped_column(String(30))
    external_vehicle_id: Mapped[str | None] = mapped_column(String(60))
    fastag_id: Mapped[str | None] = mapped_column(String(40), index=True)
    vehicle_id: Mapped[int] = fk("vehicles.id", nullable=False)
    effective_from: Mapped[date | None] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date)


class ApiIntegration(Base, MasterBase):
    """Integration configuration (toll / FASTag / fuel / bank / GPS / telematics ...).

    Secrets are *never* stored here: `credential_env_var` names an environment
    variable (or secret-manager key) that holds the credential at runtime.
    Toll API configurations are rows with integration_type = TOLL.
    """
    __tablename__ = "toll_api_configurations"
    code: Mapped[str] = mapped_column(String(30), unique=True)
    name: Mapped[str] = mapped_column(String(150))
    integration_type: Mapped[str] = mapped_column(String(30), index=True)
    provider_id: Mapped[int | None] = fk("providers.id")
    base_url: Mapped[str | None] = mapped_column(String(255))
    auth_type: Mapped[str | None] = mapped_column(String(20))  # NONE/API_KEY/BASIC/OAUTH2
    credential_env_var: Mapped[str | None] = mapped_column(String(100))
    client_id_env_var: Mapped[str | None] = mapped_column(String(100))
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=30)
    sync_frequency_minutes: Mapped[int | None] = mapped_column(Integer)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_sync_status: Mapped[str | None] = mapped_column(String(30))
    settings: Mapped[dict | None] = mapped_column(JSON)
    remarks: Mapped[str | None] = mapped_column(String(255))


class TollTransaction(Base, TxnBase, SourceMixin):
    __tablename__ = "toll_transactions"
    __table_args__ = (
        UniqueConstraint("provider_id", "transaction_id", name="uq_toll_provider_txn"),
        Index("ix_toll_vehicle_date", "vehicle_id", "txn_date"),
        Index("ix_toll_status", "status"),
    )
    provider_id: Mapped[int] = fk("providers.id", nullable=False, index=False)
    transaction_id: Mapped[str] = mapped_column(String(80))
    txn_date: Mapped[date] = mapped_column(Date)
    txn_time: Mapped[time | None] = mapped_column(Time)
    txn_datetime: Mapped[datetime | None] = mapped_column(DateTime)
    vehicle_id: Mapped[int | None] = fk("vehicles.id", index=False)
    registration_raw: Mapped[str | None] = mapped_column(String(30))
    registration_normalized: Mapped[str | None] = mapped_column(String(20), index=True)
    toll_plaza_id: Mapped[int | None] = fk("toll_plazas.id")
    plaza_external_id_raw: Mapped[str | None] = mapped_column(String(40))
    plaza_code_raw: Mapped[str | None] = mapped_column(String(40))
    plaza_name_raw: Mapped[str | None] = mapped_column(String(200))
    amount: Mapped[Decimal] = mapped_column(Money())
    direction: Mapped[str | None] = mapped_column(String(20))
    fastag_id: Mapped[str | None] = mapped_column(String(40))
    lane: Mapped[str | None] = mapped_column(String(20))
    txn_kind: Mapped[str] = mapped_column(String(10), default="DEBIT")  # DEBIT / REFUND / RECHARGE
    cost_center_id: Mapped[int | None] = fk("cost_centers.id")
    # IMPORTED / VEHICLE_MATCHED / VEHICLE_UNMATCHED / PLAZA_MATCHED / PLAZA_UNMATCHED / DUPLICATE / VALIDATED / ERROR
    status: Mapped[str] = mapped_column(String(20), default="IMPORTED")
    vehicle_match_status: Mapped[str] = mapped_column(String(20), default="VEHICLE_UNMATCHED")
    plaza_match_status: Mapped[str] = mapped_column(String(20), default="PLAZA_UNMATCHED")
    review_notes: Mapped[str | None] = mapped_column(String(500))
    remarks: Mapped[str | None] = mapped_column(String(255))


# ───────────────────────────── maintenance ─────────────────────────────
class MaintenanceType(Base, MasterBase):
    __tablename__ = "maintenance_types"
    code: Mapped[str] = mapped_column(String(30), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    category: Mapped[str] = mapped_column(String(30))  # PREVENTIVE / BREAKDOWN / REPAIR / SERVICE / ...
    interval_km: Mapped[int | None] = mapped_column(Integer)
    interval_days: Mapped[int | None] = mapped_column(Integer)
    description: Mapped[str | None] = mapped_column(String(255))


class MaintenanceJobCard(Base, TxnBase, SourceMixin):
    """A job card is the maintenance transaction (parts + labour + other)."""
    __tablename__ = "maintenance_job_cards"
    __table_args__ = (Index("ix_mjc_vehicle_date", "vehicle_id", "job_date"),)
    job_card_number: Mapped[str] = mapped_column(String(40), unique=True)
    vehicle_id: Mapped[int] = fk("vehicles.id", nullable=False, index=False)
    cost_center_id: Mapped[int | None] = fk("cost_centers.id")
    job_date: Mapped[date] = mapped_column(Date)
    completion_date: Mapped[date | None] = mapped_column(Date)
    odometer: Mapped[Decimal | None] = mapped_column(Numeric(12, 1))
    maintenance_type_id: Mapped[int] = fk("maintenance_types.id", nullable=False)
    complaint: Mapped[str | None] = mapped_column(Text)
    diagnosis: Mapped[str | None] = mapped_column(Text)
    work_performed: Mapped[str | None] = mapped_column(Text)
    vendor_id: Mapped[int | None] = fk("vendors.id")
    workshop_location_id: Mapped[int | None] = fk("locations.id")
    downtime_start: Mapped[datetime | None] = mapped_column(DateTime)
    downtime_end: Mapped[datetime | None] = mapped_column(DateTime)
    downtime_hours: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    parts_amount: Mapped[Decimal] = mapped_column(Money(), default=0)
    labour_amount: Mapped[Decimal] = mapped_column(Money(), default=0)
    other_amount: Mapped[Decimal] = mapped_column(Money(), default=0)
    amount: Mapped[Decimal] = mapped_column(Money(), default=0)
    tax_amount: Mapped[Decimal] = mapped_column(Money(), default=0)
    total_amount: Mapped[Decimal] = mapped_column(Money(), default=0)
    invoice_number: Mapped[str | None] = mapped_column(String(50))
    invoice_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default="OPEN")  # OPEN/IN_PROGRESS/COMPLETED/CANCELLED
    approval_status: Mapped[str] = mapped_column(String(20), default="NOT_REQUIRED")
    approved_by: Mapped[int | None] = mapped_column(BigId)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime)
    next_due_km: Mapped[Decimal | None] = mapped_column(Numeric(12, 1))
    next_due_date: Mapped[date | None] = mapped_column(Date)
    remarks: Mapped[str | None] = mapped_column(Text)


class MaintenancePart(Base, PKMixin):
    __tablename__ = "maintenance_parts"
    job_card_id: Mapped[int] = fk("maintenance_job_cards.id", nullable=False, ondelete="CASCADE")
    part_name: Mapped[str] = mapped_column(String(150))
    part_number: Mapped[str | None] = mapped_column(String(60))
    quantity: Mapped[Decimal] = mapped_column(Qty(), default=1)
    unit_id: Mapped[int | None] = fk("units.id")
    rate: Mapped[Decimal] = mapped_column(Money(), default=0)
    amount: Mapped[Decimal] = mapped_column(Money(), default=0)
    tax_amount: Mapped[Decimal] = mapped_column(Money(), default=0)
    is_consumable: Mapped[bool] = mapped_column(Boolean, default=False)


class MaintenanceLabour(Base, PKMixin):
    __tablename__ = "maintenance_labour"
    job_card_id: Mapped[int] = fk("maintenance_job_cards.id", nullable=False, ondelete="CASCADE")
    description: Mapped[str] = mapped_column(String(255))
    technician: Mapped[str | None] = mapped_column(String(100))
    hours: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    rate: Mapped[Decimal] = mapped_column(Money(), default=0)
    amount: Mapped[Decimal] = mapped_column(Money(), default=0)
    tax_amount: Mapped[Decimal] = mapped_column(Money(), default=0)
