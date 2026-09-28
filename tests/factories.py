"""Test data builders using the same services as the UI/API (no shortcuts)."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

from sqlalchemy import select

from app.models import compliance as C
from app.models import finance as FI
from app.models import fleet as FL
from app.models import operations as OP
from app.models import org as O
from app.models import tyres as TY
from app.services import masters


def ids(db, model, field="code"):
    return {getattr(o, field): o.id for o in db.execute(select(model)).scalars()}


def dmy(d: date) -> str:
    return d.strftime("%d/%m/%Y")


def build_fleet(ctx):
    db = ctx.db
    st = ids(db, O.State)
    co = O.Company(code="T1", name="Test Co", state_id=st["TN"])
    db.add(co)
    db.flush()
    br = O.Branch(code="B1", name="Branch 1", company_id=co.id)
    br2 = O.Branch(code="B2", name="Branch 2", company_id=co.id)
    db.add_all([br, br2])
    db.flush()
    cats, subs, fuels = ids(db, FL.CostCategory), ids(db, FL.VehicleSubCategory), ids(db, FL.FuelType)
    attrs = {(a.sub_category_id, a.code): a.id for a in db.execute(select(FL.SubCategoryAttribute)).scalars()}
    spec = masters.get_spec("vehicles")
    purchase = date.today() - timedelta(days=800)

    def veh(code, reg, cat, sub, fl, at, branch=br.id, odo="100000"):
        return masters.save_record(ctx, spec, {
            "vehicle_code": code, "registration_number": reg, "cost_category_id": cats[cat], "sub_category_id": subs[sub],
            "branch_id": branch, "vehicle_status": "ACTIVE", "purchase_date": dmy(purchase), "current_odometer": odo,
            "fuels": [{"fuel_type_id": fuels[f], "is_primary": i == 0, "is_active": True} for i, f in enumerate(fl)],
            "attributes": {str(attrs[(subs[sub], k)]): v for k, v in at.items()}})

    v = SimpleNamespace()
    v.lpg = veh("T-LPG", "TN01AA0001", "TRUCK", "LPG", ["DIESEL"], {"TANK_CAP": "18", "AXLES": "3"})
    v.open = veh("T-OPEN", "TN01AA0002", "TRUCK", "OPEN_BODY", ["DIESEL"], {"LOAD_CAP": "16"})
    v.cng = veh("T-CNG", "TN01AA0003", "TRUCK", "CONTAINER", ["CNG"], {"CONT_SIZE": "20 FT"})
    v.dual = veh("T-DUAL", "TN01AA0004", "TRUCK", "OPEN_BODY", ["DIESEL", "CNG"], {"LOAD_CAP": "10"})
    v.petrol = veh("T-PET", "TN01AA0005", "TRUCK", "OPEN_BODY", ["PETROL", "CNG"], {"LOAD_CAP": "2"}, branch=br2.id)
    prov = ids(db, O.Provider)
    banks = ids(db, O.Bank)
    a1 = O.BankAccount(bank_id=banks["HDFC"], code="ACC1", account_name="Main", account_number="111", account_type="CURRENT",
                       opening_balance=0)
    a2 = O.BankAccount(bank_id=banks["SBI"], code="ACC2", account_name="Second", account_number="222", account_type="CURRENT",
                       opening_balance=0)
    db.add_all([a1, a2])
    cust = O.Customer(code="CUST1", name="Southern Gas Distribution Ltd", match_keywords="SOUTHERN GAS", credit_days=30)
    vend = O.Vendor(code="VEND1", name="AutoCare Workshop", vendor_type="WORKSHOP", match_keywords="AUTOCARE")
    retr = O.Vendor(code="VEND2", name="Balaji Retreads", vendor_type="RETREADER")
    db.add_all([cust, vend, retr])
    for code, ext, name in (("PLZ-A", "5401", "Sriperumbudur Toll Plaza"), ("PLZ-B", "5402", "Vanagaram Toll Plaza"),
                            ("PLZ-C", "5403", "Krishnagiri Toll Plaza"), ("PLZ-PARA", "5404", "Paranur Toll Plaza"),
                            ("PLZ-VANA", "5405", "Vanagaram Toll Plaza 2")):
        db.add(OP.TollPlaza(plaza_code=code, external_plaza_id=ext, name=name))
    db.flush()
    return SimpleNamespace(v=v, branch=br, branch2=br2, acc1=a1, acc2=a2, cust=cust, vendor=vend, retreader=retr, prov=prov,
                           cats=cats, subs=subs, fuels=fuels, cc=ids(db, FL.CostCenter),
                           et=ids(db, FI.ExpenseType), ct=ids(db, FI.CreditType), tl=ids(db, TY.TyreLocation),
                           pos=ids(db, TY.TyrePosition), rt=ids(db, C.RenewalType), mt=ids(db, OP.MaintenanceType))


def make_invoice(ctx, f, number, taxable, allocations, contract_id=None, inv_date=None, itype="INVOICE", original=None,
                 tax="0"):
    return masters.save_record(ctx, masters.get_spec("invoices"), {
        "invoice_number": number, "invoice_type": itype, "customer_id": f.cust.id, "contract_id": contract_id,
        "original_invoice_id": original, "invoice_date": dmy(inv_date or date.today() - timedelta(days=10)),
        "taxable_amount": str(taxable), "tax_amount": tax,
        "allocations": [{"vehicle_id": vid, "amount": str(a)} for vid, a in allocations]})


def bank_txn(ctx, account_id, amount, direction="CR", narration="TEST", d=None, utr=None):
    return masters.save_record(ctx, masters.get_spec("bank_transactions"), {
        "bank_account_id": account_id, "txn_date": dmy(d or date.today() - timedelta(days=5)), "narration": narration,
        "credit": str(amount) if direction == "CR" else "0", "debit": str(amount) if direction == "DR" else "0",
        "utr": utr})


def fuel_txn(ctx, f, vehicle, fuel_code, qty, rate, amount=None, odo=None, when=None, **extra):
    data = {"provider_id": f.prov["FUEL_IOCL"], "txn_datetime": (when or datetime.now() - timedelta(days=3)).strftime("%d/%m/%Y %H:%M"),
            "vehicle_id": vehicle["id"], "fuel_type_id": f.fuels[fuel_code], "quantity": str(qty), "rate": str(rate),
            "amount": str(amount if amount is not None else (Decimal(str(qty)) * Decimal(str(rate))).quantize(Decimal("0.01"))),
            "odometer": str(odo) if odo is not None else None, **extra}
    return masters.save_record(ctx, masters.get_spec("fuel_transactions"), data)


def new_tyre(ctx, f, serial, cost="30000"):
    return masters.save_record(ctx, masters.get_spec("tyres"), {
        "serial_number": serial, "brand": "MRF", "size": "295/80 R22.5", "original_tread_depth": "16", "cost": cost,
        "gst_amount": "0", "purchase_date": dmy(date.today() - timedelta(days=100)), "initial_location_id": f.tl["GODOWN"]})
