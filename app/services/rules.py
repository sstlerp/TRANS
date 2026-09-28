"""Business-rule configuration (spec §67).

Every tolerance/threshold/policy used by services is read through `rule()`.
Values live in the `business_rules` table (editable in Administration →
System Settings); `DEFAULTS` only seeds the table and acts as a fallback so a
missing row never crashes a service.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

# key: (module, default, type, description, choices)
DEFAULTS: dict[str, tuple[str, str, str, str, str | None]] = {
    "RENEWAL_REMINDER_DAYS": ("COMPLIANCE", "60,30,15,7,1,0", "LIST", "Default reminder days before expiry", None),
    "RENEWAL_UPCOMING_DAYS": ("COMPLIANCE", "30", "INT", "Days before expiry a renewal becomes UPCOMING", None),
    "RENEWAL_DUE_DAYS": ("COMPLIANCE", "7", "INT", "Days before expiry a renewal becomes DUE", None),
    "FUEL_AMOUNT_TOLERANCE_PCT": ("FUEL", "2", "DECIMAL", "Allowed % difference between qty×rate and amount", None),
    "FUEL_AMOUNT_TOLERANCE_ABS": ("FUEL", "5", "DECIMAL", "Allowed absolute ₹ difference between qty×rate and amount", None),
    "FUEL_COMPATIBILITY_MODE": ("FUEL", "ERROR", "CHOICE", "Fuel type not configured for vehicle", "ERROR,WARN,IGNORE"),
    "FUEL_EFFICIENCY_ENABLED": ("FUEL", "true", "BOOL", "Calculate fuel efficiency from odometer", None),
    "ODOMETER_DECREASE_MODE": ("FLEET", "ERROR", "CHOICE", "Lower odometer than previous reading", "ERROR,WARN"),
    "ODOMETER_MAX_DAILY_KM": ("FLEET", "1500", "INT", "Maximum plausible km per day between readings", None),
    "ODOMETER_TOLERANCE_KM": ("FLEET", "0", "INT", "Tolerance (km) below previous reading that is accepted", None),
    "BANK_MATCH_DATE_TOLERANCE_DAYS": ("FINANCE", "3", "INT", "Default date window for match suggestions", None),
    "BANK_ALLOW_PARTIAL_ALLOCATION": ("FINANCE", "false", "BOOL", "Allow saving allocations that do not total the bank amount", None),
    "DUPLICATE_FILE_CHECK": ("IMPORT", "WARN", "CHOICE", "Same file (hash) imported again", "BLOCK,WARN"),
    "INCOME_RECOGNITION": ("FINANCE", "INVOICE", "CHOICE", "Income basis for profitability", "INVOICE,RECEIPT"),
    "EXPENSE_INCLUDE_TAX": ("FINANCE", "false", "BOOL", "Include GST in operating cost reports", None),
    "REFUND_TREATMENT": ("FINANCE", "NET_AGAINST_EXPENSE", "CHOICE", "Accounting for linked refunds", "NET_AGAINST_EXPENSE,OTHER_INCOME"),
    "COMMON_COST_ALLOCATION_BASIS": ("FINANCE", "NONE", "CHOICE", "Distribute COMMON cost-center costs to vehicles", "NONE,EQUAL,KM,REVENUE"),
    "TYRE_MIN_TREAD_MM": ("TYRE", "3", "DECIMAL", "Alert when tread depth is at or below", None),
    "TYRE_COST_INCLUDE_GST": ("TYRE", "true", "BOOL", "Include GST in tyre cost/km", None),
    "TYRE_COST_DEDUCT_SCRAP": ("TYRE", "true", "BOOL", "Deduct scrap value in tyre cost/km", None),
    "TYRE_COST_DEDUCT_WARRANTY": ("TYRE", "true", "BOOL", "Deduct approved warranty credits in tyre cost/km", None),
    "TYRE_ODOMETER_DECREASE_MODE": ("TYRE", "ERROR", "CHOICE", "Removal odometer below installation odometer", "ERROR,WARN"),
    "MAINTENANCE_DUE_ALERT_KM": ("MAINTENANCE", "500", "INT", "Alert when next service is within km", None),
    "MAINTENANCE_DUE_ALERT_DAYS": ("MAINTENANCE", "7", "INT", "Alert when next service is within days", None),
    "TOLL_PLAZA_REQUIRED": ("TOLL", "false", "BOOL", "Unmatched plaza keeps toll row in review", None),
}


def _cast(value: str, typ: str) -> Any:
    if typ == "INT":
        return int(value)
    if typ == "DECIMAL":
        return Decimal(value)
    if typ == "BOOL":
        return str(value).strip().lower() in ("1", "true", "yes", "y", "on")
    if typ == "LIST":
        return [x.strip() for x in str(value).split(",") if x.strip()]
    return value


def rule(db: Session, key: str) -> Any:
    from app.models.system import BusinessRule
    row = db.execute(select(BusinessRule).where(BusinessRule.rule_key == key, BusinessRule.is_active.is_(True))
                     ).scalar_one_or_none()
    default = DEFAULTS.get(key)
    if row is not None:
        try:
            return _cast(row.value, row.value_type)
        except (ValueError, ArithmeticError):
            pass
    if default is None:
        raise KeyError(f"Unknown business rule {key}")
    return _cast(default[1], default[2])


def reminder_days(value: str | None, db: Session) -> list[int]:
    raw = value.split(",") if value else rule(db, "RENEWAL_REMINDER_DAYS")
    out = sorted({int(str(x).strip()) for x in raw if str(x).strip().lstrip("-").isdigit()}, reverse=True)
    return out


def set_rule(db: Session, key: str, value: str) -> None:
    from app.models.system import BusinessRule
    row = db.execute(select(BusinessRule).where(BusinessRule.rule_key == key)).scalar_one_or_none()
    if row is None:
        mod, _, typ, desc, ch = DEFAULTS[key]
        row = BusinessRule(rule_key=key, module=mod, value_type=typ, description=desc, choices=ch, value=value)
        db.add(row)
    else:
        row.value = value
    db.flush()
