import arrow
from datetime import datetime, timedelta
time_parse = datetime.utcfromtimestamp
from dateutil.parser import parse as date_parse
import ast

from sqlalchemy import (Column, String, ForeignKey, Text, Boolean, Integer,
                        DateTime, Enum, UniqueConstraint, Index, event)
from sqlalchemy.orm import relationship, backref, validates
from sqlalchemy.types import TypeDecorator

from inbox.sqlalchemy_ext.util import MAX_TEXT_LENGTH, BigJSON, MutableList
from inbox.models.base import MailSyncBase
from inbox.models.mixins import HasPublicID, HasRevisions
from inbox.models.calendar import Calendar
from inbox.models.namespace import Namespace
from inbox.models.when import Time, TimeSpan, Date, DateSpan
from inbox.log import get_logger
log = get_logger()

TITLE_MAX_LEN = 1024
LOCATION_MAX_LEN = 255
RECURRENCE_MAX_LEN = 255
REMINDER_MAX_LEN = 255
OWNER_MAX_LEN = 1024
_LENGTHS = {'location': LOCATION_MAX_LEN,
            'owner': OWNER_MAX_LEN,
            'recurrence': RECURRENCE_MAX_LEN,
            'reminders': REMINDER_MAX_LEN,
            'title': TITLE_MAX_LEN,
            'raw_data': MAX_TEXT_LENGTH}


class FlexibleDateTime(TypeDecorator):
    """Coerce arrow times to naive datetimes before handing to the database."""

    impl = DateTime

    def process_bind_param(self, value, dialect):
        if isinstance(value, arrow.arrow.Arrow):
            value = value.to('utc').naive
        return value

    def process_result_value(self, value, dialect):
        if value is None:
            return value
        else:
            return arrow.get(value)

    def compare_values(self, x, y):
        return arrow.get(x) == arrow.get(y)


