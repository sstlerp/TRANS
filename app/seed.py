"""Idempotent seed data.

    python -m app.seed            # reference data: permissions, roles, admin, lookups, rules, masters, templates
    python -m app.seed --demo     # + demo organisation, fleet, drivers, contracts, plazas, stations, tyres

Seed rows are ordinary editable master data (nothing is immutable).
"""
from __future__ import annotations

import argparse
import os
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.core.utils import normalize_vehicle_number, now, today
from app.models import compliance as C
from app.models import finance as FI
from app.models import fleet as FL
from app.models import imports as IM
from app.models import operations as OP
from app.models import org as O
from app.models import system as S
from app.models import tyres as TY
from app.services.rules import DEFAULTS

MODULES = ["dashboard", "org", "master", "fleet", "driver", "compliance", "contract", "finance", "import", "fuel",
           "toll", "maintenance", "tyre", "vendor", "report", "admin", "audit", "approval", "notification", "document"]
CRUD = ["view", "create", "edit", "delete"]
SPECIAL = {"fleet": ["reclassify", "odometer_override"], "compliance": ["renew"], "finance": ["match", "allocate"],
           "fuel": ["override"], "tyre": ["move", "dispose", "correct", "override"], "import": ["run"],
           "report": ["export"], "approval": ["approve"]}


def upsert(db: Session, model, keys: dict, values: dict | None = None):
    obj = db.execute(select(model).filter_by(**keys)).scalar_one_or_none()
    if obj is None:
        obj = model(**keys, **(values or {}))
        db.add(obj)
        db.flush()
    return obj


def seed_security(db: Session) -> None:
    perms = {}
    for m in MODULES:
        for a in CRUD + SPECIAL.get(m, []):
            code = f"{m}.{a}"
            perms[code] = upsert(db, S.Permission, {"code": code}, {"module": m, "action": a,
                                                                   "description": f"{a.title()} {m}"})
    roles = {
        "ADMIN": ("Administrator", list(perms)),
        "FINANCE": ("Finance / Accounts", [p for p in perms if p.split(".")[0] in (
            "dashboard", "finance", "contract", "report", "import", "vendor", "notification", "document", "audit")
            or p in ("fleet.view", "fuel.view", "toll.view", "maintenance.view", "tyre.view", "compliance.view",
                     "master.view", "org.view", "approval.view", "driver.view")]),
        "OPERATIONS": ("Fleet Operations", [p for p in perms if p.split(".")[0] in (
            "dashboard", "fleet", "driver", "compliance", "fuel", "toll", "maintenance", "tyre", "import", "report",
            "notification", "document", "vendor") and p not in ("fleet.odometer_override", "fuel.override",
                                                                 "tyre.correct", "tyre.override")]
            + ["master.view", "org.view", "approval.view"]),
        "APPROVER": ("Approver / Manager", [p for p in perms if p.endswith(".view")] + [
            "approval.approve", "fleet.odometer_override", "fuel.override", "tyre.override", "tyre.correct",
            "report.export", "audit.view"]),
        "VIEWER": ("Read-only", [p for p in perms if p.endswith(".view") and not p.startswith(("admin", "audit"))]),
    }
    for code, (name, plist) in roles.items():
        r = upsert(db, S.Role, {"code": code}, {"name": name})
        if not r.permissions:
            r.permissions = [perms[p] for p in sorted(set(plist))]
    pw = os.environ.get("ERP_ADMIN_PASSWORD", "Admin@12345")
    admin = upsert(db, S.User, {"username": "admin"}, {"full_name": "System Administrator", "password_hash": hash_password(pw),
                                                        "is_superuser": True, "must_change_password": "ERP_ADMIN_PASSWORD" not in os.environ})
    if not admin.roles:
        admin.roles = [db.execute(select(S.Role).where(S.Role.code == "ADMIN")).scalar_one()]


LOOKUPS = {
    "VEHICLE_TYPE": ["HCV", "MCV", "LCV", "TRACTOR", "TRAILER", "TANKER", "CAR", "OTHER"],
    "VEHICLE_STATUS": ["ACTIVE", "IDLE", "UNDER_MAINTENANCE", "BREAKDOWN", "SOLD", "SCRAPPED"],
    "OWNERSHIP_TYPE": ["OWNED", "LEASED", "HIRED", "ATTACHED", "FINANCED"],
    "LOCATION_TYPE": ["OFFICE", "GODOWN", "WORKSHOP", "WAREHOUSE", "YARD", "PARKING", "OTHER"],
    "VENDOR_TYPE": ["SUPPLIER", "SERVICE_PROVIDER", "WORKSHOP", "TYRE_DEALER", "RETREADER", "SPARES", "TRANSPORTER", "OTHER"],
    "ACCOUNT_TYPE": ["CURRENT", "SAVINGS", "OD", "CC", "ESCROW"],
    "CONTRACT_TYPE": ["DEDICATED", "SPOT", "ANNUAL_RATE", "MONTHLY_FIXED", "TRIP_BASED"],
    "BILLING_METHOD": ["PER_TRIP", "PER_KM", "PER_TONNE", "PER_KL", "FIXED_MONTHLY", "PER_DAY"],
    "CONTRACT_STATUS": ["DRAFT", "ACTIVE", "SUSPENDED", "EXPIRED", "CLOSED"],
    "INSURANCE_POLICY_TYPE": ["VEHICLE", "DRIVER", "CLL", "PLI", "GOODS_IN_TRANSIT", "OTHER"],
    "PAYMENT_MODE": ["NEFT", "RTGS", "UPI", "CHEQUE", "CARD", "CASH", "AUTO_DEBIT"],
    "DRIVER_ENGAGEMENT": ["EMPLOYEE", "CONTRACT", "THIRD_PARTY"],
    "DRIVER_STATUS": ["ACTIVE", "ON_LEAVE", "SUSPENDED", "LEFT"],
    "LICENSE_CLASS": ["LMV", "HMV", "HGMV", "HPMV", "TRANS", "HAZ"],
    "RENEWAL_CATEGORY": ["INSURANCE", "TAX", "PERMIT", "FITNESS", "PUCC", "PESO", "HAZMAT", "REGISTRATION", "LICENSE", "OTHER"],
    "TYRE_TYPE": ["RADIAL", "NYLON", "TUBELESS", "TUBE_TYPE"],
    "TYRE_CONDITION": ["GOOD", "FAIR", "WORN", "DAMAGED", "CUT", "BULGE", "UNEVEN_WEAR"],
    "TYRE_MAINTENANCE_TYPE": ["ROTATION", "ALIGNMENT", "BALANCING", "PRESSURE_CHECK", "PUNCTURE_REPAIR", "VALVE_REPLACEMENT",
                              "TYRE_REPAIR", "RETREADING", "INSPECTION"],
    "RETREAD_TYPE": ["PRECURED", "MOULD_CURE", "HOT", "COLD"],
    "DOCUMENT_TYPE": ["INSURANCE_POLICY", "TAX_RECEIPT", "PERMIT", "FITNESS_CERT", "PUCC", "PESO_LICENSE", "HAZMAT_CERT",
                      "RC", "DRIVING_LICENSE", "ID_PROOF", "CONTRACT", "INVOICE", "BANK_STATEMENT", "TOLL_STATEMENT",
                      "FUEL_STATEMENT", "MAINTENANCE_INVOICE", "TYRE_INVOICE", "WARRANTY_CLAIM", "PHOTO", "OTHER"],
    "MAINTENANCE_CATEGORY": ["PREVENTIVE", "BREAKDOWN", "REPAIR", "SERVICE", "ACCIDENT", "BODY_WORK", "ELECTRICAL"],
    "TOLL_DIRECTION": ["UP", "DOWN", "ENTRY", "EXIT", "NA"],
}


