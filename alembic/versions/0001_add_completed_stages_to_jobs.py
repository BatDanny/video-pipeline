"""add completed_stages to jobs

Revision ID: 0001
Revises:
Create Date: 2026-03-07

"""
from alembic import op
import sqlalchemy as sa

revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('jobs', sa.Column('completed_stages', sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column('jobs', 'completed_stages')
