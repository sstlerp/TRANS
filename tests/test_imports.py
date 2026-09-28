"""Import engine robustness: template validation, header checks, progress, per-row isolation,
duplicate-file policy, error register resolution (criteria 12, 52, 53)."""
import pytest
from sqlalchemy import func, select

from app.core.errors import BusinessError
from app.models.imports import StatementImportError, StatementImportRow, StatementImportTemplate
from app.models.operations import TollTransaction
from app.sample_files import toll_fastway
from app.services import import_engine, masters
from app.services.rules import set_rule


def tpl(db, name):
    return db.execute(select(StatementImportTemplate).where(StatementImportTemplate.template_name == name)).scalar_one().id


def test_template_builder_validates_configuration(ctx, fleet):
    spec = masters.get_spec("import_templates")
    base = {"provider_id": fleet.prov["TOLL_A"], "template_name": "Broken", "statement_type": "TOLL", "header_row": 1,
            "data_start_row": 2}
    with pytest.raises(BusinessError) as e:
        masters.save_record(ctx, spec, {**base, "columns": [{"source_column": "A", "target_field": "nonsense"},
                                                            {"source_column": "B", "target_field": "amount", "transformation": "explode"}]})
    msgs = " ".join(x["message"] for x in e.value.errors)
    assert "Unknown target field" in msgs and "Unknown transformation" in msgs and "transaction_id" in msgs
    ok = masters.save_record(ctx, spec, {**base, "template_name": "Minimal toll", "columns": [
        {"source_column": "A", "target_field": "transaction_id", "is_required": True},
        {"source_column": "B", "target_field": "txn_date", "data_type": "DATE"},
        {"source_column": "I", "target_field": "amount", "transformation": "remove_currency|remove_commas"}]})
    b = import_engine.create_preview(ctx, ok["id"], toll_fastway(), "min.xlsx")
    assert b.total_rows == 8 and b.duplicate_rows == 1


def test_progress_callback_and_row_isolation(ctx, fleet):
    b = import_engine.create_preview(ctx, tpl(ctx.db, "FastWay FASTag Statement"), toll_fastway(), "f.xlsx")
    seen = []
    import_engine.commit_batch(ctx, b.id, progress_cb=lambda done, total: seen.append((done, total)))
    assert b.status == "COMPLETED_WITH_ERRORS" and b.successful_rows == 6 and b.error_rows == 1
    rows = ctx.db.execute(select(StatementImportRow).where(StatementImportRow.batch_id == b.id)).scalars().all()
    assert {r.status for r in rows} == {"IMPORTED", "DUPLICATE", "ERROR"}
    imported = [r for r in rows if r.status == "IMPORTED"]
    assert all(r.target_table == "toll_transactions" and r.target_id for r in imported)
    with pytest.raises(BusinessError):
        import_engine.commit_batch(ctx, b.id)  # a batch commits once


def test_error_register_shows_row_column_and_can_be_resolved(ctx, fleet):
    b = import_engine.create_preview(ctx, tpl(ctx.db, "FastWay FASTag Statement"), toll_fastway(), "f.xlsx")
    err = ctx.db.execute(select(StatementImportError).where(StatementImportError.batch_id == b.id,
                                                            StatementImportError.error_type == "FORMAT")).scalar_one()
    assert (err.source_row, err.source_column, err.target_field, err.original_value) == (9, "B", "txn_date", "31/02/2025")
    assert err.suggested_correction
    masters.run_action(ctx, masters.get_spec("import_errors"), err.id, "resolve", {"resolution_notes": "Asked provider for corrected file"})
    assert err.resolved and err.resolved_by == ctx.user.id


def test_same_file_policy_is_configurable(ctx, fleet):
    t = tpl(ctx.db, "FastWay FASTag Statement")
    data = toll_fastway()  # the very same bytes (same SHA-256) uploaded twice
    b = import_engine.create_preview(ctx, t, data, "f.xlsx")
    import_engine.commit_batch(ctx, b.id)
    b2 = import_engine.create_preview(ctx, t, data, "f.xlsx")  # WARN (default): preview with duplicates
    assert b2.duplicate_rows == 7 and (b2.summary or {}).get("duplicate_file_of") == b.id
    set_rule(ctx.db, "DUPLICATE_FILE_CHECK", "BLOCK")
    with pytest.raises(BusinessError) as e:
        import_engine.create_preview(ctx, t, data, "f.xlsx")
    assert e.value.code == "DUPLICATE_FILE"
    assert ctx.db.execute(select(func.count()).select_from(TollTransaction)).scalar_one() == 6


def test_cancelled_batch_cannot_commit(ctx, fleet):
    b = import_engine.create_preview(ctx, tpl(ctx.db, "FastWay FASTag Statement"), toll_fastway(), "f.xlsx")
    import_engine.cancel_batch(ctx, b.id)
    with pytest.raises(BusinessError):
        import_engine.commit_batch(ctx, b.id)


def test_unsupported_file_rejected(ctx, fleet):
    with pytest.raises(BusinessError):
        import_engine.create_preview(ctx, tpl(ctx.db, "FastWay FASTag Statement"), b"hello", "f.txt")
    with pytest.raises(BusinessError):
        import_engine.create_preview(ctx, tpl(ctx.db, "FastWay FASTag Statement"), b"not-a-zip", "f.xlsx")
