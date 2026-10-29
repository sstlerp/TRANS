"""trips & freight, e-way bills, driver advances & settlements, GST e-invoice fields

New tables trips (lorry receipt, freight, POD), trip_expenses, eway_bills, driver_advances, driver_settlements;
invoices gain einvoice_status, irn (unique), irn_ack_number, irn_ack_date, signed_qr, irn_cancelled_at,
irn_cancel_reason.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-29 05:11:31.807042
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0004'
down_revision: Union[str, None] = '0003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('trips',
    sa.Column('trip_number', sa.String(length=30), nullable=False),
    sa.Column('trip_date', sa.Date(), nullable=False),
    sa.Column('lr_number', sa.String(length=40), nullable=True),
    sa.Column('lr_date', sa.Date(), nullable=True),
    sa.Column('customer_id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=True),
    sa.Column('contract_id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=True),
    sa.Column('vehicle_id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=False),
    sa.Column('driver_id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=True),
    sa.Column('cost_center_id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=True),
    sa.Column('origin', sa.String(length=150), nullable=False),
    sa.Column('destination', sa.String(length=150), nullable=False),
    sa.Column('from_pincode', sa.String(length=6), nullable=True),
    sa.Column('to_pincode', sa.String(length=6), nullable=True),
    sa.Column('from_state_id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=True),
    sa.Column('to_state_id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=True),
    sa.Column('route_via', sa.String(length=255), nullable=True),
    sa.Column('planned_km', sa.Numeric(precision=18, scale=3), nullable=True),
    sa.Column('consignor_name', sa.String(length=200), nullable=True),
    sa.Column('consignor_gstin', sa.String(length=15), nullable=True),
    sa.Column('consignor_address', sa.String(length=500), nullable=True),
    sa.Column('consignee_name', sa.String(length=200), nullable=True),
    sa.Column('consignee_gstin', sa.String(length=15), nullable=True),
    sa.Column('consignee_address', sa.String(length=500), nullable=True),
    sa.Column('goods_description', sa.String(length=255), nullable=True),
    sa.Column('hsn_code', sa.String(length=10), nullable=True),
    sa.Column('packing_type', sa.String(length=30), nullable=True),
    sa.Column('packages', sa.Integer(), nullable=True),
    sa.Column('weight_tonnes', sa.Numeric(precision=18, scale=3), nullable=True),
    sa.Column('goods_value', sa.Numeric(precision=18, scale=2), nullable=True),
    sa.Column('goods_invoice_number', sa.String(length=60), nullable=True),
    sa.Column('goods_invoice_date', sa.Date(), nullable=True),
    sa.Column('freight_payment', sa.String(length=10), nullable=False),
    sa.Column('freight_basis', sa.String(length=15), nullable=False),
    sa.Column('freight_rate', sa.Numeric(precision=18, scale=4), nullable=True),
    sa.Column('freight_amount', sa.Numeric(precision=18, scale=2), nullable=False),
    sa.Column('loading_charges', sa.Numeric(precision=18, scale=2), nullable=False),
    sa.Column('unloading_charges', sa.Numeric(precision=18, scale=2), nullable=False),
    sa.Column('detention_charges', sa.Numeric(precision=18, scale=2), nullable=False),
    sa.Column('other_charges', sa.Numeric(precision=18, scale=2), nullable=False),
    sa.Column('total_freight', sa.Numeric(precision=18, scale=2), nullable=False),
    sa.Column('advance_received', sa.Numeric(precision=18, scale=2), nullable=False),
    sa.Column('balance_freight', sa.Numeric(precision=18, scale=2), nullable=False),
    sa.Column('scheduled_start', sa.DateTime(), nullable=True),
    sa.Column('actual_start', sa.DateTime(), nullable=True),
    sa.Column('actual_end', sa.DateTime(), nullable=True),
    sa.Column('start_odometer', sa.Numeric(precision=18, scale=3), nullable=True),
    sa.Column('end_odometer', sa.Numeric(precision=18, scale=3), nullable=True),
    sa.Column('actual_km', sa.Numeric(precision=18, scale=3), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('delivered_packages', sa.Integer(), nullable=True),
    sa.Column('shortage_damage', sa.String(length=255), nullable=True),
    sa.Column('pod_received_date', sa.Date(), nullable=True),
    sa.Column('pod_remarks', sa.String(length=255), nullable=True),
    sa.Column('invoice_id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=True),
    sa.Column('cancel_reason', sa.String(length=255), nullable=True),
    sa.Column('remarks', sa.Text(), nullable=True),
    sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.Column('created_by', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=True),
    sa.Column('updated_by', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=True),
    sa.ForeignKeyConstraint(['contract_id'], ['contracts.id'], name=op.f('fk_trips_contract_id_contracts')),
    sa.ForeignKeyConstraint(['cost_center_id'], ['cost_centers.id'], name=op.f('fk_trips_cost_center_id_cost_centers')),
    sa.ForeignKeyConstraint(['customer_id'], ['customers.id'], name=op.f('fk_trips_customer_id_customers')),
    sa.ForeignKeyConstraint(['driver_id'], ['drivers.id'], name=op.f('fk_trips_driver_id_drivers')),
    sa.ForeignKeyConstraint(['from_state_id'], ['states.id'], name=op.f('fk_trips_from_state_id_states')),
    sa.ForeignKeyConstraint(['invoice_id'], ['invoices.id'], name=op.f('fk_trips_invoice_id_invoices')),
    sa.ForeignKeyConstraint(['to_state_id'], ['states.id'], name=op.f('fk_trips_to_state_id_states')),
    sa.ForeignKeyConstraint(['vehicle_id'], ['vehicles.id'], name=op.f('fk_trips_vehicle_id_vehicles')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_trips')),
    sa.UniqueConstraint('lr_number', name=op.f('uq_trips_lr_number')),
    sa.UniqueConstraint('trip_number', name=op.f('uq_trips_trip_number'))
    )
    op.create_index(op.f('ix_trips_contract_id'), 'trips', ['contract_id'], unique=False)
    op.create_index(op.f('ix_trips_cost_center_id'), 'trips', ['cost_center_id'], unique=False)
    op.create_index(op.f('ix_trips_customer_id'), 'trips', ['customer_id'], unique=False)
    op.create_index('ix_trips_driver_status', 'trips', ['driver_id', 'status'], unique=False)
    op.create_index(op.f('ix_trips_invoice_id'), 'trips', ['invoice_id'], unique=False)
    op.create_index(op.f('ix_trips_status'), 'trips', ['status'], unique=False)
    op.create_index(op.f('ix_trips_trip_date'), 'trips', ['trip_date'], unique=False)
    op.create_index('ix_trips_vehicle_start', 'trips', ['vehicle_id', 'actual_start'], unique=False)
    op.create_table('driver_settlements',
    sa.Column('settlement_number', sa.String(length=30), nullable=False),
    sa.Column('driver_id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=False),
    sa.Column('trip_id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=True),
    sa.Column('settlement_date', sa.Date(), nullable=False),
    sa.Column('period_from', sa.Date(), nullable=True),
    sa.Column('period_to', sa.Date(), nullable=True),
    sa.Column('trip_days', sa.Numeric(precision=18, scale=3), nullable=True),
    sa.Column('allowance_per_day', sa.Numeric(precision=18, scale=2), nullable=True),
    sa.Column('allowance_amount', sa.Numeric(precision=18, scale=2), nullable=False),
    sa.Column('other_earnings', sa.Numeric(precision=18, scale=2), nullable=False),
    sa.Column('deductions', sa.Numeric(precision=18, scale=2), nullable=False),
    sa.Column('deduction_remarks', sa.String(length=255), nullable=True),
    sa.Column('total_expenses', sa.Numeric(precision=18, scale=2), nullable=False),
    sa.Column('total_advances', sa.Numeric(precision=18, scale=2), nullable=False),
    sa.Column('net_payable', sa.Numeric(precision=18, scale=2), nullable=False),
    sa.Column('settle_amount', sa.Numeric(precision=18, scale=2), nullable=False),
    sa.Column('cost_center_id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=True),
    sa.Column('status', sa.String(length=15), nullable=False),
    sa.Column('approved_by', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=True),
    sa.Column('approved_at', sa.DateTime(), nullable=True),
    sa.Column('paid_date', sa.Date(), nullable=True),
    sa.Column('payment_mode', sa.String(length=20), nullable=True),
    sa.Column('payment_reference', sa.String(length=60), nullable=True),
    sa.Column('remarks', sa.Text(), nullable=True),
    sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.Column('created_by', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=True),
    sa.Column('updated_by', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=True),
    sa.ForeignKeyConstraint(['approved_by'], ['users.id'], name=op.f('fk_driver_settlements_approved_by_users')),
    sa.ForeignKeyConstraint(['cost_center_id'], ['cost_centers.id'], name=op.f('fk_driver_settlements_cost_center_id_cost_centers')),
    sa.ForeignKeyConstraint(['driver_id'], ['drivers.id'], name=op.f('fk_driver_settlements_driver_id_drivers')),
    sa.ForeignKeyConstraint(['trip_id'], ['trips.id'], name=op.f('fk_driver_settlements_trip_id_trips')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_driver_settlements')),
    sa.UniqueConstraint('settlement_number', name=op.f('uq_driver_settlements_settlement_number'))
    )
    op.create_index(op.f('ix_driver_settlements_cost_center_id'), 'driver_settlements', ['cost_center_id'], unique=False)
    op.create_index(op.f('ix_driver_settlements_driver_id'), 'driver_settlements', ['driver_id'], unique=False)
    op.create_index(op.f('ix_driver_settlements_settlement_date'), 'driver_settlements', ['settlement_date'], unique=False)
    op.create_index(op.f('ix_driver_settlements_trip_id'), 'driver_settlements', ['trip_id'], unique=False)
    op.create_table('eway_bills',
    sa.Column('ewb_number', sa.String(length=12), nullable=False),
    sa.Column('trip_id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=True),
    sa.Column('vehicle_id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=True),
    sa.Column('generated_at', sa.DateTime(), nullable=False),
    sa.Column('valid_until', sa.DateTime(), nullable=True),
    sa.Column('distance_km', sa.Integer(), nullable=True),
    sa.Column('is_odc', sa.Boolean(), nullable=False),
    sa.Column('doc_type', sa.String(length=10), nullable=False),
    sa.Column('doc_number', sa.String(length=60), nullable=True),
    sa.Column('doc_date', sa.Date(), nullable=True),
    sa.Column('goods_value', sa.Numeric(precision=18, scale=2), nullable=True),
    sa.Column('from_place', sa.String(length=150), nullable=True),
    sa.Column('to_place', sa.String(length=150), nullable=True),
    sa.Column('transporter_gstin', sa.String(length=15), nullable=True),
    sa.Column('status', sa.String(length=15), nullable=False),
    sa.Column('extension_count', sa.Integer(), nullable=False),
    sa.Column('last_extension_reason', sa.String(length=255), nullable=True),
    sa.Column('cancel_reason', sa.String(length=255), nullable=True),
    sa.Column('closed_at', sa.DateTime(), nullable=True),
    sa.Column('remarks', sa.Text(), nullable=True),
    sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.Column('created_by', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=True),
    sa.Column('updated_by', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=True),
    sa.ForeignKeyConstraint(['trip_id'], ['trips.id'], name=op.f('fk_eway_bills_trip_id_trips')),
    sa.ForeignKeyConstraint(['vehicle_id'], ['vehicles.id'], name=op.f('fk_eway_bills_vehicle_id_vehicles')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_eway_bills')),
    sa.UniqueConstraint('ewb_number', name=op.f('uq_eway_bills_ewb_number'))
    )
    op.create_index(op.f('ix_eway_bills_trip_id'), 'eway_bills', ['trip_id'], unique=False)
    op.create_index(op.f('ix_eway_bills_vehicle_id'), 'eway_bills', ['vehicle_id'], unique=False)
    op.create_index('ix_eway_status_valid', 'eway_bills', ['status', 'valid_until'], unique=False)
    op.create_table('driver_advances',
    sa.Column('advance_number', sa.String(length=30), nullable=False),
    sa.Column('driver_id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=False),
    sa.Column('trip_id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=True),
    sa.Column('advance_date', sa.Date(), nullable=False),
    sa.Column('amount', sa.Numeric(precision=18, scale=2), nullable=False),
    sa.Column('payment_mode', sa.String(length=20), nullable=True),
    sa.Column('reference', sa.String(length=60), nullable=True),
    sa.Column('purpose', sa.String(length=255), nullable=True),
    sa.Column('status', sa.String(length=15), nullable=False),
    sa.Column('settlement_id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=True),
    sa.Column('remarks', sa.Text(), nullable=True),
    sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.Column('created_by', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=True),
    sa.Column('updated_by', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=True),
    sa.ForeignKeyConstraint(['driver_id'], ['drivers.id'], name=op.f('fk_driver_advances_driver_id_drivers')),
    sa.ForeignKeyConstraint(['settlement_id'], ['driver_settlements.id'], name=op.f('fk_driver_advances_settlement_id_driver_settlements')),
    sa.ForeignKeyConstraint(['trip_id'], ['trips.id'], name=op.f('fk_driver_advances_trip_id_trips')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_driver_advances')),
    sa.UniqueConstraint('advance_number', name=op.f('uq_driver_advances_advance_number'))
    )
    op.create_index('ix_driver_adv_driver_status', 'driver_advances', ['driver_id', 'status'], unique=False)
    op.create_index(op.f('ix_driver_advances_advance_date'), 'driver_advances', ['advance_date'], unique=False)
    op.create_index(op.f('ix_driver_advances_settlement_id'), 'driver_advances', ['settlement_id'], unique=False)
    op.create_index(op.f('ix_driver_advances_trip_id'), 'driver_advances', ['trip_id'], unique=False)
    op.create_table('trip_expenses',
    sa.Column('trip_id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=False),
    sa.Column('expense_date', sa.Date(), nullable=True),
    sa.Column('expense_head', sa.String(length=30), nullable=False),
    sa.Column('amount', sa.Numeric(precision=18, scale=2), nullable=False),
    sa.Column('paid_by', sa.String(length=10), nullable=False),
    sa.Column('bill_number', sa.String(length=50), nullable=True),
    sa.Column('remarks', sa.String(length=255), nullable=True),
    sa.Column('settlement_id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=True),
    sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), autoincrement=True, nullable=False),
    sa.ForeignKeyConstraint(['settlement_id'], ['driver_settlements.id'], name=op.f('fk_trip_expenses_settlement_id_driver_settlements')),
    sa.ForeignKeyConstraint(['trip_id'], ['trips.id'], name=op.f('fk_trip_expenses_trip_id_trips'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_trip_expenses'))
    )
    op.create_index(op.f('ix_trip_expenses_settlement_id'), 'trip_expenses', ['settlement_id'], unique=False)
    op.create_index(op.f('ix_trip_expenses_trip_id'), 'trip_expenses', ['trip_id'], unique=False)
    op.add_column('invoices', sa.Column('einvoice_status', sa.String(length=15), server_default='NOT_APPLICABLE', nullable=False))
    op.add_column('invoices', sa.Column('irn', sa.String(length=64), nullable=True))
    op.add_column('invoices', sa.Column('irn_ack_number', sa.String(length=30), nullable=True))
    op.add_column('invoices', sa.Column('irn_ack_date', sa.DateTime(), nullable=True))
    op.add_column('invoices', sa.Column('signed_qr', sa.Text(), nullable=True))
    op.add_column('invoices', sa.Column('irn_cancelled_at', sa.DateTime(), nullable=True))
    op.add_column('invoices', sa.Column('irn_cancel_reason', sa.String(length=255), nullable=True))
    op.create_unique_constraint(op.f('uq_invoices_irn'), 'invoices', ['irn'])


def downgrade() -> None:
    op.drop_constraint(op.f('uq_invoices_irn'), 'invoices', type_='unique')
    for col in ('irn_cancel_reason', 'irn_cancelled_at', 'signed_qr', 'irn_ack_date', 'irn_ack_number', 'irn',
                'einvoice_status'):
        op.drop_column('invoices', col)
    # tables in reverse dependency order; their indexes go with them (dropping those first breaks MySQL FK rules)
    for table in ('trip_expenses', 'driver_advances', 'eway_bills', 'driver_settlements', 'trips'):
        op.drop_table(table)
