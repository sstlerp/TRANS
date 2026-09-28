"""Unit tests: transformation DSL, parsing helpers, normalisation."""
from datetime import date, datetime
from decimal import Decimal

import pytest

from app.core.utils import normalize_vehicle_number, parse_date, to_decimal
from app.services.transforms import TContext, apply_pipeline, check_validation, validate_pipeline


def run(expr, value, row=None, mapper=None):
    return apply_pipeline(expr, value, TContext(row or {}, mapper))


def test_basic_steps():
    assert run("trim|upper", "  tn01 ab ") == "TN01 AB"
    assert run("lower", "ABC") == "abc"
    assert run("remove_commas|decimal", "1,23,456.50") == Decimal("123456.50")
    assert run("remove_currency|remove_commas|decimal", "Rs. 1,500.00") == Decimal("1500.00")
    assert run("remove_currency|decimal", "₹ 99") == Decimal("99")
    assert run("replace(Rs ,)|trim", "Rs 335.00") == "335.00"
    assert run("default(0)", "") == "0"
    assert run("normalize_vehicle", "TN-01 ab 1234") == "TN01AB1234"


def test_split_concat_regex_left_right():
    assert run("split(/,1)", "A/B/C") == "B"
    assert run("concat( ,B,C)", "X", {"B": "Y", "C": "Z"}) == "X Y Z"
    assert run("regex(\\d+,0)", "INV-00123-X") == "00123"
    assert run("left(4)", "ABCDEFG") == "ABCD"
    assert run("right(3)", "ABCDEFG") == "EFG"
    assert run("prefix(SL )", "5") == "SL 5"


def test_conditional_transformations():
    assert run("if(eq:CR,REFUND,DEBIT)", "CR") == "REFUND"
    assert run("if(eq:CR,REFUND,DEBIT)", "DR") == "DEBIT"
    assert run("if(col:F=CR,$value,0)", "500", {"F": "Cr"}) == "500"
    assert run("if(col:F=CR,$value,0)", "500", {"F": "Dr"}) == "0"
    assert run("if(gt:100,BIG,SMALL)", "150") == "BIG"
    assert run("abs", "-12.5") == Decimal("12.5")
    assert run("negate", "12.5") == Decimal("-12.5")


def test_dates_and_mapping():
    assert run("date(%d-%b-%Y)", "05-Aug-2025") == date(2025, 8, 5)
    assert run("datetime(%d/%m/%Y %H:%M)", "05/08/2025 07:10") == datetime(2025, 8, 5, 7, 10)
    mapper = lambda t, v: {"HSD": "DIESEL"}.get(v.upper())  # noqa: E731
    assert run("upper|map(FUEL_TYPE)", "hsd", mapper=mapper) == "DIESEL"
    assert run("map(FUEL_TYPE)", "CNG", mapper=mapper) == "CNG"  # unmapped values pass through


def test_invalid_pipeline_rejected():
    with pytest.raises(ValueError):
        validate_pipeline("trim|explode")
    validate_pipeline("trim|upper|map(FUEL_TYPE)|if(eq:CR,REFUND,DEBIT)")


def test_validation_rules():
    assert check_validation("min:0", "-1")
    assert check_validation("min:0", "5") is None
    assert check_validation("regex:[A-Z]{2}\\d+", "TN01") is None
    assert check_validation("len:10", "123")
    assert check_validation("in:DEBIT;REFUND", "credit")


def test_date_parsing_is_day_first():
    assert parse_date("03/04/2025") == date(2025, 4, 3)
    assert parse_date("2025-04-03") == date(2025, 4, 3)
    assert parse_date("03-Apr-2025") == date(2025, 4, 3)
    assert parse_date(45000) == date(2023, 3, 15)  # Excel serial
    with pytest.raises(ValueError):
        parse_date("31/02/2025")


def test_decimal_parsing():
    assert to_decimal("(1,000.50)") == Decimal("-1000.50")
    assert to_decimal("250.00 Dr") == Decimal("-250.00")
    assert to_decimal("250.00 Cr") == Decimal("250.00")
    with pytest.raises(ValueError):
        to_decimal("abc")


def test_vehicle_normalisation_preserves_meaning():
    for raw in ("TN 01 AB 1234", "tn-01-ab-1234", "TN01AB1234", " TN.01.AB.1234 "):
        assert normalize_vehicle_number(raw) == "TN01AB1234"