class Event(MailSyncBase, HasRevisions, HasPublicID):
    """Data for events."""
    API_OBJECT_NAME = 'event'

    # Don't surface 'remote' events in the transaction log since
    # they're an implementation detail we don't want our customers
    # to worry about.
    @property
    def should_suppress_transaction_creation(self):
        return self.source == 'remote'

    namespace_id = Column(ForeignKey(Namespace.id, ondelete='CASCADE'),
                          nullable=False)

    namespace = relationship(Namespace, load_on_pending=True)

    calendar_id = Column(ForeignKey(Calendar.id, ondelete='CASCADE'),
                         nullable=False)
    # Note that we configure a delete cascade, rather than
    # passive_deletes=True, in order to ensure that delete revisions are
    # created for events if their parent calendar is deleted.
    calendar = relationship(Calendar,
                            backref=backref('events', cascade='delete'),
                            load_on_pending=True)

    # A server-provided unique ID.
    uid = Column(String(767, collation='ascii_general_ci'), nullable=False)

    # DEPRECATED
    # TODO(emfree): remove
    provider_name = Column(String(64), nullable=False, default='DEPRECATED')
    source = Column('source', Enum('local', 'remote'), default='local')

    raw_data = Column(Text, nullable=False)

    title = Column(String(TITLE_MAX_LEN), nullable=True)
    owner = Column(String(OWNER_MAX_LEN), nullable=True)
    description = Column(Text, nullable=True)
    location = Column(String(LOCATION_MAX_LEN), nullable=True)
    busy = Column(Boolean, nullable=False, default=True)
    read_only = Column(Boolean, nullable=False)
    reminders = Column(String(REMINDER_MAX_LEN), nullable=True)
    recurrence = Column(String(RECURRENCE_MAX_LEN), nullable=True)
    start = Column(FlexibleDateTime, nullable=False)
    end = Column(FlexibleDateTime, nullable=True)
    all_day = Column(Boolean, nullable=False)
    is_owner = Column(Boolean, nullable=False, default=True)

    __table_args__ = (Index('ix_event_ns_uid_calendar_id',
                            'namespace_id', 'uid', 'calendar_id'),)

    participants = Column(MutableList.as_mutable(BigJSON), default=[],
                          nullable=True)

    discriminator = Column('type', String(30))
    __mapper_args__ = {'polymorphic_on': discriminator,
                       'polymorphic_identity': 'event'}

    @validates('reminders', 'recurrence', 'owner', 'location', 'title',
               'raw_data')
    def validate_length(self, key, value):
        max_len = _LENGTHS[key]
        return value if value is None else value[:max_len]

    @property
    def when(self):
        if self.all_day:
            # Dates are stored as DateTimes so transform to dates here.
            start = self.start.date()
            end = self.end.date()
            return Date(start) if start == end else DateSpan(start, end)
        else:
            start = self.start
            end = self.end
            return Time(start) if start == end else TimeSpan(start, end)

    @when.setter
    def when(self, when):
        if 'time' in when:
            self.start = self.end = time_parse(when['time'])
            self.all_day = False
        elif 'start_time' in when:
            self.start = time_parse(when['start_time'])
            self.end = time_parse(when['end_time'])
            self.all_day = False
        elif 'date' in when:
            self.start = self.end = date_parse(when['date'])
            self.all_day = True
        elif 'start_date' in when:
            self.start = date_parse(when['start_date'])
            self.end = date_parse(when['end_date'])
            self.all_day = True

    def update(self, event):
        self.uid = event.uid
        self.raw_data = event.raw_data
        self.title = event.title
        self.description = event.description
        self.location = event.location
        self.start = event.start
        self.end = event.end
        self.all_day = event.all_day
        self.owner = event.owner
        self.is_owner = event.is_owner
        self.read_only = event.read_only
        self.participants = event.participants
        self.busy = event.busy
        self.reminders = event.reminders
        self.recurrence = event.recurrence
        # TODO this update method has to handle a recurring event being updated
        # define an overload that calls super on the childrenz

    @property
    def recurring(self):
        if self.recurrence:
            r = ast.literal_eval(self.recurrence)
            # this can be a list containing at least 1 item:
            # RRULE (required)
            # EXDATE (optional)
            return r
        return []

    @property
    def is_recurring(self):
        return self.recurrence is not None

    @property
    def length(self):
        return self.when.delta

    @classmethod
    def __new__(cls, *args, **kwargs):
        # Decide whether or not to instantiate a RecurringEvent/Override
        # based on the kwargs we get.
        cls_ = cls
        if kwargs.get('recurrence') is not None:
            cls_ = RecurringEvent
        if kwargs.get('master_event_uid') is not None:
            cls_ = RecurringEventOverride
        return object.__new__(cls_, *args, **kwargs)

    def __init__(self, **kwargs):
        # Allow arguments for all subclasses to be passed to main constructor
        for k in kwargs.keys():
            if not hasattr(type(self), k):
                del kwargs[k]
        super(Event, self).__init__(**kwargs)


