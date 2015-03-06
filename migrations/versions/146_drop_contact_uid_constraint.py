"""Drop Contact.uid constraint.

Revision ID: 51d7eba5df76
Revises: 27bff6e91fc6
Create Date: 2015-03-06 19:44:10.715003

"""

# revision identifiers, used by Alembic.
revision = '51d7eba5df76'
down_revision = '27bff6e91fc6'

from alembic import op


def upgrade():
    op.drop_constraint('uid', 'contact', type_='unique')


def downgrade():
    op.create_index('uid', 'contact',
                    ['namespace_id', 'provider_name', 'uid'], unique=True)
