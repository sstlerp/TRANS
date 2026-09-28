"""Organisation, geography, parties and generic configurable lookups."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import Boolean, Date, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, MasterBase, Money, fk


class LookupValue(Base, MasterBase):
    """Configurable dropdown values (vehicle status, ownership type, contract type ...).

    Nothing in the UI uses a hard-coded list: every business dropdown is a
    `category` in this table, editable by administrators.
    """
    __tablename__ = "lookup_values"
    __table_args__ = (UniqueConstraint("category", "code"),)
    category: Mapped[str] = mapped_column(String(50), index=True)
    code: Mapped[str] = mapped_column(String(50))
    label: Mapped[str] = mapped_column(String(150))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    description: Mapped[str | None] = mapped_column(String(255))
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)


class Company(Base, MasterBase):
    __tablename__ = "companies"
    code: Mapped[str] = mapped_column(String(20), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    legal_name: Mapped[str | None] = mapped_column(String(255))
    gstin: Mapped[str | None] = mapped_column(String(15))
    pan: Mapped[str | None] = mapped_column(String(10))
    address: Mapped[str | None] = mapped_column(Text)
    state_id: Mapped[int | None] = fk("states.id")
    phone: Mapped[str | None] = mapped_column(String(20))
    email: Mapped[str | None] = mapped_column(String(150))
    timezone: Mapped[str] = mapped_column(String(50), default="Asia/Kolkata")
    currency: Mapped[str] = mapped_column(String(3), default="INR")


class State(Base, MasterBase):
    __tablename__ = "states"
    code: Mapped[str] = mapped_column(String(5), unique=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    gst_code: Mapped[str | None] = mapped_column(String(2))


class District(Base, MasterBase):
    __tablename__ = "districts"
    __table_args__ = (UniqueConstraint("state_id", "name"),)
    state_id: Mapped[int] = fk("states.id", nullable=False)
    code: Mapped[str | None] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(100))


class Rto(Base, MasterBase):
    __tablename__ = "rtos"
    code: Mapped[str] = mapped_column(String(10), unique=True)
    name: Mapped[str] = mapped_column(String(150))
    state_id: Mapped[int | None] = fk("states.id")
    district_id: Mapped[int | None] = fk("districts.id")


class Branch(Base, MasterBase):
    __tablename__ = "branches"
    company_id: Mapped[int] = fk("companies.id", nullable=False)
    code: Mapped[str] = mapped_column(String(20), unique=True)
    name: Mapped[str] = mapped_column(String(150))
    address: Mapped[str | None] = mapped_column(Text)
    state_id: Mapped[int | None] = fk("states.id")
    district_id: Mapped[int | None] = fk("districts.id")
    phone: Mapped[str | None] = mapped_column(String(20))
    email: Mapped[str | None] = mapped_column(String(150))
    gstin: Mapped[str | None] = mapped_column(String(15))


class Department(Base, MasterBase):
    __tablename__ = "departments"
    code: Mapped[str] = mapped_column(String(20), unique=True)
    name: Mapped[str] = mapped_column(String(150))
    branch_id: Mapped[int | None] = fk("branches.id")


class Location(Base, MasterBase):
    """Physical places: godowns, workshops, warehouses, yards, offices.

    `location_type` is a LOCATION_TYPE lookup, so new kinds need no code change.
    """
    __tablename__ = "locations"
    code: Mapped[str] = mapped_column(String(20), unique=True)
    name: Mapped[str] = mapped_column(String(150))
    location_type: Mapped[str] = mapped_column(String(50), index=True)
    branch_id: Mapped[int | None] = fk("branches.id")
    address: Mapped[str | None] = mapped_column(Text)
    state_id: Mapped[int | None] = fk("states.id")
    district_id: Mapped[int | None] = fk("districts.id")
    pincode: Mapped[str | None] = mapped_column(String(6))
    contact_person: Mapped[str | None] = mapped_column(String(100))
    phone: Mapped[str | None] = mapped_column(String(20))


class Unit(Base, MasterBase):
    __tablename__ = "units"
    code: Mapped[str] = mapped_column(String(20), unique=True)
    name: Mapped[str] = mapped_column(String(60))
    unit_type: Mapped[str] = mapped_column(String(30))  # VOLUME / MASS / ENERGY / LENGTH / COUNT / OTHER


class Vendor(Base, MasterBase):
    """Suppliers, service providers, workshops, retreaders ..."""
    __tablename__ = "vendors"
    code: Mapped[str] = mapped_column(String(20), unique=True)
    name: Mapped[str] = mapped_column(String(200), index=True)
    vendor_type: Mapped[str] = mapped_column(String(50), index=True)
    gstin: Mapped[str | None] = mapped_column(String(15))
    pan: Mapped[str | None] = mapped_column(String(10))
    contact_person: Mapped[str | None] = mapped_column(String(100))
    phone: Mapped[str | None] = mapped_column(String(20))
    email: Mapped[str | None] = mapped_column(String(150))
    address: Mapped[str | None] = mapped_column(Text)
    state_id: Mapped[int | None] = fk("states.id")
    bank_name: Mapped[str | None] = mapped_column(String(150))
    bank_account_no: Mapped[str | None] = mapped_column(String(30))
    bank_ifsc: Mapped[str | None] = mapped_column(String(11))
    payment_terms_days: Mapped[int | None] = mapped_column(Integer)
    match_keywords: Mapped[str | None] = mapped_column(String(255))  # narration keywords for bank matching
    remarks: Mapped[str | None] = mapped_column(Text)


class Customer(Base, MasterBase):
    __tablename__ = "customers"
    code: Mapped[str] = mapped_column(String(20), unique=True)
    name: Mapped[str] = mapped_column(String(200), index=True)
    gstin: Mapped[str | None] = mapped_column(String(15))
    pan: Mapped[str | None] = mapped_column(String(10))
    contact_person: Mapped[str | None] = mapped_column(String(100))
    phone: Mapped[str | None] = mapped_column(String(20))
    email: Mapped[str | None] = mapped_column(String(150))
    billing_address: Mapped[str | None] = mapped_column(Text)
    state_id: Mapped[int | None] = fk("states.id")
    credit_days: Mapped[int | None] = mapped_column(Integer)
    credit_limit: Mapped[Decimal | None] = mapped_column(Money())
    match_keywords: Mapped[str | None] = mapped_column(String(255))
    remarks: Mapped[str | None] = mapped_column(Text)


class Provider(Base, MasterBase):
    """External statement/data providers (bank, toll, fuel, insurance, maintenance, GPS ...)."""
    __tablename__ = "providers"
    code: Mapped[str] = mapped_column(String(30), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    provider_type: Mapped[str] = mapped_column(String(30), index=True)
    vendor_id: Mapped[int | None] = fk("vendors.id")
    contact_person: Mapped[str | None] = mapped_column(String(100))
    phone: Mapped[str | None] = mapped_column(String(20))
    email: Mapped[str | None] = mapped_column(String(150))
    website: Mapped[str | None] = mapped_column(String(200))
    remarks: Mapped[str | None] = mapped_column(Text)


class Bank(Base, MasterBase):
    __tablename__ = "banks"
    code: Mapped[str] = mapped_column(String(20), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    short_name: Mapped[str | None] = mapped_column(String(30))
    provider_id: Mapped[int | None] = fk("providers.id")


class BankAccount(Base, MasterBase):
    __tablename__ = "bank_accounts"
    __table_args__ = (UniqueConstraint("bank_id", "account_number"),)
    bank_id: Mapped[int] = fk("banks.id", nullable=False)
    company_id: Mapped[int | None] = fk("companies.id")
    branch_id: Mapped[int | None] = fk("branches.id")
    code: Mapped[str] = mapped_column(String(20), unique=True)
    account_name: Mapped[str] = mapped_column(String(200))
    account_number: Mapped[str] = mapped_column(String(34))
    account_type: Mapped[str] = mapped_column(String(30))
    bank_branch: Mapped[str | None] = mapped_column(String(150))
    ifsc: Mapped[str | None] = mapped_column(String(11))
    opening_balance: Mapped[Decimal] = mapped_column(Money(), default=0)
    opening_date: Mapped[date | None] = mapped_column(Date)
    closing_balance: Mapped[Decimal | None] = mapped_column(Money())
    closing_balance_date: Mapped[date | None] = mapped_column(Date)
    remarks: Mapped[str | None] = mapped_column(Text)
