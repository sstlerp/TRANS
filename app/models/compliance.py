"""Drivers, generic renewal architecture and insurance policies (spec §7-§9)."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import JSON, Boolean, Date, DateTime, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, BigId, MasterBase, Money, PKMixin, TxnBase, fk


class Driver(Base, MasterBase):
    __tablename__ = "drivers"
    driver_code: Mapped[str] = mapped_column(String(30), unique=True)
    name: Mapped[str] = mapped_column(String(150), index=True)
    employee_number: Mapped[str | None] = mapped_column(String(30), index=True)
    mobile: Mapped[str | None] = mapped_column(String(15))
    alt_mobile: Mapped[str | None] = mapped_column(String(15))
    address: Mapped[str | None] = mapped_column(Text)
    date_of_birth: Mapped[date | None] = mapped_column(Date)
    license_number: Mapped[str | None] = mapped_column(String(30), unique=True)
    license_class: Mapped[str | None] = mapped_column(String(50))
    license_issue_date: Mapped[date | None] = mapped_column(Date)
    license_expiry_date: Mapped[date | None] = mapped_column(Date, index=True)
    hazardous_endorsement: Mapped[bool] = mapped_column(Boolean, default=False)
    medical_expiry_date: Mapped[date | None] = mapped_column(Date)
    branch_id: Mapped[int | None] = fk("branches.id")
    cost_center_id: Mapped[int | None] = fk("cost_centers.id")
    engagement_type: Mapped[str | None] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(30), default="ACTIVE")
    remarks: Mapped[str | None] = mapped_column(Text)


class RenewalType(Base, MasterBase):
    """Insurance, QTAX, National Permit, Fitness, PUCC, PESO, Hazmat, licence ... (configurable)."""
    __tablename__ = "renewal_types"
    code: Mapped[str] = mapped_column(String(30), unique=True)
    name: Mapped[str] = mapped_column(String(150))
    applies_to: Mapped[str] = mapped_column(String(20), default="VEHICLE")  # VEHICLE / DRIVER / COMPANY
    category: Mapped[str] = mapped_column(String(30), index=True)  # RENEWAL_CATEGORY lookup
    expense_type_id: Mapped[int | None] = fk("expense_types.id")
    requires_document: Mapped[bool] = mapped_column(Boolean, default=True)
    allows_multiple: Mapped[bool] = mapped_column(Boolean, default=False)
    default_validity_months: Mapped[int | None] = mapped_column(Integer)
    default_reminder_days: Mapped[str | None] = mapped_column(String(100))  # e.g. "60,30,15,7,1,0"
    description: Mapped[str | None] = mapped_column(String(255))


class RenewalRule(Base, MasterBase):
    """Decides which vehicles need which renewals (by category / sub-category / fuel)."""
    __tablename__ = "renewal_rules"
    code: Mapped[str] = mapped_column(String(30), unique=True)
    name: Mapped[str] = mapped_column(String(150))
    renewal_type_id: Mapped[int] = fk("renewal_types.id", nullable=False)
    cost_category_id: Mapped[int | None] = fk("cost_categories.id")
    sub_category_id: Mapped[int | None] = fk("vehicle_sub_categories.id")
    fuel_type_id: Mapped[int | None] = fk("fuel_types.id")
    is_mandatory: Mapped[bool] = mapped_column(Boolean, default=True)
    instances_required: Mapped[int] = mapped_column(Integer, default=1)  # e.g. 2 PESO certificates
    validity_months: Mapped[int | None] = mapped_column(Integer)
    reminder_days: Mapped[str | None] = mapped_column(String(100))
    grace_days: Mapped[int] = mapped_column(Integer, default=0)
    description: Mapped[str | None] = mapped_column(String(255))


class VehicleRenewalAssignment(Base, MasterBase):
    """One renewal requirement slot for a vehicle (several per vehicle allowed)."""
    __tablename__ = "vehicle_renewal_assignments"
    __table_args__ = (UniqueConstraint("vehicle_id", "renewal_type_id", "reference_label"),)
    vehicle_id: Mapped[int | None] = fk("vehicles.id")
    driver_id: Mapped[int | None] = fk("drivers.id")
    renewal_type_id: Mapped[int] = fk("renewal_types.id", nullable=False)
    renewal_rule_id: Mapped[int | None] = fk("renewal_rules.id")
    reference_label: Mapped[str] = mapped_column(String(100), default="PRIMARY")  # e.g. "PESO - TANK 2"
    is_applicable: Mapped[bool] = mapped_column(Boolean, default=True)
    reminder_days: Mapped[str | None] = mapped_column(String(100))
    remarks: Mapped[str | None] = mapped_column(String(255))


class VehicleRenewal(Base, TxnBase):
    """A certificate/policy/permit instance. Renewing creates a new row linked to the previous."""
    __tablename__ = "vehicle_renewals"
    __table_args__ = (Index("ix_vr_expiry_status", "expiry_date", "status"),)
    assignment_id: Mapped[int | None] = fk("vehicle_renewal_assignments.id")
    vehicle_id: Mapped[int | None] = fk("vehicles.id")
    driver_id: Mapped[int | None] = fk("drivers.id")
    renewal_type_id: Mapped[int] = fk("renewal_types.id", nullable=False)
    certificate_number: Mapped[str | None] = mapped_column(String(80), index=True)
    issue_date: Mapped[date | None] = mapped_column(Date)
    start_date: Mapped[date | None] = mapped_column(Date)
    expiry_date: Mapped[date | None] = mapped_column(Date)
    renewal_date: Mapped[date | None] = mapped_column(Date)
    amount: Mapped[Decimal | None] = mapped_column(Money())
    tax_amount: Mapped[Decimal | None] = mapped_column(Money())
    total_amount: Mapped[Decimal | None] = mapped_column(Money())
    provider_id: Mapped[int | None] = fk("providers.id")
    authority: Mapped[str | None] = mapped_column(String(150))
    document_number: Mapped[str | None] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(20), default="NOT_DUE", index=True)
    payment_status: Mapped[str] = mapped_column(String(20), default="PENDING")
    cost_center_id: Mapped[int | None] = fk("cost_centers.id")
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    previous_renewal_id: Mapped[int | None] = fk("vehicle_renewals.id")
    remarks: Mapped[str | None] = mapped_column(Text)


class RenewalHistory(Base, PKMixin):
    __tablename__ = "renewal_history"
    renewal_id: Mapped[int] = fk("vehicle_renewals.id", nullable=False)
    action: Mapped[str] = mapped_column(String(30))
    old_status: Mapped[str | None] = mapped_column(String(20))
    new_status: Mapped[str | None] = mapped_column(String(20))
    snapshot: Mapped[dict | None] = mapped_column(JSON)
    remarks: Mapped[str | None] = mapped_column(String(500))
    changed_by: Mapped[int | None] = mapped_column(BigId)
    changed_at: Mapped[datetime] = mapped_column(DateTime)


class InsurancePolicy(Base, TxnBase):
    """Multiple (overlapping) policies per vehicle: vehicle, driver, CLL, PLI, ..."""
    __tablename__ = "insurance_policies"
    __table_args__ = (UniqueConstraint("provider_id", "policy_number"),
                      Index("ix_ins_expiry", "expiry_date"))
    vehicle_id: Mapped[int | None] = fk("vehicles.id")
    driver_id: Mapped[int | None] = fk("drivers.id")
    provider_id: Mapped[int] = fk("providers.id", nullable=False)
    policy_type: Mapped[str] = mapped_column(String(30), index=True)  # INSURANCE_POLICY_TYPE lookup
    policy_number: Mapped[str] = mapped_column(String(80))
    insured_amount: Mapped[Decimal | None] = mapped_column(Money())
    start_date: Mapped[date] = mapped_column(Date)
    expiry_date: Mapped[date] = mapped_column(Date)
    premium: Mapped[Decimal | None] = mapped_column(Money())
    tax_amount: Mapped[Decimal | None] = mapped_column(Money())
    total_premium: Mapped[Decimal | None] = mapped_column(Money())
    payment_mode: Mapped[str | None] = mapped_column(String(30))
    payment_reference: Mapped[str | None] = mapped_column(String(80))
    payment_date: Mapped[date | None] = mapped_column(Date)
    payment_status: Mapped[str] = mapped_column(String(20), default="PENDING")
    renewal_status: Mapped[str] = mapped_column(String(20), default="NOT_DUE", index=True)
    cost_center_id: Mapped[int | None] = fk("cost_centers.id")
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    previous_policy_id: Mapped[int | None] = fk("insurance_policies.id")
    remarks: Mapped[str | None] = mapped_column(Text)


class InsuranceHistory(Base, PKMixin):
    __tablename__ = "insurance_history"
    policy_id: Mapped[int] = fk("insurance_policies.id", nullable=False)
    action: Mapped[str] = mapped_column(String(30))
    old_status: Mapped[str | None] = mapped_column(String(20))
    new_status: Mapped[str | None] = mapped_column(String(20))
    snapshot: Mapped[dict | None] = mapped_column(JSON)
    remarks: Mapped[str | None] = mapped_column(String(500))
    changed_by: Mapped[int | None] = mapped_column(BigId)
    changed_at: Mapped[datetime] = mapped_column(DateTime)