def seed_reference(db: Session) -> None:
    for cat, codes in LOOKUPS.items():
        for i, c in enumerate(codes):
            upsert(db, O.LookupValue, {"category": cat, "code": c}, {"label": c.replace("_", " ").title(), "sort_order": i})
    for key, (mod, val, typ, desc, ch) in DEFAULTS.items():
        upsert(db, S.BusinessRule, {"rule_key": key}, {"module": mod, "value": val, "value_type": typ, "description": desc,
                                                       "choices": ch})
    states = [("TN", "Tamil Nadu", "33"), ("KA", "Karnataka", "29"), ("KL", "Kerala", "32"), ("AP", "Andhra Pradesh", "37"),
              ("TG", "Telangana", "36"), ("MH", "Maharashtra", "27"), ("GJ", "Gujarat", "24"), ("DL", "Delhi", "07"),
              ("RJ", "Rajasthan", "08"), ("UP", "Uttar Pradesh", "09"), ("WB", "West Bengal", "19"), ("OD", "Odisha", "21"),
              ("MP", "Madhya Pradesh", "23"), ("HR", "Haryana", "06"), ("PB", "Punjab", "03"), ("PY", "Puducherry", "34"),
              ("BR", "Bihar", "10"), ("JH", "Jharkhand", "20"), ("CG", "Chhattisgarh", "22"), ("GA", "Goa", "30"),
              ("AS", "Assam", "18"), ("UK", "Uttarakhand", "05"), ("HP", "Himachal Pradesh", "02"), ("JK", "Jammu and Kashmir", "01")]
    for c, n, g in states:
        upsert(db, O.State, {"code": c}, {"name": n, "gst_code": g})
    tn = db.execute(select(O.State).where(O.State.code == "TN")).scalar_one()
    for d in ("Chennai", "Tiruvallur", "Kancheepuram", "Coimbatore", "Salem", "Madurai", "Tiruchirappalli", "Vellore",
              "Krishnagiri", "Namakkal"):
        upsert(db, O.District, {"state_id": tn.id, "name": d})
    chn = db.execute(select(O.District).where(O.District.name == "Chennai")).scalar_one()
    for code, name in (("TN01", "Chennai Central"), ("TN02", "Chennai North West"), ("TN04", "Chennai East"),
                       ("TN09", "Chennai West"), ("TN18", "Redhills"), ("TN20", "Tiruvallur"), ("TN28", "Namakkal North")):
        upsert(db, O.Rto, {"code": code}, {"name": name, "state_id": tn.id, "district_id": chn.id})
    units = [("L", "Litre", "VOLUME"), ("KG", "Kilogram", "MASS"), ("KWH", "Kilowatt-hour", "ENERGY"), ("KM", "Kilometre", "LENGTH"),
             ("MM", "Millimetre", "LENGTH"), ("M", "Metre", "LENGTH"), ("FT", "Feet", "LENGTH"), ("TON", "Tonne", "MASS"),
             ("KL", "Kilolitre", "VOLUME"), ("NOS", "Numbers", "COUNT"), ("TRIP", "Trip", "COUNT"), ("MONTH", "Month", "TIME"),
             ("DAY", "Day", "TIME"), ("HR", "Hour", "TIME"), ("PSI", "PSI", "OTHER")]
    for c, n, t in units:
        upsert(db, O.Unit, {"code": c}, {"name": n, "unit_type": t})
    u = {x.code: x.id for x in db.execute(select(O.Unit)).scalars()}
    for c, n, unit, lbl, lo, hi in (("DIESEL", "Diesel", "L", "KM/L", "2.0", "6.5"), ("PETROL", "Petrol", "L", "KM/L", "5", "25"),
                                    ("CNG", "CNG", "KG", "KM/KG", "2.5", "12"), ("LNG", "LNG", "KG", "KM/KG", "2.0", "8"),
                                    ("ELECTRIC", "Electric", "KWH", "KM/kWh", "0.5", "8"), ("LPG", "Auto LPG", "L", "KM/L", "3", "15"),
                                    ("HYBRID", "Hybrid", "L", "KM/L", "5", "30"), ("OTHER", "Other", None, None, None, None)):
        upsert(db, FL.FuelType, {"code": c}, {"name": n, "default_unit_id": u.get(unit), "efficiency_label": lbl,
                                              "min_efficiency": Decimal(lo) if lo else None,
                                              "max_efficiency": Decimal(hi) if hi else None})
    # cost categories / sub-categories / attributes (editable examples — not hard-coded in code)
    cats = {}
    for c, n, ap in (("TRUCK", "Truck", "VEHICLE"), ("TRAILER", "Trailer", "VEHICLE"), ("ADMIN", "Administration", "NON_VEHICLE"),
                     ("WORKSHOP", "Workshop", "NON_VEHICLE"), ("WAREHOUSE", "Warehouse", "NON_VEHICLE"),
                     ("COMMON", "Common / Corporate", "NON_VEHICLE")):
        cats[c] = upsert(db, FL.CostCategory, {"code": c}, {"name": n, "applies_to": ap})
    # tyre positions & layouts
    pos = {}
    positions = [("FL", "Front Left", 1, "LEFT", "SINGLE", "STEER"), ("FR", "Front Right", 1, "RIGHT", "SINGLE", "STEER"),
                 ("R1LO", "Rear-1 Left Outer", 2, "LEFT", "OUTER", "DRIVE"), ("R1LI", "Rear-1 Left Inner", 2, "LEFT", "INNER", "DRIVE"),
                 ("R1RI", "Rear-1 Right Inner", 2, "RIGHT", "INNER", "DRIVE"), ("R1RO", "Rear-1 Right Outer", 2, "RIGHT", "OUTER", "DRIVE"),
                 ("R2LO", "Rear-2 Left Outer", 3, "LEFT", "OUTER", "DRIVE"), ("R2LI", "Rear-2 Left Inner", 3, "LEFT", "INNER", "DRIVE"),
                 ("R2RI", "Rear-2 Right Inner", 3, "RIGHT", "INNER", "DRIVE"), ("R2RO", "Rear-2 Right Outer", 3, "RIGHT", "OUTER", "DRIVE"),
                 ("T1LO", "Trailer-1 Left Outer", 4, "LEFT", "OUTER", "TRAILER"), ("T1LI", "Trailer-1 Left Inner", 4, "LEFT", "INNER", "TRAILER"),
                 ("T1RI", "Trailer-1 Right Inner", 4, "RIGHT", "INNER", "TRAILER"), ("T1RO", "Trailer-1 Right Outer", 4, "RIGHT", "OUTER", "TRAILER"),
                 ("T2LO", "Trailer-2 Left Outer", 5, "LEFT", "OUTER", "TRAILER"), ("T2LI", "Trailer-2 Left Inner", 5, "LEFT", "INNER", "TRAILER"),
                 ("T2RI", "Trailer-2 Right Inner", 5, "RIGHT", "INNER", "TRAILER"), ("T2RO", "Trailer-2 Right Outer", 5, "RIGHT", "OUTER", "TRAILER"),
                 ("SP1", "Spare 1", 9, "CENTER", "SINGLE", "SPARE"), ("SP2", "Spare 2", 9, "CENTER", "SINGLE", "SPARE")]
    for i, (c, n, ax, side, pl, pt) in enumerate(positions):
        pos[c] = upsert(db, TY.TyrePosition, {"code": c}, {"name": n, "axle_number": ax, "side": side, "placement": pl,
                                                            "position_type": pt, "display_order": i})
    layouts = {
        "6W": ("6-wheeler (2 axles)", 2, [("FL", 1, 1), ("FR", 1, 4), ("R1LO", 2, 1), ("R1LI", 2, 2), ("R1RI", 2, 3), ("R1RO", 2, 4), ("SP1", 9, 2)]),
        "10W": ("10-wheeler (3 axles)", 3, [("FL", 1, 1), ("FR", 1, 4), ("R1LO", 2, 1), ("R1LI", 2, 2), ("R1RI", 2, 3), ("R1RO", 2, 4),
                                            ("R2LO", 3, 1), ("R2LI", 3, 2), ("R2RI", 3, 3), ("R2RO", 3, 4), ("SP1", 9, 2)]),
        "TR8": ("Trailer 2-axle (8 tyres)", 2, [("T1LO", 1, 1), ("T1LI", 1, 2), ("T1RI", 1, 3), ("T1RO", 1, 4), ("T2LO", 2, 1),
                                                ("T2LI", 2, 2), ("T2RI", 2, 3), ("T2RO", 2, 4), ("SP1", 9, 2)]),
    }
    lay = {}
    for c, (n, ax, rows) in layouts.items():
        L = upsert(db, TY.TyreLayout, {"code": c}, {"name": n, "axle_count": ax})
        lay[c] = L
        for pc, r, col in rows:
            upsert(db, TY.VehicleTyrePositionConfiguration, {"layout_id": L.id, "position_id": pos[pc].id},
                   {"display_row": r, "display_col": col, "is_spare": pc.startswith("SP")})
    subs = {}
    for cat, c, n, layout in (("TRUCK", "LPG", "LPG", "10W"), ("TRUCK", "OPEN_BODY", "Open Body", "10W"),
                              ("TRUCK", "CONTAINER", "Container", "6W"), ("TRAILER", "TR_FLATBED", "Flatbed Trailer", "TR8"),
                              ("TRAILER", "TR_LPG", "LPG Bullet Trailer", "TR8")):
        subs[c] = upsert(db, FL.VehicleSubCategory, {"code": c}, {"cost_category_id": cats[cat].id, "name": n,
                                                                  "default_tyre_layout_id": lay[layout].id})
    attrs = {"LPG": [("TANK_CAP", "Tank Capacity", "DECIMAL", "KL", True), ("AXLES", "Axle Count", "INTEGER", None, True),
                     ("GVW", "GVW", "DECIMAL", "KG", False), ("TANK_TEST", "Tank Hydro-test Date", "DATE", None, False)],
             "OPEN_BODY": [("LOAD_CAP", "Load Capacity", "DECIMAL", "TON", True), ("BODY_L", "Body Length", "DECIMAL", "FT", False),
                           ("BODY_W", "Body Width", "DECIMAL", "FT", False), ("BODY_H", "Body Height", "DECIMAL", "FT", False)],
             "CONTAINER": [("CONT_SIZE", "Container Size", "DROPDOWN", None, True), ("WHEELBASE", "Wheelbase", "DECIMAL", "MM", False),
                           ("REEFER", "Refrigerated", "BOOLEAN", None, False)]}
    for sc, rows in attrs.items():
        for i, (code, name, dt, unit, req) in enumerate(rows):
            upsert(db, FL.SubCategoryAttribute, {"sub_category_id": subs[sc].id, "code": code},
                   {"name": name, "data_type": dt, "unit_id": u.get(unit), "is_mandatory": req, "display_order": i,
                    "dropdown_options": "20 FT,32 FT SXL,32 FT MXL,40 FT" if dt == "DROPDOWN" else None})
    for c, n, t, cat in (("CC-ADMIN", "Administration", "NON_VEHICLE", "ADMIN"), ("CC-WORKSHOP", "Workshop", "NON_VEHICLE", "WORKSHOP"),
                         ("CC-WAREHOUSE", "Warehouse", "NON_VEHICLE", "WAREHOUSE"), ("CC-COMMON", "Common / Corporate Overheads", "COMMON", "COMMON")):
        upsert(db, FL.CostCenter, {"code": c}, {"name": n, "cc_type": t, "cost_category_id": cats[cat].id})
    for c, n, t in (("GODOWN", "Main Tyre Godown", "GODOWN"), ("WORKSHOP", "Workshop Tyre Bay", "WORKSHOP"),
                    ("RETREAD", "Retreader Premises", "RETREADER"), ("SCRAP", "Scrap Yard", "SCRAP_YARD"),
                    ("WARRANTY", "With Manufacturer (warranty)", "WARRANTY")):
        upsert(db, TY.TyreLocation, {"code": c}, {"name": n, "location_type": t})
    # expense / credit / transaction types
    ets = {}
    for c, n, g, op in (("FUEL", "Fuel", "FUEL", True), ("TOLL", "Toll / FASTag", "TOLL", True),
                        ("MAINTENANCE", "Maintenance & Repairs", "MAINTENANCE", True), ("TYRE", "Tyres", "TYRE", True),
                        ("INSURANCE", "Insurance", "INSURANCE", True), ("ROAD_TAX", "Road Tax / QTAX", "TAX", True),
                        ("PERMIT", "Permit Fees", "PERMIT", True), ("PESO", "PESO / Hazardous Compliance", "PESO", True),
                        ("DRIVER_SALARY", "Driver Salary", "DRIVER", True), ("DRIVER_BATTA", "Driver Batta / Allowance", "DRIVER", True),
                        ("VENDOR", "Vendor Services", "VENDOR", True), ("FITNESS", "Fitness / PUCC Fees", "PERMIT", True),
                        ("OFFICE", "Office & Admin", "COMMON", True), ("SALARY_STAFF", "Staff Salary", "COMMON", True),
                        ("BANK_CHARGES", "Bank Charges", "BANK_CHARGE", True), ("OTHER_DIRECT", "Other Direct Cost", "OTHER_DIRECT", True),
                        ("ASSET", "Asset Purchase (capex)", "ASSET", False), ("LOAN_EMI", "Loan / EMI", "LOAN", False),
                        ("TAX_GST", "GST / Statutory Payment", "OTHER", False)):
        ets[c] = upsert(db, FI.ExpenseType, {"code": c}, {"name": n, "report_group": g, "is_operating": op})
    for c, n, t, lt in (("CONTRACT_INCOME", "Contract Income Receipt", "SETTLEMENT", "CONTRACT_RECEIPT"),
                        ("INVOICE_RECEIPT", "Invoice Receipt", "SETTLEMENT", "INVOICE_RECEIPT"),
                        ("ADVANCE", "Customer Advance", "SETTLEMENT", "CONTRACT_RECEIPT"),
                        ("SUPPLIER_REFUND", "Supplier Refund", "EXPENSE_REDUCTION", "REFUND"),
                        ("INSURANCE_CLAIM", "Insurance Claim", "OTHER_INCOME", None),
                        ("TAX_REFUND", "Tax Refund", "NON_OPERATING", None), ("BANK_INTEREST", "Bank Interest", "OTHER_INCOME", None),
                        ("CASHBACK", "Bank Cashback", "OTHER_INCOME", "CASHBACK"),
                        ("FUEL_CASHBACK", "Fuel-card Cashback", "EXPENSE_REDUCTION", "CASHBACK"),
                        ("TOLL_CASHBACK", "Toll / FASTag Cashback", "EXPENSE_REDUCTION", "CASHBACK"),
                        ("LOYALTY", "Loyalty Benefit", "EXPENSE_REDUCTION", "REBATE"),
                        ("VENDOR_REBATE", "Vendor Rebate", "EXPENSE_REDUCTION", "REBATE"),
                        ("CREDIT_NOTE", "Credit Note / Refund", "EXPENSE_REDUCTION", "REFUND"),
                        ("REVERSAL", "Reversal", "EXCLUDE", "REVERSAL"), ("INTERNAL_TRANSFER", "Internal Transfer", "EXCLUDE", "INTERNAL_TRANSFER"),
                        ("LOAN_RECEIPT", "Loan Receipt", "BALANCE_SHEET", None), ("CAPITAL", "Capital Contribution", "BALANCE_SHEET", None),
                        ("OTHER_RECEIPT", "Other Receipt", "OTHER_INCOME", None), ("UNKNOWN", "Unknown / Unmatched", "EXCLUDE", None)):
        upsert(db, FI.CreditType, {"code": c}, {"name": n, "accounting_treatment": t, "default_link_type": lt,
                                                "requires_link": lt in ("REFUND", "REVERSAL")})
    for c, n, m, d in (("BANK_CR", "Bank Credit", "FINANCE", "CR"), ("BANK_DR", "Bank Debit", "FINANCE", "DR"),
                       ("FUEL", "Fuel Transaction", "FUEL", "NA"), ("TOLL", "Toll Transaction", "TOLL", "NA"),
                       ("MAINT", "Maintenance Job", "MAINTENANCE", "NA"), ("TYRE", "Tyre Transaction", "TYRE", "NA"),
                       ("INVOICE", "Customer Invoice", "CONTRACT", "NA"), ("EXPENSE", "Vendor Invoice / Expense", "FINANCE", "NA")):
        upsert(db, FI.TransactionType, {"code": c}, {"name": n, "module": m, "direction": d})
    for c, n, lt, kw, pr in (("MR-INV", "Customer invoice receipts", "INVOICE_RECEIPT", "NEFT,RTGS,IMPS", 10),
                             ("MR-XFER", "Own-account transfers", "INTERNAL_TRANSFER", "SELF,OWN ACCOUNT,TRF TO,TRANSFER", 20),
                             ("MR-FUEL", "Fuel card settlements", "FUEL_PAYMENT", "IOCL,BPCL,HPCL,FLEET,XTRAPOWER,SMARTFLEET", 30),
                             ("MR-TOLL", "FASTag recharges / toll", "TOLL_PAYMENT", "FASTAG,NETC,TOLL", 40),
                             ("MR-CASHBACK", "Cashback credits", "CASHBACK", "CASHBACK,REWARD,LOYALTY", 50),
                             ("MR-REFUND", "Refunds / reversals", "REFUND", "REFUND,REV,REVERSAL,RETURN", 60),
                             ("MR-INS", "Insurance premiums", "INSURANCE_PAYMENT", "INSURANCE,LOMBARD,ASSURANCE", 70)):
        upsert(db, FI.MatchingRule, {"code": c}, {"name": n, "link_type": lt, "narration_keywords": kw, "priority": pr,
                                                  "min_score": 60})
    for c, n, cat, km, days in (("PM-10K", "Preventive service (10,000 km)", "PREVENTIVE", 10000, 90),
                                ("PM-OIL", "Engine oil change", "SERVICE", 20000, 180), ("BRK", "Breakdown repair", "BREAKDOWN", None, None),
                                ("ACC", "Accident repair", "ACCIDENT", None, None), ("ELEC", "Electrical", "ELECTRICAL", None, None),
                                ("BODY", "Body work", "BODY_WORK", None, None), ("GEN", "General repair", "REPAIR", None, None)):
        upsert(db, OP.MaintenanceType, {"code": c}, {"name": n, "category": cat, "interval_km": km, "interval_days": days})
    rts = {}
    for c, n, cat, ap, multi, months, et in (
            ("QTAX", "Road Tax / QTAX", "TAX", "VEHICLE", False, 3, "ROAD_TAX"),
            ("NATIONAL_PERMIT", "National Permit", "PERMIT", "VEHICLE", False, 12, "PERMIT"),
            ("STATE_PERMIT", "State Permit", "PERMIT", "VEHICLE", True, 12, "PERMIT"),
            ("FITNESS", "Fitness Certificate", "FITNESS", "VEHICLE", False, 12, "FITNESS"),
            ("PUCC", "PUC Certificate", "PUCC", "VEHICLE", False, 6, "FITNESS"),
            ("PESO", "PESO Licence (Tank)", "PESO", "VEHICLE", True, 12, "PESO"),
            ("HAZMAT", "Hazardous Goods Compliance", "HAZMAT", "VEHICLE", True, 12, "PESO"),
            ("REG", "Registration Renewal", "REGISTRATION", "VEHICLE", False, 60, "ROAD_TAX"),
            ("DL", "Driving Licence", "LICENSE", "DRIVER", False, 60, None),
            ("DL_HAZ", "Hazardous Endorsement", "LICENSE", "DRIVER", False, 36, None),
            ("MEDICAL", "Driver Medical Certificate", "LICENSE", "DRIVER", False, 12, None)):
        rts[c] = upsert(db, C.RenewalType, {"code": c}, {"name": n, "category": cat, "applies_to": ap, "allows_multiple": multi,
                                                         "default_validity_months": months, "expense_type_id": ets[et].id if et else None,
                                                         "default_reminder_days": "60,30,15,7,1,0"})
    for c, n, rt, cat, sub, inst in (("R-QTAX", "Road tax — all trucks", "QTAX", "TRUCK", None, 1),
                                     ("R-NP", "National permit — trucks", "NATIONAL_PERMIT", "TRUCK", None, 1),
                                     ("R-FIT", "Fitness — all trucks", "FITNESS", "TRUCK", None, 1),
                                     ("R-FIT-TR", "Fitness — trailers", "FITNESS", "TRAILER", None, 1),
                                     ("R-PUCC", "PUCC — trucks", "PUCC", "TRUCK", None, 1),
                                     ("R-PESO-LPG", "PESO — LPG tankers (tank + vehicle)", "PESO", "TRUCK", "LPG", 2),
                                     ("R-HAZ-LPG", "Hazmat — LPG tankers", "HAZMAT", "TRUCK", "LPG", 1)):
        upsert(db, C.RenewalRule, {"code": c}, {"name": n, "renewal_type_id": rts[rt].id, "cost_category_id": cats[cat].id,
                                                "sub_category_id": subs[sub].id if sub else None, "instances_required": inst})
    for c, n, ev, sev in (("NR-RENEWAL", "Renewal due", "RENEWAL_DUE", "WARNING"), ("NR-EXPIRED", "Renewal expired", "RENEWAL_EXPIRED", "CRITICAL"),
                          ("NR-INS", "Insurance expiry", "INSURANCE_EXPIRY", "WARNING"), ("NR-PERMIT", "Permit expiry", "PERMIT_EXPIRY", "WARNING"),
                          ("NR-FIT", "Fitness expiry", "FITNESS_EXPIRY", "WARNING"), ("NR-PUCC", "PUCC expiry", "PUCC_EXPIRY", "WARNING"),
                          ("NR-PESO", "PESO expiry", "PESO_EXPIRY", "CRITICAL"), ("NR-DL", "Driver licence expiry", "DRIVER_LICENSE_EXPIRY", "WARNING"),
                          ("NR-BANK", "Unmatched bank transactions", "UNMATCHED_BANK", "WARNING"),
                          ("NR-IMPORT", "Import errors", "IMPORT_ERRORS", "WARNING"), ("NR-FUEL", "Unusual fuel consumption", "FUEL_UNUSUAL", "INFO"),
                          ("NR-TREAD", "Tyre tread threshold", "TYRE_TREAD_LOW", "WARNING"), ("NR-TWARR", "Tyre warranty", "TYRE_WARRANTY", "INFO"),
                          ("NR-MAINT", "Maintenance due", "MAINTENANCE_DUE", "WARNING"), ("NR-APPROVAL", "Approval pending", "APPROVAL_PENDING", "WARNING")):
        upsert(db, S.NotificationRule, {"code": c}, {"name": n, "event_type": ev, "channels": "IN_APP", "severity": sev})
    for c, n, act, amt, lv, active in (("AR-ALLOC", "Bank allocations above ₹5 lakh", "BANK_ALLOCATION", Decimal("500000"), 1, True),
                                       ("AR-MATCH", "Bank matches above ₹10 lakh", "BANK_MATCH", Decimal("1000000"), 1, True),
                                       ("AR-JOB", "Job cards above ₹2 lakh", "LARGE_TRANSACTION", Decimal("200000"), 1, True),
                                       ("AR-ODO", "Odometer override review", "ODOMETER_OVERRIDE", None, 1, True),
                                       ("AR-TYRE", "Tyre correction review", "TYRE_CORRECTION", None, 1, True)):
        upsert(db, FI.ApprovalRule, {"code": c}, {"name": n, "action_type": act, "min_amount": amt, "levels": lv, "is_active": active})


