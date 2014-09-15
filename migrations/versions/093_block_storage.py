"""Block storage

Revision ID: 43e5867a6ef1
Revises: 1683790906cf
Create Date: 2014-08-21 18:19:26.851250

"""

# revision identifiers, used by Alembic.
revision = '43e5867a6ef1'
down_revision = '1683790906cf'

from alembic import op
from sqlalchemy.sql import text


def upgrade():
    conn = op.get_bind()

    conn.execute(text("""
        ALTER TABLE part
            DROP FOREIGN KEY part_ibfk_1,
            MODIFY block_id BIGINT
        """))

    conn.execute(text("""
        ALTER TABLE block
            MODIFY id BIGINT NULL AUTO_INCREMENT,
            MODIFY data_sha256 BINARY(32),
            ADD COLUMN encryption_scheme INTEGER DEFAULT '0',
            ADD COLUMN stored_name STRING(255)
        """))

    # Can't be batched
    op.create_foreign_key('part_ibfk_1', 'part', 'block', ['block_id'], ['id'],
                          ondelete='CASCADE')

    conn.execute(text("""
        UPDATE block SET encryption_scheme=0
        """))


def downgrade():
    raise Exception('No.')
