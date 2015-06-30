"""create sequence_number column

Revision ID: 606447e78e7
Revises: 41f957b595fc
Create Date: 2015-06-29 14:56:45.745668

"""

# revision identifiers, used by Alembic.
revision = '606447e78e7'
down_revision = '41f957b595fc'

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.add_column('event', sa.Column('sequence_number', sa.Integer(),
                                     nullable=True, server_default='0'))


def downgrade():
    op.add_column('event', 'sequence_number')