def seed_providers_and_templates(db: Session) -> None:
    """Different provider layouts prove the configurable mapping engine (see samples/)."""
    P = {}
    for c, n, t, kw in (("HDFC", "HDFC Bank", "BANK", None), ("SBI", "State Bank of India", "BANK", None),
                        ("TOLL_A", "FastWay FASTag Services", "TOLL", "FASTWAY"), ("TOLL_B", "HighRoad Toll Networks", "TOLL", "HIGHROAD"),
                        ("FUEL_IOCL", "IndianOil XTRAPOWER Fleet Card", "FUEL", "IOCL"), ("FUEL_BPCL", "BPCL SmartFleet", "FUEL", "BPCL"),
                        ("INS_ICICI", "ICICI Lombard General Insurance", "INSURANCE", None),
                        ("INS_NIA", "The New India Assurance", "INSURANCE", None), ("GPS_TRACK", "TrackOn GPS", "GPS", None),
                        ("RTO", "Transport Department / RTO", "OTHER", None), ("PESO", "PESO (Petroleum & Explosives Safety Org.)", "OTHER", None)):
        P[c] = upsert(db, O.Provider, {"code": c}, {"name": n, "provider_type": t})
    for c, n, pc in (("HDFC", "HDFC Bank Ltd", "HDFC"), ("SBI", "State Bank of India", "SBI")):
        upsert(db, O.Bank, {"code": c}, {"name": n, "short_name": c, "provider_id": P[pc].id})

    def tpl(provider, name, stype, cols, **kw):
        t = upsert(db, IM.StatementImportTemplate, {"provider_id": P[provider].id, "template_name": name, "version": 1},
                   {"statement_type": stype, **kw})
        if not db.execute(select(IM.StatementTemplateColumn).where(IM.StatementTemplateColumn.template_id == t.id)).first():
            for i, (col, hdr, tgt, dt, req, tr, lk, dflt) in enumerate(cols):
                db.add(IM.StatementTemplateColumn(template_id=t.id, source_column=col, source_header=hdr, target_field=tgt,
                                                  data_type=dt, is_required=req, transformation=tr, lookup_rule=lk,
                                                  default_value=dflt, display_order=i))
        return t

    # Bank layout 1 (HDFC style): separate Withdrawal/Deposit columns, header on row 4, data from row 5
    tpl("HDFC", "HDFC Current Account Statement", "BANK", [
        ("A", "Date", "txn_date", "DATE", True, "trim", None, None),
        ("B", "Narration", "narration", "TEXT", False, "trim|collapse_spaces", None, None),
        ("C", "Chq./Ref.No.", "reference_number", "TEXT", False, "trim", None, None),
        ("D", "Value Dt", "value_date", "DATE", False, "trim", None, None),
        ("E", "Withdrawal Amt.", "debit", "DECIMAL", False, "remove_currency|remove_commas", None, "0"),
        ("F", "Deposit Amt.", "credit", "DECIMAL", False, "remove_currency|remove_commas", None, "0"),
        ("G", "Closing Balance", "balance", "DECIMAL", False, "remove_currency|remove_commas", None, None)],
        sheet_name="Statement", header_row=4, data_start_row=5, date_format="%d/%m/%y", amount_mode="SEPARATE",
        skip_footer_keywords="STATEMENT SUMMARY,OPENING BALANCE,CLOSING BALANCE,TOTAL")
    # Bank layout 2 (SBI style): single Amount column + Dr/Cr indicator, header row 1
    tpl("SBI", "SBI Account Statement (Amount + Dr/Cr)", "BANK", [
        ("A", "Txn Date", "txn_date", "DATE", True, "trim", None, None),
        ("B", "Value Date", "value_date", "DATE", False, "trim", None, None),
        ("C", "Description", "narration", "TEXT", False, "trim", None, None),
        ("D", "Ref No./Cheque No.", "reference_number", "TEXT", False, "trim", None, None),
        ("E", "Amount", "amount", "DECIMAL", True, "remove_commas|abs", None, None),
        ("F", "Dr / Cr", "dr_cr", "TEXT", True, "trim|upper", None, None),
        ("G", "Balance", "balance", "DECIMAL", False, "remove_commas", None, None),
        ("H", "UTR", "utr", "TEXT", False, "trim|upper", None, None)],
        header_row=1, data_start_row=2, date_format="%d %b %Y", amount_mode="WITH_TYPE")
    # Toll layout A: date+time separate, plaza ID + name, vehicle column "Vehicle No."
    tpl("TOLL_A", "FastWay FASTag Statement", "TOLL", [
        ("A", "Transaction ID", "transaction_id", "TEXT", True, "trim", None, None),
        ("B", "Transaction Date", "txn_date", "DATE", True, None, None, None),
        ("C", "Transaction Time", "txn_time", "TIME", False, None, None, None),
        ("D", "Vehicle No.", "vehicle_number", "TEXT", False, "trim|upper", "vehicle", None),
        ("E", "Tag ID", "fastag_id", "TEXT", False, "trim", None, None),
        ("F", "Plaza ID", "plaza_id", "TEXT", False, "trim", None, None),
        ("G", "Plaza Name", "plaza_name", "TEXT", False, "trim", "toll_plaza", None),
        ("H", "Lane", "lane", "TEXT", False, "trim", None, None),
        ("I", "Amount (Rs)", "amount", "DECIMAL", True, "remove_currency|remove_commas", None, None),
        ("J", "Txn Type", "txn_kind", "TEXT", False, "trim|upper", None, "DEBIT")],
        header_row=1, data_start_row=2, date_format="%d-%m-%Y")
    # Toll layout B: combined date-time, different column order, plaza code, "Debit/Credit" wording
    tpl("TOLL_B", "HighRoad Toll Transactions", "TOLL", [
        ("A", "Sl", "remarks", "TEXT", False, "prefix(SL )", None, None),
        ("B", "Reader Date Time", "txn_datetime", "DATETIME", True, None, None, None),
        ("C", "Vehicle Reg Number", "vehicle_number", "TEXT", False, "trim|upper", "vehicle", None),
        ("D", "Toll Plaza Code", "plaza_code", "TEXT", False, "trim|upper", "toll_plaza", None),
        ("E", "Toll Plaza", "plaza_name", "TEXT", False, "trim", None, None),
        ("F", "Journey", "direction", "TEXT", False, "trim|upper", None, None),
        ("G", "Txn Ref", "transaction_id", "TEXT", True, "trim", None, None),
        ("H", "Debit/Credit", "txn_kind", "TEXT", False, "if(eq:CR,REFUND,DEBIT)", None, None),
        ("I", "Txn Amount", "amount", "DECIMAL", True, "remove_commas", None, None)],
        sheet_name="Transactions", header_row=3, data_start_row=4, datetime_format="%d/%m/%Y %H:%M:%S")
    # Fuel layout 1 (IOCL style)
    tpl("FUEL_IOCL", "IOCL XTRAPOWER Transactions", "FUEL", [
        ("A", "Txn ID", "provider_transaction_id", "TEXT", True, "trim", None, None),
        ("B", "Txn Date Time", "txn_datetime", "DATETIME", True, None, None, None),
        ("C", "Card No", "card_number", "TEXT", False, "trim", None, None),
        ("D", "Vehicle No", "vehicle_number", "TEXT", False, "trim|upper", "vehicle", None),
        ("E", "RO Code", "station_code", "TEXT", False, "trim", None, None),
        ("F", "RO Name", "station_name", "TEXT", False, "trim", "fuel_station", None),
        ("G", "Product", "fuel_type", "TEXT", True, "trim|upper|map(FUEL_TYPE)", "fuel_type", None),
        ("H", "Volume", "quantity", "DECIMAL", True, "remove_commas", None, None),
        ("I", "RSP", "rate", "DECIMAL", False, "remove_commas", None, None),
        ("J", "Amount", "amount", "DECIMAL", True, "remove_commas", None, None),
        ("K", "Odometer", "odometer", "DECIMAL", False, "remove_commas", None, None)],
        header_row=1, data_start_row=2, datetime_format="%d/%m/%Y %H:%M")
    # Fuel layout 2 (BPCL style): separate date/time, KG for CNG, total incl. tax, different headers/order
    tpl("FUEL_BPCL", "BPCL SmartFleet Statement", "FUEL", [
        ("A", "Date", "txn_date", "DATE", True, None, None, None),
        ("B", "Time", "txn_time", "TIME", False, None, None, None),
        ("C", "Registration", "vehicle_number", "TEXT", False, "trim|upper", "vehicle", None),
        ("D", "Outlet", "station_name", "TEXT", False, "trim", "fuel_station", None),
        ("E", "Fuel", "fuel_type", "TEXT", True, "trim|upper|map(FUEL_TYPE)", "fuel_type", None),
        ("F", "Qty", "quantity", "DECIMAL", True, None, None, None),
        ("G", "Price", "rate", "DECIMAL", False, None, None, None),
        ("H", "Net Value", "amount", "DECIMAL", False, "remove_commas", None, None),
        ("I", "Total (Rs)", "total_amount", "DECIMAL", False, "remove_commas", None, None),
        ("J", "Reference", "provider_transaction_id", "TEXT", True, "trim", None, None),
        ("K", "KM Reading", "odometer", "DECIMAL", False, None, None, None)],
        sheet_name="SmartFleet", header_row=2, data_start_row=3, date_format="%d-%b-%Y")
    for src, tgt, prov in (("HSD", "DIESEL", None), ("HIGH SPEED DIESEL", "DIESEL", None), ("XTRAMILE", "DIESEL", "FUEL_IOCL"),
                           ("MS", "PETROL", None), ("SPEED", "PETROL", "FUEL_BPCL"), ("CNG GAS", "CNG", None), ("AUTO LPG", "LPG", None)):
        upsert(db, IM.ValueMapping, {"mapping_type": "FUEL_TYPE", "provider_id": P[prov].id if prov else None, "source_value": src},
               {"target_value": tgt})


