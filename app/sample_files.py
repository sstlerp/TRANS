"""Sample statement files for the seeded provider templates.

    python -m app.sample_files            # writes samples/*.xlsx

Two different layouts per statement family (bank, toll, fuel) prove that
provider differences live only in template configuration.  Files include
deliberate problems (duplicate rows, unknown vehicle, unknown plaza, bad date,
fuel type not configured for the vehicle) so the validation/review flow can be
seen end-to-end.  Vehicle numbers match `python -m app.seed --demo`.
"""
from __future__ import annotations

import io
from datetime import date, datetime, timedelta
from pathlib import Path

from openpyxl import Workbook

BASE = date.today().replace(day=1) - timedelta(days=1)  # last day of previous month
D = lambda n: BASE.replace(day=1) + timedelta(days=n)  # noqa: E731  day n of the previous month


def _book(sheet: str) -> tuple[Workbook, object]:
    wb = Workbook()
    ws = wb.active
    ws.title = sheet
    return wb, ws


def _bytes(wb: Workbook) -> bytes:
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def bank_hdfc() -> bytes:
    """HDFC style: title rows, header on row 4, separate Withdrawal/Deposit, dd/mm/yy, footer summary."""
    wb, ws = _book("Statement")
    ws.append(["HDFC BANK LTD"])
    ws.append(["Account: 50200012345678  TRANS LOGISTICS CO."])
    ws.append([f"Statement From : {D(0):%d/%m/%Y}  To : {D(27):%d/%m/%Y}"])
    ws.append(["Date", "Narration", "Chq./Ref.No.", "Value Dt", "Withdrawal Amt.", "Deposit Amt.", "Closing Balance"])
    bal = 1000000.00
    rows = [
        (D(1), "NEFT CR-SOUTHERN GAS DISTRIBUTION LTD-INV GAS-001", "N123456789", 0, 100000.00),
        (D(2), "IOCL XTRAPOWER FLEET CARD SETTLEMENT", "IOCL0001", 5170.00, 0),
        (D(3), "FASTAG RECHARGE NETC FASTWAY", "FT0003", 1500.00, 0),
        (D(4), "TRF TO OWN ACCOUNT SBI 39876543210 SELF", "UTR000000123456", 500000.00, 0),
        (D(5), "NEFT CR-SOUTHERN GAS DISTRIBUTION LTD PART PAYMENT", "N555", 0, 40000.00),
        (D(6), "AUTOCARE WORKSHOP PAYMENT", "CHQ 000123", 100000.00, 0),
        (D(8), "CASHBACK FLEET CARD IOCL REWARD", "CB0008", 0, 2500.00),
        (D(9), "BANK CHARGES SMS ALERT", "", 59.00, 0),
        (D(10), "REFUND AUTOCARE WORKSHOP EXCESS", "RF0010", 0, 5000.00),
        (D(11), "INTEREST CREDIT", "", 0, 812.00),
        (D(12), "SALARY DRIVERS BATCH", "SAL12", 60000.00, 0),
    ]
    for d, narr, ref, dr, cr in rows:
        bal = round(bal - dr + cr, 2)
        ws.append([d.strftime("%d/%m/%y"), narr, ref, d.strftime("%d/%m/%y"), f"{dr:,.2f}" if dr else "",
                   f"{cr:,.2f}" if cr else "", f"{bal:,.2f}"])
    ws.append([])
    ws.append(["STATEMENT SUMMARY :-"])
    ws.append(["Opening Balance", "", "", "", "", "", "1,000,000.00"])
    return _bytes(wb)


def bank_sbi() -> bytes:
    """SBI style: header row 1, 'dd Mon yyyy', single Amount + Dr/Cr, separate UTR column."""
    wb, ws = _book("Sheet1")
    ws.append(["Txn Date", "Value Date", "Description", "Ref No./Cheque No.", "Amount", "Dr / Cr", "Balance", "UTR"])
    bal = 500000.00
    for d, narr, ref, amt, drcr, utr in (
            (D(4), "BY TRANSFER FROM HDFC 50200012345678 SELF", "TRF", 500000.00, "Cr", "UTR000000123456"),
            (D(7), "RTGS BHARAT FMCG LOGISTICS INV FMCG-9", "RT7", 59000.00, "Cr", "SBIN0000RT7777"),
            (D(9), "BPCL SMARTFLEET SETTLEMENT", "BP9", 2090.00, "Dr", ""),
            (D(13), "NEFT UNKNOWN PARTY", "NX13", 7777.00, "Cr", "")):
        bal = round(bal + (amt if drcr == "Cr" else -amt), 2)
        ws.append([d.strftime("%d %b %Y"), d.strftime("%d %b %Y"), narr, ref, f"{amt:,.2f}", drcr, f"{bal:,.2f}", utr])
    return _bytes(wb)


