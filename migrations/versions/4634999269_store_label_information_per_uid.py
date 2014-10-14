"""store label information per-uid

Revision ID: 4634999269
Revises: 5709063bff01
Create Date: 2014-10-14 10:04:58.710015

"""

# revision identifiers, used by Alembic.
revision = '4634999269'
down_revision = '5709063bff01'

from alembic import op
import sqlalchemy as sa

from inbox.sqlalchemy_ext.util import JSON


def upgrade():
    op.add_column('imapuid', sa.Column('labels', JSON(),
                                       nullable=False))


def downgrade():
    op.drop_column('imapuid', 'labels')
