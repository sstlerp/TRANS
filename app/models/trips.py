"""Trips & freight (lorry receipt / consignment note), trip expenses, e-way bills, driver advances & settlements.

Money flow (no double counting):
* freight income is recognised only through the customer invoice raised from a trip (invoices / ledger);
* trip expenses are operating cost of the trip's cost center (whoever paid them);
* driver advances are cash given to the driver — not cost; they are recovered in the driver settlement;
* the driver allowance (bhatta) in an approved settlement is driver cost.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, Money, PKMixin, Qty, Rate, TxnBase, fk


class Trip(Base, TxnBase):
    __tablename__ = "trips"
    __table_args__ = (Index("ix_trips_vehicle_start", "vehicle_id", "actual_start"),
                      Index("ix_trips_driver_status", "driver_id", "status"))
    trip_number: Mapped[str] = mapped_column(String(30), unique=True)
    trip_date: Mapped[date] = mapped_column(Date, index=True)  # booking date
    lr_number: Mapped[str | None] = mapped_column(String(40), unique=True)  # lorry receipt / consignment note
    lr_date: Mapped[date | None] = mapped_column(Date)
    customer_id: Mapped[int | None] = fk("customers.id")
    contract_id: Mapped[int | None] = fk("contracts.id")
    vehicle_id: Mapped[int] = fk("vehicles.id", nullable=False, index=False)
    driver_id: Mapped[int | None] = fk("drivers.id", index=False)
    cost_center_id: Mapped[int | None] = fk("cost_centers.id")
    # route
    origin: Mapped[str] = mapped_column(String(150))
    destination: Mapped[str] = mapped_column(String(150))
    from_pincode: Mapped[str | None] = mapped_column(String(6))
    to_pincode: Mapped[str | None] = mapped_column(String(6))
    from_state_id: Mapped[int | None] = fk("states.id", index=False)
    to_state_id: Mapped[int | None] = fk("states.id", index=False)
    route_via: Mapped[str | None] = mapped_column(String(255))
    planned_km: Mapped[Decimal | None] = mapped_column(Qty())
    # consignor / consignee
    consignor_name: Mapped[str | None] = mapped_column(String(200))
    consignor_gstin: Mapped[str | None] = mapped_column(String(15))
    consignor_address: Mapped[str | None] = mapped_column(String(500))
    consignee_name: Mapped[str | None] = mapped_column(String(200))
    consignee_gstin: Mapped[str | None] = mapped_column(String(15))
    consignee_address: Mapped[str | None] = mapped_column(String(500))
    # goods
    goods_description: Mapped[str | None] = mapped_column(String(255))
    hsn_code: Mapped[str | None] = mapped_column(String(10))
    packing_type: Mapped[str | None] = mapped_column(String(30))
    packages: Mapped[int | None] = mapped_column(Integer)
    weight_tonnes: Mapped[Decimal | None] = mapped_column(Qty())
    goods_value: Mapped[Decimal | None] = mapped_column(Money())
    goods_invoice_number: Mapped[str | None] = mapped_column(String(60))  # consignor's invoice / challan
    goods_invoice_date: Mapped[date | None] = mapped_column(Date)
    # freight
    freight_payment: Mapped[str] = mapped_column(String(10), default="TBB")  # PAID / TO_PAY / TBB (to be billed)
    freight_basis: Mapped[str] = mapped_column(String(15), default="FIXED")  # FIXED / PER_TONNE / PER_KM
    freight_rate: Mapped[Decimal | None] = mapped_column(Rate())
    freight_amount: Mapped[Decimal] = mapped_column(Money(), default=0)
    loading_charges: Mapped[Decimal] = mapped_column(Money(), default=0)
    unloading_charges: Mapped[Decimal] = mapped_column(Money(), default=0)
    detention_charges: Mapped[Decimal] = mapped_column(Money(), default=0)
    other_charges: Mapped[Decimal] = mapped_column(Money(), default=0)
    total_freight: Mapped[Decimal] = mapped_column(Money(), default=0)
    advance_received: Mapped[Decimal] = mapped_column(Money(), default=0)  # from the customer
    balance_freight: Mapped[Decimal] = mapped_column(Money(), default=0)
    # run
    scheduled_start: Mapped[datetime | None] = mapped_column(DateTime)
    actual_start: Mapped[datetime | None] = mapped_column(DateTime)
    actual_end: Mapped[datetime | None] = mapped_column(DateTime)
    start_odometer: Mapped[Decimal | None] = mapped_column(Qty())
    end_odometer: Mapped[Decimal | None] = mapped_column(Qty())
    actual_km: Mapped[Decimal | None] = mapped_column(Qty())
    status: Mapped[str] = mapped_column(String(20), default="PLANNED", index=True)
    # PLANNED / IN_TRANSIT / DELIVERED / POD_RECEIVED / INVOICED / CLOSED / CANCELLED
    # delivery / POD
    delivered_packages: Mapped[int | None] = mapped_column(Integer)
    shortage_damage: Mapped[str | None] = mapped_column(String(255))
    pod_received_date: Mapped[date | None] = mapped_column(Date)
    pod_remarks: Mapped[str | None] = mapped_column(String(255))
    invoice_id: Mapped[int | None] = fk("invoices.id")
    cancel_reason: Mapped[str | None] = mapped_column(String(255))
    remarks: Mapped[str | None] = mapped_column(Text)


class TripExpense(Base, PKMixin):
    """Expenses on a trip (loading, cash toll, police/RTO, parking ...). Driver-paid lines are reimbursed in the
    driver settlement."""
    __tablename__ = "trip_expenses"
    trip_id: Mapped[int] = fk("trips.id", nullable=False, ondelete="CASCADE")
    expense_date: Mapped[date | None] = mapped_column(Date)
    expense_head: Mapped[str] = mapped_column(String(30))
    amount: Mapped[Decimal] = mapped_column(Money())
    paid_by: Mapped[str] = mapped_column(String(10), default="DRIVER")  # DRIVER / COMPANY
    bill_number: Mapped[str | None] = mapped_column(String(50))
    remarks: Mapped[str | None] = mapped_column(String(255))
    settlement_id: Mapped[int | None] = fk("driver_settlements.id")


class EwayBill(Base, TxnBase):
    """GST e-way bill for goods moved on a trip (validity: 1 day per 200 km, ODC 1 day per 20 km — configurable)."""
    __tablename__ = "eway_bills"
    __table_args__ = (Index("ix_eway_status_valid", "status", "valid_until"),)
    ewb_number: Mapped[str] = mapped_column(String(12), unique=True)
    trip_id: Mapped[int | None] = fk("trips.id")
    vehicle_id: Mapped[int | None] = fk("vehicles.id")  # Part-B vehicle
    generated_at: Mapped[datetime] = mapped_column(DateTime)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime)
    distance_km: Mapped[int | None] = mapped_column(Integer)
    is_odc: Mapped[bool] = mapped_column(Boolean, default=False)  # over-dimensional cargo
    doc_type: Mapped[str] = mapped_column(String(10), default="INV")  # INV / BIL / CHL / BOE / OTH
    doc_number: Mapped[str | None] = mapped_column(String(60))
    doc_date: Mapped[date | None] = mapped_column(Date)
    goods_value: Mapped[Decimal | None] = mapped_column(Money())
    from_place: Mapped[str | None] = mapped_column(String(150))
    to_place: Mapped[str | None] = mapped_column(String(150))
    transporter_gstin: Mapped[str | None] = mapped_column(String(15))
    status: Mapped[str] = mapped_column(String(15), default="ACTIVE")  # ACTIVE / EXTENDED / CLOSED / EXPIRED / CANCELLED
    extension_count: Mapped[int] = mapped_column(Integer, default=0)
    last_extension_reason: Mapped[str | None] = mapped_column(String(255))
    cancel_reason: Mapped[str | None] = mapped_column(String(255))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime)
    remarks: Mapped[str | None] = mapped_column(Text)


class DriverAdvance(Base, TxnBase):
    __tablename__ = "driver_advances"
    __table_args__ = (Index("ix_driver_adv_driver_status", "driver_id", "status"),)
    advance_number: Mapped[str] = mapped_column(String(30), unique=True)
    driver_id: Mapped[int] = fk("drivers.id", nullable=False, index=False)
    trip_id: Mapped[int | None] = fk("trips.id")
    advance_date: Mapped[date] = mapped_column(Date, index=True)
    amount: Mapped[Decimal] = mapped_column(Money())
    payment_mode: Mapped[str | None] = mapped_column(String(20))
    reference: Mapped[str | None] = mapped_column(String(60))
    purpose: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(15), default="OPEN")  # OPEN / SETTLED / CANCELLED
    settlement_id: Mapped[int | None] = fk("driver_settlements.id")
    remarks: Mapped[str | None] = mapped_column(Text)


class DriverSettlement(Base, TxnBase):
    """Trip sheet settlement: driver-paid expenses + allowance + other earnings − deductions − advances.
    net_payable > 0: company pays the driver; < 0: the driver returns the balance."""
    __tablename__ = "driver_settlements"
    settlement_number: Mapped[str] = mapped_column(String(30), unique=True)
    driver_id: Mapped[int] = fk("drivers.id", nullable=False)
    trip_id: Mapped[int | None] = fk("trips.id")
    settlement_date: Mapped[date] = mapped_column(Date, index=True)
    period_from: Mapped[date | None] = mapped_column(Date)
    period_to: Mapped[date | None] = mapped_column(Date)
    trip_days: Mapped[Decimal | None] = mapped_column(Qty())
    allowance_per_day: Mapped[Decimal | None] = mapped_column(Money())
    allowance_amount: Mapped[Decimal] = mapped_column(Money(), default=0)
    other_earnings: Mapped[Decimal] = mapped_column(Money(), default=0)
    deductions: Mapped[Decimal] = mapped_column(Money(), default=0)
    deduction_remarks: Mapped[str | None] = mapped_column(String(255))
    total_expenses: Mapped[Decimal] = mapped_column(Money(), default=0)
    total_advances: Mapped[Decimal] = mapped_column(Money(), default=0)
    net_payable: Mapped[Decimal] = mapped_column(Money(), default=0)
    settle_amount: Mapped[Decimal] = mapped_column(Money(), default=0)  # |net_payable| (bank matching)
    cost_center_id: Mapped[int | None] = fk("cost_centers.id")
    status: Mapped[str] = mapped_column(String(15), default="DRAFT")  # DRAFT / APPROVED / PAID / CANCELLED
    approved_by: Mapped[int | None] = fk("users.id", index=False)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime)
    paid_date: Mapped[date | None] = mapped_column(Date)
    payment_mode: Mapped[str | None] = mapped_column(String(20))
    payment_reference: Mapped[str | None] = mapped_column(String(60))
    remarks: Mapped[str | None] = mapped_column(Text)
