"""Eas do-over.

Revision ID: 411958c25bd7
Revises: 2f97277cd86d
Create Date: 2014-10-08 01:41:09.232662

"""

# revision identifiers, used by Alembic.
revision = '411958c25bd7'
down_revision = '2f97277cd86d'

from alembic import op
import sqlalchemy as sa


def upgrade():
    from inbox.ignition import main_engine
    engine = main_engine()
    Base = sa.ext.declarative.declarative_base()
    Base.metadata.reflect(engine)

    # FIX THIS.
    if 'easuid' in Base.metadata.tables:
        op.alter_column('easuid', 'msg_uid',
                        type_=sa.BigInteger,
                        existing_nullable=False)


def downgrade():
    pass