def seed_demo(db: Session) -> None:
    """Demo organisation + fleet used by sample Excel files and the manual walk-through."""
    from app.core.security import load_user
    from app.services import masters
    from app.services.masters import Ctx
    import app.services.registry  # noqa: F401
    admin = db.execute(select(S.User).where(S.User.username == "admin")).scalar_one()
    ctx = Ctx(db, load_user(db, admin.id))
    st = {s.code: s.id for s in db.execute(select(O.State)).scalars()}
    co = upsert(db, O.Company, {"code": "TLC"}, {"name": "Trans Logistics Co.", "legal_name": "Trans Logistics Company Pvt Ltd",
                                                 "state_id": st["TN"], "gstin": "33AABCT1234F1Z5"})
    br = upsert(db, O.Branch, {"code": "CHN"}, {"company_id": co.id, "name": "Chennai HQ", "state_id": st["TN"]})
    upsert(db, O.Branch, {"code": "BLR"}, {"company_id": co.id, "name": "Bengaluru", "state_id": st["KA"]})
    for c, n, t in (("GDN-CHN", "Chennai Godown", "GODOWN"), ("WS-CHN", "Chennai Workshop", "WORKSHOP"),
                    ("WH-CHN", "Chennai Warehouse", "WAREHOUSE")):
        upsert(db, O.Location, {"code": c}, {"name": n, "location_type": t, "branch_id": br.id})
    banks = {b.code: b for b in db.execute(select(O.Bank)).scalars()}
    upsert(db, O.BankAccount, {"code": "HDFC-CA"}, {"bank_id": banks["HDFC"].id, "account_name": "Trans Logistics — HDFC Current",
                                                    "account_number": "50200012345678", "account_type": "CURRENT",
                                                    "ifsc": "HDFC0000123", "branch_id": br.id, "company_id": co.id,
                                                    "opening_balance": Decimal("1000000")})
    upsert(db, O.BankAccount, {"code": "SBI-CA"}, {"bank_id": banks["SBI"].id, "account_name": "Trans Logistics — SBI Current",
                                                   "account_number": "39876543210", "account_type": "CURRENT",
                                                   "ifsc": "SBIN0001234", "branch_id": br.id, "company_id": co.id,
                                                   "opening_balance": Decimal("500000")})
    for c, n, t, kw in (("V-TYREWORLD", "Tyre World Distributors", "TYRE_DEALER", "TYRE WORLD"),
                        ("V-RETREAD", "Sri Balaji Retreads", "RETREADER", "BALAJI RETREAD"),
                        ("V-AUTOCARE", "AutoCare Workshop", "WORKSHOP", "AUTOCARE"),
                        ("V-SPARES", "Chennai Spares Co.", "SPARES", "CHENNAI SPARES")):
        upsert(db, O.Vendor, {"code": c}, {"name": n, "vendor_type": t, "match_keywords": kw, "state_id": st["TN"]})
    for c, n, kw in (("C-GASCO", "Southern Gas Distribution Ltd", "SOUTHERN GAS,SGDL"),
                     ("C-FMCG", "Bharat FMCG Logistics", "BHARAT FMCG")):
        upsert(db, O.Customer, {"code": c}, {"name": n, "match_keywords": kw, "credit_days": 30, "state_id": st["TN"]})
    prov = {p.code: p.id for p in db.execute(select(O.Provider)).scalars()}
    for code, ext, name, hw in (("PLZ-SRIP", "5401", "Sriperumbudur Toll Plaza", "NH48"), ("PLZ-VANA", "5402", "Vanagaram Toll Plaza", "NH48"),
                                ("PLZ-KRIS", "5403", "Krishnagiri Toll Plaza", "NH44"), ("PLZ-PARA", "5404", "Paranur Toll Plaza", "NH32")):
        upsert(db, OP.TollPlaza, {"plaza_code": code}, {"external_plaza_id": ext, "name": name, "highway": hw, "state_id": st["TN"]})
    for code, name, pv in (("RO-1001", "IOCL COCO Guindy", "FUEL_IOCL"), ("RO-1002", "IOCL Maduravoyal", "FUEL_IOCL"),
                           ("BP-2001", "BPCL Poonamallee", "FUEL_BPCL"), ("BP-2002", "BPCL CNG Ambattur", "FUEL_BPCL")):
        upsert(db, OP.FuelStation, {"station_code": code}, {"name": name, "provider_id": prov[pv], "city": "Chennai",
                                                            "state_id": st["TN"]})
    cats = {c.code: c.id for c in db.execute(select(FL.CostCategory)).scalars()}
    subs = {s.code: s.id for s in db.execute(select(FL.VehicleSubCategory)).scalars()}
    fuels = {f.code: f.id for f in db.execute(select(FL.FuelType)).scalars()}
    attr = {(a.sub_category_id, a.code): a.id for a in db.execute(select(FL.SubCategoryAttribute)).scalars()}
    spec = masters.get_spec("vehicles")
    demo = [("V001", "TN01AB1234", "TRUCK", "LPG", [("DIESEL", True)], {"TANK_CAP": "18", "AXLES": "3"}),
            ("V002", "TN02CD5678", "TRUCK", "OPEN_BODY", [("DIESEL", True)], {"LOAD_CAP": "16"}),
            ("V003", "TN09EF9012", "TRUCK", "CONTAINER", [("CNG", True)], {"CONT_SIZE": "32 FT SXL"}),
            ("V004", "TN18GH3456", "TRUCK", "OPEN_BODY", [("DIESEL", True), ("CNG", False)], {"LOAD_CAP": "10"}),
            ("V005", "TN20JK7890", "TRAILER", "TR_FLATBED", [("DIESEL", True)], {})]
    for code, reg, cat, sub, fl, at in demo:
        if db.execute(select(FL.Vehicle).where(FL.Vehicle.vehicle_code == code)).first():
            continue
        masters.save_record(ctx, spec, {
            "vehicle_code": code, "registration_number": reg, "cost_category_id": cats[cat], "sub_category_id": subs[sub],
            "branch_id": br.id, "vehicle_status": "ACTIVE", "manufacturer": "TATA MOTORS" if cat == "TRUCK" else "ESCORTS",
            "model": "SIGNA 4825" if cat == "TRUCK" else "FLATBED 40", "manufacturing_year": 2022,
            "purchase_date": "01/04/2022", "ownership_type": "OWNED", "current_odometer": "120000",
            "fuels": [{"fuel_type_id": fuels[f], "is_primary": p, "is_active": True} for f, p in fl],
            "attributes": {str(attr[(subs[sub], k)]): v for k, v in at.items()}})
    for code, name, lic, exp in (("D001", "RAMESH KUMAR", "TN0120150012345", today() + timedelta(days=20)),
                                 ("D002", "SURESH BABU", "TN0920180054321", today() + timedelta(days=400)),
                                 ("D003", "ABDUL RAHIM", "TN1820120099887", today() - timedelta(days=5))):
        upsert(db, C.Driver, {"driver_code": code}, {"name": name, "license_number": lic, "license_class": "HGMV",
                                                     "license_expiry_date": exp, "branch_id": br.id, "status": "ACTIVE",
                                                     "mobile": "9876543210"})
    v = {x.vehicle_code: x for x in db.execute(select(FL.Vehicle)).scalars()}
    # a few renewals / policies with varied expiries
    rt = {r.code: r for r in db.execute(select(C.RenewalType)).scalars()}
    rspec = masters.get_spec("vehicle_renewals")
    for vc, rcode, label, days, cert in (("V001", "PESO", "PESO #1", 12, "PESO/LPG/2025/0091"),
                                         ("V001", "PESO", "PESO #2", 200, "PESO/TANK/2025/0192"),
                                         ("V001", "FITNESS", "PRIMARY", -3, "FC-TN01-7781"),
                                         ("V002", "QTAX", "PRIMARY", 6, "QT-TN02-2291"),
                                         ("V003", "PUCC", "PRIMARY", 45, "PUC-99812")):
        a = db.execute(select(C.VehicleRenewalAssignment).where(
            C.VehicleRenewalAssignment.vehicle_id == v[vc].id, C.VehicleRenewalAssignment.renewal_type_id == rt[rcode].id,
            C.VehicleRenewalAssignment.reference_label == label)).scalar_one_or_none()
        if a and db.execute(select(C.VehicleRenewal.id).where(C.VehicleRenewal.assignment_id == a.id)).first():
            continue
        exp = today() + timedelta(days=days)
        masters.save_record(ctx, rspec, {"vehicle_id": v[vc].id, "renewal_type_id": rt[rcode].id,
                                         "assignment_id": a.id if a else None, "reference_label": label,
                                         "certificate_number": cert, "start_date": (exp - timedelta(days=365)).strftime("%d/%m/%Y"),
                                         "expiry_date": exp.strftime("%d/%m/%Y"), "amount": "4500", "tax_amount": "0",
                                         "payment_status": "PAID"})
    ispec = masters.get_spec("insurance_policies")
    for vc, ptype, pno, days in (("V001", "VEHICLE", "ICICI/MOT/0001", 25), ("V001", "CLL", "ICICI/CLL/0001", 180),
                                 ("V002", "VEHICLE", "NIA/MOT/7788", 300)):
        if db.execute(select(C.InsurancePolicy.id).where(C.InsurancePolicy.policy_number == pno)).first():
            continue
        exp = today() + timedelta(days=days)
        masters.save_record(ctx, ispec, {"vehicle_id": v[vc].id, "provider_id": prov["INS_ICICI" if pno.startswith("ICICI") else "INS_NIA"],
                                         "policy_type": ptype, "policy_number": pno, "insured_amount": "2500000",
                                         "start_date": (exp - timedelta(days=364)).strftime("%d/%m/%Y"),
                                         "expiry_date": exp.strftime("%d/%m/%Y"), "premium": "62000", "tax_amount": "11160",
                                         "payment_status": "PAID"})
    cust = {c.code: c for c in db.execute(select(O.Customer)).scalars()}
    if not db.execute(select(FI.Contract.id).where(FI.Contract.contract_number == "CT-GAS-2025")).first():
        masters.save_record(ctx, masters.get_spec("contracts"), {
            "customer_id": cust["C-GASCO"].id, "contract_number": "CT-GAS-2025", "start_date": "01/04/2025",
            "end_date": "31/03/2027", "contract_type": "DEDICATED", "billing_method": "FIXED_MONTHLY", "rate": "100000",
            "payment_terms_days": 30, "status": "ACTIVE",
            "vehicles": [{"vehicle_id": v["V001"].id, "allocation_percent": "40"}, {"vehicle_id": v["V002"].id, "allocation_percent": "30"},
                         {"vehicle_id": v["V003"].id, "allocation_percent": "30"}]})
    tl = {t.code: t.id for t in db.execute(select(TY.TyreLocation)).scalars()}
    vend = {x.code: x.id for x in db.execute(select(O.Vendor)).scalars()}
    tspec = masters.get_spec("tyres")
    for i in range(1, 13):
        sn = f"MRF{2025000 + i}"
        if db.execute(select(TY.Tyre.id).where(TY.Tyre.serial_number == sn)).first():
            continue
        masters.save_record(ctx, tspec, {"serial_number": sn, "brand": "MRF" if i % 3 else "APOLLO",
                                         "model": "STEEL MUSCLE" if i % 3 else "ENDURACE", "size": "295/80 R22.5",
                                         "tyre_type": "RADIAL", "original_tread_depth": "16", "purchase_date": "01/06/2025",
                                         "supplier_id": vend["V-TYREWORLD"], "invoice_number": "TW/25/0456", "cost": "28000",
                                         "gst_amount": "7840", "warranty_km": 100000, "warranty_months": 36,
                                         "initial_location_id": tl["GODOWN"]})
    for code, name, ts in (("TOLL_A", "TN01AB1234", "34161FA82032D6E800001234"),):
        upsert(db, OP.TollVehicleMapping, {"provider_id": prov[code], "external_vehicle_number": name},
               {"vehicle_id": v["V001"].id, "fastag_id": ts})


def run(demo: bool = False) -> None:
    from app.database import get_engine, session_scope
    from app.models import Base
    Base.metadata.create_all(get_engine())  # no-op when Alembic already created the schema
    with session_scope() as db:
        seed_security(db)
        seed_reference(db)
        seed_providers_and_templates(db)
        if demo:
            seed_demo(db)
    print("Seed complete" + (" (with demo data)" if demo else ""))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true", help="also load demo organisation / fleet data")
    run(ap.parse_args().demo)