def toll_fastway() -> bytes:
    """Toll layout A: separate date/time, Plaza ID + name, Rs amounts, explicit Txn Type."""
    wb, ws = _book("Sheet1")
    ws.append(["Transaction ID", "Transaction Date", "Transaction Time", "Vehicle No.", "Tag ID", "Plaza ID",
               "Plaza Name", "Lane", "Amount (Rs)", "Txn Type"])
    rows = [
        ("FW1001", D(1), "08:15:00", "TN-01-AB-1234", "34161FA82032D6E800001234", "5401", "Sriperumbudur Toll Plaza", "L3", "Rs 335.00", "DEBIT"),
        ("FW1002", D(1), "10:40:00", "TN01AB1234", "34161FA82032D6E800001234", "5403", "Krishnagiri Toll Plaza", "L1", "Rs 410.00", "DEBIT"),
        ("FW1003", D(2), "06:05:00", "TN 02 CD 5678", "", "5402", "Vanagaram Toll Plaza", "L2", "Rs 95.00", "DEBIT"),
        ("FW1004", D(3), "21:30:00", "KA05ZZ9999", "", "5401", "Sriperumbudur Toll Plaza", "L4", "Rs 335.00", "DEBIT"),
        ("FW1005", D(3), "22:10:00", "TN09EF9012", "", "9999", "New Unknown Plaza", "L1", "Rs 120.00", "DEBIT"),
        ("FW1002", D(1), "10:40:00", "TN01AB1234", "", "5403", "Krishnagiri Toll Plaza", "L1", "Rs 410.00", "DEBIT"),  # duplicate id
        ("FW1006", D(4), "11:11:00", "TN01AB1234", "", "5403", "Krishnagiri Toll Plaza", "L1", "Rs 410.00", "REFUND"),
        ("FW1007", "31/02/2025", "11:11:00", "TN01AB1234", "", "5403", "Krishnagiri Toll Plaza", "L1", "Rs 50.00", "DEBIT"),  # bad date
    ]
    for tid, d, t, veh, tag, pid, pname, lane, amt, kind in rows:
        ws.append([tid, d.strftime("%d-%m-%Y") if isinstance(d, date) else d, t, veh, tag, pid, pname, lane, amt, kind])
    return _bytes(wb)


def toll_highroad() -> bytes:
    """Toll layout B: title rows, header on row 3, combined date-time, plaza code, CR/DR wording, different order.
    Uses the SAME transaction id 'FW1001' as provider A to prove ids are provider-scoped."""
    wb, ws = _book("Transactions")
    ws.append(["HighRoad Toll Networks — Fleet Statement"])
    ws.append([f"Period {D(0):%d/%m/%Y} to {D(27):%d/%m/%Y}"])
    ws.append(["Sl", "Reader Date Time", "Vehicle Reg Number", "Toll Plaza Code", "Toll Plaza", "Journey", "Txn Ref",
               "Debit/Credit", "Txn Amount"])
    for i, (dt, veh, code, name, j, ref, dc, amt) in enumerate((
            (datetime.combine(D(5), datetime.min.time()).replace(hour=7, minute=30), "TN18GH3456", "PLZ-PARA", "Paranur Toll Plaza", "UP", "FW1001", "DR", "150.00"),
            (datetime.combine(D(5), datetime.min.time()).replace(hour=19, minute=2), "TN18GH3456", "PLZ-PARA", "Paranur Toll Plaza", "DOWN", "HR-2002", "DR", "150.00"),
            (datetime.combine(D(6), datetime.min.time()).replace(hour=9, minute=45), "TN20JK7890", "PLZ-VANA", "Vanagaram Toll Plaza", "UP", "HR-2003", "DR", "1,210.00"),
            (datetime.combine(D(6), datetime.min.time()).replace(hour=12, minute=0), "TN20JK7890", "PLZ-VANA", "Vanagaram Toll Plaza", "UP", "HR-2004", "CR", "60.00")), 1):
        ws.append([i, dt.strftime("%d/%m/%Y %H:%M:%S"), veh, code, name, j, ref, dc, amt])
    return _bytes(wb)