class RecurringEvent(Event):
    API_OBJECT_NAME = 'event_recurring'

    __mapper_args__ = {'polymorphic_identity': 'recurringevent'}
    __table_args__ = None

    id = Column(Integer, ForeignKey('event.id'), primary_key=True)
    rrule = Column(String(RECURRENCE_MAX_LEN))
    exdate = Column(String(RECURRENCE_MAX_LEN))
    until = Column(FlexibleDateTime, nullable=True)
    start_timezone = Column(String(35))

    def __init__(self, **kwargs):
        self.start_timezone = kwargs.pop('original_start_tz', None)
        kwargs['recurrence'] = str(kwargs['recurrence'])
        super(RecurringEvent, self).__init__(**kwargs)
        self.unwrap_rrule()

    def inflate(self, start=None, end=None):
        # Convert a RecurringEvent into a series of InflatedEvents
        # by expanding its RRULE into a series of start times.
        from inbox.events.recurring import get_start_times
        occurrences = get_start_times(self, start, end)
        return [InflatedEvent(self, o) for o in occurrences]

    def unwrap_rrule(self):
        # Unwraps the RRULE list of strings into RecurringEvent properties.
        for item in self.recurring:
            if item.startswith('RRULE'):
                self.rrule = item
                if 'UNTIL' in item:
                    for p in item.split(';'):
                        if p.startswith('UNTIL'):
                            # UNTIL is always in UTC (RFC 2445 4.3.10)
                            # Format: 20150209T075959Z
                            self.until = arrow.get(p[6:-1], 'YYYYMMDDThhmmss')
            elif item.startswith('EXDATE'):
                self.exdate = item

    def all_events(self, start=None, end=None):
        # Returns all inflated events along with overrides that match the
        # provided time range.
        overrides = self.overrides
        if start:
            overrides = overrides.filter(RecurringEventOverride.start > start)
        if end:
            overrides = overrides.filter(RecurringEventOverride.end < end)
        events = list(overrides)
        uids = {e.uid: True for e in events}
        # If an override has not changed the start time for an event, the
        # RRULE doesn't include an exception for it. Filter out unnecessary
        # inflated events to cover this case: they will have the same UID.
        for e in self.inflate(start, end):
            if e.uid not in uids:
                events.append(e)
        return sorted(events, key=lambda e: e.start)

    def update(self, event):
        super(RecurringEvent, self).update(event)
        if isinstance(event, type(self)):
            self.rrule = event.rrule
            self.exdate = event.exdate
            self.until = event.until
            self.start_timezone = event.start_timezone


class RecurringEventOverride(Event):
    API_OBJECT_NAME = 'event_override'
    # TODO - DELETE CASCADES ! ##
    id = Column(Integer, ForeignKey('event.id'), primary_key=True)
    __mapper_args__ = {'polymorphic_identity': 'recurringeventoverride',
                       'inherit_condition': (id == Event.id)}
    __table_args__ = None

    master_event_id = Column(ForeignKey('event.id'))
    master_event_uid = Column(String(767, collation='ascii_general_ci'))
    original_start_time = Column(FlexibleDateTime)

    master = relationship(RecurringEvent, foreign_keys=[master_event_id],
                          backref=backref('overrides', lazy="dynamic"))

    def update(self, event):
        super(RecurringEventOverride, self).update(event)
        if isinstance(event, type(self)):
            self.master_event_uid = event.master_event_uid
            self.original_start_time = event.original_start_time


class InflatedEvent(Event):
    # NOTE: This is a transient object that should never be committed to the
    # database (it's generated when a recurring event is expanded).
    # Correspondingly, there doesn't need to be a table for this object,
    # however we have to pretend there is, so it behaves like an Event.
    # TODO: I don't like this that much.
    __mapper_args__ = {'polymorphic_identity': 'inflatedevent'}
    __tablename__ = 'event'
    __table_args__ = {'extend_existing': True}

    def __init__(self, event, instance_start):
        self.master = event
        self.update(self.master)
        # Give inflated events a UID consisting of the master UID and the
        # original UTC start time of the inflation.
        ts_id = instance_start.strftime("%Y%m%dT%H%M%SZ")
        self.uid = "{}_{}".format(self.master.uid, ts_id)
        self.public_id = "{}_{}".format(self.master.public_id, ts_id)
        self.set_start_end(instance_start)

    def set_start_end(self, start):
        # get the length from the master event
        length = self.length

        if start.utcoffset() is not None:
            if start.utcoffset() == timedelta(minutes=0):
                start = start.replace(tzinfo=None)  # Everything is naive UTC
            else:
                print start.utcoffset()
                raise Exception("Encountered non-UTC timezone! Eek!")

        self.start = start  # this should be a datetime in UTC
        self.end = self.start + length
        # todo - check this behaves cool with dates

    def update(self, master):
        super(InflatedEvent, self).update(master)
        self.namespace_id = master.namespace_id
        self.calendar_id = master.calendar_id


def insert_warning(mapper, connection, target):
    log.warn("InflatedEvent {} shouldn't be committed".format(target))
    raise Exception("InflatedEvent should not be committed")

event.listen(InflatedEvent, 'before_insert', insert_warning)
