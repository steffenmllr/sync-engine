"""Split ActionLog.

Revision ID: 182f2b40fa36
Revises: 4e6eedda36af
Create Date: 2015-04-20 21:22:20.523261

"""

# revision identifiers, used by Alembic.
revision = '182f2b40fa36'
down_revision = '4e6eedda36af'

from alembic import op
import sqlalchemy as sa


def upgrade():
    from inbox.ignition import main_engine

    engine = main_engine(pool_size=1, max_overflow=0)
    if not engine.has_table('easaccount'):
        return

    op.add_column('actionlog', sa.Column('type', sa.String(16)))

    op.create_table('easactionlog',
                    sa.Column('id', sa.Integer()),
                    sa.Column('foldersync_id', sa.Integer()),
                    sa.PrimaryKeyConstraint('id'),
                    sa.ForeignKeyConstraint(['id'], ['actionlog.id'],
                                            ondelete='CASCADE'),
                    sa.ForeignKeyConstraint(['foldersync_id'], ['easfoldersync.id'],
                                            ondelete='CASCADE'))
    op.create_index('ix_easactionlog_foldersync_id', 'easactionlog',
                    ['foldersync_id'])


def downgrade():
    pass