def fuel_iocl() -> bytes:
    """Fuel layout A (IOCL): combined date-time, product names mapped via value mappings (HSD → DIESEL)."""
    wb, ws = _book("Sheet1")
    ws.append(["Txn ID", "Txn Date Time", "Card No", "Vehicle No", "RO Code", "RO Name", "Product", "Volume", "RSP",
               "Amount", "Odometer"])
    for r in (("IO-5001", f"{D(1):%d/%m/%Y} 07:10", "7001", "TN01AB1234", "RO-1001", "IOCL COCO Guindy", "HSD", "200.00", "89.50", "17,900.00", "120350"),
              ("IO-5002", f"{D(6):%d/%m/%Y} 18:40", "7001", "TN01AB1234", "RO-1002", "IOCL Maduravoyal", "HSD", "180.00", "89.50", "16,110.00", "121050"),
              ("IO-5003", f"{D(2):%d/%m/%Y} 09:00", "7002", "TN02CD5678", "RO-1001", "IOCL COCO Guindy", "XTRAMILE", "150.00", "90.10", "13,515.00", "120200"),
              ("IO-5004", f"{D(3):%d/%m/%Y} 12:00", "7003", "TN09EF9012", "RO-1002", "IOCL Maduravoyal", "HSD", "50.00", "89.50", "4,475.00", ""),  # diesel for a CNG-only vehicle
              ("IO-5005", f"{D(3):%d/%m/%Y} 13:30", "7009", "MH12XX0001", "RO-1002", "IOCL Maduravoyal", "HSD", "40.00", "89.50", "3,580.00", ""),  # unknown vehicle
              ("IO-5006", f"{D(4):%d/%m/%Y} 08:00", "7002", "TN02CD5678", "RO-1001", "IOCL COCO Guindy", "HSD", "100.00", "89.50", "9,500.00", "120900"),  # amount ≠ qty×rate
              ("IO-5001", f"{D(1):%d/%m/%Y} 07:10", "7001", "TN01AB1234", "RO-1001", "IOCL COCO Guindy", "HSD", "200.00", "89.50", "17,900.00", "120350")):  # duplicate
        ws.append(list(r))
    return _bytes(wb)


def fuel_bpcl() -> bytes:
    """Fuel layout B (BPCL): title row, header row 2, separate date/time (dd-Mon-yyyy), CNG in KG, total incl. tax."""
    wb, ws = _book("SmartFleet")
    ws.append(["BPCL SmartFleet — Customer Statement"])
    ws.append(["Date", "Time", "Registration", "Outlet", "Fuel", "Qty", "Price", "Net Value", "Total (Rs)", "Reference", "KM Reading"])
    for r in ((D(2).strftime("%d-%b-%Y"), "08:20", "TN09EF9012", "BPCL CNG Ambattur", "CNG", 20.5, 82.0, "1,681.00", "1,681.00", "BP-9001", 120400),
              (D(5).strftime("%d-%b-%Y"), "17:05", "TN18GH3456", "BPCL CNG Ambattur", "CNG GAS", 18.0, 82.0, "1,476.00", "1,476.00", "BP-9002", 120300),
              (D(6).strftime("%d-%b-%Y"), "10:10", "TN18GH3456", "BPCL Poonamallee", "HSD", 60.0, 89.4, "5,364.00", "5,364.00", "BP-9003", 120520),
              (D(7).strftime("%d-%b-%Y"), "11:00", "TN20JK7890", "BPCL Poonamallee", "SPEED", 10.0, 102.0, "1,020.00", "1,020.00", "BP-9004", 120050)):
        ws.append(list(r))
    return _bytes(wb)


FILES = {"bank_hdfc_statement.xlsx": bank_hdfc, "bank_sbi_statement.xlsx": bank_sbi, "toll_fastway.xlsx": toll_fastway,
         "toll_highroad.xlsx": toll_highroad, "fuel_iocl_xtrapower.xlsx": fuel_iocl, "fuel_bpcl_smartfleet.xlsx": fuel_bpcl}


def write_all(target: Path) -> list[Path]:
    target.mkdir(parents=True, exist_ok=True)
    out = []
    for name, fn in FILES.items():
        p = target / name
        p.write_bytes(fn())
        out.append(p)
    return out


if __name__ == "__main__":
    for p in write_all(Path(__file__).resolve().parent.parent / "samples"):
        print("wrote", p)
