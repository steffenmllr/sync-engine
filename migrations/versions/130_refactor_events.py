"""refactor events

Revision ID: 2cebc0aec8e9
Revises: 5eb9b70cf13
Create Date: 2015-01-22 19:33:48.417889

"""

# revision identifiers, used by Alembic.
revision = '2cebc0aec8e9'
down_revision = '5eb9b70cf13'

from alembic import op
import sqlalchemy as sa


def upgrade():
    connection = op.get_bind()

    # Calendar table
    op.drop_constraint('calendar_ibfk_2', 'calendar', type_='foreignkey')
    op.drop_constraint('uuid', 'calendar', type_='unique')

    op.drop_column('calendar', 'provider_name')

    op.create_foreign_key('calendar_ibfk_2',
                          'calendar', 'namespace',
                          ['namespace_id'], ['id'],
                          ondelete='CASCADE')
    op.create_unique_constraint('uuid', 'calendar',
                                ['uid', 'namespace_id'])

    # Event table
    connection.execute(
        sa.sql.text(
            '''
            delete from event where source like "%remote%"
            '''
        )
    )

    op.drop_column('event', 'reminders')
    op.drop_column('event', 'recurrence')
    op.drop_column('event', 'is_owner')
    op.drop_column('event', 'busy')

    op.drop_constraint('uuid', 'event', type_='unique')
    op.drop_column('event', 'provider_name')
    op.drop_column('event', 'source')

    op.create_unique_constraint('uuid', 'event',
                                ['uid', 'namespace_id'])


def downgrade():
    raise Exception('Will not downgrade')
