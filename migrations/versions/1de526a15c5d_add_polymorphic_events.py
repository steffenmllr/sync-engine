"""Add polymorphic Events

Revision ID: 1de526a15c5d
Revises: 1c73ca99c03b
Create Date: 2015-03-11 22:51:22.180028

"""

# revision identifiers, used by Alembic.
revision = '1de526a15c5d'
down_revision = '486c7fa5b533'

import json
import ast
from alembic import op
import sqlalchemy as sa


def upgrade():
    op.create_table(
        'recurringeventoverride',
        sa.Column('id', sa.Integer(), nullable=False),
        # These have to be nullable so we can do the type conversion
        sa.Column('master_event_id', sa.Integer(), nullable=True),
        sa.Column('master_event_uid', sa.String(
            length=767, collation='ascii_general_ci'), nullable=True),
        sa.Column('original_start_time', sa.DateTime(), nullable=True),
        sa.Column('cancelled', sa.Boolean(), default=False),
        sa.ForeignKeyConstraint(['id'], ['event.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['master_event_id'], ['event.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_table(
        'recurringevent',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('rrule', sa.String(length=255), nullable=True),
        sa.Column('exdate', sa.String(length=255), nullable=True),
        sa.Column('until', sa.DateTime(), nullable=True),
        sa.Column('start_timezone', sa.String(35), nullable=True),
        sa.ForeignKeyConstraint(['id'], ['event.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.add_column(u'event', sa.Column('type', sa.String(length=30),
                  nullable=True))


def downgrade():
    op.drop_column(u'event', 'type')
    op.drop_table('recurringevent')
    op.drop_table('recurringeventoverride')


def populate():
    # Populate new classes from the existing data
    from inbox.models.event import RecurringEvent, RecurringEventOverride
    from inbox.models.session import session_scope
    from inbox.events.util import parse_datetime
    from inbox.events.recurring import link_events

    with session_scope() as db:
        # Slightly hacky way to convert types (only needed for one-off import)
        convert = """UPDATE event SET type='recurringeventoverride' WHERE
                     raw_data LIKE '%recurringEventId%'"""
        db.execute(convert)
        create = """INSERT INTO recurringeventoverride (id)
                    SELECT id FROM event
                    WHERE type='recurringeventoverride'
                    AND id NOT IN
                    (SELECT id FROM recurringeventoverride)"""
        try:
            db.execute(create)
        except Exception as e:
            print "Couldn't insert RecurringEventOverrides: {}".format(e)
            exit(2)

        print 'Converted Event -> RecurringEventOverride'

        query = db.query(RecurringEventOverride)
        for e in query:
            try:
                # Some raw data is str(dict), other is json.dumps
                raw_data = json.loads(e.raw_data)
            except:
                raw_data = ast.literal_eval(e.raw_data)
            rec_uid = raw_data.get('recurringEventId')
            if rec_uid:
                e.master_event_uid = rec_uid
                ost = raw_data.get('originalStartTime')
                if ost:
                    # this is a dictionary with one value
                    start_time = ost.values().pop()
                    e.original_start_time = parse_datetime(start_time)
                # attempt to get the ID for the event, if we can, and
                # set the relationship appropriately
                master = link_events(db, e)
                if master:
                    print "Master event found for {}".format(e.id)
                else:
                    print "Master not found for {}".format(e.id)

        db.commit()

        # Convert Event to RecurringEvent

        convert = """UPDATE event SET type='recurringevent' WHERE
                     recurrence IS NOT NULL"""
        db.execute(convert)
        create = """INSERT INTO recurringevent (id)
                    SELECT id FROM event
                    WHERE type='recurringevent'
                    AND id NOT IN
                    (SELECT id FROM recurringevent)"""
        try:
            db.execute(create)
        except Exception as e:
            print "Couldn't insert RecurringEvents: {}".format(e)
            exit(2)

        print 'Converted Event -> RecurringEvent'

        # Pull out recurrence metadata from recurrence
        query = db.query(RecurringEvent)
        for r in query:
            r.unwrap_rrule()
            try:
                raw_data = json.loads(r.raw_data)
            except:
                raw_data = ast.literal_eval(r.raw_data)
            r.start_timezone = raw_data['start'].get('timeZone')
            # find any un-found overrides that didn't have masters earlier
            overrides = link_events(db, r)
            if len(overrides) > 0:
                print "{} overrides found for {}".format(len(overrides), r.id)
            else:
                print "No overrides found for {}".format(r.id)
            db.add(r)
        db.commit()

        # Finally, convert all remaining Events to type='event'
        convert = """UPDATE event SET type='event' WHERE type IS NULL"""
        db.execute(convert)


if __name__ == "__main__":
    populate()
