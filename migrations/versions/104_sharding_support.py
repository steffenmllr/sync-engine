"""sharding support

Revision ID: 57c5a616b20
Revises: 4015edc83ba
Create Date: 2014-09-25 07:34:07.312100

"""

# revision identifiers, used by Alembic.
revision = '57c5a616b20'
down_revision = '4015edc83ba'

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.create_table(
        'namespaceshard',
        sa.Column('public_id', sa.BINARY(length=16), nullable=False),
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('namespace_id', sa.Integer(), nullable=False),
        sa.Column('shard_key', sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_namespaceshard_public_id', 'namespaceshard',
                    ['public_id'], unique=False)

    # STOPSHIP(emfree) populate namespaceshard table with existing data.

    op.drop_column('namespace', 'type')

    # Remove autoincrement on namespace.id
    conn = op.get_bind()
    conn.execute(sa.sql.text('''
        ALTER TABLE namespace CHANGE id id INT(11) NOT NULL;
        '''))
    conn.execute(sa.sql.text('''
        ALTER TABLE account CHANGE id id INT(11) NOT NULL;
        '''))


def downgrade():
    op.drop_index('ix_namespaceshard_public_id', table_name='namespaceshard')
    op.drop_table('namespaceshard')
    # STOPSHIP(emfree) add type column back.
