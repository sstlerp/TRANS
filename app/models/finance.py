"""Contracts, invoices, bank transactions, allocations, financial links,
expense transactions, reconciliation history and approvals."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (JSON, Boolean, CheckConstraint, Date, DateTime, Index, Integer, String, Text,
                        UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, BigId, MasterBase, Money, PKMixin, SourceMixin, TxnBase, fk


# ───────────────────────────── configuration masters ─────────────────────────────
class CreditType(Base, MasterBase):
    """How a bank credit is treated. Nothing is revenue until classified."""
    __tablename__ = "credit_types"
    code: Mapped[str] = mapped_column(String(30), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    # OPERATING_INCOME / OTHER_INCOME / EXPENSE_REDUCTION / NON_OPERATING / BALANCE_SHEET / SETTLEMENT / EXCLUDE
    accounting_treatment: Mapped[str] = mapped_column(String(30))
    default_link_type: Mapped[str | None] = mapped_column(String(30))
    requires_link: Mapped[bool] = mapped_column(Boolean, default=False)
    description: Mapped[str | None] = mapped_column(String(255))


class ExpenseType(Base, MasterBase):
    __tablename__ = "expense_types"
    code: Mapped[str] = mapped_column(String(30), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    # FUEL/TOLL/MAINTENANCE/TYRE/INSURANCE/TAX/PERMIT/PESO/DRIVER/VENDOR/OTHER_DIRECT/COMMON/ASSET/LOAN/BANK_CHARGE/OTHER
    report_group: Mapped[str] = mapped_column(String(30), index=True)
    is_operating: Mapped[bool] = mapped_column(Boolean, default=True)  # False → capex / loan / balance sheet
    description: Mapped[str | None] = mapped_column(String(255))


class TransactionType(Base, MasterBase):
    __tablename__ = "transaction_types"
    code: Mapped[str] = mapped_column(String(30), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    module: Mapped[str] = mapped_column(String(30))
    direction: Mapped[str | None] = mapped_column(String(10))  # CR / DR / NA
    description: Mapped[str | None] = mapped_column(String(255))


class MatchingRule(Base, MasterBase):
    __tablename__ = "matching_rules"
    code: Mapped[str] = mapped_column(String(30), unique=True)
    name: Mapped[str] = mapped_column(String(150))
    link_type: Mapped[str] = mapped_column(String(30), index=True)
    priority: Mapped[int] = mapped_column(Integer, default=100)
    date_tolerance_days: Mapped[int] = mapped_column(Integer, default=3)
    amount_tolerance: Mapped[Decimal] = mapped_column(Money(), default=0)
    match_on_amount: Mapped[bool] = mapped_column(Boolean, default=True)
    match_on_utr: Mapped[bool] = mapped_column(Boolean, default=True)
    match_on_reference: Mapped[bool] = mapped_column(Boolean, default=True)
    match_on_party_name: Mapped[bool] = mapped_column(Boolean, default=True)
    narration_keywords: Mapped[str | None] = mapped_column(String(500))
    min_score: Mapped[int] = mapped_column(Integer, default=50)
    auto_approve: Mapped[bool] = mapped_column(Boolean, default=False)
    auto_approve_min_score: Mapped[int] = mapped_column(Integer, default=95)
    description: Mapped[str | None] = mapped_column(String(255))


# ───────────────────────────── contracts & receivables ─────────────────────────────
class Contract(Base, MasterBase):
    __tablename__ = "contracts"
    customer_id: Mapped[int] = fk("customers.id", nullable=False)
    contract_number: Mapped[str] = mapped_column(String(50), unique=True)
    contract_date: Mapped[date | None] = mapped_column(Date)
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    contract_type: Mapped[str | None] = mapped_column(String(30))
    billing_method: Mapped[str | None] = mapped_column(String(30))
    rate: Mapped[Decimal | None] = mapped_column(Money())
    rate_unit_id: Mapped[int | None] = fk("units.id")
    contract_value: Mapped[Decimal | None] = mapped_column(Money())
    cost_center_id: Mapped[int | None] = fk("cost_centers.id")
    branch_id: Mapped[int | None] = fk("branches.id")
    payment_terms_days: Mapped[int | None] = mapped_column(Integer)
    invoice_details: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE", index=True)
    remarks: Mapped[str | None] = mapped_column(Text)


class ContractVehicleAllocation(Base, PKMixin):
    __tablename__ = "contract_vehicle_allocations"
    contract_id: Mapped[int] = fk("contracts.id", nullable=False, ondelete="CASCADE")
    vehicle_id: Mapped[int | None] = fk("vehicles.id")
    cost_center_id: Mapped[int | None] = fk("cost_centers.id")
    allocation_percent: Mapped[Decimal | None] = mapped_column(Money())
    fixed_amount: Mapped[Decimal | None] = mapped_column(Money())
    effective_from: Mapped[date | None] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date)
    remarks: Mapped[str | None] = mapped_column(String(255))


class Invoice(Base, TxnBase):
    """Customer invoice / advance / credit note. Income is recognised here, never from bank credits."""
    __tablename__ = "invoices"
    __table_args__ = (Index("ix_inv_customer_status", "customer_id", "status"),)
    invoice_number: Mapped[str] = mapped_column(String(50), unique=True)
    invoice_type: Mapped[str] = mapped_column(String(20), default="INVOICE")  # INVOICE/PARTIAL/ADVANCE/CREDIT_NOTE/DEBIT_NOTE
    customer_id: Mapped[int] = fk("customers.id", nullable=False, index=False)
    contract_id: Mapped[int | None] = fk("contracts.id")
    invoice_date: Mapped[date] = mapped_column(Date, index=True)
    due_date: Mapped[date | None] = mapped_column(Date)
    period_from: Mapped[date | None] = mapped_column(Date)
    period_to: Mapped[date | None] = mapped_column(Date)
    taxable_amount: Mapped[Decimal] = mapped_column(Money(), default=0)
    tax_amount: Mapped[Decimal] = mapped_column(Money(), default=0)
    total_amount: Mapped[Decimal] = mapped_column(Money(), default=0)
    received_amount: Mapped[Decimal] = mapped_column(Money(), default=0)
    outstanding_amount: Mapped[Decimal] = mapped_column(Money(), default=0)
    status: Mapped[str] = mapped_column(String(20), default="OPEN")  # OPEN/PARTIALLY_PAID/PAID/OVERPAID/CANCELLED
    original_invoice_id: Mapped[int | None] = fk("invoices.id")
    remarks: Mapped[str | None] = mapped_column(Text)


class InvoiceAllocation(Base, PKMixin):
    """Income split of an invoice across vehicles / cost centers (e.g. ₹1L → A 40k, B 30k, C 30k)."""
    __tablename__ = "invoice_allocations"
    invoice_id: Mapped[int] = fk("invoices.id", nullable=False, ondelete="CASCADE")
    vehicle_id: Mapped[int | None] = fk("vehicles.id")
    cost_center_id: Mapped[int] = fk("cost_centers.id", nullable=False)
    amount: Mapped[Decimal] = mapped_column(Money())
    remarks: Mapped[str | None] = mapped_column(String(255))


# ───────────────────────────── bank ─────────────────────────────
class BankTransaction(Base, TxnBase, SourceMixin):
    __tablename__ = "bank_transactions"
    __table_args__ = (
        UniqueConstraint("bank_account_id", "txn_hash", name="uq_bank_txn_business_key"),
        Index("ix_bt_account_date", "bank_account_id", "txn_date"),
        Index("ix_bt_status_dir", "recon_status", "direction"),
        CheckConstraint("amount >= 0", name="amount_non_negative"),
    )
    bank_account_id: Mapped[int] = fk("bank_accounts.id", nullable=False, index=False)
    txn_date: Mapped[date] = mapped_column(Date, nullable=False)
    value_date: Mapped[date | None] = mapped_column(Date)
    narration: Mapped[str | None] = mapped_column(String(500))
    credit: Mapped[Decimal] = mapped_column(Money(), default=0)
    debit: Mapped[Decimal] = mapped_column(Money(), default=0)
    amount: Mapped[Decimal] = mapped_column(Money(), default=0)  # absolute
    direction: Mapped[str] = mapped_column(String(2))  # CR / DR
    reference_number: Mapped[str | None] = mapped_column(String(80), index=True)
    utr: Mapped[str | None] = mapped_column(String(40), index=True)
    cheque_number: Mapped[str | None] = mapped_column(String(20))
    balance: Mapped[Decimal | None] = mapped_column(Money())
    counterparty: Mapped[str | None] = mapped_column(String(200))
    # classification: every credit starts as UNCLASSIFIED (credit_type_id NULL)
    credit_type_id: Mapped[int | None] = fk("credit_types.id")
    expense_type_id: Mapped[int | None] = fk("expense_types.id")
    classification: Mapped[str] = mapped_column(String(30), default="UNCLASSIFIED")
    recon_status: Mapped[str] = mapped_column(String(20), default="UNMATCHED")
    matched_amount: Mapped[Decimal] = mapped_column(Money(), default=0)
    unmatched_amount: Mapped[Decimal] = mapped_column(Money(), default=0)
    allow_partial: Mapped[bool] = mapped_column(Boolean, default=False)
    remarks: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE")  # ACTIVE / VOID


class BankTransactionAllocation(Base, TxnBase):
    """Direct allocation of an (unmatched) bank debit/credit to cost centers."""
    __tablename__ = "bank_transaction_allocations"
    bank_transaction_id: Mapped[int] = fk("bank_transactions.id", nullable=False)
    cost_center_id: Mapped[int] = fk("cost_centers.id", nullable=False)
    expense_type_id: Mapped[int | None] = fk("expense_types.id")
    credit_type_id: Mapped[int | None] = fk("credit_types.id")
    vendor_id: Mapped[int | None] = fk("vendors.id")
    vehicle_id: Mapped[int | None] = fk("vehicles.id")
    amount: Mapped[Decimal] = mapped_column(Money())
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE")  # ACTIVE / PENDING_APPROVAL / REVERSED
    remarks: Mapped[str | None] = mapped_column(String(255))


class FinancialTransactionLink(Base, PKMixin):
    """Settlement ↔ underlying-transaction links. Bank records are settlements; links
    prevent counting both the bank debit and the operational fuel/toll/... row."""
    __tablename__ = "financial_transaction_links"
    __table_args__ = (
        Index("ix_ftl_source", "source_transaction_type", "source_transaction_id"),
        Index("ix_ftl_target", "target_transaction_type", "target_transaction_id"),
    )
    source_transaction_type: Mapped[str] = mapped_column(String(30))
    source_transaction_id: Mapped[int] = mapped_column(BigId)
    target_transaction_type: Mapped[str] = mapped_column(String(30))
    target_transaction_id: Mapped[int] = mapped_column(BigId)
    linked_amount: Mapped[Decimal] = mapped_column(Money())
    link_type: Mapped[str] = mapped_column(String(30), index=True)
    match_status: Mapped[str] = mapped_column(String(20), default="MATCHED", index=True)
    matching_method: Mapped[str] = mapped_column(String(20), default="MANUAL")  # MANUAL / SUGGESTED / AUTO / API
    match_score: Mapped[int | None] = mapped_column(Integer)
    matched_by: Mapped[int | None] = mapped_column(BigId)
    matched_at: Mapped[datetime | None] = mapped_column(DateTime)
    approved_by: Mapped[int | None] = mapped_column(BigId)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime)
    remarks: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime)


class ReconciliationHistory(Base, PKMixin):
    __tablename__ = "reconciliation_history"
    bank_transaction_id: Mapped[int] = fk("bank_transactions.id", nullable=False)
    action: Mapped[str] = mapped_column(String(30))
    old_status: Mapped[str | None] = mapped_column(String(20))
    new_status: Mapped[str | None] = mapped_column(String(20))
    amount: Mapped[Decimal | None] = mapped_column(Money())
    link_id: Mapped[int | None] = mapped_column(BigId)
    allocation_id: Mapped[int | None] = mapped_column(BigId)
    snapshot: Mapped[dict | None] = mapped_column(JSON)
    remarks: Mapped[str | None] = mapped_column(String(500))
    performed_by: Mapped[int | None] = mapped_column(BigId)
    performed_at: Mapped[datetime] = mapped_column(DateTime)


# ───────────────────────────── generic operational expenses / vendor invoices ─────────────────────────────
class ExpenseTransaction(Base, TxnBase, SourceMixin):
    """Operational expense not covered by a specialised module (driver cost, tax, permit fee,
    vendor invoice, common overhead ...)."""
    __tablename__ = "expense_transactions"
    __table_args__ = (Index("ix_exp_date", "expense_date"),)
    document_number: Mapped[str] = mapped_column(String(50), unique=True)
    expense_date: Mapped[date] = mapped_column(Date)
    expense_type_id: Mapped[int] = fk("expense_types.id", nullable=False)
    vendor_id: Mapped[int | None] = fk("vendors.id")
    driver_id: Mapped[int | None] = fk("drivers.id")
    vehicle_id: Mapped[int | None] = fk("vehicles.id")
    cost_center_id: Mapped[int | None] = fk("cost_centers.id")
    invoice_number: Mapped[str | None] = mapped_column(String(50), index=True)
    invoice_date: Mapped[date | None] = mapped_column(Date)
    amount: Mapped[Decimal] = mapped_column(Money())
    tax_amount: Mapped[Decimal] = mapped_column(Money(), default=0)
    total_amount: Mapped[Decimal] = mapped_column(Money())
    status: Mapped[str] = mapped_column(String(20), default="POSTED")
    description: Mapped[str | None] = mapped_column(Text)


class ExpenseAllocation(Base, PKMixin):
    __tablename__ = "expense_allocations"
    expense_id: Mapped[int] = fk("expense_transactions.id", nullable=False, ondelete="CASCADE")
    cost_center_id: Mapped[int] = fk("cost_centers.id", nullable=False)
    vehicle_id: Mapped[int | None] = fk("vehicles.id")
    amount: Mapped[Decimal] = mapped_column(Money())
    remarks: Mapped[str | None] = mapped_column(String(255))


# ───────────────────────────── approvals ─────────────────────────────
class ApprovalRule(Base, MasterBase):
    __tablename__ = "approval_rules"
    code: Mapped[str] = mapped_column(String(30), unique=True)
    name: Mapped[str] = mapped_column(String(150))
    action_type: Mapped[str] = mapped_column(String(40), index=True)
    min_amount: Mapped[Decimal | None] = mapped_column(Money())
    levels: Mapped[int] = mapped_column(Integer, default=1)
    approver_permission: Mapped[str] = mapped_column(String(80), default="approval.approve")
    allow_self_approval: Mapped[bool] = mapped_column(Boolean, default=False)
    description: Mapped[str | None] = mapped_column(String(255))


class ApprovalRequest(Base, TxnBase):
    __tablename__ = "approval_requests"
    action_type: Mapped[str] = mapped_column(String(40), index=True)
    entity_type: Mapped[str] = mapped_column(String(40))
    entity_id: Mapped[int | None] = mapped_column(BigId)
    amount: Mapped[Decimal | None] = mapped_column(Money())
    payload: Mapped[dict | None] = mapped_column(JSON)
    summary: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(20), default="PENDING", index=True)
    current_level: Mapped[int] = mapped_column(Integer, default=0)
    required_levels: Mapped[int] = mapped_column(Integer, default=1)
    rule_id: Mapped[int | None] = fk("approval_rules.id")
    requested_by: Mapped[int | None] = mapped_column(BigId)
    remarks: Mapped[str | None] = mapped_column(String(500))


class ApprovalAction(Base, PKMixin):
    __tablename__ = "approval_actions"
    request_id: Mapped[int] = fk("approval_requests.id", nullable=False)
    level: Mapped[int] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(String(20))  # APPROVE / REJECT
    acted_by: Mapped[int | None] = mapped_column(BigId)
    acted_at: Mapped[datetime] = mapped_column(DateTime)
    remarks: Mapped[str | None] = mapped_column(String(500))
