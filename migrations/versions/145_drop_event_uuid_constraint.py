"""Drop Event.uuid constraint

Revision ID: 27bff6e91fc6
Revises: 1c73ca99c03b
Create Date: 2015-03-06 06:47:25.134033

"""

# revision identifiers, used by Alembic.
revision = '27bff6e91fc6'
down_revision = '1c73ca99c03b'

from alembic import op


def upgrade():
    op.drop_constraint('uuid', 'event', type_='unique')


def downgrade():
    op.create_index('uuid', 'event',
                    ['namespace_id', 'provider_name', 'source', 'uid'], unique=True)
