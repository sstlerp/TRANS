"""toll plaza keep manual changes (toll_plazas.details_locked, toll_plaza_sync_runs.locked)

Plazas edited by a user are locked so internet syncs do not overwrite them; runs count such plazas.

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-30 06:13:10.430908
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0003'
down_revision: Union[str, None] = '0002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('toll_plaza_sync_runs', sa.Column('locked', sa.Integer(), server_default='0', nullable=False))
    op.add_column('toll_plazas', sa.Column('details_locked', sa.Boolean(), server_default='0', nullable=False))


def downgrade() -> None:
    op.drop_column('toll_plazas', 'details_locked')
    op.drop_column('toll_plaza_sync_runs', 'locked')
