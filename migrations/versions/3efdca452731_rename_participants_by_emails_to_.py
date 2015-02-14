"""rename participants_by_emails to participants

Revision ID: 3efdca452731
Revises: 39fa82d3168e
Create Date: 2015-02-12 22:18:48.121586

"""

# revision identifiers, used by Alembic.
revision = '3efdca452731'
down_revision = '39fa82d3168e'

from alembic import op
from inbox.models.session import session_scope
from inbox.sqlalchemy_ext.util import JSON, BigJSON, safer_yield_per, MutableList
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.sql import text
from sqlalchemy import Column
from inbox.ignition import main_engine

import sqlalchemy as sa
import json


def upgrade():
    op.add_column('event', sa.Column('participants', BigJSON(),
                                     nullable=True))
    conn = op.get_bind()
    conn.execute(text("UPDATE event SET participants = '[]'"))

    engine = main_engine(pool_size=1, max_overflow=0)
    Base = declarative_base()
    Base.metadata.reflect(engine)

    class Event(Base):
        __table__ = Base.metadata.tables['event']

    with session_scope() as db_session:
        events = db_session.query(Event)
        for event in events:
            l = []
            participants_hash = json.loads(event.participants_by_email)
            for participant in participants_hash:
                dct = participants_hash[participant]

                # Also rename 'email_address' to 'email'
                if 'email_address' in dct:
                    dct['email'] = 'email_address'
                    del dct['email_address']

                l.append(dct)
            event.participants = json.dumps(l)

        db_session.commit()

    op.drop_column('event', 'participants_by_email')


def downgrade():
    op.add_column('event', sa.Column('participants_by_email', JSON(),
                                     nullable=True))
    conn = op.get_bind()
    conn.execute(text("UPDATE event SET participants_by_email = '{}'"))

    engine = main_engine(pool_size=1, max_overflow=0)
    Base = declarative_base()
    Base.metadata.reflect(engine)

    class Event(Base):
        __table__ = Base.metadata.tables['event']

    with session_scope() as db_session:
        events = db_session.query(Event)
        for event in events:
            dct = {}
            participants_list = json.loads(event.participants)
            for participant in participants_list:
                email = participant.get("email")
                if email:
                    dct[email] = participant
                    participant['email_address'] = participant['email']
                    del participant['email']

            event.participants_by_email = json.dumps(dct)

        db_session.commit()

    op.drop_column('event', 'participants')
